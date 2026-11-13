from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from dreaming_workflow.agents import (
    AnalysisResult,
    AnalysisStatus,
    Failure,
    FailureReason,
    OrganizerResult,
    OrganizerStatus,
)
from dreaming_workflow.agents.budget import TokenUsage, UsageLedger
from dreaming_workflow.memory import FormatRule, FormatViolation, MemorySnapshot, Slug
from dreaming_workflow.report import (
    FailedSession,
    FileChanges,
    IndexStats,
    OrganizerSummary,
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
SUCCEEDED = OrganizerResult(OrganizerStatus.SUCCEEDED)
SHA256 = "0" * 64


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
    *,
    organizer: OrganizerResult = SUCCEEDED,
    violations: tuple[FormatViolation, ...] = (),
    ledger: UsageLedger | None = None,
) -> Report:
    return build_report(
        run_id="20261110T213800Z",
        decisions=decisions,
        results=results,
        organizer=organizer,
        waiting_files=0,
        start=start,
        end=end,
        index=None,
        violations=violations,
        ledger=ledger or UsageLedger(),
        backup_path=None,
    )


def test_counts_add_up() -> None:
    results = [
        analyzed("a"),
        analyzed("b", parts=3),
        failed("c", FailureReason.RATE_LIMITED),
    ]
    decisions: list[SelectionDecision] = [
        *(Selected(result.session, (), SHA256) for result in results),
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
    decisions: list[SelectionDecision] = [
        Selected(r.session, (), SHA256) for r in results
    ]

    assert report_for(decisions, results).outcome is outcome


def test_failed_organizer_completes_with_failures_and_keeps_its_reason() -> None:
    organizer = OrganizerResult(
        OrganizerStatus.FAILED, Failure(FailureReason.TIMEOUT), (Slug("a"),)
    )

    report = report_for(
        [Selected(analyzed("a").session, (), SHA256)],
        [analyzed("a")],
        organizer=organizer,
    )

    assert report.organizer == OrganizerSummary(
        OrganizerStatus.FAILED, FailureReason.TIMEOUT
    )
    assert report.outcome is RunOutcome.COMPLETED_WITH_FAILURES


def test_organizer_that_did_not_run_is_not_a_failure() -> None:
    report = report_for([], [], organizer=OrganizerResult(OrganizerStatus.NOT_RUN))

    assert report.organizer == OrganizerSummary(OrganizerStatus.NOT_RUN)
    assert report.outcome is RunOutcome.SUCCESS


def test_any_violation_completes_with_failures() -> None:
    violation = FormatViolation("notes.md", FormatRule.FRONTMATTER_MISSING)

    report = report_for([], [], violations=(violation,))

    assert report.violations == (violation,)
    assert report.outcome is RunOutcome.COMPLETED_WITH_FAILURES


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

    report = report_for([], [], ledger=ledger)

    assert report.usage.input_tokens == 62_000
    assert (report.usage.cache_read_tokens, report.usage.cache_write_tokens) == (
        50_000,
        2_000,
    )
    assert report.usage.output_tokens == 1_000
    assert report.usage.cost_usd == Decimal("0.04")


@pytest.mark.parametrize(
    ("limit", "reached"), [(Decimal("0.045"), True), (Decimal("0.046"), False)]
)
def test_usage_says_whether_the_spending_limit_was_reached(
    limit: Decimal, reached: bool
) -> None:
    ledger = UsageLedger(limit_usd=limit)
    # 10,000 input tokens at US$2.00 and 2,500 output tokens at US$10.00 per
    # million cost US$0.045.
    ledger.add(
        TokenUsage(
            input_tokens=10_000,
            cache_write_tokens=0,
            cache_read_tokens=0,
            output_tokens=2_500,
        )
    )

    usage = report_for([], [], ledger=ledger).usage

    assert (usage.limit_usd, usage.limit_reached) == (limit, reached)
