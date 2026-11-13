"""A whole run over the example sessions, through the CLI and real ADK agents."""

import hashlib
import re
import stat
from pathlib import Path

import pytest

from dreaming_workflow import cli
from tests.conftest import ExampleSessions
from tests.support.examples import (
    MAILARKIV_SUBTHREAD,
    RUN_START,
    SELECTED_EXAMPLES,
    one_fact_each,
)
from tests.support.scripted_llm import ScriptedModels, organizer_done


def file_hashes(directory: Path) -> dict[Path, str]:
    return {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*.jsonl"))
    }


def test_dream_over_the_examples(
    example_sessions: ExampleSessions,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    memory = tmp_path / "memory"
    sessions_before = file_hashes(example_sessions.claude_code) | file_hashes(
        example_sessions.codex
    )
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

    captured = capsys.readouterr()
    assert exit_code == 0
    report = captured.out
    for expected in (
        r"^  found +6$",
        r"^  selected +5$",
        r"^  skipped +1  \(subthread: 1\)$",
        r"^  analyzed +5  \(in more than one part: 0\)$",
        r"^  failed +0$",
        r"^  files +5 created, 0 changed, 0 retired$",
    ):
        assert re.search(expected, report, re.MULTILINE), expected

    invoked = [invocation.session_id for invocation in models.analyses_created]
    assert invoked == [example.session_id for example in SELECTED_EXAMPLES]
    assert MAILARKIV_SUBTHREAD not in invoked
    for index in range(len(SELECTED_EXAMPLES)):
        assert (memory / f"fact-{index}.md").is_file()

    sessions_after = file_hashes(example_sessions.claude_code) | file_hashes(
        example_sessions.codex
    )
    assert sessions_after == sessions_before

    [backup] = (tmp_path / "state" / "dreaming-workflow").glob("*/backups/*")
    assert backup.name == "20261110T213800Z"
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    assert f"Pre-run copy                {backup}" in report
    assert f"Saved a copy of memory to {backup}" in captured.err
