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
    analyze_session,
)
from dreaming_workflow.agents.budget import UsageLedger
from dreaming_workflow.memory import MemoryStore, Refusal
from dreaming_workflow.memory.backup import save_copy
from dreaming_workflow.report import Report, RunOutcome, build_report, index_stats
from dreaming_workflow.sessions import (
    Selected,
    SessionSources,
    discover_and_select,
)
from dreaming_workflow.state import ensure_state_dir

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


async def run(
    options: RunOptions,
    *,
    now: datetime,
    model_factory: ModelFactory,
    progress: Progress = _to_stderr,
) -> RunResult:
    run_id = run_id_for(now)
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

    store = MemoryStore(options.memory_dir, before_first_write=save_pre_run_copy)
    start = store.snapshot()
    ledger = UsageLedger()
    factory = _StopAfterAuthenticationFailure(model_factory)

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

    index_text = store.read_index()
    report = build_report(
        run_id=run_id,
        decisions=decisions,
        results=results,
        start=start,
        end=store.snapshot(),
        index=None if isinstance(index_text, Refusal) else index_stats(index_text),
        ledger=ledger,
        backup_path=backup_path,
    )
    return RunResult(report=report, outcome=report.outcome)
