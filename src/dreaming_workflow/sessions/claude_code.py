import json
from collections.abc import Iterator
from datetime import UTC, datetime

from dreaming_workflow.sessions.model import Session, SessionFile, Tool
from dreaming_workflow.sessions.view import (
    ConversationMessage,
    ConversationView,
    MessageKind,
)

# User text starting with one of these was written by Claude Code, not typed by the user.
HARNESS_TAGS = (
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<local-command-caveat>",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "<system-reminder>",
    "<task-notification>",
)
IMAGE_TEXT = "[image]"
UNKNOWN_PROJECT_DIR = "unknown"

type Record = dict[str, object]


def read_records(file: SessionFile) -> Iterator[Record]:
    """Yield each line that parses as a JSON object; skip the rest, such as a partial last line."""
    with file.path.open("rb") as lines:
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_typed_by_user(record: Record) -> bool:
    origin = record.get("origin")
    if not isinstance(origin, dict) or "kind" not in origin:
        return True
    kind = origin["kind"]
    return isinstance(kind, str) and kind == "human"


def _is_harness_text(text: str) -> bool:
    return text.strip().startswith(HARNESS_TAGS)


def _block_text(content: object) -> str:
    """Text of a tool result: a string, or its text and image blocks."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    pieces: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if block.get("type") == "text" and isinstance(text, str):
            pieces.append(text)
        elif block.get("type") == "image":
            pieces.append(IMAGE_TEXT)
    return "\n".join(pieces)


def _user_messages(record: Record, at: datetime) -> Iterator[ConversationMessage]:
    message = record.get("message")
    if not isinstance(message, dict):
        return
    content = message.get("content")
    typed_by_user = _is_typed_by_user(record)
    if isinstance(content, str):
        if typed_by_user and content.strip() and not _is_harness_text(content):
            yield ConversationMessage(at=at, kind=MessageKind.USER, text=content)
        return
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        match block.get("type"):
            case "text":
                text = block.get("text")
                if (
                    typed_by_user
                    and isinstance(text, str)
                    and text.strip()
                    and not _is_harness_text(text)
                ):
                    yield ConversationMessage(at=at, kind=MessageKind.USER, text=text)
            case "image":
                if typed_by_user:
                    yield ConversationMessage(
                        at=at, kind=MessageKind.USER, text=IMAGE_TEXT
                    )
            case "tool_result":
                yield ConversationMessage(
                    at=at,
                    kind=MessageKind.TOOL_RESULT,
                    text=_block_text(block.get("content")),
                    is_error=block.get("is_error") is True,
                )
            case _:
                pass


def _assistant_messages(record: Record, at: datetime) -> Iterator[ConversationMessage]:
    message = record.get("message")
    if not isinstance(message, dict):
        return
    content = message.get("content")
    if isinstance(content, str):
        if content.strip():
            yield ConversationMessage(at=at, kind=MessageKind.ASSISTANT, text=content)
        return
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        match block.get("type"):
            case "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    yield ConversationMessage(
                        at=at, kind=MessageKind.ASSISTANT, text=text
                    )
            case "tool_use":
                name = block.get("name")
                yield ConversationMessage(
                    at=at,
                    kind=MessageKind.TOOL_CALL,
                    text=json.dumps(
                        block.get("input"), separators=(",", ":"), ensure_ascii=False
                    ),
                    tool_name=name if isinstance(name, str) else "unknown",
                )
            case _:
                # Thinking blocks and anything unknown stay out of the view.
                pass


def _messages(record: Record, at: datetime) -> Iterator[ConversationMessage]:
    if (
        record.get("isMeta")
        or record.get("isSidechain")
        or record.get("isCompactSummary")
    ):
        return
    match record.get("type"):
        case "user":
            yield from _user_messages(record, at)
        case "assistant":
            yield from _assistant_messages(record, at)
        case _:
            pass


def parse_claude_code(file: SessionFile) -> Session | None:
    """Read a Claude Code session file, or return None if it isn't one."""
    session_id: str | None = None
    project_dir: str | None = None
    started_at: datetime | None = None
    last_activity_at: datetime | None = None
    messages: list[ConversationMessage] = []
    for record in read_records(file):
        record_session_id = record.get("sessionId")
        if (
            session_id is None
            and isinstance(record_session_id, str)
            and record.get("type") in ("user", "assistant")
        ):
            session_id = record_session_id
        cwd = record.get("cwd")
        if project_dir is None and isinstance(cwd, str):
            project_dir = cwd
        at = parse_timestamp(record.get("timestamp"))
        if at is None:
            continue
        started_at = at if started_at is None else min(started_at, at)
        last_activity_at = at if last_activity_at is None else max(last_activity_at, at)
        messages.extend(_messages(record, at))
    if session_id is None or started_at is None or last_activity_at is None:
        return None
    return Session(
        file=file,
        tool=Tool.CLAUDE_CODE,
        session_id=session_id,
        project_dir=project_dir or UNKNOWN_PROJECT_DIR,
        started_at=started_at,
        last_activity_at=last_activity_at,
        parent_thread_id=None,
        view=ConversationView(messages=tuple(messages)),
    )
