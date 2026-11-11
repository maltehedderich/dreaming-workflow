# Implementation Plan: Dream over Claude Code and Codex sessions

**Branch**: `001-dream-sessions` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-dream-sessions/spec.md`

## Summary

Build `dream`, a Python CLI that reads finished Claude Code and Codex sessions, sends each one's conversation to Claude Haiku 5.5 for analysis, runs one organizer pass, checks the memory format, and prints a report built from its own records.

ADK runs each analysis and the organizer as a single `LlmAgent` under a `Runner`. ADK's own `AnthropicLlm` sends every model call to the Claude API through the official `anthropic` SDK. A thin subclass, `ClaudeModel`, sets the model, sends signed thinking blocks with empty text back unchanged, and turns unusable replies into failures. Plain asyncio code runs the fixed sequence: groups of at most 20 sessions, parts in order, then the organizer. There is no lead agent.

Safety lives in code, not prompts. Agents touch memory only through tool functions that refuse paths outside memory, credential-shaped strings, broken frontmatter, lost updates, citations from other sessions, and removal of a fact's last citation. `ClaudeModel` keeps every request under 95,000 input tokens and stops analysis requests at the spending limit. A dream record outside memory tracks handled sessions and files waiting for the organizer; a lock file keeps runs on one memory directory exclusive; pre-run copies of memory are kept for the last 10 writing runs.

Details: [research](research.md), [data model](data-model.md), contracts for the [CLI](contracts/cli.md), [memory format](contracts/memory-format.md), [agent tools](contracts/agent-tools.md), and [conversation view](contracts/conversation-view.md), and the [quickstart](quickstart.md).

## Technical Context

**Language/Version**: Python 3.15, pinned with mise along with uv 0.13.7 ([R1](research.md#r1-runtime-and-project-tooling))

**Primary Dependencies**: `google-adk` 2.14.0 (agent loop, tool schemas), `anthropic` 2.8.0 (Claude API client and credential resolution), `pyyaml` 6.0.3 (frontmatter; already a dependency of ADK). Standard library for CLI (`argparse`), locking (`fcntl`), and hashing.

**Storage**: Files. Memory: Markdown files and `_index.md` in the user's memory directory. Run state: `record.json`, `lock`, and `backups/` under `${XDG_STATE_HOME:-~/.local/state}/dreaming-workflow/<key>/` ([R12](research.md#r12-run-state-record-lock-and-pre-run-copies)).

**Testing**: pytest 9.2 in four layers (unit, contract, integration, eval); ruff 0.17 for lint and format, with the `ANN` and `PYI` groups; ty 0.0.101 with its off-by-default strict rules turned on ([R15](research.md#r15-tests-and-evaluations), [R16](research.md#r16-checks-and-ci))

**Target Platform**: macOS and Linux, one user, local disk. Windows is out of scope (`fcntl`, POSIX modes).

**Project Type**: Command-line tool (single Python package)

**Performance Goals**: A run over the six example sessions finishes in under 10 minutes (SC-007). A repeat run with nothing to do sends no request and finishes in under 10 seconds (SC-008).

**Constraints**: No request to the Claude API over 100,000 input tokens (SC-011); hard ceiling 95,000 in `ClaudeModel` ([R6](research.md#r6-staying-under-100000-input-tokens)). Every API request has a 300-second timeout and up to 3 retries. Spending limit, default US$10. Writes only inside the memory directory. No session or memory content in output, logs, or reports.

**Scale/Scope**: About 60 sessions per 14 days on the reference machine, conversation views from a few thousand to about 320,000 estimated tokens. Memory up to a few hundred files of at most 100,000 bytes each.

No open questions remain; the spec's provisional thresholds are confirmed in [R17](research.md#r17-spec-thresholds-the-plan-confirms).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution version 1.0.0.

| Principle | Check | Status |
| --- | --- | --- |
| I. User value, YAGNI | Scope is the spec's three stories. No lead agent, no settings beyond the four FR-029 names (session sources, window, memory directory, spending limit) plus `--preview`, no JSON output, no Windows support. Shared types exist only where two variants exist now (two session parsers produce one `ConversationView`). | Pass |
| II. Modular architecture | One package with modules per capability: `sessions`, `memory`, `agents`, plus `state` and the `dream` application service. The CLI only parses arguments and renders results. Only `state` writes the dream record; only `memory.store` writes memory. | Pass |
| III. Explicit contracts and failures | Enums for tool, skip reason, failure reason, session status, run outcome, and format rule. JSONL and model output parsed into typed values at the edge. Every API call has a timeout and defined retry and failure behavior; failures are recorded, reported, and reflected in the exit status, never swallowed. | Pass |
| IV. Security and privacy | Tool-level confinement to the memory directory, credential scan on writes, content-free output with an automated canary test, state and copies at mode 0700. Dependencies: see Complexity Tracking for ADK's transitive footprint. All versions pinned and audited with `pip-audit` before the first commit. | Pass with recorded deviation |
| V. Test according to risk | Risks ranked below with a check at the lowest layer that catches each. The Claude API is the only system replaced by doubles; ADK, files, and the SDK's retry code run for real. Model-dependent criteria run as evals, outside the default suite. | Pass |
| VI. Small batches | Delivery as vertical slices starting with a walking skeleton (below). Checks run through `mise run check` in CI. | Pass |
| Governance | ADRs for the runtime dependencies and the dev tooling. AGENTS.md gets the checks table in the same change that adds the first code. | Pass |

## Project Structure

### Documentation (this feature)

```text
specs/001-dream-sessions/
├── plan.md              # This file
├── research.md          # Phase 0: decisions and rejected alternatives
├── data-model.md        # Phase 1: types, record format, state changes
├── quickstart.md        # Phase 1: end-to-end validation guide
├── contracts/
│   ├── cli.md                 # command, options, exit codes, preview and report
│   ├── memory-format.md       # files, facts and citations, index, format rules
│   ├── agent-tools.md         # tools the analyzer and organizer get, and their guards
│   └── conversation-view.md   # what each tool's JSONL contributes to the view
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks; not created here)
```

### Source Code (repository root)

```text
pyproject.toml                  # uv project, exact pins, console script `dream`
uv.lock
mise.toml                       # Python 3.15, uv 0.13.7, tasks
.github/workflows/check.yml     # mise run check
docs/adr/
├── 0001-adk-anthropic-llm.md
└── 0002-python-tooling.md

