"""What requests cost, and how large the next prompt may grow."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from dreaming_workflow.agents.results import AgentFailure, Failure, FailureReason

READ_BUDGET = 75_000
PROMPT_CEILING = 95_000
_MILLION = Decimal(1_000_000)
CACHE_WRITE_MULTIPLIER = Decimal("1.25")
CACHE_READ_MULTIPLIER = Decimal("0.1")


@dataclass(frozen=True)
class Rates:
    """US dollars per million tokens."""

    input: Decimal
    output: Decimal


@dataclass(frozen=True)
class PriceTable:
    model: str
    checked_on: date
    standard: Rates
    # Applies to every token of a request whose prompt passes the threshold.
    long_prompt: Rates
    long_prompt_threshold: int


# List prices from Anthropic's pricing reference dated 2026-11-03.
PRICES = PriceTable(
    model="claude-haiku-5-5",
    checked_on=date(2026, 11, 11),
    standard=Rates(input=Decimal("0.10"), output=Decimal("0.50")),
    long_prompt=Rates(input=Decimal("0.50"), output=Decimal("2.50")),
    long_prompt_threshold=100_000,
)


@dataclass(frozen=True)
class TokenUsage:
    """One response's usage in the Messages API's terms."""

    input_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens


def cost(usage: TokenUsage, prices: PriceTable = PRICES) -> Decimal:
    rates = (
        prices.standard
        if usage.prompt_tokens <= prices.long_prompt_threshold
        else prices.long_prompt
    )
    total = (
        usage.input_tokens * rates.input
        + usage.cache_write_tokens * rates.input * CACHE_WRITE_MULTIPLIER
        + usage.cache_read_tokens * rates.input * CACHE_READ_MULTIPLIER
        + usage.output_tokens * rates.output
    )
    return total / _MILLION


@dataclass
class UsageLedger:
    """Usage and cost of every request in a run."""

    input_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    largest_prompt_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        """Every input token: uncached, cache writes, and cache reads."""
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens

    def add(self, usage: TokenUsage) -> None:
        self.input_tokens += usage.input_tokens
        self.cache_write_tokens += usage.cache_write_tokens
        self.cache_read_tokens += usage.cache_read_tokens
        self.output_tokens += usage.output_tokens
        self.cost_usd += cost(usage)
        self.largest_prompt_tokens = max(
            self.largest_prompt_tokens, usage.prompt_tokens
        )


@dataclass
class ContextGuard:
    """Projects one agent invocation's next prompt size.

    The projection is the last prompt's real size plus an estimate of what was
    added since: the model's reply and each tool result.
    """

    last_prompt_tokens: int = 0
    pending_estimate: int = 0
    read_budget: int = READ_BUDGET
    ceiling: int = PROMPT_CEILING

    @property
    def projected_tokens(self) -> int:
        return self.last_prompt_tokens + self.pending_estimate

    def room_for_read(self, estimated_tokens: int) -> int | None:
        """Return None if a result of this size fits the read budget, else the room left."""
        if self.projected_tokens + estimated_tokens <= self.read_budget:
            return None
        return max(self.read_budget - self.projected_tokens, 0)

    def add_pending(self, estimated_tokens: int) -> None:
        self.pending_estimate += estimated_tokens

    def check_send(self, estimated_new_tokens: int) -> None:
        """Raise `context-limit` if the next prompt would pass the ceiling."""
        if self.last_prompt_tokens + estimated_new_tokens > self.ceiling:
            raise AgentFailure(Failure(FailureReason.CONTEXT_LIMIT))

    def record_response(self, usage: TokenUsage) -> None:
        self.last_prompt_tokens = usage.prompt_tokens
        # The reply is sent back with the next request.
        self.pending_estimate = usage.output_tokens
