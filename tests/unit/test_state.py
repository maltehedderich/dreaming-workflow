import json
import stat
from pathlib import Path

import pytest

from dreaming_workflow.agents import AnalysisStatus, FailureReason
from dreaming_workflow.memory import Slug
from dreaming_workflow.sessions import AnalyzedFile, Tool
from dreaming_workflow.state import (
    DreamRecord,
    MemoryInUse,
    RecordError,
    RecordProblem,
    RunLock,
    SessionRecord,
    ensure_state_dir,
    state_dir,
)

SESSION_PATH = Path(
    "/Users/dev/.claude/projects/-Users-dev-Projects/"
    "90f95193-2c91-4a42-a506-930d4c964c45.jsonl"
)
OTHER_PATH = Path("/Users/dev/.codex/sessions/2026/11/06/rollout-x.jsonl")
OLD_CONTENT = "a" * 64
NEW_CONTENT = "b" * 64


def record_path(memory: Path) -> Path:
    return state_dir(memory) / "record.json"


def analyzed(
    sha256: str = OLD_CONTENT, run_id: str = "20261110T213800Z"
) -> SessionRecord:
    return SessionRecord(
        tool=Tool.CLAUDE_CODE,
        session_id="90f95193-2c91-4a42-a506-930d4c964c45",
        size=54_250,
        mtime_ns=1_792_230_000_000_000_000,
        sha256=sha256,
        status=AnalysisStatus.ANALYZED,
        failure=None,
        run_id=run_id,
    )


def failed(
    reason: FailureReason = FailureReason.RATE_LIMITED,
    sha256: str = OLD_CONTENT,
    run_id: str = "20261110T213800Z",
) -> SessionRecord:
    return SessionRecord(
        tool=Tool.CLAUDE_CODE,
        session_id="90f95193-2c91-4a42-a506-930d4c964c45",
        size=54_250,
        mtime_ns=1_792_230_000_000_000_000,
        sha256=sha256,
        status=AnalysisStatus.FAILED,
        failure=reason,
        run_id=run_id,
    )


def test_a_missing_record_is_empty_and_loading_creates_nothing(tmp_path: Path) -> None:
    memory = tmp_path / "memory"

    record = DreamRecord.load(memory)

    assert record.waiting_files == ()
    assert not (tmp_path / "state").exists()


