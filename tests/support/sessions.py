"""Builders for synthetic session files in the shape of the examples.

Every timestamp is passed in, so nothing depends on the clock.
"""

import json
import uuid
from datetime import datetime
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
