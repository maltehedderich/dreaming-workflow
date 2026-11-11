import subprocess
import sys


def test_help_exits_zero_and_lists_memory_option() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "dreaming_workflow", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "--memory" in completed.stdout
