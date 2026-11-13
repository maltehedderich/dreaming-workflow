"""Repeat runs send only sessions that are new, changed, or failed last time."""

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from dreaming_workflow import cli
from dreaming_workflow.agents import AgentFailure, Failure, FailureReason, Invocation
from dreaming_workflow.state import DreamRecord
from tests.conftest import ExampleSessions
from tests.support.examples import (
    EXAMPLE_PROJECT_DIR,
    PASSWORD_LIMIT,
    RUN_START,
    UV_SETUP,
    claude_code_example,
    one_fact_each,
)
from tests.support.scripted_llm import (
    FinalText,
    ScriptedLlm,
    ScriptedModels,
    organizer_done,
)
from tests.support.sessions import ClaudeCodeSession

NEXT_DAY = RUN_START + timedelta(days=1)


def run_cli(
    memory: Path,
    sessions: ExampleSessions,
    models: ScriptedModels | None,
    now: datetime = RUN_START,
) -> int:
    """Run over the examples; `models` None means no model may run."""

    def no_model(invocation: Invocation) -> ScriptedLlm:
        raise AssertionError(f"no model may run, but {invocation} started")

    return cli.main(
        [
            "--memory",
            str(memory),
            "--since",
            "2026-10-01",
            "--claude-code-dir",
            str(sessions.claude_code),
            "--codex-dir",
            str(sessions.codex),
        ],
        model_factory=models or no_model,
        now=now,
    )


def first_run(memory: Path, sessions: ExampleSessions) -> None:
    models = ScriptedModels(analyses=one_fact_each(), organizer=organizer_done())
    assert run_cli(memory, sessions, models) == 0


def test_a_repeat_run_with_nothing_new_sends_nothing(
    example_sessions: ExampleSessions,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    memory = tmp_path / "memory"
    first_run(memory, example_sessions)
    capsys.readouterr()

    exit_code = run_cli(memory, example_sessions, None, NEXT_DAY)

    report = capsys.readouterr().out
    assert exit_code == 0
    assert re.search(
        r"^  skipped +6  \(subthread: 1, already-analyzed: 5\)$", report, re.MULTILINE
    )
    assert report.endswith("\n\nNothing to dream over.\n")


def test_appended_records_select_only_that_session(
    example_sessions: ExampleSessions,
    tmp_path: Path,
) -> None:
    memory = tmp_path / "memory"
    first_run(memory, example_sessions)
    path = claude_code_example(example_sessions.claude_code, UV_SETUP)
    # Resuming a session appends to its file. The new records lie more than an
    # hour before the next run, so the session isn't active.
    appended = (
        ClaudeCodeSession(UV_SETUP, EXAMPLE_PROJECT_DIR)
        .typed_prompt(RUN_START, "Does the hook also block uv pip install?")
        .assistant_text(RUN_START, "Yes, it matches pip install anywhere.")
        .write(tmp_path / "appended.jsonl")
    )
    with path.open("ab") as session:
        session.write(appended.read_bytes())
    models = ScriptedModels(
        analyses={(UV_SETUP, 1): [FinalText("Nothing new to record.")]},
        organizer=organizer_done(),
    )

    assert run_cli(memory, example_sessions, models, NEXT_DAY) == 0

    assert [invocation.session_id for invocation in models.analyses_created] == [
        UV_SETUP
    ]
    assert DreamRecord.load(memory).sessions[path].run_id == "20261111T213800Z"


def test_a_failed_session_is_selected_again(
    example_sessions: ExampleSessions,
    tmp_path: Path,
) -> None:
    memory = tmp_path / "memory"
    analyses = one_fact_each()
    analyses[(PASSWORD_LIMIT, 1)] = [AgentFailure(Failure(FailureReason.RATE_LIMITED))]
    failing = ScriptedModels(analyses=analyses, organizer=organizer_done())
    assert run_cli(memory, example_sessions, failing) == 1

    retry = ScriptedModels(
        analyses={(PASSWORD_LIMIT, 1): [FinalText("Nothing to record.")]},
        organizer=organizer_done(),
    )

    assert run_cli(memory, example_sessions, retry, NEXT_DAY) == 0
    assert [invocation.session_id for invocation in retry.analyses_created] == [
        PASSWORD_LIMIT
    ]
