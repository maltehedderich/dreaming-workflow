from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from dreaming_workflow import cli, dream
from dreaming_workflow.agents import FailureReason, OrganizerStatus
from dreaming_workflow.memory import FormatRule, FormatViolation
from dreaming_workflow.report import (
    FailedSession,
    FileChanges,
    IndexStats,
    OrganizerSummary,
    Report,
    Usage,
)
from dreaming_workflow.sessions import (
    ConversationMessage,
    ConversationView,
    MessageKind,
    Part,
    Selected,
    Session,
    SessionFile,
    Skipped,
    SkipReason,
    Tool,
)
from dreaming_workflow.state import state_dir
from tests.support.examples import PASSWORD_LIMIT, RUN_START
from tests.support.scripted_llm import ScriptedModels

BACKUP = Path(
    "/Users/dev/.local/state/dreaming-workflow/3f2a9c1e0b7d4a65/backups/20261110T213800Z"
)

# The numbers of the contract's example report.
REPORT = Report(
    run_id="20261110T213800Z",
    found=6,
    selected=5,
    skipped_by_reason=((SkipReason.SUBTHREAD, 1),),
    analyzed=5,
    analyzed_in_parts=0,
    failed=(),
    organizer=OrganizerSummary(OrganizerStatus.SUCCEEDED),
    waiting_files=0,
    index=IndexStats(entries=9, domains=2, subdomains=1),
    files=FileChanges(created=7, changed=1, retired=0),
    conflicts_added=0,
    violations=(),
    usage=Usage(
        input_tokens=1_234_567,
        cache_read_tokens=1_000_000,
        cache_write_tokens=120_000,
        output_tokens=45_678,
        cost_usd=Decimal("0.1234"),
        limit_usd=Decimal("10.00"),
        limit_reached=False,
    ),
    backup_path=BACKUP,
)


class RunSpy:
    """Stands in for `dream.run` and keeps the options it was given."""

    def __init__(self) -> None:
        self.options: list[dream.RunOptions] = []

    async def __call__(
        self,
        options: dream.RunOptions,
        *,
        now: datetime,
        model_factory: object,
    ) -> dream.RunResult:
        self.options.append(options)
        nothing = replace(
            REPORT,
            found=0,
            selected=0,
            skipped_by_reason=(),
            analyzed=0,
            nothing_to_dream=True,
        )
        return dream.RunResult(report=nothing, outcome=nothing.outcome)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> RunSpy:
    spy = RunSpy()
    monkeypatch.setattr(dream, "run", spy)
    return spy


def main(tmp_path: Path, *arguments: str) -> int:
    return cli.main(
        ["--memory", str(tmp_path / "memory"), *arguments],
        model_factory=ScriptedModels(),
        now=RUN_START,
    )


def exit_code_of(tmp_path: Path, *arguments: str) -> int | str | None:
    with pytest.raises(SystemExit) as raised:
        main(tmp_path, *arguments)
    return raised.value.code


@pytest.mark.parametrize(
    ("since", "expected"),
    [
        ("2026-10-01", datetime(2026, 10, 1, tzinfo=UTC)),
        ("2026-10-01T12:00:00+02:00", datetime(2026, 10, 1, 10, 0, tzinfo=UTC)),
        ("2026-10-01T12:00:00Z", datetime(2026, 10, 1, 12, 0, tzinfo=UTC)),
    ],
)
def test_since_is_a_utc_window_start(
    spy: RunSpy, tmp_path: Path, since: str, expected: datetime
) -> None:
    assert main(tmp_path, "--since", since) == 0

    [options] = spy.options
    assert options.since == expected
    assert options.since.utcoffset() is not None


def test_since_defaults_to_14_days_before_now(spy: RunSpy, tmp_path: Path) -> None:
    main(tmp_path)

    assert spy.options[0].since == datetime(2026, 10, 27, 21, 38, tzinfo=UTC)


@pytest.mark.parametrize(
    "since", ["2026-10-01T12:00:00", "2026-11-11", "2026-13-01", "yesterday"]
)
def test_invalid_or_future_since_is_an_invalid_argument(
    spy: RunSpy, tmp_path: Path, since: str
) -> None:
    assert exit_code_of(tmp_path, "--since", since) == 2
    assert spy.options == []


@pytest.mark.parametrize("option", ["--claude-code-dir", "--codex-dir", "--session"])
def test_missing_named_path_is_an_invalid_argument(
    spy: RunSpy, tmp_path: Path, option: str
) -> None:
    assert exit_code_of(tmp_path, option, str(tmp_path / "missing")) == 2
    assert spy.options == []


def test_missing_default_directories_give_no_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    exit_code = main(tmp_path)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "  found                     0\n" in out
    assert out.endswith("Nothing to dream over.\n")
    assert not (tmp_path / "memory").exists()


