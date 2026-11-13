import argparse
import asyncio
import logging
import re
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from dreaming_workflow import dream
from dreaming_workflow.agents import (
    ClaudeModel,
    Invocation,
    ModelFactory,
    OrganizerStatus,
    create_client,
)
from dreaming_workflow.agents.budget import DEFAULT_SPENDING_LIMIT
from dreaming_workflow.agents.claude_model import MissingCredentials
from dreaming_workflow.report import OrganizerSummary, Report, RunOutcome
from dreaming_workflow.sessions import Selected, Skipped, SkipReason
from dreaming_workflow.state import (
    MemoryInUse,
    RecordError,
    RecordProblem,
    state_dir,
)

# Third-party loggers can carry request bodies at DEBUG level, and those hold
# session and memory content.
_QUIET_LOGGERS = ("google_adk", "anthropic", "httpx2")
_LABEL_WIDTH = 26
_DEFAULT_WINDOW = timedelta(days=14)
_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")
INTERRUPTED_EXIT_CODE = 130
MISSING_CREDENTIALS = (
    "dream: no Claude API credentials found. Set ANTHROPIC_API_KEY, "
    "or run `ant auth login` to create a profile."
)
_RECORD_PROBLEMS = {
    RecordProblem.UNKNOWN_VERSION: "it has a version this dream can't read",
    RecordProblem.INVALID: "it isn't a valid dream record",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dream",
        description="Update a memory directory from finished Claude Code and Codex sessions.",
    )
    parser.add_argument(
        "--memory",
        required=True,
        type=Path,
        metavar="DIR",
        help="memory directory; created with mode 0700 on the first run that writes",
    )
    parser.add_argument(
        "--since",
        metavar="DATE",
        help=(
            "window start: YYYY-MM-DD (midnight UTC) or an ISO 8601 timestamp "
            "with a UTC offset; default 14 days before now"
        ),
    )
    parser.add_argument(
        "--claude-code-dir",
        type=Path,
        metavar="DIR",
        help="Claude Code session directory (default ~/.claude/projects)",
    )
    parser.add_argument(
        "--codex-dir",
        type=Path,
        metavar="DIR",
        help="Codex session directory (default ~/.codex/sessions)",
    )
    parser.add_argument(
        "--session",
        action="append",
        default=[],
        type=Path,
        metavar="FILE",
        help="session file to consider instead of scanning directories; repeatable",
    )
    parser.add_argument(
        "--spending-limit",
        type=_spending_limit,
        default=DEFAULT_SPENDING_LIMIT,
        metavar="USD",
        help=(
            "stop sending analysis requests once the run's cost at list price "
            f"reaches this amount (default {DEFAULT_SPENDING_LIMIT})"
        ),
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="list what a run would send; sends nothing, changes no files, needs no credentials",
    )
    return parser


def _spending_limit(text: str) -> Decimal:
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(
            "use an amount in US dollars, such as 10.00"
        ) from None
    if not amount.is_finite() or amount <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return amount


def parse_since(text: str) -> datetime | None:
    """Parse `YYYY-MM-DD` as midnight UTC, or an ISO 8601 timestamp with an offset."""
    if _DATE_ONLY.fullmatch(text):
        try:
            day = date.fromisoformat(text)
        except ValueError:
            return None
        return datetime(day.year, day.month, day.day, tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _real_model_factory() -> ModelFactory:
    client = create_client()

    def model_for(invocation: Invocation) -> ClaudeModel:
        return ClaudeModel(
            client=client,
            role=invocation.role,
            ledger=invocation.ledger,
            guard=invocation.guard,
        )

    return model_for


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count:,} {singular if count == 1 else plural}"


def _row(label: str, value: object, indent: str = "  ") -> str:
    width = _LABEL_WIDTH + len("  ") - len(indent)
    return f"{indent}{label:<{width}}{value}"


def _usd(amount: Decimal) -> str:
    return f"US${amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"


def _limit_usd(amount: Decimal) -> str:
    """Show the limit in cents, or exactly if the user gave fractions of a cent."""
    cents = amount.quantize(Decimal("0.01"))
    return f"US${cents}" if cents == amount else f"US${amount.normalize():f}"


