from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dreaming_workflow.sessions import (
    MessageKind,
    Session,
    SessionFile,
    Tool,
    parse_claude_code,
)
from tests.support.examples import (
    CLAUDE_CODE_PROJECTS,
    CONTEXT7_CHECK,
    CTX7_SETUP,
    EXAMPLE_PROJECT_DIR,
    UV_SETUP,
    claude_code_example,
)
from tests.support.sessions import ClaudeCodeSession

T0 = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)

# Text that Claude Code injects as attachments, system prompts, or harness
# wrappers. None of it was typed by the user, so none may reach the view.
INJECTED_MARKERS = (
    "<system-reminder>",
    "brave-search: Web search via the Brave Search CLI",
    "system prompt removed from this example",
    "You are Claude Code, Anthropic's official CLI",
    "<local-command-caveat>",
    "<command-name>",
)


def parse_example(session_id: str) -> Session:
    path = claude_code_example(CLAUDE_CODE_PROJECTS, session_id)
    session = parse_claude_code(SessionFile.at(path, expected_tool=None))
    assert session is not None
    return session


def minute(at: datetime) -> datetime:
    return at.replace(second=0, microsecond=0)


@pytest.mark.parametrize(
    ("session_id", "last_activity"),
    [
        (CONTEXT7_CHECK, datetime(2026, 10, 17, 9, 21, tzinfo=UTC)),
        (CTX7_SETUP, datetime(2026, 10, 17, 9, 38, tzinfo=UTC)),
        (UV_SETUP, datetime(2026, 10, 17, 9, 42, tzinfo=UTC)),
    ],
)
def test_examples_give_session_metadata(
    session_id: str, last_activity: datetime
) -> None:
    session = parse_example(session_id)

    assert session.tool is Tool.CLAUDE_CODE
    assert session.session_id == session_id
    assert session.project_dir == EXAMPLE_PROJECT_DIR
    assert minute(session.last_activity_at) == last_activity
    assert session.parent_thread_id is None


@pytest.mark.parametrize("session_id", [CONTEXT7_CHECK, CTX7_SETUP, UV_SETUP])
def test_examples_view_leaves_out_injected_text(session_id: str) -> None:
    view = parse_example(session_id).view

    for message in view.messages:
        for marker in INJECTED_MARKERS:
            assert marker not in message.text


def test_view_opens_with_the_typed_prompt() -> None:
    view = parse_example(CONTEXT7_CHECK).view

    first = view.messages[0]
    assert first.kind is MessageKind.USER
    assert first.text == "check you context7 connection, does it work?"


def test_instruction_file_attachment_stays_out_of_the_view() -> None:
    view = parse_example(CONTEXT7_CHECK).view

    instruction_text = "Use the `ctx7` CLI to fetch current documentation whenever"
    assert all(instruction_text not in message.text for message in view.messages)


def test_hook_error_is_a_failed_tool_result() -> None:
    view = parse_example(UV_SETUP).view

    hook_errors = [
        message
        for message in view.messages
        if message.text.startswith(
            "PreToolUse:Bash hook error: [~/.claude/hooks/require-uv.sh]"
        )
    ]
    assert len(hook_errors) == 1
    assert hook_errors[0].kind is MessageKind.TOOL_RESULT
    assert hook_errors[0].is_error


def parse_synthetic(path: Path) -> Session:
    session = parse_claude_code(SessionFile.at(path, expected_tool=None))
    assert session is not None
    return session


def test_partial_last_line_is_skipped(tmp_path: Path) -> None:
    builder = (
        ClaudeCodeSession("s1", "/work")
        .typed_prompt(T0, "first question")
        .assistant_text(T0 + timedelta(minutes=1), "first answer")
        .typed_prompt(T0 + timedelta(minutes=2), "question cut off mid-write")
    )
    session = parse_synthetic(
        builder.write(tmp_path / "s1.jsonl", truncate_last_line=True)
    )

    assert [message.text for message in session.view.messages] == [
        "first question",
        "first answer",
    ]
    assert session.last_activity_at == T0 + timedelta(minutes=1)


def test_meta_sidechain_and_non_human_text_are_left_out(tmp_path: Path) -> None:
    builder = (
        ClaudeCodeSession("s1", "/work")
        .typed_prompt(T0, "typed by the user")
        .meta_user(T0, "meta record")
        .sidechain_user(T0, "sidechain record")
        .user_text_from(T0, "queued by a hook", origin_kind="hook")
        .system_reminder(T0, "reminder text")
        .attachment(T0, "instruction file text")
    )
    session = parse_synthetic(builder.write(tmp_path / "s1.jsonl"))

    assert [message.text for message in session.view.messages] == ["typed by the user"]


def test_records_left_out_of_the_view_still_count_as_activity(tmp_path: Path) -> None:
    builder = (
        ClaudeCodeSession("s1", "/work")
        .typed_prompt(T0, "question")
        .attachment(T0 + timedelta(minutes=5), "instruction file text")
    )
    session = parse_synthetic(builder.write(tmp_path / "s1.jsonl"))

    assert session.last_activity_at == T0 + timedelta(minutes=5)


def test_image_renders_as_placeholder(tmp_path: Path) -> None:
    builder = ClaudeCodeSession("s1", "/work").image(T0)
    session = parse_synthetic(builder.write(tmp_path / "s1.jsonl"))

    assert [(m.kind, m.text) for m in session.view.messages] == [
        (MessageKind.USER, "[image]")
    ]


def test_tool_use_and_result_become_tool_messages(tmp_path: Path) -> None:
    builder = (
        ClaudeCodeSession("s1", "/work")
        .tool_use(T0, "toolu_1", "Bash", {"command": "ls ~/.codex/"})
        .tool_result(T0, "toolu_1", "No such file", is_error=True)
    )
    session = parse_synthetic(builder.write(tmp_path / "s1.jsonl"))

    call, result = session.view.messages
    assert (call.kind, call.tool_name, call.text) == (
        MessageKind.TOOL_CALL,
        "Bash",
        '{"command":"ls ~/.codex/"}',
    )
    assert (result.kind, result.is_error, result.text) == (
        MessageKind.TOOL_RESULT,
        True,
        "No such file",
    )


def test_file_without_session_records_is_not_recognized(tmp_path: Path) -> None:
    path = (
        ClaudeCodeSession("s1", "/work")
        .attachment(T0, "text")
        .write(tmp_path / "x.jsonl")
    )

    assert parse_claude_code(SessionFile.at(path, expected_tool=None)) is None


def test_file_that_is_not_json_is_not_recognized(tmp_path: Path) -> None:
    path = tmp_path / "notes.jsonl"
    path.write_text("just some notes\n", encoding="utf-8")

    assert parse_claude_code(SessionFile.at(path, expected_tool=None)) is None
