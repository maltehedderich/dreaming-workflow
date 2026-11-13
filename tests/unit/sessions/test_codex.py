from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dreaming_workflow.sessions import (
    MessageKind,
    Session,
    SessionFile,
    Tool,
    parse_codex,
)
from tests.support.examples import (
    CODEX_PROJECT_DIR,
    CODEX_SESSIONS,
    MAILARKIV,
    MAILARKIV_SUBTHREAD,
    PASSWORD_LIMIT,
    codex_example,
)
from tests.support.sessions import ClaudeCodeSession, CodexSession

T0 = datetime(2026, 11, 6, 20, 0, tzinfo=UTC)
SESSION_ID = "c0dec0de-0000-4000-8000-000000000001"

# Text that Codex adds as developer or user messages: base instructions,
# skills, permissions, AGENTS.md, and environment context. None of it was
# typed by the user, so none may reach the view.
INJECTED_MARKERS = (
    "You are Codex",
    "<skills_instructions>",
    "<permissions instructions>",
    "# AGENTS.md instructions",
    "<environment_context>",
)


def parse_example(session_id: str) -> Session:
    path = codex_example(CODEX_SESSIONS, session_id)
    session = parse_codex(SessionFile.at(path, expected_tool=None))
    assert session is not None
    return session


def parse_synthetic(builder: CodexSession, tmp_path: Path) -> Session:
    path = builder.write(tmp_path / "rollout.jsonl")
    session = parse_codex(SessionFile.at(path, expected_tool=Tool.CODEX))
    assert session is not None
    return session


def started() -> CodexSession:
    return CodexSession().session_meta(T0, SESSION_ID, "/Users/dev/Projects/app")


def test_example_gives_session_metadata() -> None:
    session = parse_example(MAILARKIV)

    assert session.tool is Tool.CODEX
    assert session.session_id == MAILARKIV
    assert session.project_dir == CODEX_PROJECT_DIR
    assert session.last_activity_at.replace(second=0, microsecond=0) == datetime(
        2026, 11, 6, 20, 2, tzinfo=UTC
    )
    assert session.parent_thread_id is None


def test_example_view_holds_the_typed_message_and_no_injected_text() -> None:
    session = parse_example(MAILARKIV)
    messages = session.view.messages

    user_messages = [m for m in messages if m.kind is MessageKind.USER]
    assert len(user_messages) == 1
    assert user_messages[0].text.startswith(
        "agy from google asks all the time for read access"
    )
    for message in messages:
        for marker in INJECTED_MARKERS:
            assert marker not in message.text


def test_subthread_example_names_its_parent() -> None:
    session = parse_example(MAILARKIV_SUBTHREAD)

    assert session.parent_thread_id == MAILARKIV


def test_interrupted_example_ends_with_the_interruption() -> None:
    messages = parse_example(PASSWORD_LIMIT).view.messages
    kinds = [message.kind for message in messages]

    [user] = [m for m in messages if m.kind is MessageKind.USER]
    assert "4 mb" in user.text
    first_call = kinds.index(MessageKind.TOOL_CALL)
    assert kinds[:first_call].count(MessageKind.ASSISTANT) == 1
    assert "rg -n" in messages[first_call].text
    assert messages[-1].kind is MessageKind.INTERRUPTED
    assert messages[-1].text == "turn interrupted (interrupted)"


def test_metadata_comes_from_session_meta(tmp_path: Path) -> None:
    builder = CodexSession().session_meta(
        T0 + timedelta(seconds=30),
        SESSION_ID,
        "/Users/dev/Projects/app",
        started_at=T0,
        parent_thread_id="feedface-0000-4000-8000-000000000002",
    )
    builder.user_message_item(T0 + timedelta(minutes=2), "hello")

    session = parse_synthetic(builder, tmp_path)

    assert session.session_id == SESSION_ID
    assert session.project_dir == "/Users/dev/Projects/app"
    assert session.started_at == T0
    assert session.last_activity_at == T0 + timedelta(minutes=2)
    assert session.parent_thread_id == "feedface-0000-4000-8000-000000000002"


