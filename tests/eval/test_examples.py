"""The six example sessions from empty memory: what the model records."""

import re
from datetime import UTC, datetime

from dreaming_workflow.memory.document import citations
from dreaming_workflow.memory.index import same_name
from tests.eval.grader import Verdict, normalize
from tests.eval.harness import (
    Checks,
    EvalRun,
    ScenarioRunner,
    citing,
    copy_examples,
    fact_lines,
    headings,
)
from tests.support.examples import (
    CODEX_PROJECT_DIR,
    CONTEXT7_CHECK,
    CTX7_SETUP,
    MAILARKIV_SUBTHREAD,
)

_FOUR_MB = re.compile(r"\b4\s?MB\b", re.IGNORECASE)
_SCOPE = re.compile(r"\[scope: ([^\]]+)\]")
# The minutes each ctx7 session's messages span.
_CONTEXT7_CHECK_SPAN = (
    datetime(2026, 10, 17, 9, 18, tzinfo=UTC),
    datetime(2026, 10, 17, 9, 21, tzinfo=UTC),
)
_CTX7_SETUP_SPAN = (
    datetime(2026, 10, 17, 9, 33, tzinfo=UTC),
    datetime(2026, 10, 17, 9, 38, tzinfo=UTC),
)


def _cites_within(line: str, session_id: str, span: tuple[datetime, datetime]) -> bool:
    first, last = span
    return any(
        citation.session_id == session_id and first <= citation.at <= last
        for citation in citations(line)
    )


def _replaces_npx(line: str) -> bool:
    return (
        line.lstrip().startswith("- REPLACED:")
        and "npx" in line
        and "ctx7" in line
        and _cites_within(line, CONTEXT7_CHECK, _CONTEXT7_CHECK_SPAN)
        and _cites_within(line, CTX7_SETUP, _CTX7_SETUP_SPAN)
    )


def _check_antigravity_line(
    checks: Checks, run: EvalRun, verdict: Verdict | None
) -> None:
    """The global-settings fact is domain-wide, cites mailarkiv, and stays out of it."""
    names = (
        "Antigravity fact has a domain-wide scope",
        "Antigravity fact cites the mailarkiv project",
        "Antigravity file isn't under ### mailarkiv",
    )
    if verdict is None or verdict.slug is None:
        for name in names:
            checks.check(run, name, False, "no supported fact to inspect")
        return
    slug = verdict.slug
    quote = normalize(verdict.quote)
    candidates = [
        line
        for _, line in fact_lines({slug: run.notes()[slug]})
        if quote in normalize(line) or normalize(line) in quote
    ]
    lines = [line for line in candidates if "antigravity" in line.lower()] or candidates
    if not lines:
        for name in names:
            checks.check(run, name, False, f"quote isn't within a fact line in {slug}")
        return
    line = lines[0]
    scope = _SCOPE.search(line)
    checks.check(
        run,
        names[0],
        scope is not None and "›" not in scope.group(1),
        f"in {slug}",
    )
    checks.check(
        run,
        names[1],
        any(c.project_dir == CODEX_PROJECT_DIR for c in citations(line)),
        f"in {slug}",
    )
    index = run.index()
    heading = headings(index).get(slug) if index else None
    checks.check(
        run,
        names[2],
        heading is None or heading[1] is None or not same_name(heading[1], "mailarkiv"),
        f"{slug} is under {heading}",
    )


def test_examples(runner: ScenarioRunner, checks: Checks) -> None:
    for run in runner.three_times(copy_examples):
        report = run.report
        counts = (
            report.found,
            report.selected,
            report.skipped,
            report.analyzed,
            len(report.failed),
        )
        checks.check(
            run,
            "found 6, selected 5, skipped 1, analyzed 5, failed 0",
            counts == (6, 5, 1, 5, 0),
            f"got {counts}",
        )
        every_line = [
            line
            for data in run.memory_after.values()
            for line in data.decode("utf-8", errors="replace").splitlines()
        ]
        four_mb = sum(1 for line in every_line if _FOUR_MB.search(line))
        checks.check(
            run, "no line gives the limit as 4 MB", four_mb == 0, f"{four_mb} lines"
        )
        notes = run.notes()
        subthread = citing(notes, MAILARKIV_SUBTHREAD)
        checks.check(
            run,
            "no citation names the auto-review subthread",
            not subthread,
            ", ".join(sorted(subthread)),
        )
        violations = report.violations
        checks.check(
            run,
            "no format violations",
            not violations,
            ", ".join(f"{v.file} {v.rule}" for v in violations),
        )
        checks.check(
            run, "run takes under 600 s", run.seconds < 600, f"{run.seconds:.0f} s"
        )
        checks.check(
            run,
            "largest prompt at most 100,000 tokens",
            run.largest_prompt_tokens <= 100_000,
            f"{run.largest_prompt_tokens:,}",
        )

        checks.grade(
            run,
            "ctx7 is installed globally and called as bare ctx7",
            "ctx7 is installed globally and is called as the bare `ctx7` command.",
            expected=True,
        )
        checks.grade(
            run,
            "no file gives npx ctx7@latest as current",
            "Memory gives `npx ctx7@latest` as the current way to call ctx7.",
            expected=False,
        )
        replaced = [line for _, line in fact_lines(notes) if _replaces_npx(line)]
        checks.check(
            run,
            "npx form sits in a REPLACED line citing both ctx7 sessions",
            bool(replaced),
            "no such line",
        )
        checks.grade(
            run,
            "uv is enforced by a Claude Code hook and Codex rules",
            "Python work uses uv, enforced by a hook in Claude Code and by rules "
            "in Codex.",
            expected=True,
        )
        checks.grade(
            run,
            "the hook blocks pip install; a script file avoided it",
            "The Claude Code hook blocks any Bash command whose text contains "
            "`pip install`, and running the test from a script file avoided the "
            "block.",
            expected=True,
        )
        verdict = checks.grade(
            run,
            "Antigravity can read ~/.claude/skills recursively",
            "Antigravity's global settings grant recursive read access to "
            "`~/.claude/skills`.",
            expected=True,
        )
        _check_antigravity_line(checks, run, verdict)
    checks.done()
