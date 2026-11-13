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
from pydantic import Field, PrivateAttr

from dreaming_workflow.agents.budget import ContextGuard, TokenUsage, UsageLedger
from dreaming_workflow.agents.invocation import AgentRole
from dreaming_workflow.agents.results import AgentFailure, Failure, FailureReason
from dreaming_workflow.sessions.view import estimate_tokens

MODEL = "claude-sonnet-5-5"
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


class MissingCredentials(Exception):
    """No Claude API credentials were found. The detail names the SDK's error class, if any."""

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail)
        self.detail = detail


def create_client() -> AsyncAnthropic:
    """Build the run's client, or raise `MissingCredentials` before any request."""
    try:
        client = AsyncAnthropic(timeout=REQUEST_TIMEOUT, max_retries=MAX_RETRIES)
    except anthropic.CredentialsError as error:
        # The SDK's message can quote configuration paths and profile names;
        # keep only the class name.
        raise MissingCredentials(type(error).__name__) from None
    if (
        client.api_key is None
        and client.auth_token is None
        and getattr(client, "credentials", None) is None
    ):
        raise MissingCredentials()
    return client


def generate_content_config() -> AnthropicGenerateContentConfig:
    """Agent settings: adaptive thinking at medium effort, no sampling parameters."""
    return AnthropicGenerateContentConfig(
        effort="medium",
        # ADK sends a negative budget as adaptive thinking with summarized display.
        thinking_config=types.ThinkingConfig(thinking_budget=-1),
    )


def _fail(reason: FailureReason, detail: str = "") -> AgentFailure:
    return AgentFailure(Failure(reason, detail))


def _failure_for(error: Exception) -> AgentFailure:
    """Map what ADK raises after the SDK's own retries to a failure reason."""
    # Order matters: RateLimitError and the 529 OverloadedError are
    # APIStatusErrors, and APITimeoutError is an APIConnectionError.
    match error:
        case anthropic.RateLimitError():
            return _fail(FailureReason.RATE_LIMITED)
        case anthropic.APIStatusError(status_code=529):
            return _fail(FailureReason.OVERLOADED)
        case anthropic.APITimeoutError():
            return _fail(FailureReason.TIMEOUT)
        case anthropic.APIConnectionError():
            return _fail(FailureReason.CONNECTION_ERROR)
        case anthropic.AuthenticationError() | anthropic.PermissionDeniedError():
            return _fail(FailureReason.AUTHENTICATION_FAILED)
        case anthropic.APIStatusError():
            request_id = error.request_id or "none"
            return _fail(
                FailureReason.API_ERROR,
                f"status {error.status_code}, request ID {request_id}",
            )
        case _:
            return _fail(FailureReason.INTERNAL_ERROR, type(error).__name__)


def _usage(response: LlmResponse) -> TokenUsage | None:
    """Convert ADK's usage fields back to the Messages API's counts."""
    metadata = response.usage_metadata
    if metadata is None:
        return None
    cache_read = metadata.cached_content_token_count or 0
    cache_write = response.cache_creation_token_count or 0
    # ADK's prompt count already includes cache reads and writes.
    prompt = metadata.prompt_token_count or 0
    return TokenUsage(
        input_tokens=prompt - cache_read - cache_write,
        cache_write_tokens=cache_write,
        cache_read_tokens=cache_read,
        output_tokens=(metadata.candidates_token_count or 0)
        + (metadata.thoughts_token_count or 0),
    )


def _contents_tokens(contents: list[types.Content]) -> int:
    return sum(
        estimate_tokens(content.model_dump_json(exclude_none=True))
        for content in contents
    )


def _whole_request_tokens(llm_request: LlmRequest) -> int:
    tokens = _contents_tokens(llm_request.contents)
    if llm_request.config is not None:
        tokens += estimate_tokens(
            llm_request.config.model_dump_json(
                exclude_none=True, include={"system_instruction", "tools"}
            )
        )
    return tokens


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
    # ADK turns redacted thinking into a thought part without text. Rejecting
    # it keeps the history free of it, which _restore_empty_thinking relies on.
    if any(part.thought and part.text is None for part in parts or []):
        raise _fail(FailureReason.INVALID_MODEL_OUTPUT)


def _restore_empty_thinking(messages: list[MessageParam]) -> None:
    """Send signed thinking blocks with empty text back as thinking blocks.

    A thinking block can arrive with empty text and only a signature (the
    model omits the text unless asked for summaries), and the API needs it
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
    """The model for one agent invocation.

    `ledger` is shared by every request in the run and stops analysis requests
    at the spending limit; `guard` belongs to this invocation and stops a
    request whose prompt would pass the ceiling.
    """

    model: str = MODEL
    max_tokens: int = MAX_TOKENS
    role: AgentRole = AgentRole.ANALYSIS
    ledger: UsageLedger = Field(default_factory=UsageLedger, exclude=True)
    guard: ContextGuard = Field(default_factory=ContextGuard, exclude=True)
    # How many contents the previous request carried; ADK resends them all and
    # appends the new ones.
    _contents_sent: int | None = PrivateAttr(default=None)

    @override
    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse]:
        if self.role is AgentRole.ANALYSIS:
            self.ledger.check_before_analysis_request()
        if self._contents_sent is None:
            new_tokens = _whole_request_tokens(llm_request)
        else:
            new_tokens = _contents_tokens(llm_request.contents[self._contents_sent :])
        self.guard.check_send(new_tokens)
        self._contents_sent = len(llm_request.contents)
        responses = super().generate_content_async(llm_request, stream)
        while True:
            try:
                response = await anext(responses)
            except StopAsyncIteration:
                return
            # Every failure becomes a reason; unknown ones become internal-error.
            except Exception as error:  # noqa: BLE001
                # `from None`: some ADK conversion errors quote message content,
                # and a chained cause would carry it into any traceback.
                raise _failure_for(error) from None
            usage = _usage(response) if not response.partial else None
            if usage is not None:
                self.ledger.add(usage)
                self.guard.record_response(usage)
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
