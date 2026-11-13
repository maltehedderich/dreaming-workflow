"""Find session files and decide which ones a run analyzes.

Preview and run both call `discover_and_select`, so a preview lists exactly
what a run would select.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from dreaming_workflow.sessions.claude_code import parse_claude_code
from dreaming_workflow.sessions.codex import parse_codex
from dreaming_workflow.sessions.model import (
    Selected,
    SelectionDecision,
    Session,
    SessionFile,
    Skipped,
    SkipReason,
    Tool,
)
from dreaming_workflow.sessions.view import is_too_large, split_into_parts

ACTIVE_WINDOW = timedelta(hours=1)
_SUBAGENTS_DIR = "subagents"
_CODEX_DATE_DIRS = (re.compile(r"\d{4}"), re.compile(r"\d{2}"), re.compile(r"\d{2}"))


@dataclass(frozen=True)
class SessionSources:
    """Where to look. Named `session_files` replace both directory scans."""

    claude_code_dir: Path
    codex_dir: Path
    session_files: tuple[Path, ...] = ()


def parse_session(file: SessionFile) -> Session | None:
    """Parse with the expected tool's parser, or detect the tool from content."""
    match file.expected_tool:
        case Tool.CLAUDE_CODE:
            return parse_claude_code(file)
        case Tool.CODEX:
            return parse_codex(file)
        case None:
            return parse_codex(file) or parse_claude_code(file)


def _claude_code_files(directory: Path) -> Iterator[Path]:
    if directory.is_dir():
        yield from directory.rglob("*.jsonl")


def _codex_files(directory: Path) -> Iterator[Path]:
    if not directory.is_dir():
        return
    for path in directory.glob("*/*/*/rollout-*.jsonl"):
        date_dirs = path.relative_to(directory).parts[:3]
        if all(
            pattern.fullmatch(name)
            for pattern, name in zip(_CODEX_DATE_DIRS, date_dirs, strict=True)
        ):
            yield path


def _candidates(sources: SessionSources) -> list[SessionFile]:
    if sources.session_files:
        return [
            SessionFile.at(path, expected_tool=None) for path in sources.session_files
        ]
    found = [
        SessionFile.at(path, Tool.CLAUDE_CODE)
        for path in _claude_code_files(sources.claude_code_dir)
        if path.is_file()
    ]
    found += [
        SessionFile.at(path, Tool.CODEX)
        for path in _codex_files(sources.codex_dir)
        if path.is_file()
    ]
    return sorted(found, key=lambda file: file.path)


def _decide(file: SessionFile, since: datetime, now: datetime) -> SelectionDecision:
    session = parse_session(file)
    if session is None:
        return Skipped(file, SkipReason.UNRECOGNIZED)
    if session.parent_thread_id is not None:
        return Skipped(file, SkipReason.SUBTHREAD)
    if not session.view.messages:
        return Skipped(file, SkipReason.NO_CONVERSATION)
    if session.last_activity_at < since:
        return Skipped(file, SkipReason.OUTSIDE_WINDOW)
    if now - session.last_activity_at < ACTIVE_WINDOW:
        return Skipped(file, SkipReason.ACTIVE)
    if is_too_large(session.view):
        detail = f"{session.view.estimated_tokens:,} estimated tokens"
        return Skipped(file, SkipReason.TOO_LARGE, detail)
    return Selected(session, tuple(split_into_parts(session.view)))


def discover_and_select(
    sources: SessionSources, since: datetime, now: datetime
) -> list[SelectionDecision]:
    """Return a decision for every file found: selected sessions first, oldest
    last activity first, then skipped files in path order.
    """
    since_ns = int(since.timestamp() * 1_000_000_000)
    selected: list[Selected] = []
    skipped: list[Skipped] = []
    for file in _candidates(sources):
        if _SUBAGENTS_DIR in file.path.parent.parts:
            skipped.append(Skipped(file, SkipReason.SUBAGENT))
            continue
        # A file last written before the window can't hold activity inside it,
        # so it isn't parsed or counted as found. Named files always count.
        if not sources.session_files and file.mtime_ns < since_ns:
            continue
        match _decide(file, since, now):
            case Selected() as decision:
                selected.append(decision)
            case Skipped() as decision:
                skipped.append(decision)
    selected.sort(key=lambda d: (d.session.last_activity_at, d.session.file.path))
    return [*selected, *skipped]
