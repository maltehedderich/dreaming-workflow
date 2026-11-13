import json
import stat
from pathlib import Path

import pytest

from dreaming_workflow.memory import Slug
from dreaming_workflow.state import (
    DreamRecord,
    RecordError,
    RecordProblem,
    state_dir,
)


def record_path(memory: Path) -> Path:
    return state_dir(memory) / "record.json"


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
        "waiting_files": ["uv-python", "docs-lookup"],
    }


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
