import argparse
import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from dreaming_workflow import dream
from dreaming_workflow.agents import (
    ClaudeModel,
    Invocation,
    ModelFactory,
    create_client,
)
from dreaming_workflow.report import Report

# Third-party loggers can carry request bodies at DEBUG level, and those hold
# session and memory content.
_QUIET_LOGGERS = ("google_adk", "anthropic", "httpx2")
_LABEL_WIDTH = 26


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
        "--session",
        action="append",
        default=[],
        type=Path,
        metavar="FILE",
        help="session file to consider; repeatable",
    )
    return parser


def _real_model_factory() -> ModelFactory:
    client = create_client()

    def model_for(_invocation: Invocation) -> ClaudeModel:
        return ClaudeModel(client=client)

    return model_for


def _row(label: str, value: object, indent: str = "  ") -> str:
    return f"{indent}{label:<{_LABEL_WIDTH}}{value}"


def render_report(report: Report) -> str:
    lines = [
        f"Dream report, run {report.run_id}",
        "",
        "Sessions",
        _row("skipped", f"{report.skipped:,}"),
        _row("analyzed", f"{report.analyzed:,}"),
        _row("failed", f"{len(report.failed):,}"),
    ]
    lines.extend(
        f"  failed  {failed.tool.value} {failed.session_id}  {failed.reason.value}"
        for failed in report.failed
    )
    lines.extend(["", "Memory", _row("files", f"{report.files_created:,} created")])
    return "\n".join(lines)


def main(
    argv: list[str] | None = None,
    *,
    model_factory: ModelFactory | None = None,
    now: datetime | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    session_files: list[Path] = args.session
    for path in session_files:
        if not path.is_file():
            parser.error(f"--session {path}: no such file")
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    options = dream.RunOptions(
        memory_dir=args.memory, session_files=tuple(session_files)
    )
    result = asyncio.run(
        dream.run(
            options,
            now=now or datetime.now(UTC),
            model_factory=model_factory or _real_model_factory(),
        )
    )
    print(render_report(result.report))
    return result.outcome.exit_code
