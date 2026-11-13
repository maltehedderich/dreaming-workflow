import json
import shlex
from collections.abc import Iterator
from datetime import datetime

from dreaming_workflow.sessions.jsonl import (
    IMAGE_TEXT,
    UNKNOWN_PROJECT_DIR,
    Record,
    as_dict,
    as_str,
    parse_timestamp,
    read_records,
)
from dreaming_workflow.sessions.model import Session, SessionFile, Tool
from dreaming_workflow.sessions.view import (
    ConversationMessage,
    ConversationView,
    MessageKind,
)

_TOOL_CALLS = ("function_call", "custom_tool_call", "local_shell_call")
_TOOL_OUTPUTS = (
    "function_call_output",
    "custom_tool_call_output",
    "local_shell_call_output",
)
_IMAGE_BLOCKS = ("image", "input_image", "local_image")


def _joined_text(blocks: object, text_types: tuple[str, ...]) -> str:
    """Join the text of content blocks whose type is in `text_types`; images become a placeholder."""
    if not isinstance(blocks, list):
        return ""
    pieces: list[str] = []
    for block in blocks:
        block = as_dict(block)
        if block is None:
            continue
        block_type = block.get("type")
        text = as_str(block.get("text"))
        if block_type in text_types and text is not None:
            pieces.append(text)
        elif block_type in _IMAGE_BLOCKS:
            pieces.append(IMAGE_TEXT)
    return "\n".join(pieces)


def _output_text(output: object) -> str:
    if isinstance(output, str):
        return output
    return _joined_text(output, ("input_text", "output_text", "text"))


def _tool_call(payload: Record, at: datetime) -> ConversationMessage:
    match payload.get("type"):
        case "local_shell_call":
            action = as_dict(payload.get("action")) or {}
            command = action.get("command")
            words = (
                [word for word in command if isinstance(word, str)]
                if isinstance(command, list)
                else []
            )
            return ConversationMessage(
                at=at,
                kind=MessageKind.TOOL_CALL,
                text=shlex.join(words),
                tool_name="shell",
            )
        case "function_call":
            arguments = payload.get("arguments")
            text = (
                arguments
                if isinstance(arguments, str)
                else json.dumps(arguments, separators=(",", ":"), ensure_ascii=False)
            )
        case _:
            text = as_str(payload.get("input")) or ""
    return ConversationMessage(
        at=at,
        kind=MessageKind.TOOL_CALL,
        text=text,
        tool_name=as_str(payload.get("name")) or "unknown",
    )


def _response_item(payload: Record, at: datetime) -> Iterator[ConversationMessage]:
    payload_type = payload.get("type")
    if payload_type == "message":
        # User and developer messages carry AGENTS.md, environment context, and
        # permission instructions; what the user typed comes from UserMessage items.
        if payload.get("role") != "assistant":
            return
        text = _joined_text(payload.get("content"), ("output_text",))
        if text.strip():
            yield ConversationMessage(at=at, kind=MessageKind.ASSISTANT, text=text)
    elif payload_type in _TOOL_CALLS:
        yield _tool_call(payload, at)
    elif payload_type in _TOOL_OUTPUTS:
        yield ConversationMessage(
            at=at,
            kind=MessageKind.TOOL_RESULT,
            text=_output_text(payload.get("output")),
        )


def _user_message_item(payload: Record, at: datetime) -> ConversationMessage | None:
    item = as_dict(payload.get("item"))
    if item is None or item.get("type") != "UserMessage":
        return None
    text = _joined_text(item.get("content"), ("text",))
    if not text.strip():
        return None
    return ConversationMessage(at=at, kind=MessageKind.USER, text=text)


def _older_user_message(payload: Record, at: datetime) -> ConversationMessage | None:
    text = as_str(payload.get("message"))
    if text is None or not text.strip():
        return None
    return ConversationMessage(at=at, kind=MessageKind.USER, text=text)


def parse_codex(file: SessionFile) -> Session | None:
    """Read a Codex rollout file, or return None if it isn't one."""
    records = read_records(file)
    first = next(records, None)
    if first is None or first.get("type") != "session_meta":
        return None
    meta = as_dict(first.get("payload")) or {}
    session_id = as_str(meta.get("id"))
    if session_id is None:
        return None
    started_at = parse_timestamp(meta.get("timestamp"))
    last_activity_at = parse_timestamp(first.get("timestamp"))
    # Each message, and whether it came from an older `user_message` event.
    # Older files record typed input only that way; newer files have both, so
    # those events count only when the file has no UserMessage item.
    entries: list[tuple[ConversationMessage, bool]] = []
    has_user_message_items = False
    for record in records:
        at = parse_timestamp(record.get("timestamp"))
        if at is None:
            continue
        last_activity_at = at if last_activity_at is None else max(last_activity_at, at)
        payload = as_dict(record.get("payload"))
        if payload is None:
            continue
        match record.get("type"), payload.get("type"):
            case "response_item", _:
                entries.extend(
                    (message, False) for message in _response_item(payload, at)
                )
            case "event_msg", "item_completed":
                message = _user_message_item(payload, at)
                if message is not None:
                    has_user_message_items = True
                    entries.append((message, False))
            case "event_msg", "user_message":
                message = _older_user_message(payload, at)
                if message is not None:
                    entries.append((message, True))
            case "event_msg", "turn_aborted":
                reason = as_str(payload.get("reason")) or "unknown"
                interrupted = ConversationMessage(
                    at=at,
                    kind=MessageKind.INTERRUPTED,
                    text=f"turn interrupted ({reason})",
                )
                entries.append((interrupted, False))
            case _:
                pass
    messages = tuple(
        message
        for message, from_older_event in entries
        if not (from_older_event and has_user_message_items)
    )
    started_at = started_at or last_activity_at
    if started_at is None or last_activity_at is None:
        return None
    return Session(
        file=file,
        tool=Tool.CODEX,
        session_id=session_id,
        project_dir=as_str(meta.get("cwd")) or UNKNOWN_PROJECT_DIR,
        started_at=started_at,
        last_activity_at=last_activity_at,
        parent_thread_id=as_str(meta.get("parent_thread_id")),
        view=ConversationView(messages=messages),
    )
