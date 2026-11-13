"""Runs eval scenarios against the real model and collects what they measure.

Failure details name checks, counts, slugs, and session IDs, never memory or
session content.
"""

import asyncio
import hashlib
import shutil
import time
from collections.abc import AsyncGenerator, Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import override

import pytest
from google.adk.models import LlmRequest, LlmResponse
from pydantic import PrivateAttr

from dreaming_workflow import dream
from dreaming_workflow.agents import AgentRole, Invocation
from dreaming_workflow.agents.claude_model import ClaudeModel, create_client
from dreaming_workflow.memory.document import Citation, citations, stub_target
from dreaming_workflow.memory.index import Index, parse_index
from dreaming_workflow.sessions import Selected
from tests.eval.grader import Grader, GraderFailed, Verdict
from tests.support.examples import (
    CLAUDE_CODE_PROJECTS,
    CODEX_SESSIONS,
    RUN_START,
    SINCE,
)

SPENDING_LIMIT = Decimal("5.00")
RUNS_PER_SCENARIO = 3
INDEX = "_index.md"


class MeasuredClaudeModel(ClaudeModel):
    """The real model, recording the prompt tokens of its first request."""

    _first_prompt_tokens: int | None = PrivateAttr(default=None)

    @property
    def first_prompt_tokens(self) -> int | None:
        return self._first_prompt_tokens

    @override
    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse]:
        async for response in super().generate_content_async(llm_request, stream):
            usage = response.usage_metadata
            if (
                self._first_prompt_tokens is None
                and not response.partial
                and usage is not None
                and usage.prompt_token_count is not None
            ):
                # Counts cache reads and writes too: the whole prompt.
                self._first_prompt_tokens = usage.prompt_token_count
            yield response


@dataclass(frozen=True)
class Measurement:
    role: AgentRole
    session_id: str | None
    part_index: int | None
    # The part's estimated tokens; None for the organizer.
    estimate: int | None
    # None if the invocation failed before its first response.
    first_prompt_tokens: int | None


@dataclass(frozen=True)
class RunInput:
    """What one run reads. Unused session directories point at an empty one."""

    memory: Path
    session_files: tuple[Path, ...] = ()
    claude_code_dir: Path | None = None
    codex_dir: Path | None = None

    def options(self, run_dir: Path) -> dream.RunOptions:
        empty = run_dir / "no-sessions"
        empty.mkdir(exist_ok=True)
        return dream.RunOptions(
            memory_dir=self.memory,
            since=SINCE,
            claude_code_dir=self.claude_code_dir or empty,
            codex_dir=self.codex_dir or empty,
            session_files=self.session_files,
            spending_limit=SPENDING_LIMIT,
        )


type Prepare = Callable[[Path], RunInput]
"""Builds a run's sessions and starting memory inside the given run directory."""


def empty_memory(directory: Path) -> Path:
    memory = directory / "memory"
    memory.mkdir()
    return memory


def copy_examples(directory: Path) -> RunInput:
    """The six example sessions over empty memory."""
    claude_code = directory / "claude-code-projects"
    codex = directory / "codex-sessions"
    shutil.copytree(CLAUDE_CODE_PROJECTS, claude_code)
    shutil.copytree(CODEX_SESSIONS, codex)
    return RunInput(
        empty_memory(directory), claude_code_dir=claude_code, codex_dir=codex
    )


@dataclass(frozen=True)
class EvalRun:
    label: str
    directory: Path
    memory: Path
    preview: dream.Preview
    result: dream.RunResult
    # Memory file name → bytes, before and after the run.
    memory_before: dict[str, bytes]
    memory_after: dict[str, bytes]
    # Relative path → SHA-256 of every file in the run directory outside
    # memory and run state: session files, sentinels, everything else.
    outside_before: dict[str, str]
    outside_after: dict[str, str]
    measurements: tuple[Measurement, ...]
    largest_prompt_tokens: int
    seconds: float

    @property
    def report(self) -> dream.Report:
        return self.result.report

    def notes(self) -> dict[str, str]:
        """Non-stub memory files after the run, by slug, without the index."""
        return {
            name.removesuffix(".md"): data.decode("utf-8", errors="replace")
            for name, data in self.memory_after.items()
            if name != INDEX and stub_target(data) is None
        }

    def index(self, *, before: bool = False) -> Index | None:
        """The parsed index after the run, or before it; None if missing or invalid."""
        data = (self.memory_before if before else self.memory_after).get(INDEX)
        if data is None:
            return None
        parsed = parse_index(data.decode("utf-8", errors="replace"))
        return parsed if isinstance(parsed, Index) else None

    def resolve(self, slug: str) -> str | None:
        """Follow stubs from `slug` to a non-stub file; None if missing or cyclic."""
        seen: set[str] = set()
        current = slug
        while current not in seen:
            seen.add(current)
            data = self.memory_after.get(f"{current}.md")
            if data is None:
                return None
            target = stub_target(data)
            if target is None:
                return current
            current = target
        return None

    def changed_slugs(self) -> set[str]:
        """Files created, changed, or retired during the run."""
        names = (self.memory_before.keys() | self.memory_after.keys()) - {INDEX}
        return {
            name.removesuffix(".md")
            for name in names
            if self.memory_before.get(name) != self.memory_after.get(name)
        }


def fact_lines(notes: dict[str, str]) -> Iterator[tuple[str, str]]:
    """Every list item in the given files, as (slug, line)."""
    for slug, text in notes.items():
        for line in text.splitlines():
            if line.lstrip().startswith("- "):
                yield slug, line


def citing(notes: dict[str, str], session_id: str) -> set[str]:
    """Slugs of files with at least one citation of `session_id`."""
    return {
        slug
        for slug, text in notes.items()
        if any(citation.session_id == session_id for citation in citations(text))
    }


