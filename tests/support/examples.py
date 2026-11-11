"""Paths and clock values for tests that run over the cleaned example sessions."""

from datetime import UTC, datetime
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "transcripts"
CLAUDE_CODE_PROJECTS = EXAMPLES / "claude-code" / "projects"
CODEX_SESSIONS = EXAMPLES / "codex" / "sessions"

# The run start used by tests over the examples, and a window start before every example.
RUN_START = datetime(2026, 11, 10, 21, 38, tzinfo=UTC)
SINCE = datetime(2026, 10, 1, tzinfo=UTC)

CONTEXT7_CHECK = "90f95193-2c91-4a42-a506-930d4c964c45"
CTX7_SETUP = "40726b6c-49a1-400e-ad5e-9192e635ceb6"
UV_SETUP = "03745422-d356-454d-9d6d-db0fe9b54515"
EXAMPLE_PROJECT_DIR = "/Users/dev/Projects"


def claude_code_example(projects: Path, session_id: str) -> Path:
    return projects / "-Users-dev-Projects" / f"{session_id}.jsonl"
