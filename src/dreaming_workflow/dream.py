"""The dream run: the only module that wires sessions, agents, and memory together."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dreaming_workflow.agents import AnalysisResult, ModelFactory, analyze_session
from dreaming_workflow.memory import MemoryStore
from dreaming_workflow.report import Report, RunOutcome, build_report
from dreaming_workflow.sessions import (
    PART_TOKEN_LIMIT,
    SessionFile,
    parse_claude_code,
    split_into_parts,
)


@dataclass(frozen=True)
class RunOptions:
    memory_dir: Path
    session_files: tuple[Path, ...]


@dataclass(frozen=True)
class RunResult:
    report: Report
    outcome: RunOutcome


def run_id_for(started_at: datetime) -> str:
    return f"{started_at.astimezone(UTC):%Y%m%dT%H%M%SZ}"


async def run(
    options: RunOptions, *, now: datetime, model_factory: ModelFactory
) -> RunResult:
    store = MemoryStore(options.memory_dir)
    skipped = 0
    results: list[AnalysisResult] = []
    for path in options.session_files:
        session = parse_claude_code(SessionFile.at(path, expected_tool=None))
        # Splitting a view into several parts isn't built yet, so larger sessions are skipped.
        if (
            session is None
            or not session.view.messages
            or session.view.estimated_tokens > PART_TOKEN_LIMIT
        ):
            skipped += 1
            continue
        parts = split_into_parts(session.view)
        results.append(await analyze_session(session, parts, store, model_factory))
    report = build_report(run_id_for(now), skipped, results)
    return RunResult(report=report, outcome=report.outcome)
