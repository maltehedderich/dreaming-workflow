# Conversation view contract

What an analysis sees of a session, how each tool's JSONL maps to it, and how the view is rendered and split. This contract is the boundary with two external formats that change without notice, so the parsers are tested against the six files in [`examples/transcripts/`](../../../examples/transcripts/README.md) and synthetic files built from them.

## Reading rules for both tools

- Read line by line. A line that isn't valid JSON, including a partial last line, is skipped.
- Record timestamps are parsed as UTC. A record without a timestamp takes none and doesn't affect activity times.
- Last recorded activity is the latest timestamp of any record, including records the view leaves out.
- Reasoning is never included: Claude Code `thinking` blocks and Codex `reasoning` items are dropped.
- Images become the text `[image]`.

## Claude Code

Files: `<claude-code-dir>/<encoded cwd>/<session id>.jsonl`. Files under any `subagents/` directory are skipped as subagent transcripts.

A file is recognized as Claude Code when at least one parsed record has a `sessionId` string and a `type` of `user` or `assistant`.

| Record | In the view as |
| --- | --- |
| `type: "user"`, `message.content` is a string | `user`, unless excluded below |
| `type: "user"`, content block `text` | `user`, unless excluded below |
| `type: "user"`, content block `tool_result` | `tool-result`; `is_error` from the block; text from its string or text blocks |
| `type: "assistant"`, content block `text` | `assistant` |
| `type: "assistant"`, content block `tool_use` | `tool-call`, `tool_name` from `name`, text is `input` as compact JSON |

Excluded:

- records with `isMeta: true`, `isSidechain: true`, or `isCompactSummary: true`;
- user text from records whose `origin.kind` is present and isn't `human`;
- user text that, after trimming, starts with a harness tag: `<command-name>`, `<command-message>`, `<command-args>`, `<local-command-stdout>`, `<local-command-stderr>`, `<local-command-caveat>`, `<bash-input>`, `<bash-stdout>`, `<bash-stderr>`, `<system-reminder>`, `<task-notification>`;
- every other record type: `attachment` (instruction files, skill and tool listings, prompt snapshots, environment, date), `system`, `mode`, `permission-mode`, `atis-latch`, `last-prompt`, `ai-title`, `file-history-snapshot`, `file-history-delta`, `cost-state`, and any type not listed above.

Metadata: `session_id` from `sessionId`; `project_dir` from the first `cwd`.

## Codex

Files: `<codex-dir>/YYYY/MM/DD/rollout-<timestamp>-<thread id>.jsonl`. Recognized when the first parsed record has `type: "session_meta"`.

A session whose `session_meta.payload.parent_thread_id` is set is skipped as a subthread.

| Record | In the view as |
| --- | --- |
| `event_msg`, `payload.type: "item_completed"`, `item.type: "UserMessage"` | `user`, text blocks joined |
| `event_msg`, `payload.type: "user_message"` (older files; used only when the file has no `UserMessage` items) | `user` |
| `response_item`, `payload.type: "message"`, `role: "assistant"` | `assistant`, `output_text` blocks joined |
| `response_item`, `payload.type` `function_call`, `custom_tool_call`, `local_shell_call` | `tool-call`, `tool_name` from `name` (or `shell`), text from `arguments`, `input`, or the command |
| `response_item`, `payload.type` `function_call_output`, `custom_tool_call_output`, `local_shell_call_output` | `tool-result`, text from `output` (string, or text blocks joined) |
| `event_msg`, `payload.type: "turn_aborted"` | `interrupted`, text `turn interrupted (<reason>)` |

Excluded: `response_item` messages with role `user` or `developer` (they carry `AGENTS.md`, `<environment_context>`, permission and skill instructions), `reasoning`, `additional_tools`, `world_state`, `turn_context`, `token_usage_record`, other `event_msg` types, `compacted`, and anything not listed.

Metadata: `session_id` from `session_meta.payload.id`; `project_dir` from `session_meta.payload.cwd`; `started_at` from `session_meta.payload.timestamp`.

## Rendering

Each message is a header line and its text:

```text
--- 2026-10-17 09:40 UTC | user ---
I just installed uv and want codex / claude use uv for python, should I add a skill or how would you do it?

--- 2026-10-17 09:41 UTC | tool call: Bash ---
{"command":"ls ~/.claude/rules/ ~/.codex/"}

--- 2026-10-17 09:41 UTC | tool result (error) ---
PreToolUse:Bash hook error: …
```

Header kinds: `user`, `assistant`, `tool call: <name>`, `tool result`, `tool result (error)`, `interrupted`. Times are rounded down to the minute; analyses cite these times.

## Size, parts, and shortening

- Estimated tokens = ⌈characters ÷ 3⌉ of the rendered text ([research R5](../research.md#r5-token-estimate)).
- View over 400,000 estimated tokens: skipped as `too-large`, with its estimate.
- View of at most 40,000: one part.
- Larger: split between messages into consecutive parts of at most 40,000 estimated tokens each, filling each part in order before starting the next.
- A single message over 40,000 minus its header keeps its start and end, with this marker in the middle:

  ```text
  [… 523,104 characters removed by dreaming-workflow …]
  ```

Every analysis receives its part number and the total, for example "part 2 of 7".
