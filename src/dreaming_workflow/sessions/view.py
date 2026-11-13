from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

PART_TOKEN_LIMIT = 40_000
TOO_LARGE_TOKENS = 400_000
CHARACTERS_PER_TOKEN = 3
_PART_CHARACTER_LIMIT = PART_TOKEN_LIMIT * CHARACTERS_PER_TOKEN
_SEPARATOR = "\n\n"


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
    return _tokens_for(len(text))


def _tokens_for(characters: int) -> int:
    return -(-characters // CHARACTERS_PER_TOKEN)


def _header(message: ConversationMessage) -> str:
    match message.kind:
        case MessageKind.TOOL_CALL:
            label = f"tool call: {message.tool_name}"
        case MessageKind.TOOL_RESULT:
            label = "tool result (error)" if message.is_error else "tool result"
        case _:
            label = message.kind.value
    return f"--- {message.at:%Y-%m-%d %H:%M} UTC | {label} ---"


def _render_message(message: ConversationMessage) -> str:
    return f"{_header(message)}\n{message.text}"


def render(messages: tuple[ConversationMessage, ...]) -> str:
    return _SEPARATOR.join(_render_message(message) for message in messages)


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


def is_too_large(view: ConversationView) -> bool:
    return view.estimated_tokens > TOO_LARGE_TOKENS


def _removal_marker(removed: int) -> str:
    return f"[… {removed:,} characters removed by dreaming-workflow …]"


def _shorten_to_fit(message: ConversationMessage) -> ConversationMessage:
    """Keep the start and end of a message too large for a part on its own."""
    budget = _PART_CHARACTER_LIMIT - len(_header(message)) - 1
    text = message.text
    if len(text) <= budget:
        return message
    # The marker's length depends on the count it states; the original length
    # bounds that count, so this size always leaves room for it.
    kept = budget - len(_removal_marker(len(text))) - 2
    head = text[: -(-kept // 2)]
    tail = text[len(text) - kept // 2 :]
    shortened = f"{head}\n{_removal_marker(len(text) - kept)}\n{tail}"
    return replace(message, text=shortened)


def _part(index: int, count: int, messages: tuple[ConversationMessage, ...]) -> Part:
    return Part(
        index=index,
        count=count,
        messages=messages,
        estimated_tokens=estimate_tokens(render(messages)),
        first_at=messages[0].at,
        last_at=messages[-1].at,
    )


def split_into_parts(view: ConversationView) -> list[Part]:
    """Split a view between messages into parts of at most 40,000 estimated tokens.

    Each part is filled in order before the next one starts. A message that
    can't fit in a part on its own is shortened in the middle.
    """
    if not view.messages:
        raise ValueError("a view without messages has no parts")
    groups: list[list[ConversationMessage]] = [[]]
    characters = 0
    for message in view.messages:
        message = _shorten_to_fit(message)
        size = len(_render_message(message))
        if groups[-1] and characters + len(_SEPARATOR) + size > _PART_CHARACTER_LIMIT:
            groups.append([])
            characters = 0
        characters += size if not groups[-1] else len(_SEPARATOR) + size
        groups[-1].append(message)
    return [
        _part(index, len(groups), tuple(group))
        for index, group in enumerate(groups, start=1)
    ]
