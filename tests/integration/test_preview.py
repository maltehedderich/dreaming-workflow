"""Preview lists what a run would send, without credentials and without a trace."""

import os
import re
from pathlib import Path

import pytest

from dreaming_workflow import cli
from dreaming_workflow.state import state_dir
from tests.conftest import ExampleSessions
from tests.support.examples import (
    CODEX_PROJECT_DIR,
    CONTEXT7_CHECK,
    CTX7_SETUP,
    EXAMPLE_PROJECT_DIR,
    MAILARKIV,
    MAILARKIV_SUBTHREAD,
    PASSWORD_LIMIT,
    RUN_START,
    UV_SETUP,
    one_fact_each,
)
from tests.support.scripted_llm import ScriptedModels, organizer_done

_ROW = re.compile(
    r"^  (?P<tool>claude-code|codex) +(?P<activity>\d{4}-\d{2}-\d{2} \d{2}:\d{2}) +"
    r"(?P<project>/\S+) +(?P<size>[\d,]+\.\d KB) +(?P<tokens>[\d,]+) +(?P<parts>\d+)$"
)
_SESSION_ID = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$"
)

# Tool, project directory, and last activity of each selected example, oldest
# first; the times are the latest timestamp in each file, to the minute.
EXPECTED = [
    ("claude-code", "2026-10-17 09:21", EXAMPLE_PROJECT_DIR, CONTEXT7_CHECK),
    ("claude-code", "2026-10-17 09:38", EXAMPLE_PROJECT_DIR, CTX7_SETUP),
    ("claude-code", "2026-10-17 09:42", EXAMPLE_PROJECT_DIR, UV_SETUP),
    ("codex", "2026-11-06 20:02", CODEX_PROJECT_DIR, MAILARKIV),
    ("codex", "2026-11-07 21:21", CODEX_PROJECT_DIR, PASSWORD_LIMIT),
]


def arguments(memory: Path, sessions: ExampleSessions) -> list[str]:
    return [
        "--memory",
        str(memory),
        "--since",
        "2026-10-01",
        "--claude-code-dir",
        str(sessions.claude_code),
        "--codex-dir",
        str(sessions.codex),
    ]


def session_id_of(path: str) -> str:
    match = _SESSION_ID.search(path)
    assert match is not None, path
    return str(match.group(1))


def test_preview_lists_what_the_next_run_analyzes(
    example_sessions: ExampleSessions,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    memory = tmp_path / "memory"

    # No model factory and no credentials: a run would stop at the preflight.
    exit_code = cli.main(
        [*arguments(memory, example_sessions), "--preview"], now=RUN_START
    )

    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert exit_code == 0
    assert captured.err == ""
    assert lines[0] == "Preview: window 2026-10-01 00:00 UTC to 2026-11-10 21:38 UTC"
    assert "Selected sessions (5)" in lines

    start = lines.index("Selected sessions (5)") + 2
    rows = [_ROW.match(line) for line in lines[start : start + 10 : 2]]
    paths = [line.strip() for line in lines[start + 1 : start + 11 : 2]]
    assert all(rows), lines[start : start + 10]
    previewed = [
        (row["tool"], row["activity"], row["project"], session_id_of(path))
        for row, path in zip(rows, paths, strict=True)
        if row is not None
    ]
    assert previewed == EXPECTED
    for row, path in zip(rows, paths, strict=True):
        assert row is not None
        assert row["size"] == f"{Path(path).stat().st_size / 1024:,.1f} KB"
        assert int(row["tokens"].replace(",", "")) > 0
        assert row["parts"] == "1"
    total = sum(int(row["tokens"].replace(",", "")) for row in rows if row is not None)
    assert f"Total estimated tokens: {total:,}" in lines
    assert "Memory files waiting for the organizer: 0" in lines
    skipped_at = lines.index("Skipped sessions (1)")
    [skipped] = lines[skipped_at + 1 :]
    assert skipped.endswith("  subthread")
    assert session_id_of(skipped.removesuffix("  subthread")) == MAILARKIV_SUBTHREAD

    assert not memory.exists()
    assert not state_dir(memory).exists()
    assert not (Path(os.environ["XDG_STATE_HOME"]) / "dreaming-workflow").exists()

    models = ScriptedModels(analyses=one_fact_each(), organizer=organizer_done())
    assert (
        cli.main(
            arguments(memory, example_sessions), model_factory=models, now=RUN_START
        )
        == 0
    )
    analyzed = [str(invocation.session_id) for invocation in models.analyses_created]
    assert sorted(analyzed) == sorted(expected[3] for expected in EXPECTED)
