"""A second dream on the same memory directory is refused and changes nothing."""

import os
import subprocess
import sys
from pathlib import Path

from dreaming_workflow.memory import Slug
from dreaming_workflow.state import DreamRecord, RunLock, ensure_state_dir, state_dir
from tests.conftest import ExampleSessions
from tests.support.examples import CONTEXT7_CHECK, claude_code_example

REPOSITORY = Path(__file__).resolve().parents[2]


def contents(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_a_second_process_is_refused_while_the_lock_is_held(
    example_sessions: ExampleSessions, tmp_path: Path
) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "_index.md").write_text("# Memory index\n")
    DreamRecord.load(memory).mark_waiting(Slug("uv-python"))
    record = state_dir(memory) / "record.json"
    memory_before = contents(memory)
    record_before = record.read_bytes()
    session = claude_code_example(example_sessions.claude_code, CONTEXT7_CHECK)
    # Not a credential: the second process stops before it sends anything.
    environment = os.environ | {"ANTHROPIC_API_KEY": "placeholder-for-tests"}

    with RunLock(ensure_state_dir(memory)):
        finished = subprocess.run(
            [
                sys.executable,
                "-m",
                "dreaming_workflow",
                "--memory",
                str(memory),
                "--session",
                str(session),
            ],
            capture_output=True,
            text=True,
            env=environment,
            cwd=REPOSITORY,
            timeout=120,
            check=False,
        )

    assert finished.returncode == 2
    # The SDK may log that the key shadows profile discovery; that line names
    # only environment variables.
    assert finished.stderr.splitlines()[-1] == (
        f"dream: another dream is running on {memory}. Nothing was changed."
    )
    assert finished.stdout == ""
    assert contents(memory) == memory_before
    assert record.read_bytes() == record_before
