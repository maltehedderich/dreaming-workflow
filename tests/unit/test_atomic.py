import os
import stat
from pathlib import Path

import pytest

from dreaming_workflow.atomic import write_atomic


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_failure_before_rename_keeps_old_content_and_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "note.md"
    target.write_bytes(b"old content")

    def fail_replace(source: str, destination: Path) -> None:
        raise OSError("simulated failure before rename")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated failure"):
        write_atomic(target, b"new content", 0o600)

    assert target.read_bytes() == b"old content"
    assert [path.name for path in tmp_path.iterdir()] == ["note.md"]


@pytest.mark.parametrize("mode", [0o600, 0o640])
def test_written_file_has_requested_mode(tmp_path: Path, mode: int) -> None:
    target = tmp_path / "note.md"

    write_atomic(target, b"content", mode)

    assert target.read_bytes() == b"content"
    assert mode_of(target) == mode


def test_replaces_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "note.md"
    target.write_bytes(b"old")

    write_atomic(target, b"new", 0o600)

    assert target.read_bytes() == b"new"
    assert [path.name for path in tmp_path.iterdir()] == ["note.md"]
