"""How ClaudeModel turns API failures, prompt size, and usage into results.

Runs the real anthropic SDK, with its retries, against the fake Messages API.
"""

import asyncio
from decimal import Decimal

import anthropic._base_client
import pytest

from dreaming_workflow.agents import (
    AgentFailure,
    AgentRole,
    ClaudeModel,
    FailureReason,
)
from dreaming_workflow.agents.budget import ContextGuard, UsageLedger
from dreaming_workflow.agents.claude_model import MissingCredentials, create_client
from dreaming_workflow.agents.runner import run_agent
from tests.support.fake_messages_api import (
    FakeMessagesApi,
    FakeReply,
    JsonObject,
    MessageReply,
    StatusReply,
    TimeoutReply,
    text_block,
)

FAST_RETRY = {"retry-after-ms": "1"}
# One request plus the client's three retries.
ATTEMPTS = 4


def run(
    api: FakeMessagesApi,
    message: str = "Note: hello.",
    ledger: UsageLedger | None = None,
    role: AgentRole = AgentRole.ANALYSIS,
) -> None:
    model = ClaudeModel(
        client=api.client(),
        role=role,
        ledger=ledger or UsageLedger(),
        guard=ContextGuard(),
    )
    asyncio.run(
        run_agent(
            name="note_taker",
            model=model,
            instruction="You take notes when asked.",
            tools=[],
            message=message,
            max_llm_calls=5,
        )
    )


def failure_of(api: FakeMessagesApi, message: str = "Note: hello.") -> AgentFailure:
    with pytest.raises(AgentFailure) as raised:
        run(api, message)
    return raised.value


def always(reply: FakeReply) -> FakeMessagesApi:
    def respond(_body: JsonObject) -> FakeReply:
        return reply

    return FakeMessagesApi(respond)


@pytest.mark.parametrize(
    ("status", "reason"),
    [(429, FailureReason.RATE_LIMITED), (529, FailureReason.OVERLOADED)],
)
def test_retried_statuses_fail_after_three_retries(
    status: int, reason: FailureReason
) -> None:
    api = always(StatusReply(status, FAST_RETRY))

    failure = failure_of(api)

    assert len(api.requests) == ATTEMPTS
    assert failure.failure.reason is reason


def test_timeout_fails_after_three_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    # Timeouts have no retry-after header; shorten the client's own backoff.
    monkeypatch.setattr(anthropic._base_client, "INITIAL_RETRY_DELAY", 0.001)
    api = always(TimeoutReply())

    failure = failure_of(api)

    assert len(api.requests) == ATTEMPTS
    assert failure.failure.reason is FailureReason.TIMEOUT


def test_server_error_is_retried_then_reports_status_and_request_id() -> None:
    api = always(StatusReply(500, FAST_RETRY | {"request-id": "req_fake500"}))

    failure = failure_of(api)

    assert len(api.requests) == ATTEMPTS
    assert failure.failure.reason is FailureReason.API_ERROR
    assert failure.failure.detail == "status 500, request ID req_fake500"


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_credentials_fail_without_retries(status: int) -> None:
    api = always(StatusReply(status))

    failure = failure_of(api)

    assert len(api.requests) == 1
    assert failure.failure.reason is FailureReason.AUTHENTICATION_FAILED


def test_prompt_projected_past_the_ceiling_sends_nothing() -> None:
    api = always(MessageReply(content=[text_block("Done.")]))
    # 300,000 characters estimate to 100,000 tokens before the instruction is added.
    failure = failure_of(api, message="x" * 300_000)

    assert failure.failure.reason is FailureReason.CONTEXT_LIMIT
    assert api.requests == []


def test_usage_lands_in_the_ledger_at_list_price() -> None:
    api = always(
        MessageReply(
            content=[text_block("Done.")],
            usage={
                "input_tokens": 10_000,
                "cache_creation_input_tokens": 2_000,
                "cache_read_input_tokens": 50_000,
                "output_tokens": 1_000,
            },
        )
    )
    ledger = UsageLedger()

    run(api, ledger=ledger)

    assert (
        ledger.input_tokens,
        ledger.cache_write_tokens,
        ledger.cache_read_tokens,
        ledger.output_tokens,
    ) == (10_000, 2_000, 50_000, 1_000)
    # 10,000 × 2.00 + 2,000 × 2.50 + 50,000 × 0.10 + 1,000 × 10.00 = 40,000 per million.
    assert ledger.cost_usd == Decimal("0.04")
    assert ledger.largest_prompt_tokens == 62_000


def ledger_with_cost(cost_usd: str, limit_usd: str) -> UsageLedger:
    return UsageLedger(cost_usd=Decimal(cost_usd), limit_usd=Decimal(limit_usd))


def test_analysis_request_at_the_spending_limit_sends_nothing() -> None:
    api = always(MessageReply(content=[text_block("Done.")]))

    with pytest.raises(AgentFailure) as raised:
        run(api, ledger=ledger_with_cost("0.50", "0.50"))

    assert raised.value.failure.reason is FailureReason.SPENDING_LIMIT_REACHED
    assert api.requests == []


def test_organizer_request_at_the_spending_limit_is_sent() -> None:
    api = always(MessageReply(content=[text_block("Done.")]))

    run(api, ledger=ledger_with_cost("0.50", "0.50"), role=AgentRole.ORGANIZER)

    assert len(api.requests) == 1


def test_analysis_request_below_the_spending_limit_is_sent() -> None:
    api = always(MessageReply(content=[text_block("Done.")]))

    run(api, ledger=ledger_with_cost("0.49", "0.50"))

    assert len(api.requests) == 1


def test_create_client_without_credentials_raises() -> None:
    # The test environment removes credential variables and points
    # ANTHROPIC_CONFIG_DIR at an empty directory.
    with pytest.raises(MissingCredentials):
        create_client()


def test_create_client_with_an_api_key_returns_a_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder-for-tests")

    client = create_client()

    assert client.api_key == "placeholder-for-tests"
