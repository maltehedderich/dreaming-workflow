"""Selection against the dream record: sessions an earlier run handled."""

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dreaming_workflow.agents import AnalysisStatus, FailureReason
from dreaming_workflow.sessions import (
    AnalyzedFile,
    Selected,
    SelectionDecision,
    SessionFile,
    SessionSources,
    Skipped,
    SkipReason,
    Tool,
    discover_and_select,
)
from dreaming_workflow.sessions import discovery as discovery_module
from dreaming_workflow.state import DreamRecord, SessionRecord
from tests.support.examples import RUN_START, SINCE
from tests.support.sessions import ClaudeCodeSession

INSIDE = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
PROJECT = "/Users/dev/Projects/app"
SESSION_ID = "5e55e55e-0000-4000-8000-000000000001"


def session_file(tmp_path: Path) -> Path:
    return (
        ClaudeCodeSession(SESSION_ID, PROJECT)
        .typed_prompt(INSIDE, "How do I pin Python?")
        .assistant_text(INSIDE + timedelta(minutes=1), "Add a .python-version file.")
        .write(tmp_path / "claude" / "-Users-dev-Projects-app" / f"{SESSION_ID}.jsonl")
    )


def as_analyzed(path: Path) -> AnalyzedFile:
    """What the file holds now, as a run that analyzed it would have recorded."""
    stat = path.stat()
    return AnalyzedFile(
        stat.st_size, stat.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()
    )


def select(tmp_path: Path, analyzed: dict[Path, AnalyzedFile]) -> SelectionDecision:
    [decision] = discover_and_select(
        SessionSources(
            claude_code_dir=tmp_path / "claude", codex_dir=tmp_path / "codex"
        ),
        since=SINCE,
        now=RUN_START,
        analyzed=analyzed,
    )
    return decision


@pytest.fixture
def parser_calls(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Count calls to the Claude Code parser that selection uses."""
    calls: list[Path] = []
    parse = discovery_module.parse_claude_code

    def spy(file: SessionFile) -> object:
        calls.append(file.path)
        return parse(file)

    monkeypatch.setattr(discovery_module, "parse_claude_code", spy)
    return calls


def test_unchanged_analyzed_session_is_skipped_without_parsing(
    tmp_path: Path, parser_calls: list[Path]
) -> None:
    path = session_file(tmp_path)

    decision = select(tmp_path, {path: as_analyzed(path)})

    assert isinstance(decision, Skipped)
    assert decision.reason is SkipReason.ALREADY_ANALYZED
    assert parser_calls == []


def test_touched_file_with_the_same_content_is_skipped_after_hashing(
    tmp_path: Path, parser_calls: list[Path]
) -> None:
    path = session_file(tmp_path)
    before = as_analyzed(path)
    later = (INSIDE + timedelta(days=3)).timestamp()
    os.utime(path, (later, later))
    assert path.stat().st_mtime_ns != before.mtime_ns

    decision = select(tmp_path, {path: before})

    assert isinstance(decision, Skipped)
    assert decision.reason is SkipReason.ALREADY_ANALYZED
    assert parser_calls == []


def test_appended_records_select_the_session_again(tmp_path: Path) -> None:
    path = session_file(tmp_path)
    before = as_analyzed(path)
    # A resumed session appends to the same file.
    ClaudeCodeSession(SESSION_ID, PROJECT).typed_prompt(
        INSIDE + timedelta(hours=2), "And for Codex?"
    ).assistant_text(INSIDE + timedelta(hours=2), "The same file works.").write(
        tmp_path / "appended.jsonl"
    )
    with path.open("ab") as session:
        session.write((tmp_path / "appended.jsonl").read_bytes())

    decision = select(tmp_path, {path: before})

    assert isinstance(decision, Selected)
    assert decision.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(decision.session.view.messages) == 4


def test_failed_entry_selects_the_session_again(tmp_path: Path) -> None:
    path = session_file(tmp_path)
    now = as_analyzed(path)
    record = DreamRecord.load(tmp_path / "memory")
    record.record_session(
        path,
        SessionRecord(
            tool=Tool.CLAUDE_CODE,
            session_id=SESSION_ID,
            size=now.size,
            mtime_ns=now.mtime_ns,
            sha256=now.sha256,
            status=AnalysisStatus.FAILED,
            failure=FailureReason.RATE_LIMITED,
            run_id="20261110T213800Z",
        ),
    )

    decision = select(tmp_path, record.analyzed_files())

    assert isinstance(decision, Selected)


def test_session_without_an_entry_is_selected_with_its_hash(tmp_path: Path) -> None:
    path = session_file(tmp_path)

    decision = select(tmp_path, {})

    assert isinstance(decision, Selected)
    assert decision.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
