from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from google.adk.models import BaseLlm


class AgentRole(StrEnum):
    ANALYSIS = "analysis"
    ORGANIZER = "organizer"


@dataclass(frozen=True)
class Invocation:
    """One agent run: a part of a session's analysis, or the organizer pass."""

    role: AgentRole
    session_id: str | None
    part_index: int | None


type ModelFactory = Callable[[Invocation], BaseLlm]
