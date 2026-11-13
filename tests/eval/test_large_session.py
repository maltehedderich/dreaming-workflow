"""A session too large for one invocation runs in parts and stays within limits."""

from datetime import UTC, datetime
from pathlib import Path

from dreaming_workflow.agents import AgentRole
from tests.eval.harness import Checks, RunInput, ScenarioRunner, empty_memory
from tests.support.sessions import LARGE_SESSION_ID, realistic_large_session

_ESTIMATED_TOKENS = 250_000
_PARTS = 7


def _large_session(directory: Path) -> RunInput:
    session = realistic_large_session(
        directory / "sessions" / "large.jsonl",
        _ESTIMATED_TOKENS,
        start=datetime(2026, 11, 4, 9, 0, tzinfo=UTC),
    )
    return RunInput(empty_memory(directory), session_files=(session,))


def test_large_session_runs_in_seven_parts(
    runner: ScenarioRunner, checks: Checks
) -> None:
    for run in runner.three_times(_large_session):
        parts = sorted(
            m.part_index
            for m in run.measurements
            if m.role is AgentRole.ANALYSIS
            and m.session_id == LARGE_SESSION_ID
            and m.part_index is not None
        )
        checks.check(
            run,
            f"{_PARTS} analysis invocations, one per part",
            parts == list(range(1, _PARTS + 1)),
            f"parts invoked: {parts}",
        )
        report = run.report
        counts = (report.analyzed, report.analyzed_in_parts, len(report.failed))
        checks.check(
            run,
            "counted once, as analyzed in parts",
            counts == (1, 1, 0),
            f"analyzed, in parts, failed = {counts}",
        )
        checks.check(
            run,
            "largest prompt at most 100,000 tokens",
            run.largest_prompt_tokens <= 100_000,
            f"{run.largest_prompt_tokens:,}",
        )
    checks.done()
