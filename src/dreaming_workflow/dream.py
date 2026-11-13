"""The dream run: the only module that wires sessions, agents, and memory together."""

import asyncio
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from google.adk.models import BaseLlm

from dreaming_workflow.agents import (
    AgentFailure,
    AnalysisResult,
    AnalysisStatus,
    Failure,
    FailureReason,
    Invocation,
    ModelFactory,
    OrganizerResult,
    OrganizerStatus,
    analyze_session,
    organize,
    select_input,
)
from dreaming_workflow.agents.budget import UsageLedger
from dreaming_workflow.memory import (
    FormatViolation,
    MemoryStore,
    Refusal,
    check_format,
)
from dreaming_workflow.memory.backup import save_copy
from dreaming_workflow.report import Report, RunOutcome, build_report, index_stats
from dreaming_workflow.sessions import (
    Selected,
    SessionSources,
    discover_and_select,
)
from dreaming_workflow.state import DreamRecord, ensure_state_dir

GROUP_SIZE = 20

type Progress = Callable[[str], None]


@dataclass(frozen=True)
class RunOptions:
    memory_dir: Path
    since: datetime
    claude_code_dir: Path
    codex_dir: Path
    # When given, these files replace both directory scans.
    session_files: tuple[Path, ...] = ()


@dataclass(frozen=True)
class RunResult:
    report: Report
    outcome: RunOutcome


def run_id_for(started_at: datetime) -> str:
    return f"{started_at.astimezone(UTC):%Y%m%dT%H%M%SZ}"


def _to_stderr(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


class _StopAfterAuthenticationFailure:
    """Wraps the model factory so no new invocation starts once credentials fail.

    Every later part and session then fails with the same reason without
    sending a request.
    """

    def __init__(self, factory: ModelFactory) -> None:
        self._factory = factory
        self.stopped = False

    def __call__(self, invocation: Invocation) -> BaseLlm:
        if self.stopped:
            raise AgentFailure(Failure(FailureReason.AUTHENTICATION_FAILED))
        return self._factory(invocation)

    def note(self, result: AnalysisResult) -> None:
        if (
            result.failure is not None
            and result.failure.reason is FailureReason.AUTHENTICATION_FAILED
        ):
            self.stopped = True


def _progress_line(result: AnalysisResult) -> str:
    session = result.session
    name = f"{session.tool.value} {session.session_id}"
    if result.status is AnalysisStatus.ANALYZED:
        return f"  analyzed  {name} ({_plural(result.parts_run, 'part')})"
    reason = result.failure.reason.value if result.failure is not None else "unknown"
    return f"  failed    {name} ({reason})"


async def _organize(
    store: MemoryStore,
    record: DreamRecord,
    analyzed_any: bool,
    model_factory: ModelFactory,
    ledger: UsageLedger,
    progress: Progress,
) -> OrganizerResult:
    """Run the organizer if an analysis succeeded or files are waiting for it.

    Received files stop waiting only when the pass succeeds.
    """
    violations = check_format(store.memory_dir)
    organizer_input = select_input(record.waiting_files, violations, store)
    record.stop_waiting(organizer_input.gone)
    if not analyzed_any and not record.waiting_files:
        return OrganizerResult(OrganizerStatus.NOT_RUN)
    progress(f"Organizing {_plural(len(organizer_input.received), 'memory file')}")
    result = await organize(organizer_input, violations, store, model_factory, ledger)
    if result.status is OrganizerStatus.SUCCEEDED:
        record.stop_waiting(result.received)
    return result


async def run(
    options: RunOptions,
    *,
    now: datetime,
    model_factory: ModelFactory,
    progress: Progress = _to_stderr,
) -> RunResult:
    """Analyze the selected sessions, organize memory, and check its format.

    Raises `RecordError` before changing anything if the dream record can't be read.
    """
    run_id = run_id_for(now)
    record = DreamRecord.load(options.memory_dir)
    sources = SessionSources(
        claude_code_dir=options.claude_code_dir,
        codex_dir=options.codex_dir,
        session_files=options.session_files,
    )
    decisions = discover_and_select(sources, options.since, now)
    selected = [d for d in decisions if isinstance(d, Selected)]
    progress(
        f"Found {_plural(len(decisions), 'session')}: {len(selected)} selected, "
        f"{len(decisions) - len(selected)} skipped."
    )

    backup_path: Path | None = None

    def save_pre_run_copy() -> None:
        nonlocal backup_path
        backups = ensure_state_dir(options.memory_dir) / "backups"
        backup_path = save_copy(options.memory_dir, backups, run_id)
        progress(f"Saved a copy of memory to {backup_path}")

    store = MemoryStore(
        options.memory_dir,
        before_first_write=save_pre_run_copy,
        on_analysis_write=record.mark_waiting,
    )
    start = store.snapshot()
    ledger = UsageLedger()
    factory = _StopAfterAuthenticationFailure(model_factory)

    def report_for(
        results: list[AnalysisResult],
        organizer: OrganizerResult,
        violations: list[FormatViolation],
        *,
        nothing_to_dream: bool = False,
    ) -> Report:
        index_text = store.read_index()
        return build_report(
            run_id=run_id,
            decisions=decisions,
            results=results,
            organizer=organizer,
            waiting_files=len(record.waiting_files),
            start=start,
            end=store.snapshot(),
            index=None if isinstance(index_text, Refusal) else index_stats(index_text),
            violations=violations,
            ledger=ledger,
            backup_path=backup_path,
            nothing_to_dream=nothing_to_dream,
        )

    if not selected and not record.waiting_files:
        report = report_for(
            [], OrganizerResult(OrganizerStatus.NOT_RUN), [], nothing_to_dream=True
        )
        return RunResult(report=report, outcome=report.outcome)

    async def analyze(decision: Selected) -> AnalysisResult:
        result = await analyze_session(
            decision.session, decision.parts, store, factory, ledger
        )
        factory.note(result)
        progress(_progress_line(result))
        return result

    results: list[AnalysisResult] = []
    groups = [
        selected[index : index + GROUP_SIZE]
        for index in range(0, len(selected), GROUP_SIZE)
    ]
    for number, group in enumerate(groups, start=1):
        progress(
            f"Group {number} of {len(groups)}: "
            f"analyzing {_plural(len(group), 'session')}"
        )
        results.extend(await asyncio.gather(*(analyze(d) for d in group)))

    organizer = await _organize(
        store,
        record,
        any(r.status is AnalysisStatus.ANALYZED for r in results),
        factory,
        ledger,
        progress,
    )
    progress("Checking memory format")
    report = report_for(results, organizer, check_format(options.memory_dir))
    return RunResult(report=report, outcome=report.outcome)
