"""Writers, citations, and facts for tests of memory writes."""

from datetime import UTC, datetime

from dreaming_workflow.memory import Writer
from dreaming_workflow.memory.document import Citation
from dreaming_workflow.sessions import Tool

SESSION_ID = "5e55e55e-0000-4000-8000-0000000000a1"
OTHER_SESSION_ID = "5e55e55e-0000-4000-8000-0000000000b2"
PROJECT_DIR = "/Users/dev/Projects/app"
PART_START = datetime(2026, 11, 2, 10, 0, 12, tzinfo=UTC)
PART_END = datetime(2026, 11, 2, 10, 30, 45, tzinfo=UTC)


def analysis_writer(
    session_id: str = SESSION_ID,
    *,
    tool: Tool = Tool.CLAUDE_CODE,
    project_dir: str = PROJECT_DIR,
    first_at: datetime = PART_START,
    last_at: datetime = PART_END,
) -> Writer:
    return Writer.analysis(tool, session_id, project_dir, first_at, last_at)


def source(
    session_id: str = SESSION_ID,
    at: datetime = PART_START,
    *,
    tool: Tool = Tool.CLAUDE_CODE,
    project_dir: str = PROJECT_DIR,
) -> str:
    minute = at.replace(second=0, microsecond=0)
    return Citation(tool, session_id, project_dir, minute).render()


def fact(statement: str, citation: str | None = None) -> str:
    return f"- {statement} {citation or source()} [scope: Development]\n"
