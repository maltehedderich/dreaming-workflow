"""Evals against the real Claude API. They cost money and run only through `mise run eval`."""

from decimal import Decimal
from pathlib import Path

import pytest

from dreaming_workflow.agents import AgentRole
from dreaming_workflow.agents.claude_model import MissingCredentials, create_client
from tests.eval.grader import Grader
from tests.eval.harness import Checks, ScenarioRunner, Totals

_EVAL_DIR = Path(__file__).parent
_TOTALS = pytest.StashKey[Totals]()
NO_CREDENTIALS = (
    "The evals call the real Claude API and found no credentials. Set "
    "ANTHROPIC_API_KEY, or run `ant auth login` to create a profile, then run "
    "`mise run eval` again."
)


# First, so the `-m` selection sees the marker.
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.path.is_relative_to(_EVAL_DIR):
            item.add_marker(pytest.mark.eval)


@pytest.fixture(scope="session", autouse=True)
def credentials() -> None:
    """Fail, never skip, without credentials: a skipped eval looks like a pass."""
    try:
        create_client()
    except MissingCredentials:
        found = False
    else:
        found = True
    # Outside the except block, so the report shows only the message.
    if not found:
        pytest.fail(NO_CREDENTIALS, pytrace=False)


@pytest.fixture(scope="session")
def totals(pytestconfig: pytest.Config) -> Totals:
    collected = Totals()
    pytestconfig.stash[_TOTALS] = collected
    return collected


@pytest.fixture(scope="session")
def grader(totals: Totals) -> Grader:
    totals.grader = Grader()
    return totals.grader


@pytest.fixture
def runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, totals: Totals
) -> ScenarioRunner:
    return ScenarioRunner(tmp_path, monkeypatch, totals)


@pytest.fixture
def checks(request: pytest.FixtureRequest, grader: Grader, totals: Totals) -> Checks:
    return Checks(request.node.name, grader, totals)


def _token_lines(totals: Totals) -> list[str]:
    pairs = [
        (m.estimate, m.first_prompt_tokens)
        for m in totals.measurements
        if m.role is AgentRole.ANALYSIS
        and m.estimate is not None
        and m.first_prompt_tokens is not None
    ]
    if not pairs:
        return ["  No analysis request reported its prompt tokens."]
    estimates = [estimate for estimate, _ in pairs]
    real = [tokens for _, tokens in pairs]
    lines = [
        f"  Real vs estimated prompt tokens, first request of {len(pairs)} parts:",
        f"    ratio of sums: {sum(real) / sum(estimates):.3f}",
    ]
    mean_x = sum(estimates) / len(estimates)
    mean_y = sum(real) / len(real)
    spread = sum((x - mean_x) ** 2 for x in estimates)
    if spread > 0:
        # Least squares: the slope is real tokens per estimated token, the
        # intercept the fixed prompt (instructions, tool definitions, memory index).
        slope = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / spread
        intercept = mean_y - slope * mean_x
        lines.append(f"    fit: real ≈ {intercept:,.0f} + {slope:.3f} × estimate")
    return lines


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    totals = config.stash.get(_TOTALS, None)
    if totals is None or totals.runs == 0:
        return
    grader_cost = totals.grader.cost_usd if totals.grader else Decimal(0)
    lines = [
        f"  Dream runs: {totals.runs}, US${totals.dream_cost:.2f} at list price",
        f"  Grader: US${grader_cost:.2f}",
        f"  Total: US${totals.dream_cost + grader_cost:.2f}",
        *_token_lines(totals),
        "  Checks (runs passed):",
        *(
            f"    {sum(results)}/{len(results)}  {name}"
            for name, results in totals.checks.items()
        ),
    ]
    terminalreporter.write_sep("=", "eval summary")
    for line in lines:
        terminalreporter.write_line(line)
