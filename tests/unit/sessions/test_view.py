from datetime import UTC, datetime

import pytest

from dreaming_workflow.sessions import (
    ConversationMessage,
    ConversationView,
    MessageKind,
    render,
    split_into_parts,
)

T0 = datetime(2026, 10, 17, 9, 40, 59, tzinfo=UTC)


def test_rendering_matches_the_contract_example() -> None:
    messages = (
        ConversationMessage(
            at=datetime(2026, 10, 17, 9, 40, 33, tzinfo=UTC),
            kind=MessageKind.USER,
            text="I just installed uv and want codex / claude use uv for python",
        ),
        ConversationMessage(
            at=datetime(2026, 10, 17, 9, 41, 2, tzinfo=UTC),
            kind=MessageKind.TOOL_CALL,
            text='{"command":"ls ~/.claude/rules/ ~/.codex/"}',
            tool_name="Bash",
        ),
        ConversationMessage(
            at=datetime(2026, 10, 17, 9, 41, 47, tzinfo=UTC),
            kind=MessageKind.TOOL_RESULT,
            text="PreToolUse:Bash hook error: …",
            is_error=True,
        ),
    )

    assert render(messages) == (
        "--- 2026-10-17 09:40 UTC | user ---\n"
        "I just installed uv and want codex / claude use uv for python\n"
        "\n"
        "--- 2026-10-17 09:41 UTC | tool call: Bash ---\n"
        '{"command":"ls ~/.claude/rules/ ~/.codex/"}\n'
        "\n"
        "--- 2026-10-17 09:41 UTC | tool result (error) ---\n"
        "PreToolUse:Bash hook error: …"
    )


@pytest.mark.parametrize(
    ("kind", "is_error", "label"),
    [
        (MessageKind.ASSISTANT, False, "assistant"),
        (MessageKind.TOOL_RESULT, False, "tool result"),
        (MessageKind.INTERRUPTED, False, "interrupted"),
    ],
)
def test_header_labels(kind: MessageKind, is_error: bool, label: str) -> None:
    message = ConversationMessage(at=T0, kind=kind, text="x", is_error=is_error)

    assert render((message,)) == f"--- 2026-10-17 09:40 UTC | {label} ---\nx"


def test_estimate_rounds_characters_divided_by_three_up() -> None:
    # The header is 35 characters; with a newline and 6 characters of text the view has 42.
    message = ConversationMessage(at=T0, kind=MessageKind.USER, text="a" * 6)
    assert len(render((message,))) == 42
    assert ConversationView((message,)).estimated_tokens == 14

    message = ConversationMessage(at=T0, kind=MessageKind.USER, text="a" * 7)
    assert ConversationView((message,)).estimated_tokens == 15


def test_small_view_is_one_part_spanning_its_messages() -> None:
    first = ConversationMessage(at=T0, kind=MessageKind.USER, text="question")
    last = ConversationMessage(
        at=datetime(2026, 10, 17, 9, 45, tzinfo=UTC),
        kind=MessageKind.ASSISTANT,
        text="answer",
    )
    view = ConversationView((first, last))

    [part] = split_into_parts(view)

    assert (part.index, part.count) == (1, 1)
    assert part.messages == (first, last)
    assert part.estimated_tokens == view.estimated_tokens
    assert (part.first_at, part.last_at) == (first.at, last.at)
