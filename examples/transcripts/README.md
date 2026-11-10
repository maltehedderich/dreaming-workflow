# Example transcripts

Six real session files from Claude Code and Codex, with personal details replaced. Use them to build and test transcript parsing and fact extraction. Don't add raw transcripts here.

The directories mirror where each tool stores sessions, so discovery code can point at them as if they were `~/.claude/projects` and `~/.codex/sessions`:

- `claude-code/projects/<encoded cwd>/<session id>.jsonl`
- `codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<thread id>.jsonl`

## Sessions

### Claude Code

All three ran in `/Users/dev/Projects` on 2026-10-17, in this order.

| File | Time (UTC) | What happens | What a dream should take from it |
| --- | --- | --- | --- |
| `90f95193-….jsonl` | 09:18 | The user asks whether Context7 works. Claude runs `npx ctx7@latest library` and `docs`, and both succeed. | Context7 works, called through `npx ctx7@latest` (v0.8.0). The next session makes this outdated. |
| `40726b6c-….jsonl` | 09:33 | The user pastes Codex output and asks whether `npx ctx7@latest` is a good idea. After installing ctx7 globally, they ask Claude to configure both tools. Claude switches the rules and skills to bare `ctx7`, allows `ctx7 library` and `ctx7 docs` in both tools, and adds Context7 hosts to Codex's sandbox. One tool call fails because the system `python3` has no `tomllib`. | ctx7 is installed globally under fnm Node v26.11.1 and is called as bare `ctx7`, never through `npx`. This replaces the fact from 09:18. |
| `03745422-….jsonl` | 09:40 | The user wants both tools to use uv for Python. Claude writes `~/.claude/rules/uv.md`, appends to `~/.codex/AGENTS.md`, adds `~/.codex/rules/uv.rules`, and registers a `PreToolUse` hook `require-uv.sh`. The new hook blocks Claude's own test command, which shows up as a tool error. | Use uv for Python in Claude Code and Codex; a hook enforces it in Claude Code, and execpolicy rules enforce it in Codex. |

### Codex

| File | What happens | What a dream should take from it |
| --- | --- | --- |
| `2026/11/06/…-eef4a695-….jsonl` | In `mailarkiv`, the user asks to stop Antigravity (`agy`) from asking for read access to `~/.claude` skills. Codex reads the Antigravity docs and adds `read_file(/Users/dev/.claude/skills)` to `~/.gemini/antigravity-cli/settings.json`. The write needs escalation and is auto-reviewed. | Antigravity's global settings grant recursive read access to `~/.claude/skills`. |
| `2026/11/06/…-4cea5169-….jsonl` | The auto-review subthread for the escalated write above. `session_meta.parent_thread_id` points to `eef4a695-…`. It replays the parent's history as one user message and returns a JSON verdict. | Nothing. It isn't a user conversation, and reading it would count the parent's content twice. |
| `2026/11/07/…-0bcd2a68-….jsonl` | In `mailarkiv`, the user asks why `internal/identity` allows passwords up to 4096 bytes (they call it "4 mb"). Codex runs one `rg` search, and the user interrupts the turn (`turn_aborted`) before any answer. | Little or nothing. There is no answer, and the user's "4 mb" is wrong: 4096 bytes is 4 KB. |

## How the files were cleaned

An initial script outside this repository rewrote each source file. A second privacy review removed more context. The remaining records keep their order, field names, value types, and nesting:

- The user's name, email addresses, GitHub handle, and account IDs became `dev`, `dev@example.com`, and `example-user`. Home paths became `/Users/dev`.
- Private repository names became `project-a` to `project-e`. `mailarkiv` and `core-skills` are public and kept their names.
- Every UUID and vendor ID (`msg_`, `toolu_`, `req_`, `call_`, `resp_`, and others) was replaced with a random value. Each original maps to the same replacement in every file, so `parentUuid` chains and `parent_thread_id` links still resolve.
- Thinking signatures and Codex `encrypted_content` became `REDACTED`.
- Codex's `approved_command_prefixes` became a short list of three made-up prefixes, because the real list exposed unrelated projects.
- Timezones became `UTC`, and the macOS per-user temp folder became `/private/var/folders/xx/example/T`.
- Strings longer than 4,000 characters were cut to their first 1,500, followed by a `[... N characters removed from this example ...]` marker. This mostly hits system prompts, skill lists, and long tool output.
- Claude Code `prompt_snapshot` attachments keep their record, but the system prompt and tool definitions were replaced with a placeholder.
- Claude Code `api-request`, `api-request-blob`, and `api-request-shape` records were removed. They hold Claude Code's request cache and repeat the system prompt and the conversation.
- Git commit hashes became forty zeroes, and branch names became `example-branch`, to prevent linking sessions to specific commits or unpublished work.
- Private app descriptions, unrelated local configuration output, and directory inventories became removal markers. These included saved command permissions, local service settings, and duplicated output in the auto-review subthread. Commands and surrounding messages still describe the task, but the removed output cannot serve as evidence that it succeeded.

The initial cleaning included a manual review of strings of 40 characters or more. The second review checked conversation text, nested metadata, configuration output, and embedded copies of tool results. Local pattern scans checked for identifying home paths, email addresses, credential formats, IP addresses, and opaque data. No exposed credential was found; this is not a guarantee that every possible secret format was detected.

These examples still disclose the session dates, tools and versions, and the configuration choices discussed in the conversations. They are cleaned records of real activity, not anonymous synthetic sessions. Before adding another session, review all nested fields and embedded output, replace identifiers consistently across files, remove unrelated configuration, and check that each JSONL record parses and its session links still resolve. Do not upload raw sessions to an external scanner or print sensitive matches in audit logs.

## What these files don't cover

- Claude Code subagent transcripts (`<session>/subagents/*.jsonl`) and sidechain records
- Compaction (`compact_boundary` records and compact summaries)
- Codex sessions with several user turns, or with `compacted` records

Every local session with those features is over 1 MB and full of private project code, so none could be cleaned reliably by substitution alone.

Truncated strings no longer match their original lengths. Don't test code that relies on exact tool-output sizes against these files.
