import shutil
from pathlib import Path

DIRECTORY_MODE = 0o700


def save_copy(memory_dir: Path, backups_dir: Path, run_id: str) -> Path:
    """Copy memory to `<backups_dir>/<run_id>/` and return the copy's path.

    A memory directory that doesn't exist yet gives an empty copy.
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
    return destination
