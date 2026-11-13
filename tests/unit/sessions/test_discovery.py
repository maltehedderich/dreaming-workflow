import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dreaming_workflow.sessions import (
    Selected,
    SelectionDecision,
    SessionSources,
    Skipped,
    SkipReason,
    Tool,
    discover_and_select,
)
from tests.conftest import ExampleSessions
from tests.support.examples import (
    CONTEXT7_CHECK,
    CTX7_SETUP,
    MAILARKIV,
    MAILARKIV_SUBTHREAD,
    PASSWORD_LIMIT,
    RUN_START,
    SINCE,
    UV_SETUP,
)
from tests.support.sessions import (
    ClaudeCodeSession,
    CodexSession,
    large_claude_code_session,
)

INSIDE = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
PROJECT = "/Users/dev/Projects/app"


def sources(tmp_path: Path, *session_files: Path) -> SessionSources:
    return SessionSources(
        claude_code_dir=tmp_path / "claude",
        codex_dir=tmp_path / "codex",
        session_files=session_files,
    )


def select(source: SessionSources) -> list[SelectionDecision]:
    return discover_and_select(source, since=SINCE, now=RUN_START, analyzed={})


def claude_file(tmp_path: Path, name: str) -> Path:
    return tmp_path / "claude" / "-Users-dev-Projects-app" / f"{name}.jsonl"


def conversation(session_id: str, last_at: datetime) -> ClaudeCodeSession:
    return (
        ClaudeCodeSession(session_id, PROJECT)
        .typed_prompt(last_at - timedelta(minutes=5), "How do I pin Python?")
        .assistant_text(last_at, "Add a .python-version file.")
    )


def only_skip(decisions: list[SelectionDecision]) -> Skipped:
    [decision] = decisions
    assert isinstance(decision, Skipped)
    return decision


def selected_ids(decisions: list[SelectionDecision]) -> list[str]:
    return [d.session.session_id for d in decisions if isinstance(d, Selected)]


def test_examples(example_sessions: ExampleSessions) -> None:
    source = SessionSources(
        claude_code_dir=example_sessions.claude_code,
        codex_dir=example_sessions.codex,
    )

    decisions = select(source)

    assert len(decisions) == 6
    assert selected_ids(decisions) == [
        CONTEXT7_CHECK,
        CTX7_SETUP,
        UV_SETUP,
        MAILARKIV,
        PASSWORD_LIMIT,
    ]
    skip = decisions[-1]
    assert isinstance(skip, Skipped)
    assert skip.reason is SkipReason.SUBTHREAD
    assert MAILARKIV_SUBTHREAD in skip.file.path.name
    assert skip.detail == ""


def test_selected_session_carries_its_parts(tmp_path: Path) -> None:
    conversation("a1", INSIDE).write(claude_file(tmp_path, "a1"))

    [decision] = select(sources(tmp_path))

    assert isinstance(decision, Selected)
    assert decision.session.tool is Tool.CLAUDE_CODE
    assert [(part.index, part.count) for part in decision.parts] == [(1, 1)]


def test_unrecognized_file(tmp_path: Path) -> None:
    path = claude_file(tmp_path, "notes")
    path.parent.mkdir(parents=True)
    path.write_text('{"note": "not a session"}\n', encoding="utf-8")

    assert only_skip(select(sources(tmp_path))).reason is SkipReason.UNRECOGNIZED


def test_codex_file_in_the_claude_code_directory_is_unrecognized(
    tmp_path: Path,
) -> None:
    CodexSession().session_meta(INSIDE, "c1", PROJECT).user_message_item(
        INSIDE, "hi"
    ).write(claude_file(tmp_path, "c1"))

    assert only_skip(select(sources(tmp_path))).reason is SkipReason.UNRECOGNIZED


def test_subthread(tmp_path: Path) -> None:
    CodexSession().session_meta(
        INSIDE, "c2", PROJECT, parent_thread_id="c1"
    ).user_message_item(INSIDE, "review this").write(
        tmp_path
        / "codex"
        / "2026"
        / "11"
        / "02"
        / "rollout-2026-11-02T10-00-00-c2.jsonl"
    )

    assert only_skip(select(sources(tmp_path))).reason is SkipReason.SUBTHREAD


def test_subagent_transcript(tmp_path: Path) -> None:
    path = (
        tmp_path
        / "claude"
        / "-Users-dev-Projects-app"
        / "a1"
        / "subagents"
        / "agent-1.jsonl"
    )
    conversation("a1", INSIDE).write(path)

    assert only_skip(select(sources(tmp_path))).reason is SkipReason.SUBAGENT


