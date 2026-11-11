# Data model: Dream over Claude Code and Codex sessions

Types the implementation uses, their fields, rules, and state changes. Formats on disk that users or agents see are in the contracts: [memory format](contracts/memory-format.md), [conversation view](contracts/conversation-view.md), [agent tools](contracts/agent-tools.md), [CLI](contracts/cli.md).

Distinct states are enums, not strings or flag combinations. Untrusted input (session JSONL, memory files, model output) is parsed into these types once, at the edge.

## Sessions

### `Tool` (enum)

`claude-code`, `codex`.

### `SessionFile`

A file the run considers.

| Field | Type | Notes |
| --- | --- | --- |
| `path` | absolute `Path` | Key in the dream record |
| `expected_tool` | `Tool \| None` | From the source directory; `None` for files named with `--session` (detected from content) |
| `size` | int (bytes) | From `stat` |
| `mtime_ns` | int | From `stat` |

### `Session`

A parsed session.

| Field | Type | Notes |
| --- | --- | --- |
| `file` | `SessionFile` | |
| `tool` | `Tool` | |
| `session_id` | str | Claude Code `sessionId`; Codex `session_meta.payload.id` |
| `project_dir` | str | Claude Code first `cwd`; Codex `session_meta.payload.cwd`; `unknown` if absent |
| `started_at` | UTC datetime | Earliest record timestamp (Codex: `session_meta.payload.timestamp`) |
| `last_activity_at` | UTC datetime | Latest record timestamp of any type |
| `parent_thread_id` | str \| None | Codex only |
| `view` | `ConversationView` | |

### `ConversationMessage`

| Field | Type | Notes |
| --- | --- | --- |
| `at` | UTC datetime | From the record; rendered to the minute |
| `kind` | enum `user`, `assistant`, `tool-call`, `tool-result`, `interrupted` | |
| `tool_name` | str \| None | For `tool-call` |
| `is_error` | bool | For `tool-result` only |
| `text` | str | Rendered body |

### `ConversationView`

Ordered list of `ConversationMessage` plus `estimated_tokens` (⌈characters of the rendered view ÷ 3⌉). Rendering and inclusion rules: [conversation view contract](contracts/conversation-view.md).

### `Part`

| Field | Type | Notes |
| --- | --- | --- |
| `index` | int, 1-based | |
| `count` | int | Parts in the session |
| `messages` | list of `ConversationMessage` | Consecutive; a message over the part limit is shortened with a marker |
| `estimated_tokens` | int | ≤ 40,000 |
| `first_at`, `last_at` | UTC datetime | Used to check the times in new citations |

**Rules**: A view of at most 40,000 estimated tokens is one part. A larger view is split between messages, greedily, in order. A view over 400,000 estimated tokens isn't split; the session is skipped as too large.

### `SkipReason` (enum)

| Value | When |
| --- | --- |
| `unrecognized` | Not a Claude Code or Codex session |
| `subthread` | Codex session with `parent_thread_id` |
| `subagent` | Claude Code file under a `subagents/` directory |
| `no-conversation` | Parsed, but the view has no messages |
| `outside-window` | Last activity before the window start |
| `active` | Last activity less than one hour before the run started |
| `already-analyzed` | The record says `analyzed` and the content is unchanged |
| `too-large` | View over 400,000 estimated tokens |

### `SelectionDecision`

Either `Selected(session, parts)` or `Skipped(file, reason, detail)`. `detail` holds the estimated size for `too-large` and is empty otherwise. Preview and run both produce a list of these from the same function.

## Memory

### `Slug`

A string matching `^[a-z0-9]+(?:-[a-z0-9]+)*$`, at most 80 characters. The file is `<slug>.md` at the top of the memory directory. `_index.md` is not a slug and isn't reachable through slug-based tools.

### `MemoryFile`

| Field | Type | Notes |
| --- | --- | --- |
| `slug` | `Slug` | Equals frontmatter `name` |
| `description` | str | Non-empty |
| `metadata` | mapping \| None | Free-form, optional |
| `body` | str | Markdown after the frontmatter |
| `version` | str | First 12 hex digits of the SHA-256 of the file's bytes; used by `replace_file` |
| `citations` | set of `Citation` | Parsed from the body |

### `Stub`

A file whose whole content is `MOVED TO [[slug]]` plus an optional trailing newline. No frontmatter, no index entry.

### `Citation`

| Field | Type |
| --- | --- |
| `tool` | `Tool` |
| `session_id` | str |
| `project_dir` | str |
| `at` | UTC datetime, minute precision |