src/dreaming_workflow/
├── __init__.py
├── __main__.py                 # python -m dreaming_workflow
├── cli.py                      # argparse, exit codes, preview and report rendering
├── dream.py                    # application service: preview() and run()
├── report.py                   # Report built from run records
├── state.py                    # state directory, lock, dream record
├── sessions/
│   ├── __init__.py             # discover_and_select(), Session, Part, SkipReason
│   ├── discovery.py            # walk source directories, stat, record check
│   ├── claude_code.py          # Claude Code JSONL → Session
│   ├── codex.py                # Codex JSONL → Session
│   └── view.py                 # messages, rendering, estimate, parts, shortening
├── memory/
│   ├── __init__.py             # MemoryStore, check_format()
│   ├── store.py                # guarded reads and writes, versions, locks, change log
│   ├── document.py             # frontmatter, stubs, links, citations
│   ├── index.py                # parse, edit, render _index.md
│   ├── check.py                # format rules
│   ├── secrets.py              # credential patterns
│   └── backup.py               # pre-run copy and retention
└── agents/
    ├── __init__.py             # analyze_session(), organize()
    ├── claude_model.py         # ClaudeModel on ADK's AnthropicLlm, client, agent settings
    ├── runner.py               # one agent invocation under an ADK Runner
    ├── budget.py               # prices, UsageLedger, ContextGuard
    ├── tools.py                # tool functions bound to one invocation
    ├── analysis.py             # one session, parts in order
    ├── organizer.py            # organizer input selection and pass
    └── prompts/
        ├── analyzer.md
        └── organizer.md

