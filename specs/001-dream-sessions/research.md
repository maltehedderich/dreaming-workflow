# Research: Dream over Claude Code and Codex sessions

Decisions for the [plan](plan.md). Each entry gives the decision, why, and what was rejected. Library facts come from current docs: Google ADK through Context7 (`/websites/adk_dev`, `/websites/adk_dev_api-reference_python`), the Claude API reference bundled with Claude Code (cached 2026-11-03), PyPI metadata on 2026-11-10, and the source of the `anthropic` 2.8.0 and `google-adk` 2.14.0 wheels.

## R1. Runtime and project tooling

**Decision**: Python 3.15, pinned with mise together with uv 0.13.7. Runtime dependencies: `google-adk` 2.14.0, `anthropic` 2.8.0, `pyyaml` 6.0.3. Dev dependencies: `ruff` 0.17.4, `ty` 0.0.101, `pytest` 9.2.0, `types-pyyaml`. Versions are pinned exactly in `pyproject.toml` and locked in `uv.lock`. Before the first commit, `uvx pip-audit` runs against the lock file, and the result goes into the ADR.

**Rationale**: ADK 2.14 needs Python 3.11 or later, and `anthropic` 2.8 needs 3.10 or later. On 2026-11-11 the full resolved tree, dev tools included, installed on CPython 3.15.2, and ADK and the SDK imported with deprecation warnings raised as errors. ADK 2.14 and `google-genai` list 3.15 as supported; `anthropic` 2.8 lists up to 3.14 but ships a pure-Python wheel. Every package has a 3.15 wheel except PyYAML 6.0.3, the latest release: it builds from its sdist in seconds and uses its pure-Python parser, which is fast enough for frontmatter. That build fetches PyYAML's build requirements at install time, outside `uv.lock` and the audit; uv caches the result. In return, 3.15 gets security fixes until October 2031, a year longer than 3.14, and turns on UTF-8 mode by default, so reading transcripts doesn't depend on the system locale. `pyyaml` already comes in through ADK; declaring it directly costs no new code and avoids a hand-written frontmatter parser. `argparse` (standard library) covers the CLI.

