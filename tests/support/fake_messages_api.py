"""A fake Claude Messages API on an httpx2 transport, for driving the real anthropic SDK."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx2
from anthropic import AsyncAnthropic

from dreaming_workflow.agents.claude_model import MAX_RETRIES, MODEL, REQUEST_TIMEOUT

type JsonObject = dict[str, object]

# Not a credential: the fake transport never checks it.
DUMMY_API_KEY = "fake-messages-api-key"


@dataclass(frozen=True)
class MessageReply:
    content: list[JsonObject]
    stop_reason: str = "end_turn"
    usage: JsonObject = field(
        default_factory=lambda: {"input_tokens": 10, "output_tokens": 5}
    )


@dataclass(frozen=True)
class StatusReply:
    status: int
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TimeoutReply:
    pass


type FakeReply = MessageReply | StatusReply | TimeoutReply
type Responder = Callable[[JsonObject], FakeReply]


def text_block(text: str) -> JsonObject:
    return {"type": "text", "text": text}


def thinking_block(thinking: str, signature: str) -> JsonObject:
    return {"type": "thinking", "thinking": thinking, "signature": signature}


def redacted_thinking_block(data: str) -> JsonObject:
    return {"type": "redacted_thinking", "data": data}


def tool_use_block(tool_use_id: str, name: str, tool_input: JsonObject) -> JsonObject:
    return {"type": "tool_use", "id": tool_use_id, "name": name, "input": tool_input}


class FakeMessagesApi:
    """Records every request body and answers each through `responder`.

    The responder sees the request body, so concurrent requests get answers
    that depend on what they carry rather than on arrival order.
    """

    def __init__(self, responder: Responder) -> None:
        self._responder = responder
        self.requests: list[JsonObject] = []

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        reply = self._responder(body)
        match reply:
            case MessageReply():
                return httpx2.Response(
                    200,
                    json={
                        "id": f"msg_{len(self.requests)}",
                        "type": "message",
                        "role": "assistant",
                        "model": MODEL,
                        "content": reply.content,
                        "stop_reason": reply.stop_reason,
                        "stop_sequence": None,
                        "usage": reply.usage,
                    },
                )
            case StatusReply():
                error = {
                    "type": "error",
                    "error": {"type": "api_error", "message": "fake"},
                }
                return httpx2.Response(reply.status, headers=reply.headers, json=error)
            case TimeoutReply():
                raise httpx2.ReadTimeout("fake timeout", request=request)

    def client(self) -> AsyncAnthropic:
        """A client with create_client()'s timeout and retry settings, on this fake."""
        return AsyncAnthropic(
            api_key=DUMMY_API_KEY,
            timeout=REQUEST_TIMEOUT,
            max_retries=MAX_RETRIES,
            http_client=httpx2.AsyncClient(
                transport=httpx2.MockTransport(self._handle)
            ),
        )
