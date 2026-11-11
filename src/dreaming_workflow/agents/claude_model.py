"""How the agents call Claude: ADK's own Claude API model with this tool's settings.

ADK's `AnthropicLlm` converts between ADK's genai types and the Messages API and
sends each request through `AsyncAnthropic.messages.create`. `ClaudeModel` sets
the model and output limit, repairs one conversion, and turns responses the
agents can't use into `AgentFailure`. Design record:
docs/adr/0001-adk-anthropic-llm.md.
"""

from collections.abc import AsyncGenerator, Iterable
from typing import Any, override

import anthropic
from anthropic import AsyncAnthropic, NotGiven
from anthropic.types import (
    MessageParam,
    ThinkingBlockParam,
    ThinkingConfigAdaptiveParam,
    ThinkingConfigDisabledParam,
    ThinkingConfigEnabledParam,
    ToolChoiceParam,
    ToolUnionParam,
)
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.models import LlmRequest, LlmResponse
from google.adk.models.anthropic_llm import AnthropicGenerateContentConfig, AnthropicLlm
from google.genai import types

from dreaming_workflow.agents.results import AgentFailure, Failure, FailureReason

MODEL = "claude-haiku-5-5"
MAX_TOKENS = 16_000
REQUEST_TIMEOUT = anthropic.Timeout(300.0, connect=10.0)
MAX_RETRIES = 3

# With a cache config on the app, ADK puts cache breakpoints on the last tool
# definition, the system instruction, and the end of the conversation. Its
# default 30-minute lifetime maps to Claude's 5-minute cache.
CONTEXT_CACHE = ContextCacheConfig()

type _ThinkingParam = (
    ThinkingConfigEnabledParam
    | ThinkingConfigDisabledParam
    | ThinkingConfigAdaptiveParam
    | NotGiven
)


def create_client() -> AsyncAnthropic:
    return AsyncAnthropic(timeout=REQUEST_TIMEOUT, max_retries=MAX_RETRIES)


def generate_content_config() -> AnthropicGenerateContentConfig:
    """Agent settings: adaptive thinking at medium effort, no sampling parameters."""
    return AnthropicGenerateContentConfig(
        effort="medium",
        # ADK sends a negative budget as adaptive thinking with summarized display.
        thinking_config=types.ThinkingConfig(thinking_budget=-1),
    )


def _fail(reason: FailureReason) -> AgentFailure:
    return AgentFailure(Failure(reason))


def _check(response: LlmResponse) -> None:
    match response.finish_reason:
        case types.FinishReason.STOP:
            pass
        case types.FinishReason.MAX_TOKENS:
            raise _fail(FailureReason.MAX_TOKENS)
        case types.FinishReason.SAFETY:
            raise _fail(FailureReason.REFUSED)
        case _:
            raise _fail(FailureReason.INVALID_MODEL_OUTPUT)
    parts = response.content.parts if response.content is not None else None
    # ADK turns redacted thinking into a thought part without text. Claude Haiku
    # 5.5 doesn't send redacted thinking; rejecting it keeps the history free of
    # it, which _restore_empty_thinking relies on.
    if any(part.thought and part.text is None for part in parts or []):
        raise _fail(FailureReason.INVALID_MODEL_OUTPUT)


def _restore_empty_thinking(messages: list[MessageParam]) -> None:
    """Send signed thinking blocks with empty text back as thinking blocks.

    A thinking block can arrive with empty text and only a signature (Claude
    Haiku 5.5 omits the text unless asked for summaries), and the API needs it
    back unchanged. ADK sends such a part as redacted thinking with the
    signature as its data. Since _check rejects real redacted thinking, every
    redacted block here is one of those.
    """
    for message in messages:
        if message["role"] == "system":
            continue
        content = message["content"]
        if isinstance(content, str):
            continue
        restored = []
        for block in content:
            match block:
                case {"type": "redacted_thinking", "data": str(signature)}:
                    restored.append(
                        ThinkingBlockParam(
                            type="thinking", thinking="", signature=signature
                        )
                    )
                case _:
                    restored.append(block)
        message["content"] = restored


class ClaudeModel(AnthropicLlm):
    model: str = MODEL
    max_tokens: int = MAX_TOKENS

    @override
    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse]:
        async for response in super().generate_content_async(llm_request, stream):
            _check(response)
            yield response

    # Overrides a private ADK method, the only one that sees the converted
    # messages. The contract test fails if an ADK upgrade changes it.
    @override
    def _build_anthropic_kwargs(
        self,
        llm_request: LlmRequest,
        messages: list[MessageParam],
        tools: Iterable[ToolUnionParam] | NotGiven,
        tool_choice: ToolChoiceParam | NotGiven,
        thinking: _ThinkingParam,
    ) -> dict[str, Any]:  # Any: ADK's return type
        _restore_empty_thinking(messages)
        return super()._build_anthropic_kwargs(
            llm_request, messages, tools, tool_choice, thinking
        )
