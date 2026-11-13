"""Session and memory content never reaches stdout, stderr, logs, or the report."""

import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dreaming_workflow import cli
from tests.support.examples import RUN_START
from tests.support.scripted_llm import CallTool, FinalText, ScriptedModels
from tests.support.sessions import ClaudeCodeSession

SESSION_ID = "5e55e55e-0000-4000-8000-0000000000c9"
PROJECT = "/Users/dev/Projects/app"
AT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def test_content_stays_out_of_every_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    canary = f"canary-{secrets.token_hex(12)}"
    session_file = (
        ClaudeCodeSession(SESSION_ID, PROJECT)
        .typed_prompt(AT, f"Remember the word {canary}.")
        .assistant_text(AT, "Noted.")
        .write(tmp_path / "sessions" / f"{SESSION_ID}.jsonl")
    )
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "notes.md").write_text(
        f"---\nname: notes\ndescription: Notes.\n---\n# Notes\n\n- {canary}\n"
    )
    models = ScriptedModels(
        analyses={
            (SESSION_ID, 1): [
                CallTool("read_file", {"slug": "notes"}),
                CallTool(
                    "edit_file",
                    {
                        "slug": "notes",
                        "old_text": f"{canary} is not here",
                        "new_text": canary,
                    },
                ),
                FinalText(f"Nothing recorded about {canary}."),
            ]
        },
        organizer=[
            CallTool("read_file", {"slug": "notes"}),
            CallTool(
                "set_index_entry",
                {
                    "slug": "notes",
                    "domain": "Personal",
                    "subdomain": None,
                    "sentence": "Notes.",
                },
            ),
            FinalText(f"Listed the note about {canary}."),
        ],
    )
    caplog.set_level(logging.DEBUG)

    exit_code = cli.main(
        [
            "--memory",
            str(memory),
            "--since",
            "2026-10-01",
            "--session",
            str(session_file),
        ],
        model_factory=models,
        now=RUN_START,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    results = [result.response for result in models.model_for(SESSION_ID).tool_results]
    assert [result and result["status"] for result in results] == ["ok", "refused"]
    [organizer] = models.organizer_runs
    organizer_results = [result.response for result in organizer.tool_results]
    assert [result and result["status"] for result in organizer_results] == [
        "ok",
        "ok",
    ]
    assert canary not in captured.out
    assert canary not in captured.err
    for record in caplog.records:
        assert canary not in record.getMessage()
        assert canary not in repr(record.args)
        assert canary not in (record.exc_text or "")
