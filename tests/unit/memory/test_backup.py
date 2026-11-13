import stat
from pathlib import Path

from dreaming_workflow.memory.backup import save_copy
from dreaming_workflow.state import ensure_state_dir, state_dir

RUN_ID = "20261110T213800Z"


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def contents(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_copy_matches_memory_byte_for_byte(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "_index.md").write_bytes(b"# Memory index\n")
    (memory / "uv-python.md").write_bytes(
        "---\nname: uv-python\n---\n- café\n".encode()
    )
    backups = ensure_state_dir(memory) / "backups"

    copy = save_copy(memory, backups, RUN_ID)

    assert copy == backups / RUN_ID
    assert contents(copy) == contents(memory)
    assert mode_of(copy) == 0o700
    assert not copy.is_relative_to(memory)


def test_copy_of_missing_memory_is_an_empty_directory(tmp_path: Path) -> None:
    memory = tmp_path / "memory"

    copy = save_copy(memory, tmp_path / "state" / "backups", RUN_ID)

    assert copy.is_dir()
    assert list(copy.iterdir()) == []
    assert mode_of(copy) == 0o700
    assert not memory.exists()


def test_state_dir_is_under_xdg_state_home_and_not_created(tmp_path: Path) -> None:
    memory = tmp_path / "memory"

    path = state_dir(memory)

    # The test environment points XDG_STATE_HOME at tmp_path / "state".
    assert path.parent == tmp_path / "state" / "dreaming-workflow"
    assert len(path.name) == 16
    assert not path.exists()


def test_state_dir_key_follows_the_real_path(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    (tmp_path / "link").symlink_to(memory)

    assert state_dir(tmp_path / "link") == state_dir(memory)
    assert state_dir(tmp_path / "other") != state_dir(memory)


def test_ensure_state_dir_creates_a_private_directory(tmp_path: Path) -> None:
    path = ensure_state_dir(tmp_path / "memory")

    assert path.is_dir()
    assert mode_of(path) == 0o700
