"""Builders for synthetic session files in the shape of the examples.

Every timestamp is passed in, so nothing depends on the clock.
"""

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Self

type JsonObject = dict[str, object]


def iso(at: datetime) -> str:
    return at.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ClaudeCodeSession:
    """A Claude Code JSONL file, built record by record."""

    def __init__(self, session_id: str, cwd: str) -> None:
        self.session_id = session_id
        self.cwd = cwd
        self._records: list[JsonObject] = []

    def _add(self, record_type: str, at: datetime, extra: JsonObject) -> Self:
        record: JsonObject = {
            "type": record_type,
            "sessionId": self.session_id,
            "cwd": self.cwd,
            "timestamp": iso(at),
            "uuid": str(uuid.UUID(int=len(self._records) + 1)),
        }
        record.update(extra)
        self._records.append(record)
        return self

    def _user(
        self, at: datetime, content: object, extra: JsonObject | None = None
    ) -> Self:
        return self._add(
            "user",
            at,
            {"message": {"role": "user", "content": content}} | (extra or {}),
        )

    def typed_prompt(self, at: datetime, text: str) -> Self:
        return self._user(at, text, {"origin": {"kind": "human"}})

    def user_text_from(self, at: datetime, text: str, origin_kind: str) -> Self:
        """User-role text that Claude Code didn't get from the user's keyboard."""
        return self._user(at, text, {"origin": {"kind": origin_kind}})

    def system_reminder(self, at: datetime, text: str) -> Self:
        return self._user(at, f"<system-reminder>\n{text}\n</system-reminder>")

    def meta_user(self, at: datetime, text: str) -> Self:
        return self._user(at, text, {"isMeta": True})

    def sidechain_user(self, at: datetime, text: str) -> Self:
        return self._user(at, text, {"isSidechain": True, "origin": {"kind": "human"}})

    def image(self, at: datetime) -> Self:
        block = {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": ""},
        }
        return self._user(at, [block], {"origin": {"kind": "human"}})

    def tool_result(
        self, at: datetime, tool_use_id: str, content: str, *, is_error: bool = False
    ) -> Self:
        block = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content,
            "is_error": is_error,
        }
        return self._user(at, [block])

    def _assistant(self, at: datetime, blocks: list[JsonObject]) -> Self:
        return self._add(
            "assistant", at, {"message": {"role": "assistant", "content": blocks}}
        )

    def assistant_text(self, at: datetime, text: str) -> Self:
        return self._assistant(at, [{"type": "text", "text": text}])

    def tool_use(
        self, at: datetime, tool_use_id: str, name: str, tool_input: JsonObject
    ) -> Self:
        return self._assistant(
            at,
            [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": name,
                    "input": tool_input,
                }
            ],
        )

    def attachment(self, at: datetime, text: str) -> Self:
        """An attachment record carrying instruction-file text, as Claude Code writes them."""
        return self._add(
            "attachment",
            at,
            {
                "attachment": {
                    "type": "instructions",
                    "path": "/Users/dev/AGENTS.md",
                    "text": text,
                }
            },
        )

    def write(self, path: Path, *, truncate_last_line: bool = False) -> Path:
        lines = [json.dumps(record) for record in self._records]
        if truncate_last_line and lines:
            lines[-1] = lines[-1][: len(lines[-1]) // 2]
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(lines)
        path.write_text(text if truncate_last_line else text + "\n", encoding="utf-8")
        return path


def _write_jsonl(records: list[JsonObject], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")
    return path


class CodexSession:
    """A Codex rollout file, built record by record.

    Start with `session_meta`; a file whose first record is anything else
    isn't a Codex session.
    """

    def __init__(self) -> None:
        self._records: list[JsonObject] = []

    def _add(self, record_type: str, at: datetime, payload: JsonObject) -> Self:
        self._records.append(
            {"timestamp": iso(at), "type": record_type, "payload": payload}
        )
        return self

    def session_meta(
        self,
        at: datetime,
        session_id: str,
        cwd: str,
        *,
        started_at: datetime | None = None,
        parent_thread_id: str | None = None,
    ) -> Self:
        payload: JsonObject = {
            "id": session_id,
            "timestamp": iso(started_at or at),
            "cwd": cwd,
            "originator": "codex_cli_rs",
        }
        if parent_thread_id is not None:
            payload["parent_thread_id"] = parent_thread_id
        return self._add("session_meta", at, payload)

    def user_message_item(self, at: datetime, text: str) -> Self:
        """What the user typed, as newer Codex versions record it."""
        item: JsonObject = {
            "type": "UserMessage",
            "id": str(uuid.UUID(int=len(self._records) + 1)),
            "content": [{"type": "text", "text": text, "text_elements": []}],
        }
        return self._add("event_msg", at, {"type": "item_completed", "item": item})

    def user_message_event(self, at: datetime, text: str) -> Self:
        """What the user typed, as older Codex versions record it."""
        return self._add(
            "event_msg", at, {"type": "user_message", "message": text, "images": []}
        )

    def context_message(self, at: datetime, role: str, text: str) -> Self:
        """A user- or developer-role message Codex adds, such as AGENTS.md text."""
        return self._add(
            "response_item",
            at,
            {
                "type": "message",
                "role": role,
                "content": [{"type": "input_text", "text": text}],
            },
        )

    def assistant_message(self, at: datetime, text: str) -> Self:
        return self._add(
            "response_item",
            at,
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            },
        )

    def function_call(
        self, at: datetime, call_id: str, name: str, arguments: str
    ) -> Self:
        return self._add(
            "response_item",
            at,
            {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
            },
        )

    def function_call_output(self, at: datetime, call_id: str, output: str) -> Self:
        return self._add(
            "response_item",
            at,
            {"type": "function_call_output", "call_id": call_id, "output": output},
        )

    def custom_tool_call(
        self, at: datetime, call_id: str, name: str, tool_input: str
    ) -> Self:
        return self._add(
            "response_item",
            at,
            {
                "type": "custom_tool_call",
                "call_id": call_id,
                "name": name,
                "input": tool_input,
            },
        )

    def custom_tool_call_output(
        self, at: datetime, call_id: str, output: str | list[str]
    ) -> Self:
        """Output as a string, or as a list of `input_text` blocks when given a list."""
        body: object = (
            output
            if isinstance(output, str)
            else [{"type": "input_text", "text": text} for text in output]
        )
        return self._add(
            "response_item",
            at,
            {"type": "custom_tool_call_output", "call_id": call_id, "output": body},
        )

    def local_shell_call(self, at: datetime, call_id: str, command: list[str]) -> Self:
        return self._add(
            "response_item",
            at,
            {
                "type": "local_shell_call",
                "call_id": call_id,
                "status": "completed",
                "action": {"type": "exec", "command": command},
            },
        )

    def local_shell_call_output(self, at: datetime, call_id: str, output: str) -> Self:
        return self._add(
            "response_item",
            at,
            {"type": "local_shell_call_output", "call_id": call_id, "output": output},
        )

    def reasoning(self, at: datetime, summary: str) -> Self:
        return self._add(
            "response_item",
            at,
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": summary}],
                "encrypted_content": "synthetic",
            },
        )

    def turn_aborted(self, at: datetime, reason: str) -> Self:
        return self._add("event_msg", at, {"type": "turn_aborted", "reason": reason})

    def write(self, path: Path) -> Path:
        return _write_jsonl(self._records, path)


