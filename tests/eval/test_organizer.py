"""The organizer over a large seeded memory: merges, conflicts, links, headings."""

import shutil
from datetime import UTC, datetime
from pathlib import Path

from dreaming_workflow.agents import OrganizerStatus
from dreaming_workflow.memory.document import Slug, citations, conflict_lines, links
from dreaming_workflow.memory.index import Index, same_name
from dreaming_workflow.state import DreamRecord, ensure_state_dir
from tests.eval.harness import Checks, EvalRun, RunInput, ScenarioRunner
from tests.support.examples import CLAUDE_CODE_PROJECTS, CTX7_SETUP, claude_code_example
from tests.support.memory import (
    CTX7_CACHE_SESSION,
    CTX7_FRESH_SESSION,
    SOFTWARE_DEVELOPMENT,
    seeded_memory,
)

_CTX7_FILES = ("ctx7-cli", "context7-usage")
_CACHE_AT = datetime(2026, 10, 5, 14, 2, tzinfo=UTC)
_FRESH_AT = datetime(2026, 10, 12, 8, 47, tzinfo=UTC)
_DEVELOPMENT_NAMES = ("Development", SOFTWARE_DEVELOPMENT)
# Seeded fact text no analysis should touch, besides the numbered filler facts.
_NAMED_MARKERS = (
    "24 hours",
    "on every call",
    "Tag the release before publishing",
    "lists files in long form",
    "Rotate the backup drive monthly",
)


def _seeded(directory: Path) -> RunInput:
    """200 files, two Development headings, and ctx7-cli left waiting by an earlier run."""
    memory = directory / "memory"
    seeded_memory(memory, duplicate_domain=True)
    docs_lookup = memory / "docs-lookup.md"
    docs_lookup.write_text(
        docs_lookup.read_text() + "\nSee also [[ctx7-cli]] and [[context7-usage]].\n"
    )
    ensure_state_dir(memory)
    DreamRecord.load(memory).mark_waiting(Slug("ctx7-cli"))
    session = directory / "sessions" / f"{CTX7_SETUP}.jsonl"
    session.parent.mkdir()
    shutil.copy(claude_code_example(CLAUDE_CODE_PROJECTS, CTX7_SETUP), session)
    return RunInput(memory, session_files=(session,))


def _markers(run: EvalRun) -> list[str]:
    filler = sum(1 for name in run.memory_before if name.startswith("filler-"))
    return [f"Filler fact {number}." for number in range(1, filler + 1)] + list(
        _NAMED_MARKERS
    )


def _development_slugs(index: Index) -> set[str]:
    return {
        entry.slug
        for domain in index.domains
        if any(same_name(domain.name, name) for name in _DEVELOPMENT_NAMES)
        for entries in (domain.entries, *(s.entries for s in domain.subdomains))
        for entry in entries
    }


def _check_ctx7_merge(checks: Checks, run: EvalRun) -> None:
    targets = {run.resolve(slug) for slug in _CTX7_FILES}
    stubs = [slug for slug in _CTX7_FILES if run.resolve(slug) != slug]
    merged = next(iter(targets)) if len(targets) == 1 else None
    checks.check(
        run,
        "the ctx7 files become one file plus a MOVED TO stub",
        merged is not None and bool(stubs),
        f"resolve to {sorted(map(str, targets))}",
    )
    if merged is None:
        checks.check(
            run, "the merged file holds every ctx7 citation", False, "no merge"
        )
        checks.check(
            run, "links to a ctx7 file resolve to the merged file", False, "no merge"
        )
        return
    seeded = {
        citation
        for slug in _CTX7_FILES
        for citation in citations(run.memory_before[f"{slug}.md"].decode())
    }
    merged_text = run.notes()[merged]
    missing = seeded - citations(merged_text)
    checks.check(
        run,
        "the merged file holds every ctx7 citation",
        not missing,
        f"{len(missing)} missing from {merged}",
    )
    resolved = [
        run.resolve(link)
        for text in run.notes().values()
        for link in links(text)
        if link in _CTX7_FILES or link == merged
    ]
    checks.check(
        run,
        "links to a ctx7 file resolve to the merged file",
        bool(resolved) and all(target == merged for target in resolved),
        f"{len(resolved)} links, targets {sorted({str(t) for t in resolved})}",
    )


def _ctx7_conflicts(run: EvalRun) -> int:
    count = 0
    for text in run.notes().values():
        for line in conflict_lines(text):
            found = {(c.session_id, c.at) for c in citations(line)}
            if {
                (CTX7_CACHE_SESSION, _CACHE_AT),
                (CTX7_FRESH_SESSION, _FRESH_AT),
            } <= found:
                count += 1
    return count


def test_organizer_on_seeded_memory(runner: ScenarioRunner, checks: Checks) -> None:
    for run in runner.three_times(_seeded):
        organizer = run.result.organizer
        checks.check(
            run,
            "organizer succeeded",
            organizer.status is OrganizerStatus.SUCCEEDED,
            str(organizer.status),
        )
        notes_text = "\n".join(run.notes().values())
        markers = _markers(run)
        missing = [marker for marker in markers if marker not in notes_text]
        checks.check(
            run,
            "every seeded fact marker in a non-stub file",
            not missing,
            f"{len(missing)} of {len(markers)} missing",
        )
        _check_ctx7_merge(checks, run)
        conflicts = _ctx7_conflicts(run)
        checks.check(
            run,
            "one CONFLICT line names both ctx7 sources and times",
            conflicts == 1,
            f"{conflicts} lines",
        )
        received = set(organizer.received)
        outside = organizer.slugs_read - received - run.changed_slugs()
        checks.check(
            run,
            "organizer reads only received files and files it changed",
            not outside,
            f"{len(received)} received, read outside: {sorted(outside)}",
        )
        before = run.index(before=True)
        after = run.index()
        listed_before = _development_slugs(before) if before else set()
        headings_after = (
            [
                domain.name
                for domain in after.domains
                if any(same_name(domain.name, name) for name in _DEVELOPMENT_NAMES)
            ]
            if after
            else []
        )
        listed_after = _development_slugs(after) if after else set()
        lost = sorted(
            slug for slug in listed_before if run.resolve(slug) not in listed_after
        )
        checks.check(
            run,
            "Development and Software development end as one heading with every entry",
            len(headings_after) == 1 and not lost,
            f"headings {headings_after}, {len(lost)} entries elsewhere or gone",
        )
    checks.done()
