"""The run report, built only from the run's own records, never from logs or content."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from dreaming_workflow.agents import (
    AnalysisResult,
    AnalysisStatus,
    FailureReason,
    OrganizerResult,
    OrganizerStatus,
)
from dreaming_workflow.agents.budget import UsageLedger
from dreaming_workflow.memory import FormatViolation, MemorySnapshot
from dreaming_workflow.memory.index import IndexParseError, parse_index
from dreaming_workflow.sessions import (
    Selected,
    SelectionDecision,
    Skipped,
    SkipReason,
    Tool,
)


class RunOutcome(StrEnum):
    SUCCESS = "success"
    COMPLETED_WITH_FAILURES = "completed-with-failures"
    NOT_STARTED = "not-started"

    @property
    def exit_code(self) -> int:
        match self:
            case RunOutcome.SUCCESS:
                return 0
            case RunOutcome.COMPLETED_WITH_FAILURES:
                return 1
            case RunOutcome.NOT_STARTED:
                return 2


@dataclass(frozen=True)
class FailedSession:
    tool: Tool
    session_id: str
    reason: FailureReason


@dataclass(frozen=True)
class OrganizerSummary:
    status: OrganizerStatus
    # Set when the organizer failed.
    failure: FailureReason | None = None


@dataclass(frozen=True)
class IndexStats:
    entries: int
    domains: int
    subdomains: int


@dataclass(frozen=True)
class FileChanges:
    created: int
    changed: int
    retired: int


@dataclass(frozen=True)
class Usage:
    """Token counts and cost at list price. `input_tokens` counts every input token."""

    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    cost_usd: Decimal


@dataclass(frozen=True)
class Report:
    run_id: str
    found: int
    selected: int
    # In SkipReason order, only reasons that occurred.
    skipped_by_reason: tuple[tuple[SkipReason, int], ...]
    analyzed: int
    analyzed_in_parts: int
    failed: tuple[FailedSession, ...]
    organizer: OrganizerSummary
    # Files still waiting for the organizer after the run.
    waiting_files: int
    # None when _index.md can't be parsed.
    index: IndexStats | None
    files: FileChanges
    conflicts_added: int
    violations: tuple[FormatViolation, ...]
    usage: Usage
    # None when the run wrote nothing, so no copy was made.
    backup_path: Path | None
    # The run stopped after selection: nothing was selected and nothing waited.
    nothing_to_dream: bool = False

    @property
    def skipped(self) -> int:
        return sum(count for _, count in self.skipped_by_reason)

    @property
    def outcome(self) -> RunOutcome:
        if (
            self.failed
            or self.organizer.status is OrganizerStatus.FAILED
            or self.violations
        ):
            return RunOutcome.COMPLETED_WITH_FAILURES
        return RunOutcome.SUCCESS


def index_stats(index_text: str) -> IndexStats | None:
    index = parse_index(index_text)
    if isinstance(index, IndexParseError):
        return None
    return IndexStats(
        entries=len(index.slugs()),
        domains=len(index.domains),
        subdomains=sum(len(domain.subdomains) for domain in index.domains),
    )


def file_changes(start: MemorySnapshot, end: MemorySnapshot) -> FileChanges:
    retired = {
        slug for slug in start.hashes if slug not in start.stubs and slug in end.stubs
    }
    changed = {
        slug
        for slug, digest in end.hashes.items()
        if slug in start.hashes and start.hashes[slug] != digest
    } - retired
    created = end.hashes.keys() - start.hashes.keys()
    return FileChanges(created=len(created), changed=len(changed), retired=len(retired))


def usage_of(ledger: UsageLedger) -> Usage:
    return Usage(
        input_tokens=ledger.prompt_tokens,
        cache_read_tokens=ledger.cache_read_tokens,
        cache_write_tokens=ledger.cache_write_tokens,
        output_tokens=ledger.output_tokens,
        cost_usd=ledger.cost_usd,
    )


def build_report(
    *,
    run_id: str,
    decisions: Sequence[SelectionDecision],
    results: Sequence[AnalysisResult],
    organizer: OrganizerResult,
    waiting_files: int,
    start: MemorySnapshot,
    end: MemorySnapshot,
    index: IndexStats | None,
    violations: Sequence[FormatViolation],
    ledger: UsageLedger,
    backup_path: Path | None,
    nothing_to_dream: bool = False,
) -> Report:
    skip_counts = Counter(d.reason for d in decisions if isinstance(d, Skipped))
    analyzed = [r for r in results if r.status is AnalysisStatus.ANALYZED]
    failed = tuple(
        FailedSession(r.session.tool, r.session.session_id, r.failure.reason)
        for r in results
        if r.failure is not None
    )
    return Report(
        run_id=run_id,
        found=len(decisions),
        selected=sum(isinstance(d, Selected) for d in decisions),
        skipped_by_reason=tuple(
            (reason, skip_counts[reason])
            for reason in SkipReason
            if skip_counts[reason]
        ),
        analyzed=len(analyzed),
        analyzed_in_parts=sum(r.parts_run > 1 for r in analyzed),
        failed=failed,
        organizer=OrganizerSummary(
            organizer.status,
            None if organizer.failure is None else organizer.failure.reason,
        ),
        waiting_files=waiting_files,
        index=index,
        files=file_changes(start, end),
        conflicts_added=len(end.conflicts - start.conflicts),
        violations=tuple(violations),
        usage=usage_of(ledger),
        backup_path=backup_path,
        nothing_to_dream=nothing_to_dream,
    )
