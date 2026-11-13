from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from dreaming_workflow.agents import (
    AnalysisResult,
    AnalysisStatus,
    Failure,
    FailureReason,
)
from dreaming_workflow.agents.budget import TokenUsage, UsageLedger
from dreaming_workflow.memory import MemorySnapshot, Slug
from dreaming_workflow.report import (
    FailedSession,
    FileChanges,
    IndexStats,
    Report,
    RunOutcome,
    build_report,
    file_changes,
    index_stats,
)
from dreaming_workflow.sessions import (
    ConversationView,
    Selected,
    SelectionDecision,
    Session,
    SessionFile,
    Skipped,
    SkipReason,
    Tool,
)

AT = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
EMPTY = MemorySnapshot(hashes={}, stubs=frozenset(), conflicts=frozenset())


def session(name: str, tool: Tool = Tool.CLAUDE_CODE) -> Session:
    file = SessionFile(Path(f"/sessions/{name}.jsonl"), tool, size=1, mtime_ns=1)
    return Session(
        file, tool, name, "/Users/dev/Projects", AT, AT, None, ConversationView(())
    )


def skipped(name: str, reason: SkipReason) -> Skipped:
    return Skipped(session(name).file, reason)


def analyzed(name: str, parts: int = 1) -> AnalysisResult:
    return AnalysisResult(
        session(name), AnalysisStatus.ANALYZED, None, parts, frozenset()
    )


def failed(name: str, reason: FailureReason, tool: Tool = Tool.CODEX) -> AnalysisResult:
    return AnalysisResult(
        session(name, tool), AnalysisStatus.FAILED, Failure(reason), 1, frozenset()
    )


def report_for(
    decisions: list[SelectionDecision],
    results: list[AnalysisResult],
    start: MemorySnapshot = EMPTY,
    end: MemorySnapshot = EMPTY,
) -> Report:
    return build_report(
        run_id="20261110T213800Z",
        decisions=decisions,
        results=results,
        start=start,
        end=end,
        index=None,
        ledger=UsageLedger(),
        backup_path=None,
    )


def test_counts_add_up() -> None:
    results = [
        analyzed("a"),
        analyzed("b", parts=3),
        failed("c", FailureReason.RATE_LIMITED),
    ]
    decisions: list[SelectionDecision] = [
        *(Selected(result.session, ()) for result in results),
        skipped("d", SkipReason.SUBTHREAD),
        skipped("e", SkipReason.ACTIVE),
        skipped("f", SkipReason.SUBTHREAD),
    ]

    report = report_for(decisions, results)

    assert report.found == 6
    assert report.selected == 3
    assert report.skipped_by_reason == (
        (SkipReason.SUBTHREAD, 2),
        (SkipReason.ACTIVE, 1),
    )
    assert report.found == report.selected + report.skipped
    assert report.selected == report.analyzed + len(report.failed)
    assert report.analyzed_in_parts == 1
    assert report.failed == (
        FailedSession(Tool.CODEX, "c", FailureReason.RATE_LIMITED),
    )


@pytest.mark.parametrize(
    ("results", "outcome"),
    [
        ([analyzed("a")], RunOutcome.SUCCESS),
        ([], RunOutcome.SUCCESS),
        (
            [analyzed("a"), failed("b", FailureReason.TIMEOUT)],
            RunOutcome.COMPLETED_WITH_FAILURES,
        ),
    ],
)
def test_any_failed_analysis_completes_with_failures(
    results: list[AnalysisResult], outcome: RunOutcome
) -> None:
    decisions: list[SelectionDecision] = [Selected(r.session, ()) for r in results]

    assert report_for(decisions, results).outcome is outcome


def test_file_changes_from_two_snapshots() -> None:
    start = MemorySnapshot(
        hashes={
            Slug("kept"): "1",
            Slug("edited"): "2",
            Slug("retired"): "3",
            Slug("old-stub"): "4",
        },
        stubs=frozenset({Slug("old-stub")}),
        conflicts=frozenset({"- CONFLICT: A says x; B says y."}),
    )
    end = MemorySnapshot(
        hashes={
            Slug("kept"): "1",
            Slug("edited"): "2b",
            Slug("retired"): "3b",
            Slug("old-stub"): "4",
            Slug("new-one"): "5",
            Slug("new-two"): "6",
        },
        stubs=frozenset({Slug("old-stub"), Slug("retired")}),
        conflicts=frozenset(
            {"- CONFLICT: A says x; B says y.", "- CONFLICT: C says p; D says q."}
        ),
    )

    report = report_for([], [], start, end)

    assert file_changes(start, end) == FileChanges(created=2, changed=1, retired=1)
    assert report.files == FileChanges(created=2, changed=1, retired=1)
    assert report.conflicts_added == 1


def test_index_stats() -> None:
    text = (
        "# Memory index\n\n## Development\n\n- [[uv-python]] — Python uses uv.\n\n"
        "### mailarkiv\n\n- [[mailarkiv-identity]] — Password rules.\n\n"
        "## Business\n\n- [[service-pricing]] — How services are priced.\n"
    )

    assert index_stats(text) == IndexStats(entries=3, domains=2, subdomains=1)
    assert index_stats("") == IndexStats(entries=0, domains=0, subdomains=0)
    assert index_stats("## Development\n\nprose\n") is None


def test_usage_counts_every_input_token() -> None:
    ledger = UsageLedger()
    ledger.add(
        TokenUsage(
            input_tokens=10_000,
            cache_write_tokens=2_000,
            cache_read_tokens=50_000,
            output_tokens=1_000,
        )
    )

    report = build_report(
        run_id="20261110T213800Z",
        decisions=[],
        results=[],
        start=EMPTY,
        end=EMPTY,
        index=None,
        ledger=ledger,
        backup_path=None,
    )

    assert report.usage.input_tokens == 62_000
    assert (report.usage.cache_read_tokens, report.usage.cache_write_tokens) == (
        50_000,
        2_000,
    )
    assert report.usage.output_tokens == 1_000
    assert report.usage.cost_usd == Decimal("0.00225")