**Alternatives considered**: Python 3.14 (wheels for every package, but security support ends a year earlier). `click` for the CLI (ADK ships it, but argparse handles one command with a handful of options). `mypy` or `pyright` instead of ty (see [R16](#r16-checks-and-ci)).

## R2. Agent runtime: ADK without a lead agent

**Decision**: Each part of a session runs as one ADK invocation: a fresh `LlmAgent` with the analyzer instruction and tools, run by a `Runner` with an `InMemorySessionService`. The organizer is one more invocation with its own agent. Plain `asyncio` code runs the fixed sequence: groups of at most 20 sessions through `asyncio.gather`, parts of one session in order, then the organizer. `RunConfig(max_llm_calls=…)` caps each invocation (40 for a part, 80 for the organizer). Sync tool functions run on the event loop, ADK's default when `tool_thread_pool_config` is unset.

**Rationale**: The spec fixes the sequence (no lead agent), and the tool builds the report from its own records. Plain asyncio keeps per-session failure isolation, the spending check, and counting in ordinary code. ADK 2.0 moved agents onto a graph engine but still runs a single `LlmAgent` under `Runner`; that is the smallest ADK surface that gives us tool schemas from Python functions and the tool-call loop.

**Alternatives considered**: ADK `ParallelAgent` or a 2.0 workflow graph for the groups. Both share one ADK session between branches and make per-session failure, retries, and spending checks harder to follow. A hand-written tool loop on the Anthropic SDK alone would drop ADK, which the README makes the point of this project.

## R3. Calling Claude from ADK

**Decision**: ADK's own `google.adk.models.anthropic_llm.AnthropicLlm` calls the Claude API. It converts ADK's `google.genai` types into a Messages API request, sends it with `anthropic.AsyncAnthropic.messages.create` (non-streaming), and converts the reply back. A thin subclass, `ClaudeModel` in `agents/claude_model.py`, adds this tool's settings, one conversion fix, and failure mapping. It is the only code that touches ADK's model internals.

What `AnthropicLlm` does, read from the `google-adk` 2.14.0 source:

| ADK (`google.genai.types`) | Messages API |
| --- | --- |
| `config.system_instruction` | `system`, one text block; with a cache config, it carries a `cache_control` breakpoint |
| `config.tools[].function_declarations[]` | `tools[]` with `input_schema` from `parameters_json_schema`, type names lowercased; with a cache config, the last tool carries a breakpoint |
| `Part(thought=True, text=…, thought_signature=…)` | assistant `thinking` block, signature unchanged |
| `Part(thought=True, thought_signature=…)` without text | assistant `redacted_thinking` block with the signature as its data (fixed below) |
| `Part(function_call=FunctionCall(id, name, args))` | assistant `tool_use` block with the same `id` |
| `Part(function_response=FunctionResponse(id, name, response))` | user `tool_result`. Its content is the response's `content` string if it has one, otherwise the whole response as JSON with non-ASCII characters escaped. `is_error` is set when the response has `is_error` or `isError` |
| end of the conversation | with a cache config, a breakpoint on the last block that isn't thinking |

Replies map back: `thinking` → thought part with the signature as bytes and the text kept even when empty; `redacted_thinking` → thought part without text; `tool_use` → `FunctionCall` with the API's `id`; `text` → text part. Stop reasons become `finish_reason`: `end_turn`, `tool_use`, `stop_sequence`, and `pause_turn` → `STOP`; `max_tokens` and `model_context_window_exceeded` → `MAX_TOKENS`, and a reply cut off inside a tool call returns no calls; `refusal` → `SAFETY`.

Settings, in three places:

- On the model: `model="claude-haiku-5-5"`, `max_tokens=16000`, and the client from `create_client()`, `AsyncAnthropic(timeout=anthropic.Timeout(300.0, connect=10.0), max_retries=3)`. ADK uses a client it is given as is.
- On each agent: `generate_content_config=AnthropicGenerateContentConfig(effort="medium", thinking_config=ThinkingConfig(thinking_budget=-1))`. ADK sends `thinking={"type": "adaptive", "display": "summarized"}` and `output_config={"effort": "medium"}`, and no sampling parameters.
- On each app: `context_cache_config=ContextCacheConfig()`, which turns on the three breakpoints above, each `{"type": "ephemeral"}`. ADK asks for Claude's 1-hour cache only when the TTL is at least an hour; the default is 30 minutes.

`run_agent()` in `agents/runner.py` builds every agent and app this way, so analyses, the organizer, and the contract test share the settings.

`ClaudeModel` changes two things:

1. **Thinking blocks with empty text go back as thinking blocks.** Claude Haiku 5.5 omits thinking text unless the request asks for summaries, and the API needs every thinking block back unchanged with the tool results. ADK reads a thought part with empty text as redacted thinking and sends `{"type": "redacted_thinking", "data": <signature>}` in its place. `ClaudeModel` overrides ADK's private `_build_anthropic_kwargs`, the one method that sees the converted messages, and turns each such block back into `{"type": "thinking", "thinking": "", "signature": …}`. That is safe because `ClaudeModel` fails any reply that holds real redacted thinking, which Claude Haiku 5.5 doesn't send. Summarized display makes empty text rare; the override covers the rest.
2. **Unusable replies fail the part.** `STOP` is normal. `MAX_TOKENS` raises `AgentFailure` with `max-tokens`. `SAFETY` raises `refused`; Claude Haiku 5.5 has no server-side fallback. Any other finish reason, or a thought part without text (redacted thinking), raises `invalid-model-output` rather than dropping the block silently.

The tools adapt to ADK's tool results ([agent tools contract](contracts/agent-tools.md)): refusals carry `is_error: true`, and no result has a `content` field, because ADK would send that string alone and drop the rest, such as `read_file`'s `version`.

**Rationale**: ADK 2.14 ships two classes on the `anthropic` SDK. `AnthropicLlm` calls the Claude API directly; its subclass `Claude` goes through Vertex AI. An earlier draft of this plan assumed ADK reached Claude only through Vertex AI and wrote its own `BaseLlm` subclass with its own conversion. `AnthropicLlm` makes that unnecessary: ADK maintains the conversion, including tool IDs, thinking signatures, cache breakpoints, and usage. Given our client, it keeps the SDK's credential chain: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_PROFILE`, workload identity, then the active `ant auth login` profile. Claude Haiku 5.5 thinks by default and needs thinking blocks passed back unchanged with tool results. ADK keeps thought parts and their signatures in session history; a contract test runs the real ADK `Runner` against a fake Messages API and asserts the second request carries the first reply's thinking block and signature, with text and with empty text.

Caching: the system prompt and tool definitions are identical for every analysis, so their breakpoints let parallel analyses share them, and the breakpoint at the end of the conversation covers each loop's growing history. Claude Haiku 5.5 caches prefixes of 512 tokens or more; cache reads cost 0.1× the input rate and 5-minute writes 1.25×.

Retries: the SDK retries 408, 409, 429, 5xx (529 is the overload response), timeouts, and connection errors with backoff, honoring `retry-after`. `max_retries=3` gives the spec's "up to 3 times" for rate limits, overloads, and timeouts. The other retried classes are a superset that costs nothing extra: a failed request isn't billed, and the Messages API has no side effects to duplicate. ADK re-raises the SDK's `RateLimitError` as a subclass with a longer message, so checks with `isinstance` still match.

Credentials preflight: constructing `AsyncAnthropic()` runs the SDK's credential chain locally without a network call. If the client ends up with `api_key`, `auth_token`, and `credentials` all `None`, the run stops with "not started" and names `ANTHROPIC_API_KEY` and `ant auth login`. A `CredentialsError` at construction (a broken profile) stops the run the same way, with the error class in the message. An `AuthenticationError` or `PermissionDeniedError` during the run stops all further requests; remaining sessions fail with `authentication-failed`. ADK runs the same credential check only when it builds the client itself, so `create_client()` keeps its own.

Accepted cost: ADK escapes non-ASCII characters in tool results (`ü` becomes `\u00fc`), so memory text in languages other than English costs a few more tokens than it would unescaped.

**Alternatives considered**: Our own `BaseLlm` subclass with its own conversion (the earlier draft): more code to keep in step with ADK and the SDK, where ADK's class needs one fix. `LiteLlm` (adds the `litellm` dependency and doesn't resolve `ant auth login` profiles). Leaving `thinking` unset to get the model's default, omitted display (it would depend on a model default, and ADK has no way to request adaptive thinking with omitted display). Streaming responses (not needed: 16,000 output tokens at Haiku speed fits the 300-second timeout, and the SDK only requires streaming for much larger `max_tokens`). Disabling thinking (`{"type": "disabled"}` is accepted at effort `high` or below, but Anthropic's migration notes recommend lowering effort instead, and the round trip is testable).

