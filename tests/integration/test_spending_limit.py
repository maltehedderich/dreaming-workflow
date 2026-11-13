"""The spending limit stops analysis requests; the organizer still runs.

Uses the real ClaudeModel on the fake Messages API, so the ledger sees the
usage each response reports.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dreaming_workflow import cli
from dreaming_workflow.agents import (
    AnalysisStatus,
    ClaudeModel,
    FailureReason,
    Invocation,
)
from dreaming_workflow.state import DreamRecord
from tests.support.examples import RUN_START
from tests.support.fake_messages_api import (
    FakeMessagesApi,
    FakeReply,
    JsonObject,
    MessageReply,
    Responder,
    text_block,
    tool_use_block,
)
from tests.support.sessions import ClaudeCodeSession

DAY = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)
PROJECT = "/Users/dev/Projects/app"
# 10,000 input tokens at US$2.00 per million cost US$0.02.
TWO_CENTS: JsonObject = {"input_tokens": 10_000, "output_tokens": 0}
_SESSION_ID = re.compile(r"Session ID: ([0-9a-f-]{36})")


def write_sessions(directory: Path, count: int) -> list[str]:
    """Write `count` small sessions, last active one minute apart; return their IDs."""
    ids: list[str] = []
    for index in range(count):
        session_id = f"5e55e55e-0000-4000-8000-{index:012d}"
        at = DAY + timedelta(minutes=index)
        ClaudeCodeSession(session_id, PROJECT).typed_prompt(
            at, f"Question {index}"
        ).assistant_text(at, f"Answer {index}").write(directory / f"{session_id}.jsonl")
        ids.append(session_id)
    return ids


def has_tool_result(body: JsonObject) -> bool:
    return '"type": "tool_result"' in json.dumps(body["messages"])


def session_of(body: JsonObject) -> str | None:
    """The session an analysis request belongs to; None for the organizer."""
    messages = body["messages"]
    assert isinstance(messages, list)
    match = _SESSION_ID.search(json.dumps(messages[0]))
    return str(match.group(1)) if match else None


def responder(first_session: str) -> Responder:
    """The first session ends its turn at once; every other session reads the
    index first. Every response costs US$0.02."""

    def respond(body: JsonObject) -> FakeReply:
        session = session_of(body)
        if session is None or session == first_session or has_tool_result(body):
            return MessageReply([text_block("Done.")], usage=TWO_CENTS)
        return MessageReply(
            [tool_use_block(f"toolu_{session[-4:]}", "read_index", {})],
            stop_reason="tool_use",
            usage=TWO_CENTS,
        )

    return respond


def test_the_limit_stops_analyses_and_lets_the_organizer_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    claude_code = tmp_path / "claude"
    codex = tmp_path / "codex"
    codex.mkdir()
    ids = write_sessions(claude_code / "-Users-dev-Projects-app", 22)
    api = FakeMessagesApi(responder(ids[0]))
    client = api.client()

    def model_for(invocation: Invocation) -> ClaudeModel:
        return ClaudeModel(
            client=client,
            role=invocation.role,
            ledger=invocation.ledger,
            guard=invocation.guard,
        )

    memory = tmp_path / "memory"
    arguments = [
        "--memory",
        str(memory),
        "--since",
        "2026-10-01",
        "--claude-code-dir",
        str(claude_code),
        "--codex-dir",
        str(codex),
    ]

    exit_code = cli.main(
        [*arguments, "--spending-limit", "0.10"],
        model_factory=model_for,
        now=RUN_START,
    )

    report = capsys.readouterr().out
    assert exit_code == 1
    sent_for = {session_of(body) for body in api.requests}
    assert sent_for.isdisjoint(ids[20:])
    # The first session succeeded, so the organizer ran and sent a request.
    assert None in sent_for
    assert re.search(r"^Organizer +ran and succeeded$", report, re.MULTILINE)
    assert re.search(r"^  spending limit +US\$0\.10, reached$", report, re.MULTILINE)

    sessions = DreamRecord.load(memory).sessions
    outcomes = {record.session_id: record for record in sessions.values()}
    assert sorted(outcomes) == ids
    assert outcomes[ids[0]].status is AnalysisStatus.ANALYZED
    failed = sorted(
        session_id
        for session_id, record in outcomes.items()
        if record.status is AnalysisStatus.FAILED
    )
    assert failed
    assert set(ids[20:]) <= set(failed)
    assert all(
        record.status is AnalysisStatus.ANALYZED
        or record.failure is FailureReason.SPENDING_LIMIT_REACHED
        for record in outcomes.values()
    )
    for session_id in failed:
        assert f"  failed  claude-code {session_id}  spending-limit-reached" in report

    assert cli.main([*arguments, "--preview"], now=RUN_START) == 0
    preview = capsys.readouterr().out
    # Only selected sessions print a line that ends in their path.
    previewed = re.findall(r"^    \S+/([0-9a-f-]{36})\.jsonl$", preview, re.MULTILINE)
    assert f"Selected sessions ({len(failed)})" in preview
    assert sorted(previewed) == failed
