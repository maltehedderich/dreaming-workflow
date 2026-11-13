"""A run over existing memory keeps unrelated facts and corrects outdated ones."""

import shutil
from pathlib import Path

from tests.eval.harness import Checks, RunInput, ScenarioRunner
from tests.support.examples import CLAUDE_CODE_PROJECTS, CTX7_SETUP, claude_code_example
from tests.support.memory import marked_memory


def _ctx7_setup_over_marked_memory(directory: Path) -> RunInput:
    memory = directory / "memory"
    marked_memory(memory)
    session = directory / "sessions" / f"{CTX7_SETUP}.jsonl"
    session.parent.mkdir()
    shutil.copy(claude_code_example(CLAUDE_CODE_PROJECTS, CTX7_SETUP), session)
    return RunInput(memory, session_files=(session,))


def test_existing_memory_is_kept_and_corrected(
    runner: ScenarioRunner, checks: Checks
) -> None:
    # Building the memory again gives the same lines in every run.
    unrelated = marked_memory(runner.scratch("marked"))
    for run in runner.three_times(_ctx7_setup_over_marked_memory):
        checks.check(
            run,
            "session analyzed",
            run.report.analyzed == 1,
            f"analyzed {run.report.analyzed}",
        )
        present = {line for text in run.notes().values() for line in text.splitlines()}
        missing = [line for line in unrelated if line not in present]
        checks.check(
            run,
            "unrelated fact lines still present, byte for byte",
            not missing,
            f"{len(missing)} of {len(unrelated)} missing",
        )
        checks.grade(
            run,
            "memory gives bare ctx7 as current",
            "ctx7 is currently called as the bare `ctx7` command.",
            expected=True,
        )
        outdated = sorted(
            {
                name
                for name, data in run.memory_after.items()
                for line in data.decode("utf-8", errors="replace").splitlines()
                if "npx ctx7@latest" in line
                and not line.lstrip().startswith("- REPLACED:")
            }
        )
        checks.check(
            run,
            "npx ctx7@latest only in REPLACED lines",
            not outdated,
            ", ".join(outdated),
        )
    checks.done()
