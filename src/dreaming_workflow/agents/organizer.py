"""The organizer pass: which files it receives, and its one agent invocation."""

from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources

from dreaming_workflow.agents.budget import ContextGuard, UsageLedger
from dreaming_workflow.agents.invocation import AgentRole, Invocation, ModelFactory
from dreaming_workflow.agents.results import OrganizerResult, OrganizerStatus
from dreaming_workflow.agents.runner import failure_of, run_agent
from dreaming_workflow.agents.tools import organizer_tools
from dreaming_workflow.memory import (
    FormatViolation,
    MemoryStore,
    Refusal,
    Slug,
    parse_slug,
)
from dreaming_workflow.sessions.view import estimate_tokens

MAX_LLM_CALLS = 80
# Estimated tokens of file content the organizer receives. Files past it wait
# for the next run, which keeps its prompts far below the input limit.
RECEIVE_BUDGET = 40_000
INDEX_FILE = "_index.md"


@dataclass(frozen=True)
class OrganizerInput:
    received: tuple[Slug, ...]
    # Waiting slugs whose file no longer exists; they stop waiting.
    gone: tuple[Slug, ...]


def _slug_of(file: str) -> Slug | None:
    if not file.endswith(".md"):
        return None
    return parse_slug(file.removesuffix(".md"))


def select_input(
    waiting: Sequence[Slug],
    violations: Sequence[FormatViolation],
    store: MemoryStore,
) -> OrganizerInput:
    """Pick the files the organizer receives.

    Files with violations come first, then waiting files, oldest first, until
    their content reaches the receive budget. The first file is always taken,
    however large.
    """
    candidates: list[Slug] = []
    for violation in violations:
        slug = _slug_of(violation.file)
        if slug is not None and slug not in candidates:
            candidates.append(slug)
    candidates.extend(slug for slug in waiting if slug not in candidates)

    received: list[Slug] = []
    gone: list[Slug] = []
    total = 0
    budget_reached = False
    for slug in candidates:
        lines = store.read_file(slug)
        if isinstance(lines, Refusal):
            # The slug is valid, so the store refuses only a missing file.
            if slug in waiting:
                gone.append(slug)
            continue
        tokens = estimate_tokens(lines.content)
        if received and (budget_reached or total + tokens > RECEIVE_BUDGET):
            budget_reached = True
            continue
        received.append(slug)
        total += tokens
    return OrganizerInput(received=tuple(received), gone=tuple(gone))


def _organizer_instruction() -> str:
    return (
        resources.files(__package__)
        .joinpath("prompts/organizer.md")
        .read_text(encoding="utf-8")
    )


def first_message(
    received: Sequence[Slug], violations: Sequence[FormatViolation]
) -> str:
    """The organizer's first user message: slugs and rule names, never content."""
    rules: dict[str, list[str]] = {}
    for violation in violations:
        rules.setdefault(violation.file, []).append(violation.rule.value)

    def line(name: str, label: str) -> str:
        found = rules.get(name)
        return f"- {label}: {', '.join(found)}" if found else f"- {label}"

    if received:
        parts = [
            f"Received files ({len(received)}), with their format violations:",
            *(line(f"{slug}.md", slug) for slug in received),
        ]
    else:
        parts = ["No files were received. Work from the index alone."]
    index_rules = rules.get(INDEX_FILE)
    parts.append("")
    parts.append(
        f"Index violations: {', '.join(index_rules)}"
        if index_rules
        else "Index violations: none"
    )
    return "\n".join(parts)


async def organize(
    organizer_input: OrganizerInput,
    violations: Sequence[FormatViolation],
    store: MemoryStore,
    model_factory: ModelFactory,
    ledger: UsageLedger,
) -> OrganizerResult:
    """Run the organizer once over the received files."""
    guard = ContextGuard()
    slugs_read: set[Slug] = set()
    received = organizer_input.received

    async def invoke() -> None:
        invocation = Invocation(
            AgentRole.ORGANIZER, None, None, guard=guard, ledger=ledger
        )
        await run_agent(
            name="organizer",
            model=model_factory(invocation),
            instruction=_organizer_instruction(),
            tools=organizer_tools(store, guard, slugs_read.add),
            message=first_message(received, violations),
            max_llm_calls=MAX_LLM_CALLS,
        )

    failure = await failure_of(invoke())
    return OrganizerResult(
        status=OrganizerStatus.SUCCEEDED if failure is None else OrganizerStatus.FAILED,
        failure=failure,
        received=received,
        slugs_read=frozenset(slugs_read),
    )