tests/
├── support/                    # synthetic session builders, scripted BaseLlm, fake Messages API
├── unit/
├── contract/                   # ClaudeModel and ADK against a fake Messages API
├── integration/                # full dream runs with the scripted model
└── eval/                       # real Claude API; pytest marker `eval`; mise run eval
```

**Structure Decision**: A single `src/` package with three capability subpackages. Sessions, memory, and agents change for different reasons (external file formats, the memory contract, model behavior), so they get separate modules with small public interfaces in their `__init__.py`. `dream.py` is the only module that wires them together; `cli.py` calls `dream.preview()` and `dream.run()` and nothing else. The repository's `.gitignore` ignores `lib/`, `parts/`, and `var/` anywhere, so no source directory may use those names.

## Delivery slices

Each slice ends in behavior a test or the quickstart can show. `tasks.md` breaks them down.

1. **Tooling skeleton** (structural): `pyproject.toml`, `uv.lock`, `mise.toml` with all tasks, CI workflow, ADRs, the AGENTS.md checks table, and an empty package with one passing test.
2. **Walking skeleton**: `dream --memory DIR --session <one Claude Code example>` parses the file, renders one part, runs one analysis through ADK and `ClaudeModel` against the real API, writes a memory file and index entry through the guarded store, and prints a minimal report. Tests: parser unit test on the example, `ClaudeModel` contract test with the fake Messages API (including the thinking round trip), integration test with the scripted model.
3. **User Story 1**: discovery in both directories, the Codex parser, all skip rules, parts and shortening, groups of 20, credentials preflight, failure handling and exit codes, all write guards (paths, credentials, versions, citations), domains in the index, pre-run copy, full report.
4. **User Story 2**: waiting files in the dream record, organizer input selection, organizer tools and pass, format check, organizer failure and recovery.
5. **User Story 3**: preview, handled-session records and change detection, spending limit, run lock, copy retention.
6. **Evals**: the eval harness, grader, synthetic scenarios, and a first full eval run recorded in the PR.

## Verification

### Required checks

These go into AGENTS.md with the first code.

| Task | Command | Layer | In CI |
| --- | --- | --- | --- |
| `setup` | `uv sync --locked` | — | yes |
| `format` | `uv run ruff format . && uv run ruff check --fix .` | — | no (writes files) |
| `lint` | `uv run ruff check . && uv run ruff format --check .` | static | yes |
| `typecheck` | `uv run ty check src tests` (strict rule set from R16) | static | yes |
| `test` | `uv run pytest` (unit, contract, integration; excludes `eval`) | unit, contract, integration | yes |
| `check` | runs `lint`, `typecheck`, `test` | CI gate | yes |
| `eval` | `uv run pytest -m eval tests/eval` | acceptance against the real API | no: needs credentials, costs money, varies between runs |

`eval` runs by hand before merging any change to prompts, tools, `ClaudeModel` or the agent settings, or the parsers, and its summary goes in the PR description.

### Risks and where they're caught

Ranked by harm times likelihood. Each is checked at the lowest layer that would catch it.

| Risk | Harm | Check | Layer |
| --- | --- | --- | --- |
| An agent writes outside memory or changes a session file | High | Path guard tests (`..`, absolute paths, symlinked files and directories); scripted run attempting each; session file hashes before and after; SC-004 | unit, integration, eval |
| A credential lands in memory | High | Pattern tests with 12 fake credential families; scripted write refused; SC-003 | unit, integration, eval |
| Session or memory content leaks into output or logs | High | Canary string in a session and a memory file, run at DEBUG, asserted absent from stdout, stderr, log records, and the report | integration |
| The organizer drops facts | High | Citation removal and `retire_file` rules; SC-006 on seeded memory | unit, eval |
| Thinking blocks or tool IDs lost between ADK and the API, breaking tool loops | High | Real ADK `Runner` with `ClaudeModel` against the fake Messages API; asserts the second request carries the first response's thinking block (with text and with empty text), signature, and `tool_use` id | contract |
| Instruction files or system prompts reach the analysis as user statements | Medium | Parser tests on all six examples: the view contains the typed prompts and none of the `AGENTS.md`, `<environment_context>`, skill-listing, or system-prompt text | unit |
| Wrong selection or miscounted report | Medium | Each skip rule with a synthetic file; scenario 2 counts on the examples; `found = selected + skipped`, `selected = analyzed + failed`; preview equals run | unit, integration |
| Concurrent analyses lose each other's facts | Medium | Two scripted analyses append to and edit the same file; `replace_file` with a stale version refused | unit, integration |
| A request passes 100,000 input tokens | Medium | `ClaudeModel` refuses above 95,000; tools refuse reads past 75,000; the 250,000-token synthetic session splits into 7 parts of at most 40,000; SC-011 from the ledger | unit, contract, eval |
| Spending runs past the limit | Medium | Cost formula against hand-computed values from the price table; scripted run with a low limit stops analysis requests and lets the organizer run | unit, integration |
| Retries missing or excessive | Medium | Fake API returns 429, 529, and timeouts; asserts 4 attempts, then the matching failure reason | contract |
| A failed organizer leaves facts unorganized for good | Medium | Organizer fails; next run with no new sessions runs only the organizer over the waiting files; a third run sends nothing | integration |
| Two runs on one memory directory | Medium | Second process gets exit 2 while the first holds the lock | integration |
| Crash corrupts the record or memory | Low | Atomic write helpers tested with a simulated failure before rename | unit |

Model-dependent outcomes (SC-001, SC-002, SC-004, SC-006, SC-012, and the semantic acceptance scenarios) can't be proven by deterministic tests. The eval runs each scenario 3 times from empty memory and checks with deterministic assertions where possible and a quote-verified grader otherwise ([R15](research.md#r15-tests-and-evaluations)).

## Constitution Check after design

The design adds no new modules, services, or dependencies beyond those listed before research.

- **II**: The tool functions call `MemoryStore`; agents never touch the file system directly. `ClaudeModel` depends on `budget` only through `UsageLedger` and `ContextGuard`.
- **III**: ADK converts between genai and Anthropic types. `agents/claude_model.py`, where ADK's model interface requires them, is the only place for `Any` or `cast`, each with a comment. Failure reasons come from an enum, so no exception message reaches output.
- **IV**: Credential preflight runs before any session is read. Pre-run copies and the record sit outside memory at mode 0700.
- **V**: Each high-harm risk has an automated check in the default suite, except fact loss and injection resistance, whose model-dependent half runs as an eval by design.

Result: pass, with the one deviation below.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
| --- | --- | --- |
| `google-adk` brings a large transitive dependency tree (FastAPI, Uvicorn, OpenTelemetry, google-genai, websockets, and more), against principle IV's "keep dependencies few" | The project exists to reimplement the cookbook on ADK (README). ADK supplies the tool-call loop and builds tool schemas from Python functions. | A hand-written loop on the `anthropic` SDK alone would cut the tree but drop the project's stated purpose. The unused parts (web server, Gemini clients) are never imported at runtime; versions are pinned and audited, and ADR 0001 records the trade-off. |