def test_no_conversation(tmp_path: Path) -> None:
    ClaudeCodeSession("a1", PROJECT).system_reminder(INSIDE, "Today is Monday.").write(
        claude_file(tmp_path, "a1")
    )

    assert only_skip(select(sources(tmp_path))).reason is SkipReason.NO_CONVERSATION


def test_outside_window(tmp_path: Path) -> None:
    conversation("a1", SINCE - timedelta(minutes=1)).write(claude_file(tmp_path, "a1"))

    assert only_skip(select(sources(tmp_path))).reason is SkipReason.OUTSIDE_WINDOW


def test_last_active_59_minutes_ago_is_active(tmp_path: Path) -> None:
    conversation("a1", RUN_START - timedelta(minutes=59)).write(
        claude_file(tmp_path, "a1")
    )

    assert only_skip(select(sources(tmp_path))).reason is SkipReason.ACTIVE


def test_last_active_an_hour_ago_is_selected(tmp_path: Path) -> None:
    conversation("a1", RUN_START - timedelta(hours=1)).write(
        claude_file(tmp_path, "a1")
    )

    assert selected_ids(select(sources(tmp_path))) == ["a1"]


def test_too_large_session_gives_its_estimate(tmp_path: Path) -> None:
    # 1,334 messages of 900 characters, less the final blank line, make
    # 1,200,598 characters: 400,200 estimated tokens.
    large_claude_code_session(claude_file(tmp_path, "big"), 400_200, start=INSIDE)

    skip = only_skip(select(sources(tmp_path)))

    assert skip.reason is SkipReason.TOO_LARGE
    assert skip.detail == "400,200 estimated tokens"


def test_file_written_before_the_window_is_not_found(tmp_path: Path) -> None:
    path = conversation("a1", INSIDE).write(claude_file(tmp_path, "a1"))
    before = (SINCE - timedelta(days=1)).timestamp()
    os.utime(path, (before, before))

    assert select(sources(tmp_path)) == []


def test_named_files_replace_the_directory_scan(tmp_path: Path) -> None:
    conversation("scanned", INSIDE).write(claude_file(tmp_path, "scanned"))
    named = (
        CodexSession()
        .session_meta(INSIDE, "c1", PROJECT)
        .user_message_item(INSIDE, "hi")
        .write(tmp_path / "elsewhere" / "named.jsonl")
    )
    before = (SINCE - timedelta(days=1)).timestamp()
    os.utime(named, (before, before))

    [decision] = select(sources(tmp_path, named))

    assert isinstance(decision, Selected)
    assert decision.session.session_id == "c1"
    assert decision.session.tool is Tool.CODEX
    assert decision.session.file.expected_tool is None


def test_named_claude_code_file_is_detected_from_content(tmp_path: Path) -> None:
    named = conversation("a1", INSIDE).write(tmp_path / "named.jsonl")

    [decision] = select(sources(tmp_path, named))

    assert isinstance(decision, Selected)
    assert decision.session.tool is Tool.CLAUDE_CODE


def test_codex_files_outside_dated_directories_are_not_found(tmp_path: Path) -> None:
    builder = (
        CodexSession()
        .session_meta(INSIDE, "c1", PROJECT)
        .user_message_item(INSIDE, "hi")
    )
    builder.write(tmp_path / "codex" / "archived" / "11" / "02" / "rollout-x.jsonl")
    builder.write(tmp_path / "codex" / "2026" / "11" / "02" / "history.jsonl")

    assert select(sources(tmp_path)) == []


def test_missing_directories_give_no_sessions(tmp_path: Path) -> None:
    assert select(sources(tmp_path)) == []


def test_selected_sessions_are_ordered_by_last_activity(tmp_path: Path) -> None:
    conversation("later", INSIDE + timedelta(days=1)).write(claude_file(tmp_path, "a"))
    conversation("earlier", INSIDE).write(claude_file(tmp_path, "b"))
    CodexSession().session_meta(INSIDE, "middle", PROJECT).user_message_item(
        INSIDE + timedelta(hours=1), "hi"
    ).write(tmp_path / "codex" / "2026" / "11" / "02" / "rollout-middle.jsonl")

    assert selected_ids(select(sources(tmp_path))) == ["earlier", "middle", "later"]