## R4. Model, prices, and cost

**Decision**: Claude Haiku 5.5 (`claude-haiku-5-5`) for analyses and the organizer, as the spec assumes. `ClaudeModel` computes each response's cost from the usage ADK reports on the `LlmResponse`: `usage_metadata.prompt_token_count` (input, cache writes, and cache reads together), `usage_metadata.cached_content_token_count` (cache reads), `cache_creation_token_count` (cache writes), and output as `candidates_token_count` plus `thoughts_token_count`. In the API's terms:

```
prompt   = input_tokens + cache_creation_input_tokens + cache_read_input_tokens
rate     = $0.10 / $0.50 per million input / output tokens if prompt ≤ 100,000, else $0.50 / $2.50
cost     = input_tokens × in + cache_creation_input_tokens × in × 1.25
         + cache_read_input_tokens × in × 0.1 + output_tokens × out
```

Thinking tokens are billed as output and are included in `output_tokens`. Prices live in one table in `agents/budget.py` with the date they were checked. Before release, the implementer checks them against Anthropic's live pricing page.

**Rationale**: The spending limit (FR-033) is only as good as the price table. Using the API's reported counts makes the cost exact at list price.

**Alternatives considered**: Asking the API for cost (no such field). Counting tokens with `messages.count_tokens` before each request (an extra request per turn, and the spec requires the preview to send nothing).

