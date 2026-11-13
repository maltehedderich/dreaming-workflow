"""ClaudeModel on ADK's own Claude API model, run through a real ADK Runner."""

import asyncio

import pytest

from dreaming_workflow.agents import AgentFailure, ClaudeModel, FailureReason
from dreaming_workflow.agents.runner import run_agent
from dreaming_workflow.agents.tools import ToolFunction, refused
from tests.support.fake_messages_api import (
    FakeMessagesApi,
    JsonObject,
    MessageReply,
    redacted_thinking_block,
    text_block,
    thinking_block,
    tool_use_block,
)

INSTRUCTION = "You take notes when asked."
TOOL_USE_ID = "toolu_01ExampleToolUse"
SIGNATURE = "c2lnbmF0dXJlLWZyb20tdGhlLWFwaQ=="
EPHEMERAL = {"type": "ephemeral"}

type ToolResult = dict[str, object]


def note_ok(text: str) -> ToolResult:
    """Store a note.

    Args:
      text: The note.
    """
    return {"status": "ok"}


def note_refused(text: str) -> ToolResult:
    """Store a note.

    Args:
      text: The note.
    """
    return refused("Notes are full.")


def run(api: FakeMessagesApi, tool: ToolFunction) -> None:
    asyncio.run(
        run_agent(
            name="note_taker",
            model=ClaudeModel(client=api.client()),
            instruction=INSTRUCTION,
            tools=[tool],
            message="Note: hello.",
            max_llm_calls=5,
        )
    )


def tool_loop(first: list[JsonObject], tool_name: str = "note_ok") -> FakeMessagesApi:
    """First answer: `first` and a tool call. Second answer: end of turn."""

    def respond(body: JsonObject) -> MessageReply:
        if len(api.requests) == 1:
            return MessageReply(
                content=[
                    *first,
                    tool_use_block(TOOL_USE_ID, tool_name, {"text": "hello"}),
                ],
                stop_reason="tool_use",
            )
        return MessageReply(content=[text_block("Done.")])

    api = FakeMessagesApi(respond)
    return api


@pytest.mark.parametrize("thinking_text", ["", "The user wants a note; call the tool."])
def test_second_request_carries_thinking_and_tool_use_unchanged(
    thinking_text: str,
) -> None:
    thinking = thinking_block(thinking_text, SIGNATURE)
    api = tool_loop([thinking])

    run(api, note_ok)

    assert len(api.requests) == 2
    assert api.requests[1]["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Note: hello."}]},
        {
            "role": "assistant",
            "content": [
                thinking,
                tool_use_block(TOOL_USE_ID, "note_ok", {"text": "hello"}),
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": TOOL_USE_ID,
                    "content": '{"status": "ok"}',
                    "is_error": False,
                    "cache_control": EPHEMERAL,
                }
            ],
        },
    ]


def test_request_settings() -> None:
    api = tool_loop([thinking_block("", SIGNATURE)])

    run(api, note_ok)

    for body in api.requests:
        assert body["model"] == "claude-sonnet-5-5"
        assert body["max_tokens"] == 16000
        assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
        assert body["output_config"] == {"effort": "medium"}
        assert body["tool_choice"] == {"type": "auto"}
        assert "temperature" not in body
        assert "top_p" not in body
        assert "top_k" not in body
        # ADK appends the agent's name to the instruction.
        assert body["system"] == [
            {
                "type": "text",
                "text": f'{INSTRUCTION}\n\nYou are an agent. Your internal name is "note_taker".',
                "cache_control": EPHEMERAL,
            }
        ]
        assert body["tools"] == [
            {
                "name": "note_ok",
                "description": "Store a note.\n\nArgs:\n  text: The note.",
                "input_schema": {
                    "type": "object",
                    "title": "note_okParams",
                    "properties": {"text": {"type": "string", "title": "Text"}},
                    "required": ["text"],
                },
                "cache_control": EPHEMERAL,
            }
        ]


def test_first_request_marks_the_end_of_the_conversation_for_caching() -> None:
    api = tool_loop([])

    run(api, note_ok)

    # The second request's mark sits on its tool result, as the round-trip test shows.
    assert api.requests[0]["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Note: hello.", "cache_control": EPHEMERAL}
            ],
        }
    ]


def test_refused_tool_result_is_an_error() -> None:
    api = tool_loop([], tool_name="note_refused")

    run(api, note_refused)

    assert api.requests[1]["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Note: hello."}]},
        {
            "role": "assistant",
            "content": [tool_use_block(TOOL_USE_ID, "note_refused", {"text": "hello"})],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": TOOL_USE_ID,
                    "content": (
                        '{"status": "refused", "reason": "Notes are full.", "is_error": true}'
                    ),
                    "is_error": True,
                    "cache_control": EPHEMERAL,
                }
            ],
        },
    ]


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (
            MessageReply(content=[text_block("cut off")], stop_reason="max_tokens"),
            "max-tokens",
        ),
        (
            MessageReply(
                content=[tool_use_block(TOOL_USE_ID, "note_ok", {"text": "hel"})],
                stop_reason="max_tokens",
            ),
            "max-tokens",
        ),
        (MessageReply(content=[], stop_reason="refusal"), "refused"),
        (
            MessageReply(content=[redacted_thinking_block("opaque"), text_block("x")]),
            "invalid-model-output",
        ),
    ],
)
def test_unusable_responses_fail_with_their_reason(
    reply: MessageReply, reason: str
) -> None:
    api = FakeMessagesApi(lambda body: reply)

    with pytest.raises(AgentFailure) as raised:
        run(api, note_ok)

    assert raised.value.failure.reason is FailureReason(reason)
    assert len(api.requests) == 1
