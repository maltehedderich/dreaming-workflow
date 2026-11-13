"""A session too long for one invocation is analyzed part by part, in order."""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dreaming_workflow import cli
from dreaming_workflow.memory.document import Citation
from dreaming_workflow.sessions import Tool
from tests.support.examples import RUN_START
from tests.support.scripted_llm import (
    CallTool,
    FinalText,
    ScriptedLlm,
    ScriptedModels,
    Step,
    create_file_call,
    organizer_done,
)
from tests.support.sessions import large_claude_code_session

SESSION_ID = "5e55e55e-0000-4000-8000-0000000000f6"
PROJECT = "/Users/dev/Projects/large"
START = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)
SENTENCE = "Build settings learned in the long session."


def first_message(llm: ScriptedLlm) -> str:
    content = llm.requests[0].contents[0]
    return "".join(part.text or "" for part in content.parts or [])


def test_a_long_session_runs_as_seven_parts_in_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 833 messages of 300 estimated tokens; a part holds 133 of them.
    session_file = large_claude_code_session(
        tmp_path / "sessions" / f"{SESSION_ID}.jsonl",
        250_000,
        start=START,
        session_id=SESSION_ID,
        cwd=PROJECT,
    )
    citation = Citation(Tool.CLAUDE_CODE, SESSION_ID, PROJECT, START).render()
    analyses: dict[tuple[str, int], list[Step]] = {
        (SESSION_ID, 1): [
            CallTool("read_index", {}),
            create_file_call(
                "build-settings",
                f"# Build settings\n\n- A fact. {citation} [scope: Development]\n",
                sentence=SENTENCE,
            ),
            FinalText("Recorded one fact."),
        ],
        (SESSION_ID, 2): [CallTool("read_index", {}), FinalText("Nothing new.")],
    }
    for part_index in range(3, 8):
        analyses[(SESSION_ID, part_index)] = [FinalText("Nothing new.")]
    models = ScriptedModels(analyses=analyses, organizer=organizer_done())

    exit_code = cli.main(
        [
            "--memory",
            str(tmp_path / "memory"),
            "--since",
            "2026-10-01",
            "--session",
            str(session_file),
        ],
        model_factory=models,
        now=RUN_START,
    )

    report = capsys.readouterr().out
    assert exit_code == 0
    assert [invocation.part_index for invocation in models.analyses_created] == list(
        range(1, 8)
    )
    for part_index in range(1, 8):
        message = first_message(models.model_for(SESSION_ID, part_index))
        assert f"Part {part_index} of 7, " in message
    first_index = models.model_for(SESSION_ID, 1).tool_results[0].response
    assert first_index == {"status": "ok", "text": ""}
    second_index = models.model_for(SESSION_ID, 2).tool_results[0].response
    assert second_index is not None
    assert f"- [[build-settings]] — {SENTENCE}" in str(second_index["text"])
    assert re.search(
        r"^  analyzed +1  \(in more than one part: 1\)$", report, re.MULTILINE
    )
