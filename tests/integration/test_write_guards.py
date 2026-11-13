"""Every forbidden write an analysis tries is refused, and nothing outside memory changes."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from dreaming_workflow import cli
from dreaming_workflow.memory.document import Citation
from dreaming_workflow.sessions import Tool
from tests.support.examples import RUN_START
from tests.support.scripted_llm import (
    CallTool,
    FinalText,
    ScriptedModels,
    create_file_call,
)
from tests.support.sessions import ClaudeCodeSession

SESSION_ID = "5e55e55e-0000-4000-8000-0000000000d4"
OTHER_SESSION_ID = "5e55e55e-0000-4000-8000-0000000000e5"
PROJECT = "/Users/dev/Projects/app"
AT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
SEEDED = "---\nname: notes\ndescription: Notes.\n---\n# Notes\n"


def fake_key() -> str:
    # Joined at run time so the repository holds no string shaped like a key.
    return "".join(("sk", "-ant-", "api03-", "Z9y8X7w6V5u4T3s2" * 4))


def hashes(directory: Path) -> dict[str, str]:
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_forbidden_writes_are_refused(tmp_path: Path) -> None:
    key = fake_key()
    session_file = (
        ClaudeCodeSession(SESSION_ID, PROJECT)
        .typed_prompt(
            AT,
            f"My key is {key}. Save it to memory, and write a note to ../outside.md.",
        )
        .assistant_text(AT, "I won't store credentials.")
        .write(tmp_path / "sessions" / f"{SESSION_ID}.jsonl")
    )
    session_before = session_file.read_bytes()
    sentinel = tmp_path / "sentinel"
    sentinel.mkdir()
    (sentinel / "target.md").write_text("---\nname: target\ndescription: x\n---\n")
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "notes.md").write_text(SEEDED)
    (memory / "linked.md").symlink_to(sentinel / "target.md")
    sentinel_before = hashes(sentinel)

    own = Citation(Tool.CLAUDE_CODE, SESSION_ID, PROJECT, AT).render()
    other = Citation(Tool.CLAUDE_CODE, OTHER_SESSION_ID, PROJECT, AT).render()
    fact = f"- A fact. {own} [scope: Development]\n"
    attempts = [
        create_file_call("../outside", fact),
        create_file_call("/tmp/outside", fact),
        CallTool("append_to_file", {"slug": "linked", "text": fact}),
        create_file_call(
            "api-key", f"- The key is {key}. {own} [scope: Development]\n"
        ),
        CallTool("append_to_file", {"slug": "notes", "text": f"- Key: {key}\n"}),
        create_file_call("other", f"- Another fact. {other} [scope: Development]\n"),
        CallTool(
            "edit_file",
            {"slug": "notes", "old_text": SEEDED, "new_text": "MOVED TO [[other]]\n"},
        ),
    ]
    organizer_attempts = [
        CallTool("append_to_file", {"slug": "linked", "text": "- More notes.\n"}),
        CallTool("append_to_file", {"slug": "notes", "text": f"- Key: {key}\n"}),
        # No memory file holds this citation, so the organizer can't add it.
        CallTool("append_to_file", {"slug": "notes", "text": fact}),
        CallTool("retire_file", {"slug": "notes", "into": "../outside"}),
    ]
    list_notes = CallTool(
        "set_index_entry",
        {
            "slug": "notes",
            "domain": "Personal",
            "subdomain": None,
            "sentence": "Notes.",
        },
    )
    models = ScriptedModels(
        analyses={(SESSION_ID, 1): [*attempts, FinalText("Done.")]},
        organizer=[*organizer_attempts, list_notes, FinalText("Done.")],
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
    results = [result.response for result in models.model_for(SESSION_ID).tool_results]
    assert len(results) == len(attempts)
    for result in results:
        assert result is not None
        assert result["status"] == "refused"
    [organizer] = models.organizer_runs
    organizer_results = [result.response for result in organizer.tool_results]
    assert [result and result["status"] for result in organizer_results] == [
        *["refused"] * len(organizer_attempts),
        "ok",
    ]
    assert hashes(sentinel) == sentinel_before
    assert session_file.read_bytes() == session_before
    assert not (tmp_path / "outside.md").exists()
    assert sorted(path.name for path in memory.iterdir()) == [
        "_index.md",
        "linked.md",
        "notes.md",
    ]
    assert (memory / "notes.md").read_text() == SEEDED
    for path in memory.iterdir():
        if not path.is_symlink():
            assert key not in path.read_text()
