from dataclasses import dataclass
from enum import StrEnum

from dreaming_workflow.memory import Slug
from dreaming_workflow.sessions import Session


class FailureReason(StrEnum):
    RATE_LIMITED = "rate-limited"
    OVERLOADED = "overloaded"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection-error"
    API_ERROR = "api-error"
    AUTHENTICATION_FAILED = "authentication-failed"
    REFUSED = "refused"
    MAX_TOKENS = "max-tokens"
    CONTEXT_LIMIT = "context-limit"
    TURN_LIMIT = "turn-limit"
    SPENDING_LIMIT_REACHED = "spending-limit-reached"
    INVALID_MODEL_OUTPUT = "invalid-model-output"
    INTERNAL_ERROR = "internal-error"


@dataclass(frozen=True)
class Failure:
    reason: FailureReason
    # Never session or memory content: only the status code and request ID for
    # `api-error`, or the exception class name for `internal-error`.
    detail: str = ""


class AgentFailure(Exception):
    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.reason.value)
        self.failure = failure


class AnalysisStatus(StrEnum):
    ANALYZED = "analyzed"
    FAILED = "failed"


@dataclass(frozen=True)
class AnalysisResult:
    session: Session
    status: AnalysisStatus
    failure: Failure | None
    parts_run: int
    slugs_written: frozenset[Slug]


class OrganizerStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NOT_RUN = "not-run"


@dataclass(frozen=True)
class OrganizerResult:
    status: OrganizerStatus
    failure: Failure | None = None
    received: tuple[Slug, ...] = ()
    # Slugs whose content `read_file` returned. Kept for tests; never printed.
    slugs_read: frozenset[Slug] = frozenset()

    @property
    def ran(self) -> bool:
        return self.status is not OrganizerStatus.NOT_RUN
