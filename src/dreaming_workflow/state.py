"""A memory directory's run state: kept outside memory, keyed by its path."""

import fcntl
import hashlib
import json
import os
import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Self

from dreaming_workflow.agents import AnalysisStatus, FailureReason
from dreaming_workflow.atomic import write_atomic
from dreaming_workflow.memory import Slug, parse_slug
from dreaming_workflow.sessions import AnalyzedFile, Tool

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


LOCK_FILE = "lock"
LOCK_MODE = 0o600


class MemoryInUse(Exception):
    """Another dream holds the lock on this memory directory."""


class RunLock:
    """Keeps runs on one memory directory exclusive, for as long as it is held.

    Uses `flock`, which the kernel releases when the process dies, so a crash
    never leaves a stale lock.
    """

    def __init__(self, directory: Path) -> None:
        self._path = directory / LOCK_FILE
        self._fd: int | None = None

    def __enter__(self) -> Self:
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT, LOCK_MODE)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise MemoryInUse from None
        self._fd = fd
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._fd is not None:
            # Closing the descriptor releases the lock.
            os.close(self._fd)
            self._fd = None


RECORD_VERSION = 1
RECORD_FILE = "record.json"
RECORD_MODE = 0o600
_SHA256 = re.compile(r"[0-9a-f]{64}")


class RecordProblem(StrEnum):
    UNKNOWN_VERSION = "unknown-version"
    INVALID = "invalid"


class RecordError(Exception):
    """The dream record can't be read. The run stops before it changes anything."""

    def __init__(self, path: Path, problem: RecordProblem) -> None:
        super().__init__(f"{path}: {problem.value}")
        self.path = path
        self.problem = problem


@dataclass(frozen=True)
class SessionRecord:
    """A finished session: what its file held when analyzed, and how that ended."""

    tool: Tool
    session_id: str
    size: int
    mtime_ns: int
    sha256: str
    status: AnalysisStatus
    # Set exactly when the analysis failed.
    failure: FailureReason | None
    run_id: str

    def to_json(self) -> dict[str, object]:
        return {
            "tool": self.tool.value,
            "session_id": self.session_id,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "sha256": self.sha256,
            "status": self.status.value,
            "failure": None if self.failure is None else self.failure.value,
            "run_id": self.run_id,
        }


def _int(value: object) -> int | None:
    # bool is an int subclass; JSON true and false aren't sizes.
    return value if type(value) is int and value >= 0 else None


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _parse_session_record(value: object) -> SessionRecord | None:
    if not isinstance(value, dict):
        return None
    tool, session_id, sha256, status, run_id = (
        _str(value.get(key))
        for key in ("tool", "session_id", "sha256", "status", "run_id")
    )
    size, mtime_ns = _int(value.get("size")), _int(value.get("mtime_ns"))
    raw_failure = value.get("failure")
    failure = None if raw_failure is None else _str(raw_failure)
    if (
        tool not in Tool
        or status not in AnalysisStatus
        or (raw_failure is not None and failure not in FailureReason)
        or session_id is None
        or run_id is None
        or sha256 is None
        or not _SHA256.fullmatch(sha256)
        or size is None
        or mtime_ns is None
    ):
        return None
    record = SessionRecord(
        tool=Tool(tool),
        session_id=session_id,
        size=size,
        mtime_ns=mtime_ns,
        sha256=sha256,
        status=AnalysisStatus(status),
        failure=None if failure is None else FailureReason(failure),
        run_id=run_id,
    )
    if (record.status is AnalysisStatus.FAILED) != (record.failure is not None):
        return None
    return record


def _parse_record(
    path: Path, data: bytes
) -> tuple[list[Slug], dict[Path, SessionRecord]]:
    """Parse `record.json` into its waiting files and sessions, or raise `RecordError`."""
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
    sessions = parsed.get("sessions", {})
    if (
        not isinstance(parsed.get("memory_dir"), str)
        or not isinstance(waiting, list)
        or not isinstance(sessions, dict)
    ):
        raise RecordError(path, RecordProblem.INVALID)
    slugs: list[Slug] = []
    for item in waiting:
        slug = parse_slug(item) if isinstance(item, str) else None
        if slug is None:
            raise RecordError(path, RecordProblem.INVALID)
        slugs.append(slug)
    records: dict[Path, SessionRecord] = {}
    for key, value in sessions.items():
        record = _parse_session_record(value)
        if record is None or not Path(key).is_absolute():
            raise RecordError(path, RecordProblem.INVALID)
        records[Path(key)] = record
    return slugs, records


class DreamRecord:
    """What runs on one memory directory remember between them.

    Stored as `record.json` in the state directory and saved atomically after
    every change. This class is the only code that reads or writes it. Safe to
    call from the threads that run agent tools.
    """

    def __init__(
        self,
        memory_dir: Path,
        waiting_files: list[Slug],
        sessions: Mapping[Path, SessionRecord],
    ) -> None:
        self._memory_dir = memory_dir
        self._waiting: list[Slug] = list(dict.fromkeys(waiting_files))
        self._sessions: dict[Path, SessionRecord] = dict(sessions)
        self._lock = threading.Lock()

    @classmethod
    def load(cls, memory_dir: Path) -> DreamRecord:
        """Read the record, or start an empty one. Creates nothing."""
        path = state_dir(memory_dir) / RECORD_FILE
        if not path.exists():
            return cls(memory_dir, [], {})
        waiting, sessions = _parse_record(path, path.read_bytes())
        return cls(memory_dir, waiting, sessions)

    @property
    def waiting_files(self) -> tuple[Slug, ...]:
        """Files waiting for the organizer, oldest first."""
        with self._lock:
            return tuple(self._waiting)

    @property
    def sessions(self) -> Mapping[Path, SessionRecord]:
        """Finished sessions by absolute file path."""
        with self._lock:
            return MappingProxyType(dict(self._sessions))

    def analyzed_files(self) -> dict[Path, AnalyzedFile]:
        """Files whose last analysis succeeded, for selection to skip if unchanged."""
        with self._lock:
            return {
                path: AnalyzedFile(record.size, record.mtime_ns, record.sha256)
                for path, record in self._sessions.items()
                if record.status is AnalysisStatus.ANALYZED
            }

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

    def record_session(self, path: Path, record: SessionRecord) -> None:
        """Store how a session ended, replacing its entry from an earlier run."""
        with self._lock:
            self._sessions[path] = record
            self._save()

    def _save(self) -> None:
        record = {
            "version": RECORD_VERSION,
            "memory_dir": os.path.realpath(self._memory_dir, strict=False),
            "sessions": {
                str(path): entry.to_json() for path, entry in self._sessions.items()
            },
            "waiting_files": self._waiting,
        }
        data = (json.dumps(record, indent=2) + "\n").encode()
        write_atomic(
            ensure_state_dir(self._memory_dir) / RECORD_FILE, data, RECORD_MODE
        )