# A user header ("--- 2026-10-17 09:40 UTC | user ---") is 35 characters and an
# assistant header 40. With the newline after the header and the blank line
# between messages, these text lengths make every message 900 characters of the
# rendered view: 300 estimated tokens.
_USER_TEXT_LENGTH = 900 - 2 - 1 - 35
_ASSISTANT_TEXT_LENGTH = 900 - 2 - 1 - 40


def _filler(index: int, length: int) -> str:
    label = f"Message {index}: "
    return label + "x" * (length - len(label))


def large_claude_code_session(
    path: Path,
    estimated_tokens: int,
    *,
    start: datetime,
    session_id: str = "5e55e55e-0000-4000-8000-000000000001",
    cwd: str = "/Users/dev/Projects/large",
) -> Path:
    """Write a session whose view is about `estimated_tokens` large.

    Typed prompts and assistant replies alternate, one minute apart, each
    300 estimated tokens long.
    """
    session = ClaudeCodeSession(session_id, cwd)
    for index in range(estimated_tokens // 300):
        at = start + timedelta(minutes=index)
        if index % 2 == 0:
            session.typed_prompt(at, _filler(index, _USER_TEXT_LENGTH))
        else:
            session.assistant_text(at, _filler(index, _ASSISTANT_TEXT_LENGTH))
    return session.write(path)
