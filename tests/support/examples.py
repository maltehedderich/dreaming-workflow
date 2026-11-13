"""Paths and clock values for tests that run over the cleaned example sessions."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dreaming_workflow.memory.document import Citation
from dreaming_workflow.sessions import Tool

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


MAILARKIV = "eef4a695-6c41-4e5f-ba21-c3b858881bd1"
MAILARKIV_SUBTHREAD = "4cea5169-365b-4853-93c8-e00a4221cc20"
PASSWORD_LIMIT = "0bcd2a68-df00-491e-a9b7-f531e448d793"
CODEX_PROJECT_DIR = "/Users/dev/Projects/mailarkiv"


def codex_example(sessions: Path, session_id: str) -> Path:
    [path] = sessions.glob(f"*/*/*/rollout-*-{session_id}.jsonl")
    return path


@dataclass(frozen=True)
class SelectedExample:
    """An example session a run over the examples selects."""

    tool: Tool
    session_id: str
    project_dir: str
    # The minute of the first message the user typed, read from the file by
    # hand; it lies inside the session's only part.
    first_typed_at: datetime

    def citation(self) -> str:
        return Citation(
            self.tool, self.session_id, self.project_dir, self.first_typed_at
        ).render()


# In the order a run selects them: oldest last activity first.
SELECTED_EXAMPLES = (
    SelectedExample(
        Tool.CLAUDE_CODE,
        CONTEXT7_CHECK,
        EXAMPLE_PROJECT_DIR,
        datetime(2026, 10, 17, 9, 18, tzinfo=UTC),
    ),
    SelectedExample(
        Tool.CLAUDE_CODE,
        CTX7_SETUP,
        EXAMPLE_PROJECT_DIR,
        datetime(2026, 10, 17, 9, 33, tzinfo=UTC),
    ),
    SelectedExample(
        Tool.CLAUDE_CODE,
        UV_SETUP,
        EXAMPLE_PROJECT_DIR,
        datetime(2026, 10, 17, 9, 40, tzinfo=UTC),
    ),
    SelectedExample(
        Tool.CODEX,
        MAILARKIV,
        CODEX_PROJECT_DIR,
        datetime(2026, 11, 6, 20, 2, tzinfo=UTC),
    ),
    SelectedExample(
        Tool.CODEX,
        PASSWORD_LIMIT,
        CODEX_PROJECT_DIR,
        datetime(2026, 11, 7, 21, 21, tzinfo=UTC),
    ),
)