def _minute(at: datetime) -> str:
    return f"{at.astimezone(UTC):%Y-%m-%d %H:%M}"


def _selected_table(selected: list[Selected]) -> list[str]:
    """Rows of selected sessions, each followed by its file path."""
    rows = [
        (
            decision.session.tool.value,
            _minute(decision.session.last_activity_at),
            decision.session.project_dir,
            f"{decision.session.file.size / 1024:,.1f} KB",
            f"{decision.session.view.estimated_tokens:,}",
            f"{len(decision.parts):,}",
        )
        for decision in selected
    ]
    header = ("tool", "last activity", "project dir", "size", "est. tokens", "parts")
    widths = [
        max(len(row[column]) for row in (header, *rows))
        for column in range(len(header))
    ]

    def line(row: tuple[str, ...]) -> str:
        tool, activity, project, size, tokens, parts = row
        return (
            f"  {tool:<{widths[0]}}  {activity:<{widths[1]}}   "
            f"{project:<{widths[2]}}  {size:>{widths[3]}}  "
            f"{tokens:>{widths[4]}}  {parts:>{widths[5]}}"
        )

    lines = [line(header)]
    for decision, row in zip(selected, rows, strict=True):
        lines.extend([line(row), f"    {decision.session.file.path}"])
    return lines


def _skipped_line(decision: Skipped) -> str:
    reason = decision.reason.value
    if decision.reason is SkipReason.TOO_LARGE:
        reason += f" ({decision.detail})"
    return f"  {decision.file.path}  {reason}"


def render_preview(preview: dream.Preview) -> str:
    selected = [d for d in preview.decisions if isinstance(d, Selected)]
    skipped = [d for d in preview.decisions if isinstance(d, Skipped)]
    total = sum(d.session.view.estimated_tokens for d in selected)
    lines = [
        f"Preview: window {_minute(preview.since)} UTC to {_minute(preview.until)} UTC",
        "",
        f"Selected sessions ({len(selected):,})",
        *(_selected_table(selected) if selected else []),
        f"Total estimated tokens: {total:,}",
        "",
        f"Memory files waiting for the organizer: {preview.waiting_files:,}",
        "",
        f"Skipped sessions ({len(skipped):,})",
        *(_skipped_line(d) for d in skipped),
    ]
    return "\n".join(lines)


def _sessions_block(report: Report) -> list[str]:
    skipped = f"{report.skipped:,}"
    if report.skipped_by_reason:
        reasons = ", ".join(f"{r.value}: {n:,}" for r, n in report.skipped_by_reason)
        skipped += f"  ({reasons})"
    lines = [
        "Sessions",
        _row("found", f"{report.found:,}"),
        _row("selected", f"{report.selected:,}"),
        _row("skipped", skipped),
        _row(
            "analyzed",
            f"{report.analyzed:,}  (in more than one part: {report.analyzed_in_parts:,})",
        ),
        _row("failed", f"{len(report.failed):,}"),
    ]
    lines.extend(
        f"  failed  {failed.tool.value} {failed.session_id}  {failed.reason.value}"
        for failed in report.failed
    )
    return lines


def _organizer_line(organizer: OrganizerSummary) -> str:
    match organizer.status:
        case OrganizerStatus.SUCCEEDED:
            return "ran and succeeded"
        case OrganizerStatus.FAILED:
            reason = "unknown" if organizer.failure is None else organizer.failure.value
            return f"failed ({reason}); memory was not organized"
        case OrganizerStatus.NOT_RUN:
            return "did not run"


def _format_check_lines(report: Report) -> list[str]:
    if not report.violations:
        return [_row("format check", "no violations")]
    count = _plural(len(report.violations), "violation", "violations")
    return [
        _row("format check", count),
        *(f"  {v.file}  {v.rule.value}" for v in report.violations),
    ]


