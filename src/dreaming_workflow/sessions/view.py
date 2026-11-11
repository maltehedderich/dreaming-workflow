from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

PART_TOKEN_LIMIT = 40_000


class MessageKind(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool-call"
    TOOL_RESULT = "tool-result"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class ConversationMessage:
    at: datetime
    kind: MessageKind
    text: str
    tool_name: str | None = None
    is_error: bool = False


def estimate_tokens(text: str) -> int:
    # Three characters per token keeps the estimate above what Claude Haiku 5.5
    # really counts, so parts stay well below the 100,000-token price step.
    return -(-len(text) // 3)


def _header(message: ConversationMessage) -> str:
    match message.kind:
        case MessageKind.TOOL_CALL:
            label = f"tool call: {message.tool_name}"
        case MessageKind.TOOL_RESULT:
            label = "tool result (error)" if message.is_error else "tool result"
        case _:
            label = message.kind.value
    return f"--- {message.at:%Y-%m-%d %H:%M} UTC | {label} ---"


def render(messages: tuple[ConversationMessage, ...]) -> str:
    return "\n\n".join(f"{_header(message)}\n{message.text}" for message in messages)


@dataclass(frozen=True)
class ConversationView:
    messages: tuple[ConversationMessage, ...]

    @property
    def estimated_tokens(self) -> int:
        return estimate_tokens(render(self.messages))


@dataclass(frozen=True)
class Part:
    index: int
    count: int
    messages: tuple[ConversationMessage, ...]
    estimated_tokens: int
    first_at: datetime
    last_at: datetime


def split_into_parts(view: ConversationView) -> list[Part]:
    if not view.messages:
        raise ValueError("a view without messages has no parts")
    estimated_tokens = view.estimated_tokens
    if estimated_tokens > PART_TOKEN_LIMIT:
        raise NotImplementedError("splitting a view into several parts")
    return [
        Part(
            index=1,
            count=1,
            messages=view.messages,
            estimated_tokens=estimated_tokens,
            first_at=view.messages[0].at,
            last_at=view.messages[-1].at,
        )
    ]
