"""Two analyses in one group change the same memory file without losing facts."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from dreaming_workflow import cli
from dreaming_workflow.memory.document import Citation
from dreaming_workflow.sessions import Tool
from tests.support.examples import RUN_START
from tests.support.scripted_llm import (
    CallTool,
    FinalText,
    ScriptedModels,
    Signal,
    WaitFor,
    create_file_call,
)
from tests.support.sessions import ClaudeCodeSession

FIRST_ID = "5e55e55e-0000-4000-8000-0000000000a7"
SECOND_ID = "5e55e55e-0000-4000-8000-0000000000b8"
PROJECT = "/Users/dev/Projects/app"
FIRST_AT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
SECOND_AT = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


def write_session(directory: Path, session_id: str, at: datetime) -> Path:
    return (
        ClaudeCodeSession(session_id, PROJECT)
        .typed_prompt(at, "Which Python version does the app use?")
        .assistant_text(at, "Python 3.15.")
        .write(directory / f"{session_id}.jsonl")
    )


def test_both_sessions_facts_survive_interleaved_writes(tmp_path: Path) -> None:
    first_file = write_session(tmp_path / "sessions", FIRST_ID, FIRST_AT)
    second_file = write_session(tmp_path / "sessions", SECOND_ID, SECOND_AT)
    first_source = Citation(Tool.CLAUDE_CODE, FIRST_ID, PROJECT, FIRST_AT).render()
    second_source = Citation(Tool.CLAUDE_CODE, SECOND_ID, PROJECT, SECOND_AT).render()
    first_fact = f"- The app uses Python. {first_source} [scope: Development]\n"
    edited_fact = f"- The app uses Python 3.15. {first_source} [scope: Development]\n"
    second_fact = (
        f"- The app pins Python in mise.toml. {second_source} [scope: Development]\n"
    )
    created = asyncio.Event()
    appended = asyncio.Event()
    models = ScriptedModels(
        analyses={
            (FIRST_ID, 1): [
                create_file_call("python", f"# Python\n\n{first_fact}"),
                Signal(created),
                WaitFor(appended),
                CallTool(
                    "edit_file",
                    {"slug": "python", "old_text": first_fact, "new_text": edited_fact},
                ),
                FinalText("Recorded the version."),
            ],
            (SECOND_ID, 1): [
                WaitFor(created),
                create_file_call("python", f"# Python\n\n{second_fact}"),
                CallTool("append_to_file", {"slug": "python", "text": second_fact}),
                Signal(appended),
                FinalText("Recorded the pin."),
            ],
        }
    )
    memory = tmp_path / "memory"

    exit_code = cli.main(
        [
            "--memory",
            str(memory),
            "--since",
            "2026-10-01",
            "--session",
            str(first_file),
            "--session",
            str(second_file),
        ],
        model_factory=models,
        now=RUN_START,
    )

    assert exit_code == 0
    first_results = [r.response for r in models.model_for(FIRST_ID).tool_results]
    second_results = [r.response for r in models.model_for(SECOND_ID).tool_results]
    assert [result and result["status"] for result in first_results] == ["ok", "ok"]
    assert [result and result["status"] for result in second_results] == [
        "refused",
        "ok",
    ]
    text = (memory / "python.md").read_text()
    assert edited_fact in text
    assert second_fact in text
    assert first_fact not in text