def test_waiting_files_round_trip_oldest_first(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    record = DreamRecord.load(memory)

    record.mark_waiting(Slug("uv-python"))
    record.mark_waiting(Slug("ctx7-setup"))
    record.mark_waiting(Slug("uv-python"))
    record.mark_waiting(Slug("docs-lookup"))
    record.stop_waiting([Slug("ctx7-setup")])

    assert DreamRecord.load(memory).waiting_files == ("uv-python", "docs-lookup")
    assert json.loads(record_path(memory).read_text()) == {
        "version": 1,
        "memory_dir": str(memory.resolve()),
        "sessions": {},
        "waiting_files": ["uv-python", "docs-lookup"],
    }


def test_session_entries_round_trip_in_the_documented_format(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    record = DreamRecord.load(memory)

    record.record_session(SESSION_PATH, analyzed())
    record.record_session(OTHER_PATH, failed(FailureReason.SPENDING_LIMIT_REACHED))

    loaded = DreamRecord.load(memory)
    assert dict(loaded.sessions) == {
        SESSION_PATH: analyzed(),
        OTHER_PATH: failed(FailureReason.SPENDING_LIMIT_REACHED),
    }
    stored = json.loads(record_path(memory).read_text())
    assert stored["sessions"][str(SESSION_PATH)] == {
        "tool": "claude-code",
        "session_id": "90f95193-2c91-4a42-a506-930d4c964c45",
        "size": 54_250,
        "mtime_ns": 1_792_230_000_000_000_000,
        "sha256": OLD_CONTENT,
        "status": "analyzed",
        "failure": None,
        "run_id": "20261110T213800Z",
    }
    assert stored["sessions"][str(OTHER_PATH)]["status"] == "failed"
    assert stored["sessions"][str(OTHER_PATH)]["failure"] == "spending-limit-reached"


def test_a_record_without_sessions_loads_with_none(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    path = record_path(memory)
    path.parent.mkdir(parents=True)
    path.write_text('{"version": 1, "memory_dir": "/m", "waiting_files": ["a"]}')

    record = DreamRecord.load(memory)

    assert record.sessions == {}
    assert record.waiting_files == ("a",)


@pytest.mark.parametrize(
    "previous",
    [None, analyzed(OLD_CONTENT), failed(sha256=OLD_CONTENT)],
    ids=["no entry", "analyzed with changed content", "failed"],
)
@pytest.mark.parametrize(
    "outcome",
    [
        analyzed(NEW_CONTENT, "20261111T080000Z"),
        failed(FailureReason.TIMEOUT, NEW_CONTENT, "20261111T080000Z"),
    ],
    ids=["analyzed", "failed"],
)
def test_a_finished_session_replaces_its_entry(
    tmp_path: Path, previous: SessionRecord | None, outcome: SessionRecord
) -> None:
    memory = tmp_path / "memory"
    if previous is not None:
        DreamRecord.load(memory).record_session(SESSION_PATH, previous)

    DreamRecord.load(memory).record_session(SESSION_PATH, outcome)

    assert DreamRecord.load(memory).sessions == {SESSION_PATH: outcome}


def test_only_analyzed_entries_count_as_analyzed_files(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    record = DreamRecord.load(memory)
    record.record_session(SESSION_PATH, analyzed())
    record.record_session(OTHER_PATH, failed())

    assert DreamRecord.load(memory).analyzed_files() == {
        SESSION_PATH: AnalyzedFile(54_250, 1_792_230_000_000_000_000, OLD_CONTENT)
    }


def test_a_session_interrupted_before_it_finishes_keeps_its_previous_entry(
    tmp_path: Path,
) -> None:
    memory = tmp_path / "memory"
    DreamRecord.load(memory).record_session(SESSION_PATH, analyzed())

    # A later run finishes another session; the run stops before this one finishes.
    later_run = DreamRecord.load(memory)
    later_run.record_session(OTHER_PATH, failed(run_id="20261111T080000Z"))
    later_run.mark_waiting(Slug("uv-python"))

    assert DreamRecord.load(memory).sessions[SESSION_PATH] == analyzed()


def test_record_and_state_directory_are_private(tmp_path: Path) -> None:
    memory = tmp_path / "memory"

    DreamRecord.load(memory).mark_waiting(Slug("uv-python"))

    assert stat.S_IMODE(record_path(memory).stat().st_mode) == 0o600
    assert stat.S_IMODE(state_dir(memory).stat().st_mode) == 0o700


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ('{"version": 2, "memory_dir": "/m", "waiting_files": []}', "unknown-version"),
        ('{"memory_dir": "/m", "waiting_files": []}', "unknown-version"),
        ("not json", "invalid"),
        ("[]", "invalid"),
        (
            '{"version": 1, "memory_dir": "/m", "waiting_files": ["Bad Slug"]}',
            "invalid",
        ),
        ('{"version": 1, "waiting_files": []}', "invalid"),
        ('{"version": 1, "memory_dir": "/m", "sessions": []}', "invalid"),
    ],
)
def test_an_unreadable_record_raises_with_its_path(
    tmp_path: Path, content: str, problem: str
) -> None:
    memory = tmp_path / "memory"
    path = record_path(memory)
    path.parent.mkdir(parents=True)
    path.write_text(content)

    with pytest.raises(RecordError) as raised:
        DreamRecord.load(memory)

    assert raised.value.path == path
    assert raised.value.problem is RecordProblem(problem)


def session_entry(**changes: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "tool": "codex",
        "session_id": "eef4a695-6c41-4e5f-ba21-c3b858881bd1",
        "size": 10,
        "mtime_ns": 20,
        "sha256": OLD_CONTENT,
        "status": "failed",
        "failure": "timeout",
        "run_id": "20261110T213800Z",
    }
    entry.update(changes)
    return entry


@pytest.mark.parametrize(
    ("key", "entry"),
    [
        ("relative/path.jsonl", session_entry()),
        (str(OTHER_PATH), session_entry(tool="cursor")),
        (str(OTHER_PATH), session_entry(status="skipped")),
        (str(OTHER_PATH), session_entry(failure=None)),
        (str(OTHER_PATH), session_entry(status="analyzed")),
        (str(OTHER_PATH), session_entry(failure="exploded")),
        (str(OTHER_PATH), session_entry(sha256="abc")),
        (str(OTHER_PATH), session_entry(size=True)),
        (str(OTHER_PATH), session_entry(mtime_ns=-1)),
        (str(OTHER_PATH), session_entry(session_id="")),
        (str(OTHER_PATH), {}),
    ],
)
def test_an_invalid_session_entry_makes_the_record_unreadable(
    tmp_path: Path, key: str, entry: dict[str, object]
) -> None:
    memory = tmp_path / "memory"
    path = record_path(memory)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"version": 1, "memory_dir": "/m", "sessions": {key: entry}})
    )

    with pytest.raises(RecordError) as raised:
        DreamRecord.load(memory)

    assert raised.value.problem is RecordProblem.INVALID


def test_a_second_lock_on_the_same_memory_is_refused_until_the_first_is_released(
    tmp_path: Path,
) -> None:
    directory = ensure_state_dir(tmp_path / "memory")

    with RunLock(directory):
        with pytest.raises(MemoryInUse), RunLock(directory):
            pass
        assert stat.S_IMODE((directory / "lock").stat().st_mode) == 0o600

    with RunLock(directory):
        pass


def test_locks_on_different_memory_directories_are_independent(tmp_path: Path) -> None:
    with (
        RunLock(ensure_state_dir(tmp_path / "memory")),
        RunLock(ensure_state_dir(tmp_path / "other-memory")),
    ):
        pass
