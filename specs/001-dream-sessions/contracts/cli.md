# CLI contract: `dream`

One command runs or previews a dream. Installed as the `dream` console script; `uv run dream` works from the repository.

## Synopsis

```text
dream --memory DIR [--since DATE] [--claude-code-dir DIR] [--codex-dir DIR]
      [--session FILE]... [--spending-limit USD] [--preview]
```

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--memory DIR` | required | Memory directory. Created with mode 0700 on the first run that writes. Preview never creates it. |
| `--since DATE` | 14 days before now | Window start, as `YYYY-MM-DD` (midnight UTC) or an ISO 8601 timestamp with a UTC offset. Must be in the past. The window ends at the run's start time. |
| `--claude-code-dir DIR` | `~/.claude/projects` | Claude Code session directory. |
| `--codex-dir DIR` | `~/.codex/sessions` | Codex session directory. |
| `--session FILE` | none | Session file to consider; repeatable. When given, no directory is scanned. The tool is detected from the file's content. |
| `--spending-limit USD` | `10.00` | Stop sending analysis requests once the run's cost at list price reaches this amount. Must be greater than 0. |
| `--preview` | off | List what a run would send. Sends nothing to the Claude API, changes no files, and needs no credentials. |

A default session directory that doesn't exist means that tool has no sessions. A directory or file the user names that doesn't exist is an invalid argument.

## Exit status

| Code | Outcome |
| --- | --- |
| 0 | Success. Includes "nothing to dream over" and every preview. |
| 1 | Completed with failures: a failed analysis, a failed organizer pass, or a format violation. |
| 2 | Not started: invalid arguments, missing credentials, or the memory directory is in use. Memory and the record are unchanged. |
| 130 | Interrupted by a signal. Memory may be partly updated; see the pre-run copy. |

## Output streams

- **stdout**: the preview listing or the run report.
- **stderr**: progress lines and error messages.

Neither stream ever contains session or memory content. They may contain paths, session IDs, slugs, counts, rule names, and failure reasons.

## Not started messages (stderr)

```text
dream: no Claude API credentials found. Set ANTHROPIC_API_KEY, or run `ant auth login` to create a profile.
```

```text
dream: another dream is running on /Users/dev/memory. Nothing was changed.
```

## Preview (stdout)

```text
Preview: window 2026-10-01 00:00 UTC to 2026-11-10 21:38 UTC

Selected sessions (5)
  tool         last activity      project dir                    size      est. tokens  parts
  claude-code  2026-10-17 09:22   /Users/dev/Projects             53.0 KB         989      1
  claude-code  2026-10-17 09:39   /Users/dev/Projects            139.8 KB       5,797      1
  …
Total estimated tokens: 17,789

Memory files waiting for the organizer: 0

Skipped sessions (1)
  codex/sessions/2026/11/06/rollout-…-4cea5169-….jsonl  subthread
```

Numbers above are illustrative. Each selected row also prints the file path on the following line.

## Progress (stderr, during a run)

```text
Found 6 sessions: 5 selected, 1 skipped.
Saved a copy of memory to /Users/dev/.local/state/dreaming-workflow/3f2a9c1e0b7d4a65/backups/20261110T213800Z
Group 1 of 1: analyzing 5 sessions
  analyzed  claude-code 90f95193-2c91-4a42-a506-930d4c964c45 (1 part)
  failed    codex 0bcd2a68-df00-491e-a9b7-f531e448d793 (rate-limited)
Organizing 7 memory files
Checking memory format
```

## Report (stdout, at the end of a run)

```text
Dream report, run 20261110T213800Z

Sessions
  found                     6
  selected                  5
  skipped                   1  (subthread: 1)
  analyzed                  5  (in more than one part: 0)
  failed                    0

Organizer                   ran and succeeded
Waiting for the organizer   0 files

Memory
  index                     9 entries, 2 domains, 1 subdomain
  files                     7 created, 1 changed, 0 retired
  conflicts added           0
  format check              no violations

Usage
  tokens                    1,234,567 input (1,000,000 cache read, 120,000 cache write), 45,678 output
  cost at list price        US$0.12
  spending limit            US$10.00, not reached

Pre-run copy                /Users/dev/.local/state/dreaming-workflow/3f2a9c1e0b7d4a65/backups/20261110T213800Z
```

Variants:

- Failed sessions are listed under **Sessions** as `failed  <tool> <session id>  <reason>`, one per line.
- Violations are listed under **Memory** as `<file>  <rule>`, one per line.
- If the organizer didn't run or failed, the line says so and gives the reason, for example `Organizer  failed (timeout); memory was not organized`.
- When nothing was selected and no file was waiting, the report is the **Sessions** block followed by `Nothing to dream over.`, and no request was sent.
- When the run wrote nothing, **Pre-run copy** reads `none (memory unchanged)`.
- "Input" counts every input token: uncached, cache reads, and cache writes.
