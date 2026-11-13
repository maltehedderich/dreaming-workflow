from decimal import Decimal

import pytest

from dreaming_workflow.agents import AgentFailure, FailureReason
from dreaming_workflow.agents.budget import (
    ContextGuard,
    TokenUsage,
    UsageLedger,
    cost,
)

USAGE = TokenUsage(
    input_tokens=10_000,
    cache_write_tokens=2_000,
    cache_read_tokens=50_000,
    output_tokens=1_000,
)


def test_cost_at_the_standard_rate() -> None:
    # 10,000 × 0.10 + 2,000 × 0.125 + 50,000 × 0.01 + 1,000 × 0.50 = 2,250 per million.
    assert cost(USAGE) == Decimal("0.00225")


def test_prompt_over_100000_uses_the_higher_rate_on_every_token() -> None:
    usage = TokenUsage(
        input_tokens=60_000,
        cache_write_tokens=2_000,
        cache_read_tokens=50_000,
        output_tokens=1_000,
    )
    assert usage.prompt_tokens == 112_000

    # 60,000 × 0.50 + 2,000 × 0.625 + 50,000 × 0.05 + 1,000 × 2.50 = 36,250 per million.
    assert cost(usage) == Decimal("0.03625")


def test_prompt_of_exactly_100000_uses_the_standard_rate() -> None:
    usage = TokenUsage(
        input_tokens=100_000, cache_write_tokens=0, cache_read_tokens=0, output_tokens=0
    )

    assert cost(usage) == Decimal("0.01")


def test_ledger_sums_responses_and_keeps_the_largest_prompt() -> None:
    ledger = UsageLedger()
    smaller = TokenUsage(
        input_tokens=1_000, cache_write_tokens=0, cache_read_tokens=0, output_tokens=200
    )

    ledger.add(USAGE)
    ledger.add(smaller)

    assert (
        ledger.input_tokens,
        ledger.cache_write_tokens,
        ledger.cache_read_tokens,
        ledger.output_tokens,
    ) == (11_000, 2_000, 50_000, 1_200)
    assert ledger.prompt_tokens == 63_000
    # 0.00225 plus 1,000 × 0.10 + 200 × 0.50 = 200 per million.
    assert ledger.cost_usd == Decimal("0.00245")
    assert ledger.largest_prompt_tokens == 62_000


def test_read_past_the_budget_is_refused_with_the_room_left() -> None:
    guard = ContextGuard(last_prompt_tokens=70_000, pending_estimate=1_000)

    assert guard.room_for_read(4_000) is None
    assert guard.room_for_read(4_001) == 4_000


def test_room_left_is_never_negative() -> None:
    guard = ContextGuard(last_prompt_tokens=80_000)

    assert guard.room_for_read(1) == 0


def test_send_past_95000_is_refused() -> None:
    guard = ContextGuard(last_prompt_tokens=90_000)

    guard.check_send(5_000)
    with pytest.raises(AgentFailure) as raised:
        guard.check_send(5_001)

    assert raised.value.failure.reason is FailureReason.CONTEXT_LIMIT


def test_a_response_resets_the_projection_to_its_prompt_and_reply() -> None:
    guard = ContextGuard(last_prompt_tokens=10_000, pending_estimate=3_000)

    guard.record_response(USAGE)

    assert guard.projected_tokens == 62_000 + 1_000


def test_analysis_requests_stop_once_cost_equals_the_limit() -> None:
    ledger = UsageLedger(limit_usd=Decimal("0.00225"))
    ledger.check_before_analysis_request()
    assert not ledger.limit_reached

    ledger.add(USAGE)

    assert ledger.cost_usd == Decimal("0.00225")
    assert ledger.limit_reached
    with pytest.raises(AgentFailure) as raised:
        ledger.check_before_analysis_request()
    assert raised.value.failure.reason is FailureReason.SPENDING_LIMIT_REACHED


def test_analysis_requests_continue_below_the_limit() -> None:
    ledger = UsageLedger(limit_usd=Decimal("0.00226"))

    ledger.add(USAGE)

    assert not ledger.limit_reached
    ledger.check_before_analysis_request()


def test_the_default_limit_is_ten_dollars() -> None:
    assert UsageLedger().limit_usd == Decimal("10.00")
