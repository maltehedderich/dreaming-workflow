"""Where a memory directory's run state lives: outside memory, keyed by its path."""

import hashlib
import os
from pathlib import Path

DIRECTORY_MODE = 0o700
_APP_DIR = "dreaming-workflow"


def _state_home() -> Path:
    # The XDG spec says to ignore relative values.
    configured = os.environ.get("XDG_STATE_HOME", "")
    if configured and Path(configured).is_absolute():
        return Path(configured)
    return Path.home() / ".local" / "state"


def state_dir(memory_dir: Path) -> Path:
    """Return the state directory for `memory_dir` without creating anything.

    Preview computes this path too, and must leave no trace.
    """
    # Non-strict, because the memory directory may not exist yet.
    real_path = os.path.realpath(memory_dir, strict=False)
    key = hashlib.sha256(real_path.encode()).hexdigest()[:16]
    return _state_home() / _APP_DIR / key


def ensure_state_dir(memory_dir: Path) -> Path:
    path = state_dir(memory_dir)
    path.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
    # mkdir applies the umask; set the mode explicitly.
    path.chmod(DIRECTORY_MODE)
    return path
