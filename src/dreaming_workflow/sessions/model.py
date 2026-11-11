from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from dreaming_workflow.sessions.view import ConversationView


class Tool(StrEnum):
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"


@dataclass(frozen=True)
class SessionFile:
    path: Path
    expected_tool: Tool | None
    size: int
    mtime_ns: int

    @classmethod
    def at(cls, path: Path, expected_tool: Tool | None) -> SessionFile:
        """Stat a session file. `expected_tool` is None for files the user named."""
        absolute = path.absolute()
        stat = absolute.stat()
        return cls(
            path=absolute,
            expected_tool=expected_tool,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )


@dataclass(frozen=True)
class Session:
    file: SessionFile
    tool: Tool
    session_id: str
    project_dir: str
    started_at: datetime
    last_activity_at: datetime
    parent_thread_id: str | None
    view: ConversationView
