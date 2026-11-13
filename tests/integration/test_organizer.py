"""The organizer pass: what it receives, and how files wait for it across runs."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dreaming_workflow import cli
from dreaming_workflow.agents import AgentFailure, Failure, FailureReason, Invocation
from dreaming_workflow.memory.document import Citation
from dreaming_workflow.sessions import Tool
from dreaming_workflow.state import DreamRecord
from tests.conftest import ExampleSessions
from tests.support.examples import RUN_START, SELECTED_EXAMPLES, one_fact_each
from tests.support.memory import seeded_memory
from tests.support.scripted_llm import (
    CallTool,
    FinalText,
    ScriptedLlm,
    ScriptedModels,
    create_file_call,
    first_user_text,
    organizer_done,
)
from tests.support.sessions import ClaudeCodeSession

PROJECT = "/Users/dev/Projects/app"
PYTHON_SESSION = "5e55e55e-0000-4000-8000-0000000000a7"
DEPLOY_SESSION = "5e55e55e-0000-4000-8000-0000000000a8"
PYTHON_AT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
DEPLOY_AT = datetime(2026, 11, 2, 9, 30, tzinfo=UTC)


def received_slugs(organizer: ScriptedLlm) -> list[str]:
    """The slugs the organizer's first message lists as received, in order."""
    return [
        line.removeprefix("- ").split(":")[0]
        for line in first_user_text(organizer).splitlines()
        if line.startswith("- ")
    ]


def write_session(directory: Path, session_id: str, at: datetime) -> Path:
    return (
        ClaudeCodeSession(session_id, PROJECT)
        .typed_prompt(at, "Which settings does the app use?")
        .assistant_text(at, "The ones in mise.toml.")
        .write(directory / f"{session_id}.jsonl")
    )


def run_cli(
    memory: Path,
    sessions: Path,
    models: ScriptedModels | None,
    now: datetime,
) -> int:
    """Run over every session under `sessions`; `models` None means no model may run."""
    claude_code = sessions / "claude"
    codex = sessions / "codex"
    claude_code.mkdir(parents=True, exist_ok=True)
    codex.mkdir(parents=True, exist_ok=True)

    def no_model(invocation: Invocation) -> ScriptedLlm:
        raise AssertionError(f"no model may run, but {invocation} started")

    return cli.main(
        [
            "--memory",
            str(memory),
            "--since",
            "2026-10-01",
            "--claude-code-dir",
            str(claude_code),
            "--codex-dir",
            str(codex),
        ],
        model_factory=models or no_model,
        now=now,
    )


