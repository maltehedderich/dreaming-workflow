# Agent tools contract

The analyzer and the organizer act on memory only through these tools. They are Python functions that ADK exposes to the model; every guarantee about memory (confinement, no secrets, no lost updates, no dropped citations) is enforced here, not in the prompts.

Each tool returns a JSON object:

- success: `{"status": "ok", …}` with the fields listed below;
- refusal: `{"status": "refused", "reason": "<message for the model>", "is_error": true}`. ADK's Claude model marks a tool result with `is_error` set as an error. Refusals are expected; the agent reads the reason and adapts.

No result has a field named `content`. When a result has a `content` string, ADK sends only that string to Claude and drops the other fields. Every other result reaches Claude as the whole object in JSON.

Refusal messages go only to the model. Logs and the report never contain them.

## Who gets which tool

| Tool | Analyzer | Organizer |
| --- | --- | --- |
| `read_index` | ✓ | ✓ |
| `search_memory` | ✓ | ✓ |
| `read_file` | ✓ | ✓ |
| `create_file` | ✓ | ✓ |
| `edit_file` | ✓ | ✓ |
| `append_to_file` | ✓ | ✓ |
| `replace_file` | | ✓ |
| `retire_file` | | ✓ |
| `set_index_entry` | | ✓ |
| `rename_domain` | | ✓ |
| `move_subdomain` | | ✓ |

No tool reads session files, runs commands, or touches anything outside the memory directory. Analyzers can't delete, rename, or retire files, rewrite a whole file, or move index entries.

## Reading

### `read_index() → {text}`

Returns `_index.md`, or an empty string if there is none.

### `search_memory(text) → {matches: [{slug, line, excerpt}], truncated}`

Case-insensitive literal search across memory files and stubs. Returns at most 50 matches; each excerpt is the matching line cut to 300 characters. Used to find existing facts without reading whole files.

### `read_file(slug, start_line=1, max_lines=null) → {text, version, total_lines}`

Returns the file (or the requested lines) and its version token. A stub returns its `MOVED TO [[slug]]` line. Lines let the organizer work through a file too large to read at once.

**Read budget**: `read_index`, `search_memory`, and `read_file` refuse when their result would take the agent's projected prompt past 75,000 tokens. The reason states the size of the result and the room left, and tells the agent to finish with what it has.

## Writing

Every write tool applies these checks, in order, before anything reaches disk:

1. **Slug**: matches `^[a-z0-9]+(?:-[a-z0-9]+)*$`, at most 80 characters. The target must not be a symbolic link and must resolve to a direct child of the memory directory.
2. **Credentials**: the new text contains no match for the credential patterns ([research R11](../research.md#r11-credential-detection)). Reason: "Refer to the credential by name instead of writing its value."
3. **Format of the result**: frontmatter is valid YAML, `name` equals the slug, `description` is non-empty, and only `name`, `description`, and `metadata` keys are present. Analyzers can't produce a stub.
4. **Citations** ([memory format](memory-format.md#machine-checked-rules)): an analysis's new citations name its own tool, session ID, and project directory with a time inside its part; the organizer adds no new citations; removed citations survive in another non-stub file.
5. **Write**: temporary file, `fsync`, atomic rename, mode 0600, under a per-slug lock.

Before the run's first write, the store saves the pre-run copy of memory. After each analysis write, the slug joins the dream record's waiting files.

### `create_file(slug, description, body, domain, subdomain, index_sentence) → {version}`

Creates `<slug>.md` with frontmatter and body, and adds `- [[slug]] — <index_sentence>` under `## <domain>`, and under `### <subdomain>` when `subdomain` is not null. Creates the headings if needed, reusing an existing heading whose name matches case-insensitively. Refuses if the slug exists (the agent should read and edit it instead) or if `index_sentence` spans more than one line.

### `edit_file(slug, old_text, new_text) → {version}`

Replaces the single exact occurrence of `old_text` in the current content. Refuses if `old_text` occurs zero or several times.

### `append_to_file(slug, text) → {version}`

Appends `text` to the end of the current content, adding a newline first if needed.

### `replace_file(slug, content, version) → {version}` (organizer)

Replaces the whole file. Refuses if the file changed since the `read_file` that returned `version`.

### `retire_file(slug, into) → {}` (organizer)

Turns `slug` into the stub `MOVED TO [[into]]` and removes its index entry. Refuses if `into` doesn't exist or is a stub, or if any citation in `slug` is missing from every other non-stub file.

## Index (organizer)

### `set_index_entry(slug, domain, subdomain, sentence) → {}`

Adds the entry, or moves and rewrites it if the slug is already listed. Creates headings as needed and removes headings left empty. Refuses for a slug with no file or a stub.

### `rename_domain(name, new_name) → {}`

Renames a domain. If `new_name` already exists, moves all entries and subdomains into it (merging subdomains with matching names) and removes the old heading.

### `move_subdomain(domain, subdomain, to_domain, to_subdomain) → {}`

Moves or renames a subdomain. With `to_subdomain` null, its entries become domain-wide entries of `to_domain`. Merges into an existing subdomain with a matching name.

## What each agent receives

**Analyzer**, per part, as the first user message:

- tool, session ID, project directory, part number and count, and the UTC time range of the part;
- the part's rendered messages ([conversation view](conversation-view.md)) inside a delimiter with a random boundary string, introduced as data to draw facts from.

**Organizer**, once per run:

- the received slugs: files waiting for it and files that break the format, up to 40,000 estimated tokens of content ([research R6](../research.md#r6-staying-under-100000-input-tokens));
- the format violations for those files, by rule.

Both get a fixed system instruction with no dates, IDs, or other per-run values, so all invocations share the cached prefix.
