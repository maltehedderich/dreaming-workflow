from dataclasses import dataclass
from enum import StrEnum

from dreaming_workflow.agents import AnalysisResult, AnalysisStatus, FailureReason
from dreaming_workflow.sessions import Tool


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
class Report:
    """What a run did, built only from its own records, never from logs or content."""

    run_id: str
    skipped: int
    analyzed: int
    failed: tuple[FailedSession, ...]
    files_created: int

    @property
    def outcome(self) -> RunOutcome:
        return RunOutcome.COMPLETED_WITH_FAILURES if self.failed else RunOutcome.SUCCESS


def build_report(run_id: str, skipped: int, results: list[AnalysisResult]) -> Report:
    failed = tuple(
        FailedSession(
            result.session.tool, result.session.session_id, result.failure.reason
        )
        for result in results
        if result.failure is not None
    )
    created = set[str]().union(*(result.slugs_written for result in results))
    return Report(
        run_id=run_id,
        skipped=skipped,
        analyzed=sum(result.status is AnalysisStatus.ANALYZED for result in results),
        failed=failed,
        files_created=len(created),
    )
