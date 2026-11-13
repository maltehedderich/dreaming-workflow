import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dreaming_workflow.sessions import (
    PART_TOKEN_LIMIT,
    ConversationMessage,
    ConversationView,
    MessageKind,
    SessionFile,
    is_too_large,
    parse_claude_code,
    render,
    split_into_parts,
)
from dreaming_workflow.sessions.view import estimate_tokens
from tests.support.sessions import large_claude_code_session

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


def test_seven_characters_estimate_to_three_tokens() -> None:
    assert estimate_tokens("a" * 7) == 3


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


# A user header is 35 characters and is followed by a newline, so a user
# message with n characters of text renders to 36 + n characters.
USER_OVERHEAD = 36


def user_message(text_length: int, at: datetime = T0) -> ConversationMessage:
    return ConversationMessage(at=at, kind=MessageKind.USER, text="a" * text_length)


def test_single_message_of_exactly_the_part_limit_is_one_unshortened_part() -> None:
    message = user_message(120_000 - USER_OVERHEAD)
    view = ConversationView((message,))
    assert view.estimated_tokens == 40_000

    [part] = split_into_parts(view)

    assert part.messages == (message,)
    assert part.estimated_tokens == 40_000


def test_messages_totalling_the_part_limit_are_one_part() -> None:
    # Two messages and the blank line between them: 2 * 36 + 2 + 119,926 = 120,000.
    half = 119_926 // 2
    view = ConversationView((user_message(half), user_message(half)))
    assert view.estimated_tokens == 40_000

    assert len(split_into_parts(view)) == 1


def test_one_character_over_the_part_limit_splits_between_messages() -> None:
    first = user_message(119_926 // 2)
    second = user_message(
        119_926 // 2 + 1, at=datetime(2026, 10, 17, 9, 50, tzinfo=UTC)
    )

    parts = split_into_parts(ConversationView((first, second)))

    assert [part.messages for part in parts] == [(first,), (second,)]
    assert [(part.index, part.count) for part in parts] == [(1, 2), (2, 2)]
    assert (parts[1].first_at, parts[1].last_at) == (second.at, second.at)


def test_large_session_splits_into_full_parts_in_order(tmp_path: Path) -> None:
    path = large_claude_code_session(
        tmp_path / "large.jsonl", 250_000, start=datetime(2026, 10, 17, tzinfo=UTC)
    )
    session = parse_claude_code(SessionFile.at(path, expected_tool=None))
    assert session is not None
    view = session.view
    # 833 messages of 900 characters each, less the blank line after the last one.
    assert view.estimated_tokens == -(-(833 * 900 - 2) // 3)

    parts = split_into_parts(view)

    # 133 messages make 119,998 characters; a 134th would pass 120,000.
    assert len(parts) == 7
    assert [len(part.messages) for part in parts] == [133] * 6 + [35]
    assert all(part.estimated_tokens <= PART_TOKEN_LIMIT for part in parts)
    assert tuple(m for part in parts for m in part.messages) == view.messages
    assert [(part.index, part.count) for part in parts] == [(i, 7) for i in range(1, 8)]
    for part in parts:
        assert (part.first_at, part.last_at) == (
            part.messages[0].at,
            part.messages[-1].at,
        )
        assert part.estimated_tokens == estimate_tokens(render(part.messages))


MARKER = re.compile(
    r"\n\[… (\d{1,3}(?:,\d{3})*) characters removed by dreaming-workflow …\]\n"
)


def test_oversized_message_keeps_its_start_and_end_around_a_marker() -> None:
    text = "START-" + "m" * (130_000 - 10) + "-END"
    assert len(text) == 130_000
    message = ConversationMessage(
        at=T0, kind=MessageKind.TOOL_RESULT, text=text, is_error=False
    )

    [part] = split_into_parts(ConversationView((message,)))

    [shortened] = part.messages
    assert shortened.kind is MessageKind.TOOL_RESULT
    [head, removed, tail] = MARKER.split(shortened.text)
    assert head.startswith("START-")
    assert tail.endswith("-END")
    assert text.startswith(head)
    assert text.endswith(tail)
    assert len(head) + int(removed.replace(",", "")) + len(tail) == 130_000
    assert part.estimated_tokens <= PART_TOKEN_LIMIT


def test_removed_count_uses_thousands_separators() -> None:
    message = user_message(643_068)

    [part] = split_into_parts(ConversationView((message,)))

    match = MARKER.search(part.messages[0].text)
    assert match is not None
    assert re.fullmatch(r"\d{3},\d{3}", match.group(1))


def test_too_large_means_over_400000_estimated_tokens() -> None:
    at_limit = ConversationView((user_message(1_200_000 - USER_OVERHEAD),))
    over_limit = ConversationView((user_message(1_200_001 - USER_OVERHEAD),))
    assert (at_limit.estimated_tokens, over_limit.estimated_tokens) == (
        400_000,
        400_001,
    )

    assert not is_too_large(at_limit)
    assert is_too_large(over_limit)


def test_view_without_messages_has_no_parts() -> None:
    with pytest.raises(ValueError):
        split_into_parts(ConversationView(()))