def test_organizer_receives_exactly_the_files_the_analyses_wrote(
    example_sessions: ExampleSessions,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    memory = tmp_path / "memory"
    models = ScriptedModels(analyses=one_fact_each(), organizer=organizer_done())

    exit_code = cli.main(
        [
            "--memory",
            str(memory),
            "--since",
            "2026-10-01",
            "--claude-code-dir",
            str(example_sessions.claude_code),
            "--codex-dir",
            str(example_sessions.codex),
        ],
        model_factory=models,
        now=RUN_START,
    )

    report = capsys.readouterr().out
    assert exit_code == 0
    [organizer] = models.organizer_runs
    assert sorted(received_slugs(organizer)) == [
        f"fact-{index}" for index in range(len(SELECTED_EXAMPLES))
    ]
    assert DreamRecord.load(memory).waiting_files == ()
    assert re.search(r"^Organizer +ran and succeeded$", report, re.MULTILINE)
    assert re.search(r"^Waiting for the organizer +0 files$", report, re.MULTILINE)


def test_files_wait_after_a_failed_organizer_until_a_later_pass_succeeds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    memory = tmp_path / "memory"
    sessions = tmp_path / "sessions"
    project = sessions / "claude" / "-Users-dev-Projects-app"
    write_session(project, PYTHON_SESSION, PYTHON_AT)
    write_session(project, DEPLOY_SESSION, DEPLOY_AT)
    python_body = (
        "# Python\n\n- The app uses Python 3.15. "
        f"{Citation(Tool.CLAUDE_CODE, PYTHON_SESSION, PROJECT, PYTHON_AT).render()} "
        "[scope: Development]\n"
    )
    deploy_body = (
        "# Deploy\n\n- The app deploys to Fly.io. "
        f"{Citation(Tool.CLAUDE_CODE, DEPLOY_SESSION, PROJECT, DEPLOY_AT).render()} "
        "[scope: Development]\n"
    )
    failing = ScriptedModels(
        analyses={
            (PYTHON_SESSION, 1): [
                create_file_call("python-version", python_body),
                FinalText("Recorded one fact."),
            ],
            (DEPLOY_SESSION, 1): [
                create_file_call("deploy-target", deploy_body),
                FinalText("Recorded one fact."),
            ],
        },
        organizer=[
            CallTool("read_index", {}),
            AgentFailure(Failure(FailureReason.OVERLOADED)),
        ],
    )

    first_exit = run_cli(memory, sessions, failing, RUN_START)

    first_report = capsys.readouterr().out
    assert first_exit == 1
    assert re.search(
        r"^Organizer +failed \(overloaded\); memory was not organized$",
        first_report,
        re.MULTILINE,
    )
    assert re.search(
        r"^Waiting for the organizer +2 files$", first_report, re.MULTILINE
    )
    assert (memory / "python-version.md").read_text().endswith(python_body)
    assert (memory / "deploy-target.md").read_text().endswith(deploy_body)
    waiting = sorted(DreamRecord.load(memory).waiting_files)
    assert waiting == ["deploy-target", "python-version"]

    organizing = ScriptedModels(organizer=organizer_done())
    second_exit = run_cli(
        memory, tmp_path / "no-sessions", organizing, RUN_START + timedelta(hours=1)
    )

    second_report = capsys.readouterr().out
    assert second_exit == 0
    assert organizing.analyses_created == []
    [organizer] = organizing.organizer_runs
    assert sorted(received_slugs(organizer)) == waiting
    assert re.search(r"^Organizer +ran and succeeded$", second_report, re.MULTILINE)
    assert DreamRecord.load(memory).waiting_files == ()

    third_exit = run_cli(
        memory, tmp_path / "no-sessions", None, RUN_START + timedelta(hours=2)
    )

    assert third_exit == 0
    assert "Nothing to dream over." in capsys.readouterr().out


def test_on_seeded_memory_the_organizer_receives_changed_and_violating_files(
    tmp_path: Path,
) -> None:
    seeded = seeded_memory(tmp_path / "memory")
    sessions = tmp_path / "sessions"
    write_session(
        sessions / "claude" / "-Users-dev-Projects-app", PYTHON_SESSION, PYTHON_AT
    )
    citation = Citation(Tool.CLAUDE_CODE, PYTHON_SESSION, PROJECT, PYTHON_AT).render()
    changed = ["filler-005", "filler-010", "filler-015"]
    models = ScriptedModels(
        analyses={
            (PYTHON_SESSION, 1): [
                *(
                    CallTool(
                        "append_to_file",
                        {
                            "slug": slug,
                            "text": f"- A new fact. {citation} [scope: Development]\n",
                        },
                    )
                    for slug in changed
                ),
                FinalText("Recorded three facts."),
            ]
        },
        organizer=organizer_done(),
    )

    exit_code = run_cli(seeded.path, sessions, models, RUN_START)

    # The organizer script fixes none of the seeded format violations.
    assert exit_code == 1
    appended = models.model_for(PYTHON_SESSION).tool_results
    assert [result.response and result.response["status"] for result in appended] == [
        "ok"
    ] * len(changed)
    [organizer] = models.organizer_runs
    assert received_slugs(organizer) == [
        seeded.hand_written,
        seeded.broken_link,
        seeded.unlisted,
        *changed,
    ]
    assert DreamRecord.load(seeded.path).waiting_files == ()