## R5. Token estimate

**Decision**: Estimated tokens = ⌈characters ÷ 3⌉ of the rendered text. Part size stays at 40,000 estimated tokens and the skip threshold at 400,000, as the spec sets them.

**Rationale**: The spec's four-characters-per-token figure came from a measurement on the user's machine. Anthropic's migration notes say Claude Haiku 5.5's tokenizer counts the same text as about 30% more tokens than Claude Haiku 4.5's. Three characters per token keeps the estimate on the high side, so a 40,000-token part stays well below the 100,000-token price step once the instructions, memory reads, and replies are added. The cost is about a third more parts than four characters per token would give. On the user's 61 sessions this moves the largest view from about 241,000 to about 321,000 estimated tokens, still under the 400,000 skip threshold. The eval measures the real ratio from the first request of each part (`usage` against the estimate) and prints it, so the divisor can be corrected with data.

**Alternatives considered**: Four characters per token with a smaller part size (same effect, but the preview's numbers would understate cost). A real tokenizer (none is published for Claude; `count_tokens` is a network call).

## R6. Staying under 100,000 input tokens

**Decision**: Three layers.

1. **Part size** (R5) bounds the session text in each request.
2. **Read budget in the tools**: each agent invocation has a `ContextGuard` that knows the last request's real prompt size (from `usage`) plus the estimate of everything added since. `read_index`, `read_file`, and `search_memory` refuse a result that would take the projected prompt past 75,000 tokens and tell the agent how much room is left and to finish with what it has.
3. **Hard ceiling in `ClaudeModel`**: before sending, `ClaudeModel` projects the prompt size the same way. Above 95,000 it doesn't send, and the part (or organizer pass) fails with `context-limit`.

The organizer receives waiting and format-violating files only up to 40,000 estimated tokens of content, violating files first, then waiting files oldest first, and always at least one file. Files beyond that keep waiting for the next run, and the report counts them (FR-018 allows this: a file stops waiting only when an organizer pass that received it succeeds).

**Rationale**: Every turn of a tool loop resends the whole history, so reading files is what grows a request. Refusing a read is recoverable; sending a 101,000-token request costs five times as much and breaks SC-011.

**Alternatives considered**: Server-side context editing or compaction (beta features that change cache behavior and don't give a hard bound). Splitting the organizer into several passes per run (the spec asks for one pass; the receive budget gets the same effect across runs).

## R7. Reading sessions

**Decision**: Two parsers produce one `ConversationView` type (see [conversation view contract](contracts/conversation-view.md)). Each reads the file line by line, skips lines that aren't valid JSON, and keeps only conversation records:

- **Claude Code**: `user` records that aren't `isMeta`, `isSidechain`, or `isCompactSummary`; user text from records whose `origin.kind` is `human` or absent, minus harness wrappers (`<command-name>`, `<local-command-stdout>`, `<system-reminder>`, and the others listed in the contract); `tool_result` blocks; `assistant` records' `text` and `tool_use` blocks. Everything else (attachments with instruction files, skill listings, system prompts, mode and title records, cost and file-history records, `thinking` blocks) is left out.
- **Codex**: user text from `event_msg` `item_completed` items of type `UserMessage` (older files: `event_msg` `user_message`), never from `response_item` user messages, which carry `AGENTS.md` and `<environment_context>`; assistant text from `response_item` `message` with role `assistant`; tool calls and outputs from `function_call`, `custom_tool_call`, `local_shell_call`, and their outputs; a marker message for `turn_aborted`. Developer messages, reasoning, `world_state`, `turn_context`, and token counts are left out.

A Codex file whose `session_meta` has `parent_thread_id` is skipped as a subthread. A Claude Code file under a `subagents/` directory is skipped as a subagent transcript.

**Rationale**: The examples show both tools inject instruction files as user-role content. Codex's `UserMessage` items and Claude Code's `origin.kind: "human"` mark what the user typed; the examples confirm both. Compaction records and multi-turn Codex sessions aren't covered by the examples; the parsers handle them as described in the contract, without tests on real files (the spec lists this as out of scope).

**Alternatives considered**: Filtering Codex `response_item` user messages by text prefix (fragile; the `UserMessage` items already separate typed input). Including model reasoning (Codex stores it encrypted; Claude Haiku's job is the outcome, and the spec leaves reasoning out).

## R8. Finding and selecting sessions

**Decision**: A session file's key in the dream record is its absolute path. Selection order for each file:

1. Path rules: under `subagents/` → skip.
2. Prefilter: files whose modification time is before the window start aren't counted as found (activity can't be newer than the last write). Files named with `--session` are always found.
3. Record check: if the record says `analyzed` and size and modification time match, skip as already analyzed without parsing. If they differ, hash the file; an unchanged SHA-256 also counts as already analyzed.
4. Parse: unrecognized format, subthread, no conversation, last activity outside the window, last activity less than one hour ago (active), view over 400,000 estimated tokens (too large).
5. Otherwise selected. Selected sessions are ordered by last recorded activity, oldest first.

Preview and run call the same function, so the preview lists exactly what the run would select (SC-009).

**Rationale**: A repeat run with nothing new only stats files and reads the record, which keeps it far below SC-008's 10 seconds. Keying by path handles resumed sessions: Claude Code and Codex append to the same file, so the size changes and the session is selected again.

**Alternatives considered**: Keying by session ID (two files can carry the same ID after a resume into a new file; the path is unambiguous). Hashing every file on every run (correct but slower, and the size and time check already catches appends).

## R9. Writing memory safely

**Decision**: Agents change memory only through tool functions backed by one `MemoryStore` (see [agent tools contract](contracts/agent-tools.md)). Every write:

- takes a slug, never a path; slugs match `^[a-z0-9]+(?:-[a-z0-9]+)*$` (at most 80 characters), and the store refuses a target that is a symbolic link or resolves outside the memory directory;
- runs the credential scan (R11) on the new text and refuses on a match, telling the agent to refer to the credential by name;
- validates frontmatter (`name` equals the slug, non-empty `description`) on the result;
- checks citations (R10);
- writes atomically: temporary file in the memory directory, `fsync`, `os.replace`, mode 0600;
- holds a per-slug lock across read-modify-write.

`edit_file` and `append_to_file` work on the file's current content, so two analyses adding facts to the same file both land (FR-016). `replace_file` requires the version token `read_file` returned and refuses if the file changed since. Analyses get no tool that deletes, renames, or retires a file, and can't write a stub (FR-015). The index changes only through tools that edit one entry or heading at a time.

Before the first write of a run, the store triggers the pre-run copy (R12). Each write by an analysis adds the slug to the dream record's waiting set immediately, so an interrupted run leaves the right files waiting.

**Rationale**: Prompts can't guarantee confinement, secrecy, or no lost updates; tools can. Session content and memory content are untrusted (FR-014), so the guarantees must hold even if the model follows an injected instruction.

**Alternatives considered**: Generic file tools with path checks only (the agent could clobber `_index.md` or another analysis's changes). A file-level OS lock (all analyses run in one process; an in-process lock is enough and the run lock (R12) stops a second process).

## R10. Fact citations and the no-loss invariant

**Decision**: Every fact ends with a citation in a fixed syntax:

```
[source: <tool> <session-id> · <project-dir> · <YYYY-MM-DD HH:MM> UTC]
```

`REPLACED:` and `CONFLICT:` lines use the same citations (see [memory format contract](contracts/memory-format.md)). The store enforces two rules on every write:

- **New citations from an analysis** must name that analysis's tool, session ID, and project directory, with a time inside its part's time range. The organizer may not add citations that don't already exist in memory.
- **Removed citations** must still appear in another non-stub memory file after the write. `retire_file` therefore succeeds only after every citation in the retired file exists in its target.

**Rationale**: FR-013 requires a source per fact, and FR-020 forbids dropping facts. A citation is the one part of a fact that code can check. The rules stop an analysis from citing another session (or a session text from forging a source), and stop a merge or split from losing facts wholesale. Several facts can share one citation, so the check doesn't prove every sentence survived; the eval measures that (SC-006).

**Alternatives considered**: A structured `record_fact` tool that formats facts itself (rigid for corrections, `REPLACED:` rewrites, and organizer merges). No machine check (leaves FR-020 to the prompt alone).

## R11. Credential detection

**Decision**: An in-house list of regular expressions, each tested with a fake credential: Anthropic (`sk-ant-…`), OpenAI (`sk-…`, `sk-proj-…`), GitHub (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`), AWS access key IDs (`AKIA…`, `ASIA…`), Google API keys (`AIza…`), Slack (`xox[abprs]-…`), Stripe (`sk_live_`, `rk_live_`), npm (`npm_…`), PEM private key headers, JSON Web Tokens (`eyJ….….…`), `Bearer` tokens of 20 or more characters, and URLs with a password (`scheme://user:password@host`).

**Rationale**: SC-003 asks for 10 common formats; this list covers 12 families. The scan runs only on text an agent writes, so it's cheap.

**Alternatives considered**: `detect-secrets` or similar (a new dependency with entropy heuristics that would flag ordinary hashes and IDs in facts).

## R12. Run state: record, lock, and pre-run copies

**Decision**: State lives outside the memory directory, under `${XDG_STATE_HOME:-~/.local/state}/dreaming-workflow/<key>/`, where `<key>` is the first 16 hex digits of the SHA-256 of the memory directory's real path. The directory has mode 0700 and holds:

- `record.json`, the dream record (see [data model](data-model.md)), written atomically after each session finishes and after each memory write by an analysis;
- `lock`, held with `fcntl.flock(LOCK_EX | LOCK_NB)` for the whole run; a second run gets "memory directory in use" and exits as not started;
- `backups/<run-id>/`, a copy of the memory directory made before the run's first write, keeping the 10 most recent and deleting older ones after a new copy succeeds.

The memory directory is created with mode 0700 if missing. Order at start: parse arguments, check credentials, take the lock, read the record, select sessions.

**Rationale**: Keeping the record and copies out of memory keeps them away from agent tools and the format check. `flock` is released by the kernel if the process dies, so a crash never leaves a stale lock. The run id is the UTC start time (`20261110T213800Z`), which sorts by age.

**Alternatives considered**: A lock file with a PID (stale after crashes). The state inside the memory directory (agents and the user's tools would see it).

## R13. Keeping content out of output and logs

**Decision**: The CLI prints only counts, paths, session IDs, slugs, rule names, and failure reasons from fixed enums. Tool refusal messages go to the model, never to logs. Logging for `google_adk`, `anthropic`, and `httpx2` is set to WARNING, and no OpenTelemetry exporter is configured, so ADK's spans stay in the process. An integration test runs a dream at DEBUG log level over a session and memory file containing a unique marker string and asserts the marker appears in no output stream, log record, or report.

**Rationale**: FR-026 and the constitution forbid personal data in logs. Exceptions are the usual leak: failure reasons come from enums (`FailureReason`), not exception messages.

## R14. CLI

**Decision**: One command, `dream`, built with `argparse` (see [CLI contract](contracts/cli.md)). `--preview` lists instead of running. Exit codes: 0 success, 1 completed with failures, 2 not started, 130 interrupted by a signal.

**Rationale**: FR-029 asks for one command; argparse already exits with 2 on invalid arguments, which matches "not started".

## R15. Tests and evaluations

**Decision**: Four layers.

| Layer | What it uses | What it covers |
| --- | --- | --- |
| Unit | Pure functions, temporary directories | Parsers (on the six examples and synthetic files), view rendering, estimate, parts, selection rules, index parsing and edits, format check, path and credential guards, citation rules, cost math, record, backup retention |
| Contract | `ClaudeModel` on ADK's `AnthropicLlm`, the real `anthropic` SDK, and a real ADK `Runner`, fake Messages API through `httpx2.MockTransport` | Request shape, tool and thinking round trip (including empty thinking text), cache breakpoints, refused tool results marked as errors, usage and cost, retry count on 429/529/timeouts (with `retry-after-ms: 1` to keep it fast), refusal and `max_tokens`, the 95,000-token ceiling, credential preflight |
| Integration | Full `dream` runs with a scripted `BaseLlm` test double, real ADK, real files | Report counts on the examples, groups and ordering, part order, failures and exit codes, spending limit, waiting files and organizer recovery, preview equals run, repeat run sends nothing, lock, backups, content-free output, writes outside memory refused, concurrent edits |
| Eval | Real Claude API, `mise run eval`, run by hand | Model-dependent criteria: SC-001, SC-002, SC-003, SC-004, SC-006, SC-011, SC-012, the semantic acceptance scenarios, and SC-007 timing. Each scenario runs 3 times from empty memory. |

Evals check deterministic facts directly (no `4 MB` claim, no citation of the subthread's ID, none of the seeded credentials, no file outside memory changed, seeded fact markers present, request sizes from the run's ledger). Semantic facts ("memory gives bare `ctx7` as current") go to a grader call on Claude Opus 5.5 with structured output that returns a verdict and a verbatim quote; the harness accepts the verdict only if the quote appears in memory. Each eval run uses a US$5 spending limit and prints its cost.

The default `test` task excludes evals (pytest marker `eval`). They need credentials and money, and their results vary between runs, which the constitution doesn't allow in the default suite.

**Rationale**: The constitution asks for real collaborators where we own them (ADK, files, the SDK's own retry code) and doubles for systems we don't (the Claude API). The scripted model drives real tools, so guards are tested where they're enforced.

**Alternatives considered**: Recording real API responses as fixtures (they'd go stale with model changes and could contain personal data). Regex-only evals (too brittle for "states X as current").

## R16. Checks and CI

**Decision**: mise tasks `setup`, `format`, `lint`, `typecheck`, `test`, `check`, and `eval`; GitHub Actions runs `mise run check` through `jdx/mise-action` pinned to a commit SHA. `ty check` on `src/` and `tests/`, set up as ty's mypy migration guide recommends for strict checking: the off-by-default rules `dynamic-function-decorator-return`, `missing-type-argument`, `possibly-unresolved-reference`, and `unsound-return-statement` are on, and ruff adds the `ANN` and `PYI` rule groups, because ty doesn't report missing annotations. ty exits non-zero on warnings as well as errors, so any diagnostic fails `check`. Escape hatches (`Any`, `cast`, `# ty: ignore[rule]`) are allowed only in `agents/claude_model.py`, where ADK's model interface requires them, with a comment saying why.

**Rationale**: AGENTS.md makes `mise run` the only interface and `check` the CI gate. ty comes from Astral, like uv and ruff, which the project already uses. It is in beta and ships almost daily (0.0.96 through 0.0.101 between 2026-11-03 and 2026-11-11), so an upgrade can add diagnostics. The exact pin keeps `check` stable, and each upgrade is its own change.

**Alternatives considered**: `mypy --strict` (the reference checker, stable, with strict mode built in; ty fits the existing Astral toolchain). `pyright` (another separate toolchain).

## R17. Spec thresholds the plan confirms

| Threshold | Spec value | Decision |
| --- | --- | --- |
| Part size | 40,000 estimated tokens | Keep, with the three-characters-per-token estimate (R5) |
| Skip as too large | 400,000 estimated tokens | Keep |
| Default spending limit | US$10 | Keep |
| Pre-run copies kept | 10 | Keep |
| Retries | 3 | Keep, through the SDK (R3) |

The spec's assumption that tool results and views were measured at "four characters per token" stays true as a description of that measurement; the plan's estimator differs on purpose (R5).
