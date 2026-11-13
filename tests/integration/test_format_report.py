"""The format check at the end of a run: every violation in the report, and the exit."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dreaming_workflow import cli
from dreaming_workflow.memory.document import Citation
from dreaming_workflow.sessions import Tool
from tests.support.examples import RUN_START
from tests.support.memory import fact, write_index, write_memory_file
from tests.support.scripted_llm import (
    FinalText,
    ScriptedModels,
    Step,
    create_file_call,
    organizer_done,
)
from tests.support.sessions import ClaudeCodeSession

SESSION_ID = "5e55e55e-0000-4000-8000-0000000000a9"
PROJECT = "/Users/dev/Projects/app"
AT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def dream(memory: Path, sessions: Path, analysis: list[Step]) -> int:
    session_file = (
        ClaudeCodeSession(SESSION_ID, PROJECT)
        .typed_prompt(AT, "Which Python version does the app use?")
        .assistant_text(AT, "Python 3.15.")
        .write(sessions / f"{SESSION_ID}.jsonl")
    )
    return cli.main(
        [
            "--memory",
            str(memory),
            "--since",
            "2026-10-01",
            "--session",
            str(session_file),
        ],
        model_factory=ScriptedModels(
            analyses={(SESSION_ID, 1): analysis}, organizer=organizer_done()
        ),
        now=RUN_START,
    )


def test_violations_left_after_the_organizer_are_listed_and_fail_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    memory = tmp_path / "memory"
    write_memory_file(
        memory,
        "release-checklist",
        f"# Release checklist\n\n{fact('Tag the release first.')}\nSee [[deploy-steps]].\n",
    )
    write_memory_file(
        memory, "shell-aliases", f"# Shell aliases\n\n{fact('`ll` lists long.')}"
    )
    write_index(
        memory,
        {"Development": {None: [("release-checklist", "Steps before a release.")]}},
    )

    exit_code = dream(memory, tmp_path / "sessions", [FinalText("Nothing to record.")])

    assert exit_code == 1
    assert (
        "\n  format check              2 violations\n"
        "  release-checklist.md  broken-link\n"
        "  shell-aliases.md  index-entry-missing\n"
    ) in capsys.readouterr().out


def test_a_clean_run_reports_no_violations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    citation = Citation(Tool.CLAUDE_CODE, SESSION_ID, PROJECT, AT).render()

    exit_code = dream(
        tmp_path / "memory",
        tmp_path / "sessions",
        [
            create_file_call(
                "python-version",
                f"# Python\n\n- The app uses Python 3.15. {citation} "
                "[scope: Development]\n",
            ),
            FinalText("Recorded one fact."),
        ],
    )

    assert exit_code == 0
    assert "\n  format check              no violations\n" in capsys.readouterr().out