def test_missing_cwd_gives_unknown_project(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    path.write_text(
        '{"timestamp":"2026-11-06T20:00:00.000Z","type":"session_meta",'
        '"payload":{"id":"c0dec0de-0000-4000-8000-000000000001",'
        '"timestamp":"2026-11-06T20:00:00.000Z"}}\n',
        encoding="utf-8",
    )

    session = parse_codex(SessionFile.at(path, expected_tool=Tool.CODEX))

    assert session is not None
    assert session.project_dir == "unknown"


def test_user_message_items_replace_older_user_message_events(tmp_path: Path) -> None:
    builder = (
        started()
        .user_message_event(T0, "typed, older record")
        .user_message_item(T0, "typed, newer record")
    )

    texts = [m.text for m in parse_synthetic(builder, tmp_path).view.messages]

    assert texts == ["typed, newer record"]


def test_older_user_message_events_count_without_items(tmp_path: Path) -> None:
    builder = started().user_message_event(T0, "typed in an older Codex")

    [message] = parse_synthetic(builder, tmp_path).view.messages

    assert (message.kind, message.text) == (MessageKind.USER, "typed in an older Codex")


def test_context_messages_and_reasoning_are_excluded(tmp_path: Path) -> None:
    builder = (
        started()
        .context_message(
            T0,
            "developer",
            "<permissions instructions>sandbox</permissions instructions>",
        )
        .context_message(
            T0, "user", "# AGENTS.md instructions for /Users/dev/Projects/app"
        )
        .context_message(
            T0, "user", "<environment_context><cwd>/x</cwd></environment_context>"
        )
        .reasoning(T0, "Thinking about the request")
        .assistant_message(T0, "Done.")
    )

    messages = parse_synthetic(builder, tmp_path).view.messages

    assert [(m.kind, m.text) for m in messages] == [(MessageKind.ASSISTANT, "Done.")]


def test_tool_calls_and_outputs(tmp_path: Path) -> None:
    builder = (
        started()
        .function_call(T0, "call-1", "read_file", '{"path":"README.md"}')
        .function_call_output(T0, "call-1", "# App")
        .custom_tool_call(T0, "call-2", "apply_patch", "*** Begin Patch")
        .custom_tool_call_output(T0, "call-2", ["patched", "1 file"])
        .local_shell_call(T0, "call-3", ["rg", "-n", "two words"])
        .local_shell_call_output(T0, "call-3", "src/app.py:1")
    )

    messages = parse_synthetic(builder, tmp_path).view.messages

    assert [(m.kind, m.tool_name, m.text) for m in messages] == [
        (MessageKind.TOOL_CALL, "read_file", '{"path":"README.md"}'),
        (MessageKind.TOOL_RESULT, None, "# App"),
        (MessageKind.TOOL_CALL, "apply_patch", "*** Begin Patch"),
        (MessageKind.TOOL_RESULT, None, "patched\n1 file"),
        (MessageKind.TOOL_CALL, "shell", "rg -n 'two words'"),
        (MessageKind.TOOL_RESULT, None, "src/app.py:1"),
    ]


def test_aborted_turn_without_reason(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    started().write(path)
    with path.open("a", encoding="utf-8") as file:
        file.write(
            '{"timestamp":"2026-11-06T20:01:00.000Z","type":"event_msg",'
            '"payload":{"type":"turn_aborted"}}\n'
        )

    session = parse_codex(SessionFile.at(path, expected_tool=Tool.CODEX))

    assert session is not None
    [message] = session.view.messages
    assert message.text == "turn interrupted (unknown)"


@pytest.mark.parametrize("first_record", ["event_msg", "claude_code"])
def test_file_not_starting_with_session_meta_is_not_codex(
    tmp_path: Path, first_record: str
) -> None:
    path = tmp_path / "session.jsonl"
    if first_record == "claude_code":
        ClaudeCodeSession(SESSION_ID, "/Users/dev").typed_prompt(T0, "hi").write(path)
    else:
        CodexSession().user_message_item(T0, "hi").session_meta(
            T0, SESSION_ID, "/Users/dev"
        ).write(path)

    assert parse_codex(SessionFile.at(path, expected_tool=None)) is None
