"""A memory directory's run state: kept outside memory, keyed by its path."""

import hashlib
import json
import os
import threading
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path

from dreaming_workflow.atomic import write_atomic
from dreaming_workflow.memory import Slug, parse_slug

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


RECORD_VERSION = 1
RECORD_FILE = "record.json"
RECORD_MODE = 0o600


class RecordProblem(StrEnum):
    UNKNOWN_VERSION = "unknown-version"
    INVALID = "invalid"


class RecordError(Exception):
    """The dream record can't be read. The run stops before it changes anything."""

    def __init__(self, path: Path, problem: RecordProblem) -> None:
        super().__init__(f"{path}: {problem.value}")
        self.path = path
        self.problem = problem


def _parse_record(path: Path, data: bytes) -> list[Slug]:
    """Parse `record.json` into its waiting files, or raise `RecordError`."""
    try:
        parsed: object = json.loads(data)
    except ValueError:
        raise RecordError(path, RecordProblem.INVALID) from None
    if not isinstance(parsed, dict):
        raise RecordError(path, RecordProblem.INVALID)
    version = parsed.get("version")
    if type(version) is not int or version != RECORD_VERSION:
        raise RecordError(path, RecordProblem.UNKNOWN_VERSION)
    waiting = parsed.get("waiting_files", [])
    if not isinstance(parsed.get("memory_dir"), str) or not isinstance(waiting, list):
        raise RecordError(path, RecordProblem.INVALID)
    slugs: list[Slug] = []
    for item in waiting:
        slug = parse_slug(item) if isinstance(item, str) else None
        if slug is None:
            raise RecordError(path, RecordProblem.INVALID)
        slugs.append(slug)
    return slugs


class DreamRecord:
    """What runs on one memory directory remember between them.

    Stored as `record.json` in the state directory and saved atomically after
    every change. This class is the only code that reads or writes it. Safe to
    call from the threads that run agent tools.
    """

    def __init__(self, memory_dir: Path, waiting_files: list[Slug]) -> None:
        self._memory_dir = memory_dir
        self._waiting: list[Slug] = list(dict.fromkeys(waiting_files))
        self._lock = threading.Lock()

    @classmethod
    def load(cls, memory_dir: Path) -> DreamRecord:
        """Read the record, or start an empty one. Creates nothing."""
        path = state_dir(memory_dir) / RECORD_FILE
        if not path.exists():
            return cls(memory_dir, [])
        return cls(memory_dir, _parse_record(path, path.read_bytes()))

    @property
    def waiting_files(self) -> tuple[Slug, ...]:
        """Files waiting for the organizer, oldest first."""
        with self._lock:
            return tuple(self._waiting)

    def mark_waiting(self, slug: Slug) -> None:
        """Add a file the organizer hasn't seen yet. A file already waiting keeps its place."""
        with self._lock:
            if slug in self._waiting:
                return
            self._waiting.append(slug)
            self._save()

    def stop_waiting(self, slugs: Iterable[Slug]) -> None:
        done = set(slugs)
        with self._lock:
            if not done & set(self._waiting):
                return
            self._waiting = [slug for slug in self._waiting if slug not in done]
            self._save()

    def _save(self) -> None:
        record = {
            "version": RECORD_VERSION,
            "memory_dir": os.path.realpath(self._memory_dir, strict=False),
            "waiting_files": self._waiting,
        }
        data = (json.dumps(record, indent=2) + "\n").encode()
        write_atomic(
            ensure_state_dir(self._memory_dir) / RECORD_FILE, data, RECORD_MODE
        )
