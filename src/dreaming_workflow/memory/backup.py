import re
import shutil
from pathlib import Path

DIRECTORY_MODE = 0o700
COPIES_KEPT = 10
# Run IDs are UTC start times, so they sort by age.
_RUN_ID = re.compile(r"\d{8}T\d{6}Z")


def save_copy(memory_dir: Path, backups_dir: Path, run_id: str) -> Path:
    """Copy memory to `<backups_dir>/<run_id>/` and return the copy's path.

    A memory directory that doesn't exist yet gives an empty copy. Once the
    copy succeeds, only the newest copies are kept. A failed copy raises and
    deletes nothing.
    """
    destination = backups_dir / run_id
    backups_dir.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
    backups_dir.chmod(DIRECTORY_MODE)
    if memory_dir.exists():
        # Links are copied as links, so the copy never reads outside memory.
        shutil.copytree(memory_dir, destination, symlinks=True)
    else:
        destination.mkdir(mode=DIRECTORY_MODE)
    destination.chmod(DIRECTORY_MODE)
    _delete_old_copies(backups_dir)
    return destination


def _delete_old_copies(backups_dir: Path) -> None:
    # Only directories named like run IDs are copies; anything else stays.
    copies = sorted(
        path
        for path in backups_dir.iterdir()
        if _RUN_ID.fullmatch(path.name) and path.is_dir() and not path.is_symlink()
    )
    for old in copies[:-COPIES_KEPT]:
        shutil.rmtree(old)
