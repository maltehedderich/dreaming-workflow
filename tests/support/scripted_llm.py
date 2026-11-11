"""A scripted stand-in for Claude that runs inside real ADK agents.

Each agent invocation gets its own script, chosen by session ID and part, or
by the organizer role. The real tools run, so their guards are what tests see.
"""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import override

from google.adk.models import BaseLlm, LlmCapabilities, LlmRequest, LlmResponse
from google.genai import types
from pydantic import PrivateAttr

from dreaming_workflow.agents import AgentFailure, AgentRole, Invocation


@dataclass(frozen=True)
class CallTool:
    name: str
    args: dict[str, object]


@dataclass(frozen=True)
class FinalText:
    text: str


@dataclass(frozen=True)
class WaitFor:
    """Pause the script until the event is set, to interleave concurrent analyses."""

    event: asyncio.Event


type Step = CallTool | FinalText | WaitFor | AgentFailure


class ScriptedLlm(BaseLlm):
    model: str = "scripted"
    _steps: list[Step] = PrivateAttr(default_factory=list)
    _requests: list[LlmRequest] = PrivateAttr(default_factory=list)
    _tool_results: list[types.FunctionResponse] = PrivateAttr(default_factory=list)

    @classmethod
    def with_steps(cls, steps: list[Step]) -> ScriptedLlm:
        llm = cls()
        llm._steps = list(steps)
        return llm

    @property
    def requests(self) -> list[LlmRequest]:
        return self._requests

    @property
    def tool_results(self) -> list[types.FunctionResponse]:
        return self._tool_results

    @property
    @override
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=False)

    @override
    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse]:
        self._requests.append(llm_request)
        latest = llm_request.contents[-1] if llm_request.contents else None
        if latest is not None and latest.role == "user":
            self._tool_results.extend(
                part.function_response
                for part in latest.parts or []
                if part.function_response is not None
            )
        while True:
            if not self._steps:
                raise AssertionError("the scripted model ran out of steps")
            step = self._steps.pop(0)
            match step:
                case WaitFor():
                    await step.event.wait()
                case AgentFailure():
                    raise step
                case CallTool():
                    call = types.FunctionCall(
                        id=f"call-{len(self._requests)}", name=step.name, args=step.args
                    )
                    yield LlmResponse(
                        content=types.Content(
                            role="model", parts=[types.Part(function_call=call)]
                        ),
                        partial=False,
                    )
                    return
                case FinalText():
                    yield LlmResponse(
                        content=types.Content(
                            role="model", parts=[types.Part(text=step.text)]
                        ),
                        partial=False,
                    )
                    return


class ScriptedModels:
    """A model factory that hands each invocation its own scripted model."""

    def __init__(
        self,
        analyses: dict[tuple[str, int], list[Step]] | None = None,
        organizer: list[Step] | None = None,
    ) -> None:
        self._analyses = analyses or {}
        self._organizer = organizer
        self.created: list[tuple[Invocation, ScriptedLlm]] = []

    def __call__(self, invocation: Invocation) -> ScriptedLlm:
        match invocation.role:
            case AgentRole.ANALYSIS:
                key = (invocation.session_id or "", invocation.part_index or 0)
                steps = self._analyses.get(key)
            case AgentRole.ORGANIZER:
                steps = self._organizer
        if steps is None:
            raise AssertionError(f"no script for {invocation}")
        llm = ScriptedLlm.with_steps(steps)
        self.created.append((invocation, llm))
        return llm

    def model_for(self, session_id: str, part_index: int = 1) -> ScriptedLlm:
        for invocation, llm in self.created:
            if (
                invocation.session_id == session_id
                and invocation.part_index == part_index
            ):
                return llm
        raise AssertionError(f"session {session_id} part {part_index} never ran")