def all_citations(notes: dict[str, str]) -> set[Citation]:
    return {citation for text in notes.values() for citation in citations(text)}


def headings(index: Index) -> dict[str, tuple[str, str | None]]:
    """Slug → (domain, subdomain or None) of its index entry."""
    found: dict[str, tuple[str, str | None]] = {}
    for domain in index.domains:
        for entry in domain.entries:
            found[entry.slug] = (domain.name, None)
        for subdomain in domain.subdomains:
            for entry in subdomain.entries:
                found[entry.slug] = (domain.name, subdomain.name)
    return found


def _read_memory(memory: Path) -> dict[str, bytes]:
    if not memory.is_dir():
        return {}
    return {path.name: path.read_bytes() for path in sorted(memory.glob("*.md"))}


def _hash_outside(directory: Path, memory: Path) -> dict[str, str]:
    state = directory / "state"
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
        and not path.is_relative_to(memory)
        and not path.is_relative_to(state)
    }


def _part_estimates(preview: dream.Preview) -> dict[tuple[str, int], int]:
    return {
        (decision.session.session_id, part.index): part.estimated_tokens
        for decision in preview.decisions
        if isinstance(decision, Selected)
        for part in decision.parts
    }


@dataclass
class Totals:
    """What every eval in the pytest session spent and measured."""

    runs: int = 0
    dream_cost: Decimal = Decimal(0)
    measurements: list[Measurement] = field(default_factory=list)
    # "test: check" → one result per run.
    checks: dict[str, list[bool]] = field(default_factory=dict)
    grader: Grader | None = None


class ScenarioRunner:
    """Runs a scenario in fresh directories with its own run state."""

    def __init__(
        self, root: Path, monkeypatch: pytest.MonkeyPatch, totals: Totals
    ) -> None:
        self._root = root
        self._monkeypatch = monkeypatch
        self._totals = totals

    def scratch(self, name: str) -> Path:
        """A directory for test data that no run reads."""
        path = self._root / "scratch" / name
        path.mkdir(parents=True)
        return path

    def three_times(self, prepare: Prepare) -> list[EvalRun]:
        return [
            self.run_once(f"run {number}", prepare)
            for number in range(1, RUNS_PER_SCENARIO + 1)
        ]

    def run_once(self, label: str, prepare: Prepare) -> EvalRun:
        directory = self._root / label.replace(" ", "-")
        directory.mkdir(parents=True)
        self._monkeypatch.setenv("XDG_STATE_HOME", str(directory / "state"))
        run_input = prepare(directory)
        options = run_input.options(directory)
        preview = dream.preview(options, now=RUN_START)
        estimates = _part_estimates(preview)
        memory_before = _read_memory(run_input.memory)
        outside_before = _hash_outside(directory, run_input.memory)

        # One client per run: each `asyncio.run` starts a new event loop.
        client = create_client()
        models: list[tuple[Invocation, MeasuredClaudeModel]] = []

        def model_for(invocation: Invocation) -> MeasuredClaudeModel:
            model = MeasuredClaudeModel(
                client=client,
                role=invocation.role,
                ledger=invocation.ledger,
                guard=invocation.guard,
            )
            models.append((invocation, model))
            return model

        started = time.monotonic()
        result = asyncio.run(
            dream.run(
                options,
                now=RUN_START,
                model_factory=model_for,
                progress=lambda _line: None,
            )
        )
        seconds = time.monotonic() - started

        measurements = tuple(
            Measurement(
                role=invocation.role,
                session_id=invocation.session_id,
                part_index=invocation.part_index,
                estimate=(
                    estimates.get((invocation.session_id, invocation.part_index))
                    if invocation.session_id is not None
                    and invocation.part_index is not None
                    else None
                ),
                first_prompt_tokens=model.first_prompt_tokens,
            )
            for invocation, model in models
        )
        run = EvalRun(
            label=label,
            directory=directory,
            memory=run_input.memory,
            preview=preview,
            result=result,
            memory_before=memory_before,
            memory_after=_read_memory(run_input.memory),
            outside_before=outside_before,
            outside_after=_hash_outside(directory, run_input.memory),
            measurements=measurements,
            largest_prompt_tokens=max(
                (invocation.ledger.largest_prompt_tokens for invocation, _ in models),
                default=0,
            ),
            seconds=seconds,
        )
        self._totals.runs += 1
        self._totals.dream_cost += result.report.usage.cost_usd
        self._totals.measurements.extend(measurements)
        return run


class Checks:
    """Collects one test's check results across runs, then fails with all of them."""

    def __init__(self, test: str, grader: Grader, totals: Totals) -> None:
        self._test = test
        self._grader = grader
        self._totals = totals
        self._failures: list[str] = []

    def check(self, run: EvalRun, name: str, ok: bool, detail: str = "") -> None:
        self._totals.checks.setdefault(f"{self._test}: {name}", []).append(ok)
        if not ok:
            self._failures.append(
                f"{run.label}: {name}" + (f" ({detail})" if detail else "")
            )

    def grade(
        self, run: EvalRun, name: str, claim: str, *, expected: bool
    ) -> Verdict | None:
        """Check a claim with the grader: supported if `expected`, else rejected."""
        try:
            verdict = self._grader.grade(run.memory, claim)
        except GraderFailed as error:
            self.check(run, name, False, f"grader failed: {error}")
            return None
        ok = verdict.holds if expected else verdict.rejected
        detail = f"grader: {verdict.finding}" + (
            f" in {verdict.slug}" if verdict.slug else ""
        )
        self.check(run, name, ok, detail)
        return verdict

    def done(self) -> None:
        if self._failures:
            pytest.fail("Failed checks:\n" + "\n".join(self._failures), pytrace=False)
