"""Only the 10 newest pre-run copies are kept, and only after a copy succeeds."""

import shutil
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest

from dreaming_workflow.memory.backup import save_copy

# Twelve runs on consecutive days in November 2026, oldest first.
EXISTING = [f"202611{day:02d}T080000Z" for day in range(1, 13)]
NEW_RUN = "20261113T080000Z"


def backups_with_copies(tmp_path: Path) -> Path:
    backups = tmp_path / "state" / "backups"
    for run_id in EXISTING:
        (backups / run_id).mkdir(parents=True)
        (backups / run_id / "_index.md").write_text("# Memory index\n")
    return backups


def memory_with_files(tmp_path: Path, count: int) -> Path:
    memory = tmp_path / "memory"
    memory.mkdir()
    for index in range(count):
        (memory / f"note-{index}.md").write_text(f"---\nname: note-{index}\n---\n")
    return memory


def names(backups: Path) -> list[str]:
    return sorted(path.name for path in backups.iterdir())


def test_a_new_copy_leaves_the_10_newest(tmp_path: Path) -> None:
    backups = backups_with_copies(tmp_path)
    memory = memory_with_files(tmp_path, 2)

    copy = save_copy(memory, backups, NEW_RUN)

    assert copy == backups / NEW_RUN
    assert names(backups) == [*EXISTING[3:], NEW_RUN]
    assert len(names(backups)) == 10


def test_entries_not_named_like_runs_are_kept(tmp_path: Path) -> None:
    backups = backups_with_copies(tmp_path)
    (backups / "notes.txt").write_text("kept by hand\n")

    save_copy(memory_with_files(tmp_path, 1), backups, NEW_RUN)

    assert "notes.txt" in names(backups)


def test_a_copy_that_fails_partway_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backups = backups_with_copies(tmp_path)
    memory = memory_with_files(tmp_path, 3)
    copied: list[str] = []

    def copy_then_fail(source: str, destination: str) -> object:
        if copied:
            raise OSError("disk full")
        copied.append(source)
        return shutil.copy2(source, destination)

    real_copytree: Callable[..., object] = shutil.copytree
    monkeypatch.setattr(
        shutil, "copytree", partial(real_copytree, copy_function=copy_then_fail)
    )

    with pytest.raises(OSError):
        save_copy(memory, backups, NEW_RUN)

    assert len(copied) == 1
    assert set(EXISTING) <= set(names(backups))