def test_interrupt_exits_130(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def interrupted(*args: object, **kwargs: object) -> dream.RunResult:
        raise KeyboardInterrupt

    monkeypatch.setattr(dream, "run", interrupted)

    assert main(tmp_path) == 130
    assert "interrupted" in capsys.readouterr().err


def test_report_matches_the_contract_layout() -> None:
    assert cli.render_report(REPORT).splitlines() == [
        "Dream report, run 20261110T213800Z",
        "",
        "Sessions",
        "  found                     6",
        "  selected                  5",
        "  skipped                   1  (subthread: 1)",
        "  analyzed                  5  (in more than one part: 0)",
        "  failed                    0",
        "",
        "Organizer                   ran and succeeded",
        "Waiting for the organizer   0 files",
        "",
        "Memory",
        "  index                     9 entries, 2 domains, 1 subdomain",
        "  files                     7 created, 1 changed, 0 retired",
        "  conflicts added           0",
        "  format check              no violations",
        "",
        "Usage",
        "  tokens                    1,234,567 input (1,000,000 cache read, 120,000 cache write), 45,678 output",
        "  cost at list price        US$0.12",
        "  spending limit            US$10.00, not reached",
        "",
        f"Pre-run copy                {BACKUP}",
    ]


def test_report_lists_failed_sessions_and_a_missing_copy() -> None:
    failed = replace(
        REPORT,
        analyzed=4,
        failed=(FailedSession(Tool.CODEX, PASSWORD_LIMIT, FailureReason.RATE_LIMITED),),
        backup_path=None,
    )

    lines = cli.render_report(failed).splitlines()

    assert lines[6:9] == [
        "  analyzed                  4  (in more than one part: 0)",
        "  failed                    1",
        f"  failed  codex {PASSWORD_LIMIT}  rate-limited",
    ]
    assert lines[-1] == "Pre-run copy                none (memory unchanged)"


def test_report_with_nothing_to_dream_is_the_sessions_block_and_one_line() -> None:
    nothing = replace(
        REPORT,
        found=1,
        selected=0,
        skipped_by_reason=((SkipReason.ALREADY_ANALYZED, 1),),
        analyzed=0,
        organizer=OrganizerSummary(OrganizerStatus.NOT_RUN),
        backup_path=None,
        nothing_to_dream=True,
    )

    assert cli.render_report(nothing).splitlines() == [
        "Dream report, run 20261110T213800Z",
        "",
        "Sessions",
        "  found                     1",
        "  selected                  0",
        "  skipped                   1  (already-analyzed: 1)",
        "  analyzed                  0  (in more than one part: 0)",
        "  failed                    0",
        "",
        "Nothing to dream over.",
    ]


@pytest.mark.parametrize(
    ("limit", "reached", "line"),
    [
        ("10.00", True, "  spending limit            US$10.00, reached"),
        ("2.5", False, "  spending limit            US$2.50, not reached"),
        ("0.005", True, "  spending limit            US$0.005, reached"),
    ],
)
def test_report_shows_the_spending_limit_and_whether_it_was_reached(
    limit: str, reached: bool, line: str
) -> None:
    usage = replace(REPORT.usage, limit_usd=Decimal(limit), limit_reached=reached)

    assert line in cli.render_report(replace(REPORT, usage=usage)).splitlines()


def test_report_with_nothing_selected_but_files_waiting_is_complete() -> None:
    organizer_only = replace(REPORT, found=0, selected=0, analyzed=0, waiting_files=1)

    lines = cli.render_report(organizer_only).splitlines()

    assert "Organizer                   ran and succeeded" in lines
    assert "Waiting for the organizer   1 file" in lines
    assert "Nothing to dream over." not in lines


@pytest.mark.parametrize(
    ("organizer", "line"),
    [
        (
            OrganizerSummary(OrganizerStatus.FAILED, FailureReason.TIMEOUT),
            "Organizer                   failed (timeout); memory was not organized",
        ),
        (
            OrganizerSummary(OrganizerStatus.NOT_RUN),
            "Organizer                   did not run",
        ),
    ],
)
def test_report_says_when_the_organizer_failed_or_did_not_run(
    organizer: OrganizerSummary, line: str
) -> None:
    lines = cli.render_report(replace(REPORT, organizer=organizer, waiting_files=2))

    assert f"\n{line}\nWaiting for the organizer   2 files\n" in lines


def test_report_lists_violations_by_file_and_rule() -> None:
    violations = (
        FormatViolation("_index.md", FormatRule.INDEX_HEADING_EMPTY),
        FormatViolation("notes.md", FormatRule.FRONTMATTER_MISSING),
    )

    lines = cli.render_report(replace(REPORT, violations=violations)).splitlines()

    start = lines.index("  format check              2 violations")
    assert lines[start + 1 : start + 4] == [
        "  _index.md  index-heading-empty",
        "  notes.md  frontmatter-missing",
        "",
    ]


def test_unreadable_record_means_not_started(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = state_dir(tmp_path / "memory") / "record.json"
    record.parent.mkdir(parents=True)
    record.write_text('{"version": 99}')
    empty = tmp_path / "empty"
    empty.mkdir()

    exit_code = main(
        tmp_path, "--claude-code-dir", str(empty), "--codex-dir", str(empty)
    )

    assert exit_code == 2
    assert capsys.readouterr().err == (
        f"dream: can't read the dream record {record}: it has a version this dream "
        "can't read. Nothing was changed.\n"
    )
    assert not (tmp_path / "memory").exists()


def test_spending_limit_defaults_to_ten_dollars_and_accepts_cents(
    spy: RunSpy, tmp_path: Path
) -> None:
    main(tmp_path)
    main(tmp_path, "--spending-limit", "2.50")

    assert [options.spending_limit for options in spy.options] == [
        Decimal("10.00"),
        Decimal("2.50"),
    ]


@pytest.mark.parametrize("limit", ["0", "-1", "0.00", "ten", "NaN", "Infinity"])
def test_spending_limit_must_be_a_positive_amount(
    spy: RunSpy, tmp_path: Path, limit: str
) -> None:
    assert exit_code_of(tmp_path, "--spending-limit", limit) == 2
    assert spy.options == []


CLAUDE_CODE_FILE = Path(
    "/Users/dev/.claude/projects/-Users-dev-Projects/"
    "90f95193-2c91-4a42-a506-930d4c964c45.jsonl"
)
CODEX_FILE = Path(
    "/Users/dev/.codex/sessions/2026/11/06/"
    "rollout-2026-11-06T19-50-12-eef4a695-6c41-4e5f-ba21-c3b858881bd1.jsonl"
)
SUBTHREAD_FILE = Path(
    "/Users/dev/.codex/sessions/2026/11/06/"
    "rollout-2026-11-06T20-10-00-4cea5169-365b-4853-93c8-e00a4221cc20.jsonl"
)
LARGE_FILE = Path("/Users/dev/.claude/projects/-Users-dev-Projects/big.jsonl")


def selected(
    path: Path,
    tool: Tool,
    size: int,
    project_dir: str,
    last_at: datetime,
    text_length: int,
) -> Selected:
    """A selected session whose view is one user message of `text_length` characters."""
    message = ConversationMessage(last_at, MessageKind.USER, "x" * text_length)
    view = ConversationView((message,))
    file = SessionFile(path, tool, size=size, mtime_ns=0)
    session = Session(
        file,
        tool,
        path.stem,
        project_dir,
        last_at - timedelta(minutes=5),
        last_at,
        None,
        view,
    )
    part = Part(1, 1, (message,), view.estimated_tokens, last_at, last_at)
    return Selected(session, (part,), "0" * 64)


def test_preview_matches_the_contract_layout() -> None:
    # The header "--- 2026-10-17 09:22 UTC | user ---" and its newline are 36
    # characters, so 2,931 more make 2,967 characters: 989 estimated tokens.
    # 17,355 more make 17,391 characters: 5,797 estimated tokens.
    preview = dream.Preview(
        since=datetime(2026, 10, 1, tzinfo=UTC),
        until=RUN_START,
        decisions=(
            selected(
                CLAUDE_CODE_FILE,
                Tool.CLAUDE_CODE,
                54_250,
                "/Users/dev/Projects",
                datetime(2026, 10, 17, 9, 22, 41, tzinfo=UTC),
                2_931,
            ),
            selected(
                CODEX_FILE,
                Tool.CODEX,
                143_155,
                "/Users/dev/Projects/mailarkiv",
                datetime(2026, 11, 6, 20, 2, tzinfo=UTC),
                17_355,
            ),
            Skipped(
                SessionFile(SUBTHREAD_FILE, Tool.CODEX, 1, 0), SkipReason.SUBTHREAD
            ),
            Skipped(
                SessionFile(LARGE_FILE, Tool.CLAUDE_CODE, 1, 0),
                SkipReason.TOO_LARGE,
                "523,104 estimated tokens",
            ),
        ),
        waiting_files=3,
    )

    assert cli.render_preview(preview).splitlines() == [
        "Preview: window 2026-10-01 00:00 UTC to 2026-11-10 21:38 UTC",
        "",
        "Selected sessions (2)",
        "  tool         last activity      project dir                        size  est. tokens  parts",
        "  claude-code  2026-10-17 09:22   /Users/dev/Projects             53.0 KB          989      1",
        f"    {CLAUDE_CODE_FILE}",
        "  codex        2026-11-06 20:02   /Users/dev/Projects/mailarkiv  139.8 KB        5,797      1",
        f"    {CODEX_FILE}",
        "Total estimated tokens: 6,786",
        "",
        "Memory files waiting for the organizer: 3",
        "",
        "Skipped sessions (2)",
        f"  {SUBTHREAD_FILE}  subthread",
        f"  {LARGE_FILE}  too-large (523,104 estimated tokens)",
    ]


def test_preview_with_nothing_found() -> None:
    preview = dream.Preview(
        since=datetime(2026, 10, 1, tzinfo=UTC),
        until=RUN_START,
        decisions=(),
        waiting_files=0,
    )

    assert cli.render_preview(preview).splitlines() == [
        "Preview: window 2026-10-01 00:00 UTC to 2026-11-10 21:38 UTC",
        "",
        "Selected sessions (0)",
        "Total estimated tokens: 0",
        "",
        "Memory files waiting for the organizer: 0",
        "",
        "Skipped sessions (0)",
    ]
