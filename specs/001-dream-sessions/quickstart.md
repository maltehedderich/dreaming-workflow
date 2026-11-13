# Quickstart: validate dream sessions end to end

Runnable checks that the feature works, from setup to the model-dependent evals. Commands run from the repository root. Formats and options are in the [CLI contract](contracts/cli.md); report fields in the [data model](data-model.md#report).

## Prerequisites

- mise installed; it pins Python 3.15 and uv.
- For the steps that call Claude: credentials through `ANTHROPIC_API_KEY` or a profile from `ant auth login`. Each run over the examples sends their conversation views to the Claude API and costs money at Claude Sonnet 5.5 list prices; the report prints the cost.

## 1. Set up and run the required checks

```bash
mise run setup
mise run check
```

Expected: `lint`, `typecheck`, and `test` pass. `test` runs the unit, contract, and integration layers and needs no credentials or network.

## 2. Prepare a scratch area

Work on copies, keep memory and run state out of the repository and out of your real state directory:

```bash
work=$(mktemp -d)
cp -R examples/transcripts/claude-code/projects "$work/claude"
cp -R examples/transcripts/codex/sessions "$work/codex"
export XDG_STATE_HOME="$work/state"
dream() { uv run dream --memory "$work/memory" --since 2026-10-01 \
  --claude-code-dir "$work/claude" --codex-dir "$work/codex" "$@"; }
```

`--since 2026-10-01` is needed because the examples date from 2026-10-17 to 2026-11-07, before the default 14-day window.

## 3. Preview (User Story 3, scenario 1)

```bash
dream --preview; echo "exit $?"
```

Expected: 5 selected sessions (3 Claude Code, 2 Codex) with tool, project directory, date, size, estimated tokens, and 1 part each; the total estimated tokens; 0 files waiting; 1 skipped session, the `4cea5169-…` rollout, with reason `subthread`; exit 0. `$work/memory` and `$work/state` don't exist afterwards.

## 4. First dream (User Story 1, scenarios 1–3 and 9)

```bash
dream; echo "exit $?"
```

Expected:

- Report: found 6, selected 5, skipped 1 (subthread: 1), analyzed 5, failed 0; organizer ran and succeeded; format check no violations; a pre-run copy path under `$work/state`; exit 0; finished in under 10 minutes.
- The selected sessions match the preview from step 3.
- Memory (`ls "$work/memory"`, then read `_index.md` and the files it lists) says that ctx7 is installed globally and called as bare `ctx7`, with the `npx ctx7@latest` form only in a `REPLACED:` line; that Python work uses uv, enforced by `require-uv.sh` in Claude Code and execpolicy rules in Codex; that the hook blocks any Bash command containing `pip install` and running the test from a script file avoided it; and that Antigravity's global settings grant recursive read access to `~/.claude/skills`, filed domain-wide and citing `/Users/dev/Projects/mailarkiv`.
- No line states the password limit as 4 MB, and no citation names `4cea5169-365b-4853-93c8-e00a4221cc20`.
- `diff -r examples/transcripts/claude-code/projects "$work/claude"` and the same for Codex print nothing: session files are untouched.

Model output varies, so a single run is a smoke test. Step 8 runs the measured version.

## 5. Repeat run (User Story 3, scenario 2)

```bash
time dream; echo "exit $?"
```

Expected: `Nothing to dream over.`, usage of 0 tokens, exit 0, under 10 seconds.

## 6. Spending limit (User Story 3, scenario 6)

```bash
rm -rf "$work/memory" "$work/state"
dream --spending-limit 0.01; echo "exit $?"
dream --preview
```

Expected: the first run's report shows the limit reached, lists the sessions it cut off or didn't start with `spending-limit-reached`, and shows the organizer ran if any analysis succeeded; exit 1. The preview selects those sessions again.

## 7. Refusals that leave everything unchanged (User Story 1, scenario 6; User Story 3, scenario 5)

Missing credentials:

```bash
env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u ANTHROPIC_PROFILE \
  ANTHROPIC_CONFIG_DIR="$work/no-profile" \
  uv run dream --memory "$work/other-memory" --since 2026-10-01 \
  --claude-code-dir "$work/claude" --codex-dir "$work/codex"; echo "exit $?"
```

Expected: a message naming `ANTHROPIC_API_KEY` and `ant auth login`, exit 2, and no `$work/other-memory`.

Memory directory in use:

```bash
rm -rf "$work/memory" "$work/state"
dream & sleep 2; dream; echo "exit $?"; wait
```

Expected: the second command says another dream is running on the memory directory, exit 2; the first finishes normally.

## 8. Model-dependent acceptance (evals)

```bash
mise run eval
```

Needs credentials and spends money; each run has a US$5 spending limit and the eval prints the total cost. It runs each scenario 3 times from empty memory and reports pass or fail for SC-001 to SC-007, SC-011, SC-012, and the semantic acceptance scenarios, plus the measured ratio of real to estimated tokens. Run it after any change to prompts, tools, `ClaudeModel` or the agent settings, or the parsers.
