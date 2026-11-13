"""Failed analyses: their effect on other sessions, later parts, and the run."""

import asyncio
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dreaming_workflow import cli, dream
from dreaming_workflow.agents import (
    AgentFailure,
    AgentRole,
    Failure,
    FailureReason,
    Invocation,
)
from dreaming_workflow.memory.document import Citation
from dreaming_workflow.sessions import Tool
from tests.conftest import ExampleSessions
from tests.support.examples import PASSWORD_LIMIT, RUN_START, SELECTED_EXAMPLES, SINCE
from tests.support.scripted_llm import (
    FinalText,
    ScriptedLlm,
    ScriptedModels,
    Step,
    create_file_call,
    organizer_done,
)
from tests.support.sessions import ClaudeCodeSession, large_claude_code_session

DAY = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)
PROJECT = "/Users/dev/Projects/app"


def fail(reason: FailureReason) -> AgentFailure:
    return AgentFailure(Failure(reason))


def run_cli(
    memory: Path, claude_code: Path, codex: Path, models: ScriptedModels
) -> int:
    codex.mkdir(parents=True, exist_ok=True)
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
        model_factory=models,
        now=RUN_START,
    )


def synthetic_sessions(directory: Path, count: int) -> list[str]:
    """Write `count` small sessions, last active one minute apart; return their IDs."""
    ids: list[str] = []
    for index in range(count):
        session_id = f"5e55e55e-0000-4000-8000-{index:012d}"
        at = DAY + timedelta(minutes=index)
        ClaudeCodeSession(session_id, PROJECT).typed_prompt(
            at, f"Question {index}"
        ).assistant_text(at, f"Answer {index}").write(directory / f"{session_id}.jsonl")
        ids.append(session_id)
    return ids


def test_one_failed_session_does_not_stop_the_others(
    example_sessions: ExampleSessions,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    analyses: dict[tuple[str, int], list[Step]] = {
        (example.session_id, 1): [FinalText("Nothing to record.")]
        for example in SELECTED_EXAMPLES
    }
    analyses[(PASSWORD_LIMIT, 1)] = [fail(FailureReason.RATE_LIMITED)]

    exit_code = run_cli(
        tmp_path / "memory",
        example_sessions.claude_code,
        example_sessions.codex,
        ScriptedModels(analyses=analyses, organizer=organizer_done()),
    )

    report = capsys.readouterr().out
    assert exit_code == 1
    assert re.search(r"^Organizer +ran and succeeded$", report, re.MULTILINE)
    assert re.search(r"^  analyzed +4  ", report, re.MULTILINE)
    assert re.search(r"^  failed +1$", report, re.MULTILINE)
    assert f"\n  failed  codex {PASSWORD_LIMIT}  rate-limited\n" in report


def test_authentication_failure_stops_further_invocations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    claude_code = tmp_path / "claude" / "-Users-dev-Projects-app"
    ids = synthetic_sessions(claude_code, 21)
    analyses: dict[tuple[str, int], list[Step]] = {
        (session_id, 1): [FinalText("Nothing to record.")] for session_id in ids[:20]
    }
    analyses[(ids[0], 1)] = [fail(FailureReason.AUTHENTICATION_FAILED)]
    models = ScriptedModels(analyses=analyses, organizer=organizer_done())

    exit_code = run_cli(
        tmp_path / "memory", tmp_path / "claude", tmp_path / "codex", models
    )

    report = capsys.readouterr().out
    assert exit_code == 1
    # The 21st session is in the second group, which starts after the failure,
    # and the organizer comes after both groups.
    assert [invocation.session_id for invocation, _ in models.created] == ids[:20]
    assert re.search(
        r"^Organizer +failed \(authentication-failed\); memory was not organized$",
        report,
        re.MULTILINE,
    )
    assert f"  failed  claude-code {ids[0]}  authentication-failed" in report
    assert f"  failed  claude-code {ids[20]}  authentication-failed" in report
    assert re.search(r"^  analyzed +19  ", report, re.MULTILINE)


def test_failed_part_stops_the_session_and_keeps_earlier_facts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session_id = "5e55e55e-0000-4000-8000-0000000000c3"
    claude_code = tmp_path / "claude" / "-Users-dev-Projects-app"
    # 333 messages of 300 estimated tokens split 133, 133, and 67.
    large_claude_code_session(
        claude_code / f"{session_id}.jsonl",
        100_000,
        start=DAY,
        session_id=session_id,
        cwd=PROJECT,
    )
    citation = Citation(Tool.CLAUDE_CODE, session_id, PROJECT, DAY).render()
    models = ScriptedModels(
        analyses={
            (session_id, 1): [
                create_file_call(
                    "part-one",
                    f"# Part one\n\n- A fact. {citation} [scope: Development]\n",
                ),
                FinalText("Recorded one fact."),
            ],
            (session_id, 2): [fail(FailureReason.OVERLOADED)],
            (session_id, 3): [FinalText("Nothing to record.")],
        },
        organizer=organizer_done(),
    )
    memory = tmp_path / "memory"

    exit_code = run_cli(memory, tmp_path / "claude", tmp_path / "codex", models)

    report = capsys.readouterr().out
    assert exit_code == 1
    assert [invocation.part_index for invocation in models.analyses_created] == [
        1,
        2,
    ]
    assert (memory / "part-one.md").is_file()
    assert f"  failed  claude-code {session_id}  overloaded" in report
    assert re.search(r"^  analyzed +0  ", report, re.MULTILINE)


def test_sessions_run_in_groups_of_20(tmp_path: Path) -> None:
    claude_code = tmp_path / "claude" / "-Users-dev-Projects-app"
    ids = synthetic_sessions(claude_code, 25)
    events: list[tuple[str, str]] = []
    position = {session_id: index for index, session_id in enumerate(ids)}

    def factory(invocation: Invocation) -> ScriptedLlm:
        if invocation.role is AgentRole.ORGANIZER:
            events.append(("organize", ""))
            return ScriptedLlm.with_steps(organizer_done())
        events.append(("start", invocation.session_id or ""))
        return ScriptedLlm.with_steps([FinalText("Nothing to record.")])

    def progress(line: str) -> None:
        if line.startswith("  analyzed  "):
            events.append(("finish", line.split()[2]))

    result = asyncio.run(
        dream.run(
            dream.RunOptions(
                memory_dir=tmp_path / "memory",
                since=SINCE,
                claude_code_dir=tmp_path / "claude",
                codex_dir=tmp_path / "codex",
            ),
            now=RUN_START,
            model_factory=factory,
            progress=progress,
        )
    )

    assert result.report.analyzed == 25
    first_group = {session_id for session_id in ids[:20]}
    last_first_group_finish = max(
        index
        for index, (kind, session_id) in enumerate(events)
        if kind == "finish" and session_id in first_group
    )
    first_second_group_start = min(
        index
        for index, (kind, session_id) in enumerate(events)
        if kind == "start" and position[session_id] >= 20
    )
    assert last_first_group_finish < first_second_group_start
    assert sorted(position[s] for kind, s in events if kind == "start") == list(
        range(25)
    )
    assert events[-1] == ("organize", "")
