from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from google.adk.models import BaseLlm

from dreaming_workflow.agents.budget import ContextGuard, UsageLedger


class AgentRole(StrEnum):
    ANALYSIS = "analysis"
    ORGANIZER = "organizer"


@dataclass(frozen=True)
class Invocation:
    """One agent run: a part of a session's analysis, or the organizer pass.

    `guard` belongs to this invocation; `ledger` is the run's, shared by all.
    """

    role: AgentRole
    session_id: str | None
    part_index: int | None
    guard: ContextGuard = field(default_factory=ContextGuard, compare=False)
    ledger: UsageLedger = field(default_factory=UsageLedger, compare=False)


type ModelFactory = Callable[[Invocation], BaseLlm]
