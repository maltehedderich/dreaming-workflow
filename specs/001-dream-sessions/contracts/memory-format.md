# Memory format contract

The memory directory is the product: Claude Code, Codex, and the user read it. This file defines its layout, the syntax agents write, and the rules the format check enforces.

## Layout

```text
<memory>/
├── _index.md          # the index
├── ctx7-setup.md      # memory file
├── uv-python.md       # memory file
└── docs-lookup.md     # stub: MOVED TO [[ctx7-setup]]
```

Only `*.md` files at the top level belong to memory. Other files and subdirectories are ignored by the tools and the format check.

## Memory files

```markdown
---
name: ctx7-setup
description: How the Context7 CLI (ctx7) is installed and called from Claude Code and Codex. Read before fetching library docs.
---
# Context7 CLI (ctx7)

- ctx7 is installed globally under fnm Node v26.11.1 and is called as bare `ctx7`, never through `npx`. Checked by running `ctx7 library` and `ctx7 docs` after the install. May go stale when the Node version changes. [source: claude-code 40726b6c-49a1-400e-ad5e-9192e635ceb6 · /Users/dev/Projects · 2026-10-17 09:36 UTC] [scope: Development]
- REPLACED: [source: claude-code 90f95193-2c91-4a42-a506-930d4c964c45 · /Users/dev/Projects · 2026-10-17 09:19 UTC] said ctx7 is called through `npx ctx7@latest`; [source: claude-code 40726b6c-49a1-400e-ad5e-9192e635ceb6 · /Users/dev/Projects · 2026-10-17 09:36 UTC] replaced it.

See also [[uv-python]].
```

Times and the example's wording are illustrative.

- **Frontmatter**: YAML between `---` lines at the very start. Keys: `name` (required, equals the file name without `.md`), `description` (required, non-empty: what the file covers and when to read it), `metadata` (optional mapping). No other keys.
- **Slug**: lowercase letters and digits in hyphen-separated groups, at most 80 characters.
- **Domain and subdomain** are not stored in the file. The index alone says where a file belongs, so moving a file or merging domains changes only `_index.md`.
- **Size**: at most 100,000 bytes.
- **Links**: `[[slug]]`; each must name an existing file or stub.

## Facts and citations

A fact is one list item that ends with a citation and a scope:

```text
- <statement>[ How it was checked.][ May go stale: <reason>.][ Uncertain: <why>.] [source: <tool> <session-id> · <project-dir> · <YYYY-MM-DD HH:MM> UTC] [scope: <domain>[ › <subdomain>]]
```

- `<tool>` is `claude-code` or `codex`. `<session-id>` is the full ID. `<project-dir>` is the session's working directory. The time is the UTC minute of the message that shows the fact.
- `[scope: Development]` means the whole domain; `[scope: Development › mailarkiv]` means one subdomain. Files under a subdomain hold only facts scoped to it.
- A fact learned in one project but true for the whole domain, such as a change to global settings, has a domain scope and still cites the project directory it came from.

### Replaced facts and conflicts

```text
- REPLACED: [source: …] said <old statement>; [source: …] replaced it.
- CONFLICT: [source: …] says <statement A>; [source: …] says <statement B>.
```

The older fact is rewritten in place as a `REPLACED:` line when a later one plainly corrects it. Otherwise both stay in a `CONFLICT:` line. A passing remark, or a search that found nothing, doesn't replace a decision the user recorded.

### Machine-checked rules

The memory tools enforce these on every write (see [agent tools](agent-tools.md)):

1. A citation an analysis adds must name its own tool, session ID, and project directory, with a time inside its part.
2. The organizer can't add a citation that doesn't already exist in memory.
3. A citation removed from a file must still exist in another non-stub file after the write.

## Stubs

A retired file's whole content:

```text
MOVED TO [[ctx7-setup]]
```

No frontmatter and no index entry. Links to the retired slug still resolve through the stub. A stub may point to another stub; cycles are violations.

## Index

`_index.md`:

```markdown
# Memory index

## Development

- [[ctx7-setup]] — How ctx7 is installed and called in Claude Code and Codex.
- [[uv-python]] — Python work uses uv, enforced by a hook in Claude Code and rules in Codex.

### mailarkiv

- [[mailarkiv-identity]] — Password rules in internal/identity.

## Business

- [[service-pricing]] — How services are priced.
```

- Optional first line `# Memory index`; nothing else outside headings and entries, apart from blank lines.
- `## <domain>` headings. Entries directly under a domain heading belong to the whole domain.
- `### <subdomain>` headings sit inside a domain, after its domain-wide entries.
- Each entry: `- [[slug]] — <one sentence>` (em dash with a space on each side).
- Every non-stub memory file appears exactly once. Stubs don't appear.

## Format check rules

The check runs at the end of every run and on the organizer's input. Each violation is reported as `<file>  <rule>`.

| Rule | Violation |
| --- | --- |
| `file-name` | File name isn't `<slug>.md` |
| `frontmatter-missing` | Non-stub file doesn't start with frontmatter |
| `frontmatter-invalid` | Frontmatter isn't valid YAML or isn't a mapping |
| `frontmatter-key` | Frontmatter has a key other than `name`, `description`, `metadata` |
| `name-mismatch` | `name` missing or not equal to the file's slug |
| `description-missing` | `description` missing or empty |
| `file-too-large` | File over 100,000 bytes |
| `broken-link` | `[[slug]]` names no file or stub |
| `stub-invalid` | File contains `MOVED TO [[…]]` together with other content |
| `stub-cycle` | Following stubs leads back to a stub already seen |
| `index-missing` | `_index.md` doesn't exist while memory has files |
| `index-syntax` | A line in the index isn't a title, heading, entry, or blank |
| `index-entry-missing` | Non-stub file has no index entry |
| `index-entry-duplicate` | Slug listed more than once |
| `index-entry-stub` | Index lists a stub |
| `index-entry-dangling` | Index lists a slug with no file |
| `index-domain-duplicate` | Two `##` headings with the same name (case-insensitive) |
| `index-subdomain-duplicate` | Two `###` headings with the same name within one domain |
| `index-heading-empty` | `###` heading with no entries, or `##` heading with no entries of its own and none in its subdomains |
| `index-subdomain-orphan` | `###` heading before any `##` heading |