Two citations are equal when all four fields are equal. Syntax: [memory format contract](contracts/memory-format.md#facts-and-citations).

### `Index`

Parsed `_index.md`: an ordered list of `Domain`.

| Type | Fields |
| --- | --- |
| `Domain` | `name`, `entries` (list of `IndexEntry`), `subdomains` (ordered list of `Subdomain`) |
| `Subdomain` | `name`, `entries` |
| `IndexEntry` | `slug`, `sentence` |

**Rules**: Domain names are unique, compared case-insensitively after collapsing whitespace; the same holds for subdomain names within a domain. A slug appears at most once. A heading left without entries is removed. Adding an entry under a name that matches an existing heading case-insensitively reuses that heading's spelling.

### `FormatViolation`

| Field | Type |
| --- | --- |
| `file` | str (file name, or `_index.md`) |
| `rule` | `FormatRule` (enum; values in the [memory format contract](contracts/memory-format.md#format-check-rules)) |

## Dream record

Stored at `<state>/record.json` (location in [research R12](research.md#r12-run-state-record-lock-and-pre-run-copies)). Written atomically. Only the `record` module reads or writes it.

```json
{
  "version": 1,
  "memory_dir": "/Users/dev/memory",
  "sessions": {
    "/Users/dev/.claude/projects/-Users-dev-Projects/90f95193-2c91-4a42-a506-930d4c964c45.jsonl": {
      "tool": "claude-code",
      "session_id": "90f95193-2c91-4a42-a506-930d4c964c45",
      "size": 54250,
      "mtime_ns": 1792230000000000000,
      "sha256": "…",
      "status": "analyzed",
      "failure": null,
      "run_id": "20261110T213800Z"
    }
  },
  "waiting_files": ["ctx7-setup", "uv-python"]
}
```

### `SessionRecord`

| Field | Type | Notes |
| --- | --- | --- |
| `tool`, `session_id` | | For people reading the file |
| `size`, `mtime_ns`, `sha256` | | Content at the time of analysis |
| `status` | enum `analyzed`, `failed` | |
| `failure` | `FailureReason` \| null | Set when `failed` |
| `run_id` | str | Run that wrote this entry |

**State changes**:

```
(no entry) ──analysis succeeds──▶ analyzed
(no entry) ──analysis fails─────▶ failed
analyzed ──content changes; next run selects it──▶ analyzed | failed
failed ──next run selects it again──────────────▶ analyzed | failed
```

A session interrupted mid-run gets no entry, or keeps its previous one, so the next run selects it again. A failed part marks the whole session `failed`; facts from earlier parts stay in memory.

### Waiting files

A set of slugs.

```
(not waiting) ──an analysis creates or changes the file──▶ waiting
waiting ──an organizer pass that received it succeeds──▶ (not waiting)
```

The set is written to the record right after each analysis write. Files the organizer changes don't become waiting. A slug whose file no longer exists is dropped when the organizer's input is built.

## Run

### `FailureReason` (enum)

| Value | Cause |
| --- | --- |
| `rate-limited` | 429 after 3 retries |
| `overloaded` | 529 after 3 retries |
| `timeout` | Request timed out after 3 retries |
| `connection-error` | Network failure after 3 retries |
| `api-error` | Any other API status; detail holds the status code and request ID |
| `authentication-failed` | 401 or 403; stops the run's remaining requests |
| `refused` | `stop_reason: "refusal"` (ADK's `finish_reason` `SAFETY`) |
| `max-tokens` | `stop_reason: "max_tokens"` or `"model_context_window_exceeded"` (ADK's `finish_reason` `MAX_TOKENS`) |
| `context-limit` | Next request would pass 95,000 input tokens |
| `turn-limit` | ADK `max_llm_calls` reached |
| `spending-limit-reached` | Spending limit reached before or during the analysis |
| `invalid-model-output` | Reply `ClaudeModel` rejects: `redacted_thinking`, or a finish reason other than stop, `MAX_TOKENS`, or `SAFETY` |
| `internal-error` | Unexpected exception; detail holds the exception class name only |

### `AnalysisResult`

`session`, `status` (`analyzed` or `failed`), `failure` (`FailureReason | None`), `parts_run` (int), `slugs_written` (set).

### `OrganizerResult`

`ran` (bool), `status` (`succeeded`, `failed`, or `not-run`), `failure`, `received` (list of slugs), `slugs_read` (set, kept for tests; never printed).

### `UsageLedger`

Shared by every request in a run.

| Field | Type |
| --- | --- |
| `input_tokens`, `cache_write_tokens`, `cache_read_tokens`, `output_tokens` | int |
| `cost_usd` | `Decimal` |
| `limit_usd` | `Decimal` |
| `limit_reached` | bool |
| `largest_prompt_tokens` | int (for SC-011 checks in evals) |

**Rules**: Before each analysis request, if `cost_usd ≥ limit_usd`, set `limit_reached` and raise `SpendingLimitReached`. Organizer requests skip this check. After each response, add its usage and cost (formula in [research R4](research.md#r4-model-prices-and-cost)).

### `ContextGuard`

One per agent invocation: `last_prompt_tokens` (from the previous response's usage), `pending_estimate` (estimated tokens added since), `read_budget` 75,000, `ceiling` 95,000. Tools ask it before returning content; `ClaudeModel` asks it before sending.

### `RunOutcome` (enum)

`success` (exit 0), `completed-with-failures` (exit 1), `not-started` (exit 2). Completed with failures means at least one failed analysis, a failed organizer pass, or a format violation.

### `Report`

Built from the run's own records, never from logs.

| Field | Source |
| --- | --- |
| `run_id` | Start time |
| `found`, `selected`, `skipped_by_reason`, `analyzed`, `analyzed_in_parts`, `failed` (with reasons) | Selection decisions and analysis results |
| `organizer` | `OrganizerResult.status` |
| `waiting_files` | Record after the run |
| `index_entries`, `domains`, `subdomains` | Index parsed at the end |
| `files_created`, `files_changed`, `files_retired` | Content hashes at start versus end |
| `conflicts_added` | `CONFLICT:` lines present at the end but not at the start |
| `violations` | Format check at the end |
| `usage` | `UsageLedger` |
| `backup_path` | Pre-run copy, or none if the run didn't write |

**Invariants** (checked by unit tests): `found = selected + Σ skipped_by_reason`; `selected = analyzed + failed`.
