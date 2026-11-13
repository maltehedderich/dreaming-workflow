"""One example session through the CLI, ADK, the scripted model, and the memory store."""

import re
import stat
from pathlib import Path

import pytest

from dreaming_workflow import cli
from tests.conftest import ExampleSessions
from tests.support.examples import (
    CONTEXT7_CHECK,
    RUN_START,
    claude_code_example,
)
from tests.support.scripted_llm import (
    CallTool,
    FinalText,
    ScriptedModels,
    first_user_text,
    organizer_done,
)

SLUG = "context7-connection"
TYPED_PROMPT = "check you context7 connection, does it work?"
BODY = (
    "# Context7 connection\n\n"
    "- The Context7 connection is checked by asking the agent to call it. "
    f"[source: claude-code {CONTEXT7_CHECK} · /Users/dev/Projects · 2026-10-17 09:18 UTC] "
    "[scope: Development]\n"
)


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_one_session_becomes_one_memory_file(
    example_sessions: ExampleSessions,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    memory = tmp_path / "memory"
    session_file = claude_code_example(example_sessions.claude_code, CONTEXT7_CHECK)
    models = ScriptedModels(
        analyses={
            (CONTEXT7_CHECK, 1): [
                CallTool("read_index", {}),
                CallTool(
                    "create_file",
                    {
                        "slug": SLUG,
                        "description": "How the Context7 connection is checked.",
                        "body": BODY,
                        "domain": "Development",
                        "subdomain": None,
                        "index_sentence": "How the Context7 connection is checked.",
                    },
                ),
                FinalText("Recorded one fact."),
            ]
        },
        organizer=organizer_done(),
    )

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

    assert exit_code == 0
    memory_file = (memory / f"{SLUG}.md").read_text()
    assert memory_file.startswith(
        f"---\nname: {SLUG}\ndescription: How the Context7 connection is checked.\n---\n"
    )
    assert memory_file.endswith(BODY)
    assert (memory / "_index.md").read_text() == (
        "# Memory index\n\n"
        "## Development\n\n"
        f"- [[{SLUG}]] — How the Context7 connection is checked.\n"
    )
    assert mode_of(memory) == 0o700
    assert mode_of(memory / f"{SLUG}.md") == 0o600
    assert mode_of(memory / "_index.md") == 0o600

    model = models.model_for(CONTEXT7_CHECK)
    read_index, create_file = [result.response for result in model.tool_results]
    assert read_index == {"status": "ok", "text": ""}
    assert create_file is not None
    assert create_file["status"] == "ok"
    first_user_message = first_user_text(model)
    data = re.search(
        r"^=== BEGIN SESSION DATA (\w+) ===\n(.*)\n=== END SESSION DATA \1 ===$",
        first_user_message,
        re.MULTILINE | re.DOTALL,
    )
    assert data is not None
    assert TYPED_PROMPT in data.group(2)

    report = capsys.readouterr().out
    assert re.search(r"^  analyzed +1  \(", report, re.MULTILINE)
    assert re.search(
        r"^  files +1 created, 0 changed, 0 retired$", report, re.MULTILINE
    )
    [organizer] = models.organizer_runs
    assert f"- {SLUG}\n" in first_user_text(organizer)
    assert re.search(r"^Organizer +ran and succeeded$", report, re.MULTILINE)
    assert re.search(r"^Waiting for the organizer +0 files$", report, re.MULTILINE)
    assert re.search(r"^  format check +no violations$", report, re.MULTILINE)