def render_report(report: Report) -> str:
    lines = [f"Dream report, run {report.run_id}", "", *_sessions_block(report)]
    if report.nothing_to_dream:
        lines.extend(["", "Nothing to dream over."])
        return "\n".join(lines)
    index = (
        "not readable"
        if report.index is None
        else ", ".join(
            (
                _plural(report.index.entries, "entry", "entries"),
                _plural(report.index.domains, "domain", "domains"),
                _plural(report.index.subdomains, "subdomain", "subdomains"),
            )
        )
    )
    files = report.files
    usage = report.usage
    lines.extend(
        [
            "",
            _row("Organizer", _organizer_line(report.organizer), indent=""),
            _row(
                "Waiting for the organizer",
                _plural(report.waiting_files, "file", "files"),
                indent="",
            ),
            "",
            "Memory",
            _row("index", index),
            _row(
                "files",
                f"{files.created:,} created, {files.changed:,} changed, "
                f"{files.retired:,} retired",
            ),
            _row("conflicts added", f"{report.conflicts_added:,}"),
            *_format_check_lines(report),
            "",
            "Usage",
            _row(
                "tokens",
                f"{usage.input_tokens:,} input ({usage.cache_read_tokens:,} cache read, "
                f"{usage.cache_write_tokens:,} cache write), {usage.output_tokens:,} output",
            ),
            _row("cost at list price", _usd(usage.cost_usd)),
            _row(
                "spending limit",
                f"{_limit_usd(usage.limit_usd)}, "
                f"{'reached' if usage.limit_reached else 'not reached'}",
            ),
            "",
            _row(
                "Pre-run copy",
                report.backup_path or "none (memory unchanged)",
                indent="",
            ),
        ]
    )
    return "\n".join(lines)


def _record_unreadable(error: RecordError) -> int:
    print(
        f"dream: can't read the dream record {error.path}: "
        f"{_RECORD_PROBLEMS[error.problem]}. Nothing was changed.",
        file=sys.stderr,
    )
    return RunOutcome.NOT_STARTED.exit_code


def main(
    argv: list[str] | None = None,
    *,
    model_factory: ModelFactory | None = None,
    now: datetime | None = None,
) -> int:
    started_at = now or datetime.now(UTC)
    parser = build_parser()
    args = parser.parse_args(argv)
    since = started_at - _DEFAULT_WINDOW
    if args.since is not None:
        parsed = parse_since(args.since)
        if parsed is None:
            parser.error(
                "--since: use YYYY-MM-DD or an ISO 8601 timestamp with a UTC offset"
            )
        if parsed >= started_at:
            parser.error("--since: must be in the past")
        since = parsed
    for option, directory in (
        ("--claude-code-dir", args.claude_code_dir),
        ("--codex-dir", args.codex_dir),
    ):
        if directory is not None and not directory.is_dir():
            parser.error(f"{option} {directory}: no such directory")
    session_files: list[Path] = args.session
    for path in session_files:
        if not path.is_file():
            parser.error(f"--session {path}: no such file")

    options = dream.RunOptions(
        memory_dir=args.memory,
        since=since,
        claude_code_dir=args.claude_code_dir or Path.home() / ".claude" / "projects",
        codex_dir=args.codex_dir or Path.home() / ".codex" / "sessions",
        session_files=tuple(session_files),
        spending_limit=args.spending_limit,
    )
    if args.preview:
        try:
            preview = dream.preview(options, now=started_at)
        except RecordError as error:
            return _record_unreadable(error)
        print(render_preview(preview))
        return RunOutcome.SUCCESS.exit_code

    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    if model_factory is None:
        try:
            model_factory = _real_model_factory()
        except MissingCredentials:
            print(MISSING_CREDENTIALS, file=sys.stderr)
            return RunOutcome.NOT_STARTED.exit_code

    try:
        result = asyncio.run(
            dream.run(options, now=started_at, model_factory=model_factory)
        )
    except MemoryInUse:
        print(
            f"dream: another dream is running on {args.memory}. Nothing was changed.",
            file=sys.stderr,
        )
        return RunOutcome.NOT_STARTED.exit_code
    except RecordError as error:
        return _record_unreadable(error)
    except KeyboardInterrupt:
        backups = state_dir(args.memory) / "backups"
        print(
            f"dream: interrupted. Memory may be partly updated; "
            f"pre-run copies are in {backups}.",
            file=sys.stderr,
        )
        return INTERRUPTED_EXIT_CODE
    print(render_report(result.report))
    return result.outcome.exit_code
