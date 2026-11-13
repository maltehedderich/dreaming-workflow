"""Without credentials the run stops before it reads sessions or touches memory."""

import os
from pathlib import Path

import pytest

from dreaming_workflow import cli, dream
from dreaming_workflow.state import state_dir
from tests.conftest import ExampleSessions
from tests.support.examples import RUN_START


def test_missing_credentials_stop_the_run_before_any_work(
    example_sessions: ExampleSessions,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def spy(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("sessions were discovered")

    monkeypatch.setattr(dream, "discover_and_select", spy)
    memory = tmp_path / "memory"

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
        now=RUN_START,
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "ANTHROPIC_API_KEY" in captured.err
    assert "ant auth login" in captured.err
    assert captured.out == ""
    assert calls == []
    assert not memory.exists()
    assert not state_dir(memory).exists()
    assert not (Path(os.environ["XDG_STATE_HOME"]) / "dreaming-workflow").exists()
