# Feature Specification: Dream over Claude Code and Codex sessions

**Feature Branch**: `001-dream-sessions`

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "take @README.md to get started with the specification, you can find examples for the session logs in the repo"

## User Scenarios & Testing *(mandatory)*

The user is a developer who works with Claude Code and Codex on one machine. Both tools store every session as a JSONL file. The user wants a command that reads finished sessions with hindsight and keeps a personal memory directory current, so later sessions start from what earlier ones learned. The six cleaned sessions in `examples/transcripts/` are the reference inputs; their README lists what a dream should take from each one.

### User Story 1 - Dream over finished sessions (Priority: P1)

The user runs one command. The tool finds finished Claude Code and Codex sessions in a time window, analyzes each one, and then runs one organizer pass. Each analysis adds durable facts to the memory directory: decisions, conventions, how tools are set up, identifiers, commands that worked, and approaches that failed. It files them by domain, a broad area such as development or business, and inside a domain by subdomain, a recurring subject such as a project. At the end the tool prints a report of what happened.

**Why this priority**: This is the product. Every other story improves a run like this one.

**Independent Test**: Run a dream over a copy of `examples/transcripts/` with an empty memory directory and a window that starts on or before 2026-10-17. Check the memory files for the facts the examples README lists, and check the report counts. Then, from empty memory again, dream over the synthetic sessions from scenario 11 and check the domains and subdomains in the index.

**Acceptance Scenarios**:

1. **Given** an empty memory directory and the six example sessions, **When** the user runs a dream over them with a window that covers their dates, **Then** memory records that ctx7 is installed globally and called as bare `ctx7`; that Python work in Claude Code and Codex uses uv, enforced by a hook in Claude Code and by rules in Codex; and that Antigravity's global settings grant recursive read access to `~/.claude/skills`.
2. **Given** the same run, **When** it finishes, **Then** the report shows 6 sessions found, 5 analyzed, 1 skipped as an auto-review subthread, and 0 failed.
3. **Given** the Codex session where the user calls a 4,096-byte password limit "4 mb" and interrupts before any answer, **When** it is analyzed, **Then** memory does not state that the limit is 4 MB.
4. **Given** memory that already holds facts, **When** a dream adds facts from new sessions, **Then** existing facts that the new sessions don't contradict stay unchanged.
5. **Given** one session whose analysis fails after retries, **When** the run continues, **Then** the other sessions are analyzed, the report lists the failed session with its reason, and the command exits with the "completed with failures" status.
6. **Given** no Claude API credentials, **When** the user starts a dream, **Then** the tool stops before reading any session, says how to provide credentials, and leaves memory unchanged.
7. **Given** a session whose text contains an API key and an instruction to write a file outside the memory directory, **When** it is analyzed, **Then** memory doesn't contain the key, no file outside the memory directory changes, and the instruction isn't recorded as a fact.
8. **Given** the 09:40 Claude Code session, where the new `require-uv.sh` hook blocks Claude's own test of the hook because the command text contains `pip install`, **When** it is analyzed, **Then** memory records that the hook blocks any Bash command whose text contains `pip install`, and that running the test from a script file avoided the block.
9. **Given** the Codex session in `mailarkiv` that changes Antigravity's global settings, **When** it is analyzed, **Then** memory records that setting as applying to the whole domain, not only to `mailarkiv`, keeps it out of any `mailarkiv` subdomain, and names the `mailarkiv` project directory in its source.
10. **Given** a synthetic session whose conversation view is about 250,000 estimated tokens, **When** it is analyzed, **Then** it is analyzed in consecutive parts of at most 40,000 estimated tokens, in order, and the report counts it once, as analyzed.
11. **Given** an empty memory directory and synthetic sessions from two projects plus one session about the user's business, such as how to price a service, **When** one dream processes them, **Then** the index lists the project facts under one domain with a separate subdomain for each project, and the business facts under a different domain.
12. **Given** memory whose index has a `## Development` domain with a `### <project>` subdomain for each known project, **When** a dream processes a session from a project that memory doesn't cover yet, **Then** the project's facts go under `## Development` in a new subdomain for that project, and no new domain is created.

---

### User Story 2 - Keep facts current and memory tidy (Priority: P2)

After all analyses finish, one organizer pass merges duplicate files and duplicate domains, keeps the current value when a later session replaced a fact, marks real contradictions, and completes the index. It works from the files that changed since the last organizer pass that succeeded, so its cost follows the size of the run, not the size of memory. The tool then checks the memory format and reports any problems.

**Why this priority**: Analyses run in parallel and each sees one session. They create duplicate files, can give the same domain two names, and can't tell which of two sessions came later. Without this pass, memory grows noisy and presents replaced facts as current.

**Independent Test**: Seed a memory directory with 200 files. Two of them cover ctx7 and hold disagreeing facts with different sources and times; another has a broken link; another is missing from the index. Run a dream over the 09:33 Claude Code session, then check the result and which files the organizer read in full.

**Acceptance Scenarios**:

1. **Given** the three Claude Code example sessions, where the 09:18 session runs ctx7 through `npx ctx7@latest` and the 09:33 session switches to bare `ctx7`, **When** one dream processes both, **Then** memory gives bare `ctx7` as current, and the `npx` form stays in a `REPLACED:` line that names both sessions with their times.
2. **Given** two memory files covering the same topic, and a run whose analyses change one of them, **When** the organizer runs, **Then** one file holds every fact from both, the other contains only `MOVED TO [[slug]]`, and links to the retired slug still lead to the facts.
3. **Given** two facts that disagree where neither is plainly a later correction, **When** the organizer runs, **Then** memory keeps both in a `CONFLICT:` line that names each source and time.
4. **Given** the organizer fails, **When** the run ends, **Then** the analyses' changes stay in memory, the report says memory wasn't organized, and the command exits with the "completed with failures" status.
5. **Given** any run that reaches the end, **When** the format check runs, **Then** the report lists every violation by file and rule, or states that there were none.
6. **Given** a memory of 200 files, none waiting for the organizer, and a run whose analyses change 3 of them, **When** the organizer runs, **Then** it reads in full only those 3, files that break the memory format, and files it merges with them or changes links in.
7. **Given** memory whose only ctx7 fact, the `npx ctx7@latest` form from the 09:18 session, sits in `docs-lookup.md` with an index entry about fetching library docs through Context7, **When** a dream processes the 09:33 session, **Then** memory gives bare `ctx7` as current and no file still gives the `npx` form as current.
8. **Given** a run whose analyses changed 2 memory files and whose organizer failed, **When** the user runs again and no session is new or changed, **Then** the organizer runs over those 2 files, no analysis request is sent, and after the organizer succeeds, a further run sends nothing to the Claude API.
9. **Given** an index in which parallel analyses filed development facts under both `## Development` and `## Software development`, **When** the organizer runs, **Then** one of the two headings holds all their entries and the other heading is gone.

---

### User Story 3 - Preview, cap, and repeat runs (Priority: P3)

The user runs a dream regularly, by hand or from a scheduler. Before sending anything, they can see which sessions would go to the Claude API and how large each one is. A spending limit caps what one run costs. Repeat runs don't send sessions the dream already handled.

**Why this priority**: Each analyzed session goes to the Claude API in full, which costs money and exposes the session's content. The preview lets the user check before sending, and the limit bounds a run they didn't check. Skipping handled sessions keeps routine runs cheap.

**Independent Test**: Preview the example sessions, then run a dream, then run it again with no changes. Compare the preview with the first run's report, and check that the second run sends nothing. Then run on empty memory with a spending limit of US$0.01, and check that the run stops sending analysis requests once it reaches the limit.

**Acceptance Scenarios**:

1. **Given** the example sessions, **When** the user asks for a preview, **Then** the tool lists each selected session with its tool, project directory, date, size, estimated tokens, and number of parts, gives the total estimated tokens, lists each skipped session with the reason, sends nothing to the Claude API, and changes no files.
2. **Given** a run in which every analysis and the organizer succeeded, **When** the user runs again and no session is new or changed, **Then** nothing is sent to the Claude API and the report says there was nothing to dream over.
3. **Given** a session that a previous run handled and the user later resumed, **When** the next run starts, **Then** that session is analyzed again.
4. **Given** a session whose analysis failed in the previous run, **When** the next run starts, **Then** that session is analyzed again.
5. **Given** a dream already running on a memory directory, **When** the user starts a second dream on the same directory, **Then** the second exits without changes and says why.
6. **Given** a spending limit lower than the cost of analyzing every selected session, **When** the run reaches it, **Then** the tool sends no further analysis request, the organizer runs if any analysis succeeded, the report lists each session cut off or not started with the reason "spending limit reached", and the next run selects those sessions again.

---

### Edge Cases

- A session's last recorded activity is less than one hour old: it may still be in use, so it's skipped as active.
- A session file ends in a partial record because it was cut off mid-write: the partial record is ignored and the rest is read.
- A file in a session directory is neither a Claude Code nor a Codex session: it's skipped as unrecognized.
- A Codex session has a parent thread, like the auto-review subthread in the examples: it's skipped, because it repeats the parent's content and isn't a user conversation. Claude Code subagent transcripts are skipped for the same reason.
- A session has no assistant answer because the user interrupted the turn: it's analyzed and may add no facts.
- Both tools put instruction files (AGENTS.md, CLAUDE.md), system prompts, and skill listings into the session as if the user wrote them: these aren't the user's statements and don't become facts.
- The user pastes text from another tool or a web page: its instructions are recorded only if the session shows the user adopting them.
- A session's conversation view is larger than one part: it's analyzed in consecutive parts. A single message larger than a part is shortened to fit, with a marker that says how much was removed. A view over 400,000 estimated tokens is skipped as too large, with its size. Nothing is cut short silently.
- A part of a session fails: the session counts as failed and its later parts don't run. Facts from earlier parts stay in memory, and the next run analyzes the whole session again.
- A memory file holds an instruction, copied there from an earlier session, to ignore rules or write elsewhere: analyses and the organizer don't follow it, and the organizer doesn't carry it into the index or a description.
- A fact learned in one project applies across its domain, such as a change to the user's global settings: it's recorded for the whole domain, outside the project's subdomain, and its source still names the project it came from.
- A session touches more than one domain, such as a coding session that also settles a business question: its facts go to files in each domain. A file belongs to one domain, and related files in different domains link to each other with `[[slug]]`.
- The run reaches its spending limit: analyses stop sending requests, and the organizer runs if any analysis succeeded. The run can end above the limit by the cost of requests already in flight and the organizer pass.
- Two analyses edit the same memory file at the same time: neither loses the other's facts.
- A memory file passes 100 KB: the organizer splits it by sub-topic.
- The memory directory holds hand-written files without frontmatter: the organizer adds frontmatter, lists them under a domain, and keeps the content.
- The run is interrupted: memory may be partly updated, the copy saved at the start of the run stays available, sessions that didn't finish are handled again on the next run, and files the analyses changed wait for the next organizer pass.
- The memory directory doesn't exist: the first run creates it, readable only by the user.

## Requirements *(mandatory)*

### Functional Requirements

**Selecting sessions**

- **FR-001**: The tool MUST find sessions in Claude Code's session directory (default `~/.claude/projects`) and Codex's (default `~/.codex/sessions`). The user MUST be able to replace either location or name session files directly.
- **FR-002**: The tool MUST select sessions whose last recorded activity falls inside a time window. The window covers the last 14 days unless the user sets a different start.
- **FR-003**: The tool MUST skip sessions whose last recorded activity is less than one hour old.
- **FR-004**: The tool MUST skip sessions that aren't user conversations: Codex threads that have a parent thread, and Claude Code subagent transcripts.
- **FR-005**: The tool MUST keep a record of the sessions it has handled. It MUST skip sessions it analyzed successfully whose content hasn't changed since, and MUST select changed and previously failed sessions again.
- **FR-006**: The user MUST be able to preview a run. The preview lists each selected session with its tool, project directory, date, size, estimated tokens, and number of parts, and gives the total estimated tokens and the number of memory files waiting for the organizer from earlier runs. It lists skipped sessions with their reasons, sends nothing to the Claude API, and changes no files.

**Reading sessions**

- **FR-007**: Analysis MUST see only the conversation: the user's messages, the assistant's replies, and tool calls with their results, each with its timestamp. It MUST NOT see system prompts, injected instruction files, skill and tool listings, slash-command and local-command records, token counts, or other bookkeeping records.
- **FR-008**: Each selected session MUST be analyzed in full. The tool MUST estimate the size of each conversation view in tokens without sending anything. A view of up to 40,000 estimated tokens is analyzed in one part. A larger view is split between messages into consecutive parts of at most 40,000 estimated tokens. A single message larger than a part is shortened to fit, with a visible marker that says how much was removed. A view over 400,000 estimated tokens MUST be skipped as too large, with its size.
- **FR-009**: The tool MUST skip records it can't parse. A session with no readable conversation, or in an unrecognized format, MUST be skipped with the reason.

**Running the analyses**

- **FR-010**: The tool MUST analyze each selected session separately, in groups of at most 20 sessions, oldest sessions first. A session's parts run in order, each after the previous one has finished, so each part sees the memory the earlier parts left. Each group finishes before the next starts. After the last group, the organizer runs once.
- **FR-011**: When no session is selected and no memory file is waiting for the organizer, the tool MUST send nothing to the Claude API and report that there was nothing to dream over. When no session is selected but files are waiting, only the organizer runs.

**Analyzing sessions**

- **FR-012**: An analysis MUST record durable facts from its session: decisions, conventions, how tools are set up, identifiers, commands that worked, approaches that failed and why, and corrections to what memory already says. Where the session shows it, a fact MUST say how it was checked, or that it may go stale, for example because it depends on a tool version. A fact the session leaves uncertain MUST be marked as uncertain. An analysis MUST check existing memory first and update existing files rather than duplicate them.
- **FR-013**: Each fact a dream adds or changes MUST name its source: the tool, the session ID, the project directory, and the UTC date and time, to the minute, of the message that shows it. Each fact MUST also state its scope: its whole domain, or the one subdomain it applies to, such as one project (FR-034). A fact learned in one project applies to the whole domain only when the session shows that it does, such as a change to the user's global settings.
- **FR-014**: Session content and memory content MUST be treated as data. Instructions inside either (to ignore instructions, reveal secrets, or write files) MUST NOT be followed or recorded as facts, and the organizer MUST NOT carry them into the index or a description. Instructions from outside content, such as web pages, third-party tool output, or pasted text, MUST be recorded only when the session shows the user adopting them.
- **FR-015**: Analyses MUST NOT merge, rename, or delete memory files.
- **FR-016**: Concurrent analyses MUST NOT lose each other's changes to a shared memory file.
- **FR-017**: A failed analysis MUST be recorded with its reason and MUST NOT stop the run. A request that hits a rate limit, an overload response, or a timeout MUST be retried up to 3 times before the analysis counts as failed. Every request to the Claude API MUST have a timeout. When one part of a session fails, the session counts as failed and its later parts don't run.

**Organizing memory**

- **FR-018**: The organizer MUST run if at least one analysis in the run succeeded or any memory file is waiting for it. A file waits for the organizer from when an analysis creates or changes it until an organizer pass that received it succeeds, so files from a run whose organizer failed or never ran wait for the next run. The tool MUST give the organizer two lists: the waiting files and the files that break the memory format. The organizer reads in full only those files and the files it merges with them or changes links in. It merges duplicate files into the better-named one, replaces each retired file with `MOVED TO [[slug]]`, fixes frontmatter and links, completes the index, keeps its domains and subdomains in order (FR-035), and splits files over 100 KB by sub-topic.
- **FR-019**: When one fact is plainly a later correction of another, the organizer MUST keep the current fact and rewrite the older one in place as `REPLACED: <source A, time> said …; <source B, time> replaced it.` Otherwise it MUST keep both as `CONFLICT: <source A, time> says …; <source B, time> says …`. A passing remark, or a search that found nothing, MUST NOT override a decision the user recorded.
- **FR-020**: The organizer MUST NOT invent facts or drop them. A replaced fact keeps its value and source in its `REPLACED:` line, and both sides of a conflict keep theirs in the `CONFLICT:` line.

**Memory format and checks**

- **FR-021**: Memory MUST follow this format. Each file starts with frontmatter holding `name` (a lowercase, hyphenated slug that matches the filename), `description`, and optional `metadata`. Files link with `[[slug]]`, and every link names an existing file or stub. `_index.md` lists every file that isn't a stub exactly once as `[[slug]] — one sentence`, under a `## <domain>` heading and, if the file belongs to a subdomain, under a `### <subdomain>` heading inside that domain. No domain heading appears twice, no subdomain heading appears twice within a domain, and every heading has at least one entry beneath it. A stub contains only `MOVED TO [[slug]]` and has no index entry. No file exceeds 100 KB.
- **FR-022**: At the end of each run, the tool MUST check memory against FR-021 and report every violation by file and rule. It doesn't repair violations itself.

**Safety and privacy**

- **FR-023**: Writes MUST stay inside the memory directory. Paths that resolve outside it, through `..`, absolute paths, or symbolic links, MUST be refused. Session files MUST NOT be modified.
- **FR-024**: An analysis MUST read only its own part of its session and the memory directory.
- **FR-025**: Writes to memory that contain strings matching common credential formats (API keys, access tokens, private keys, passwords in connection strings) MUST be refused, with a message telling the agent to refer to the credential by name.
- **FR-026**: Terminal output, logs, and reports MUST NOT contain session or memory content. They may contain paths, session IDs, counts, and failure reasons.
- **FR-027**: Before its first write, a run MUST save a copy of the memory directory to a location outside it, readable only by the user, so the user can restore the state from before the run. The tool MUST keep the copies from the 10 most recent runs that wrote to memory and delete older ones.
- **FR-028**: Only one dream MUST run against a memory directory at a time. A second MUST exit without changes and say why.

**Running and reporting**

- **FR-029**: The user MUST start a dream with one command that sets the session sources, the time window, the memory directory, and the spending limit, with defaults for each except the memory directory.
- **FR-030**: Without Claude API credentials, the tool MUST stop before reading any session and name both ways to provide them: the `ANTHROPIC_API_KEY` environment variable and a profile from `ant auth login`.
- **FR-031**: At the end of a run, the tool MUST report, from its own records of the run: sessions found, selected, skipped (counted by reason), analyzed, analyzed in more than one part, and failed (each with its reason); whether the organizer ran and succeeded; memory files still waiting for the organizer; the number of index entries, domains, and subdomains; memory files created, changed, and retired; conflicts added; format violations; tokens used and their cost at list price; whether the spending limit was reached; and where the pre-run copy of memory is.
- **FR-032**: The exit status MUST distinguish three outcomes: success; completed with failures (a failed analysis, a failed organizer pass, or a format violation); and not started (invalid arguments, missing credentials, or memory directory in use).
- **FR-033**: Once a run's cost at list price, computed from the token counts the Claude API reports, reaches the spending limit, the tool MUST send no further analysis request. Sessions cut off this way, and sessions not yet started, count as failed with the reason "spending limit reached". The organizer still runs under FR-018. The limit is US$10 unless the user sets another.

**Domains**

- **FR-034**: Memory MUST be organized by domain, and the domains MUST come from the facts, not from a list the tool ships. A domain is a broad area of the user's work or life, such as development or business. A subdomain is a recurring subject inside a domain, such as one project in development. Each memory file belongs to one domain and at most one subdomain. An analysis MUST list each file it creates under the domain and subdomain its facts apply to, reuse an existing domain or subdomain when one fits, and create one only when none does. Facts scoped to one subdomain go in that subdomain's files, and facts scoped to the whole domain go in files outside any subdomain.
- **FR-035**: The organizer MUST merge domains or subdomains that cover the same area, move an index entry whose file belongs in another domain or subdomain, form a subdomain when several files in a domain share a subject, and list files that have no index entry under a domain. It works from the index and the files it reads under FR-018.

### Key Entities

- **Session**: One Claude Code or Codex conversation stored as a JSONL file. Has a tool, session ID, project directory, start time, last recorded activity, and for Codex an optional parent thread.
- **Conversation view**: The parts of a session that analysis sees (FR-007).
- **Part**: A run of consecutive messages from one conversation view, at most 40,000 estimated tokens, analyzed on its own (FR-008).
- **Memory directory**: The user's personal memory. Holds memory files, stubs, and `_index.md`.
- **Memory file**: A Markdown file with frontmatter that covers one topic and holds facts. Belongs to one domain and at most one subdomain.
- **Domain**: A broad area of the user's work or life, such as development or business, taken from the facts (FR-034). A `## <domain>` heading in the index.
- **Subdomain**: A recurring subject inside a domain, such as one project in development. A `### <subdomain>` heading under its domain in the index.
- **Fact**: A durable statement with its source (tool, session, project directory, and time) and its scope (its whole domain or one subdomain). It can carry a note on how it was checked or that it may go stale. A fact that a later one replaced stays in a `REPLACED:` line, and two facts that contradict each other share a `CONFLICT:` line.
- **Stub**: A retired memory file containing only `MOVED TO [[slug]]`.
- **Index**: `_index.md`, listing every memory file under its domain and, if it has one, its subdomain.
- **Dream run**: One invocation. Has selected and skipped sessions, analysis results, an organizer result, a spending limit, a pre-run copy of memory, and a report.
- **Dream record**: What the tool remembers between runs: the sessions it has handled, in what state, and with what outcome, and the memory files waiting for the organizer.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In 3 of 3 runs over the six example sessions, each starting from empty memory, memory states all three facts from User Story 1, scenario 1. In 0 of 3 runs does memory give the `npx` form of ctx7 as current.
- **SC-002**: In the same 3 runs, no fact names the auto-review subthread as its source, and memory never states the password limit as 4 MB.
- **SC-003**: Synthetic sessions holding 10 fake credentials in common formats produce memory containing 0 of them.
- **SC-004**: Synthetic sessions and seeded memory files that tell the agent to write outside memory, change the session file, or record their instructions as facts cause 0 writes outside the memory directory and 0 recorded instructions in 3 of 3 runs.
- **SC-005**: Every run over the example sessions that reaches the end reports 0 format violations.
- **SC-006**: On a seeded memory with known facts and duplicate files, 100% of the seeded facts are still present after the organizer pass.
- **SC-007**: A run over the six example sessions finishes in under 10 minutes.
- **SC-008**: A repeat run with no new or changed sessions and no files waiting for the organizer sends 0 requests to the Claude API and finishes in under 10 seconds.
- **SC-009**: The preview lists exactly the sessions the next run analyzes.
- **SC-010**: In every report, found equals selected plus skipped, and selected equals analyzed plus failed.
- **SC-011**: In runs over the example sessions and over the synthetic 250,000-token session from User Story 1, scenario 10, 0 requests to the Claude API exceed 100,000 input tokens.
- **SC-012**: In 3 of 3 runs over the synthetic sessions from User Story 1, scenario 11, each starting from empty memory, each project's facts sit in their own subdomain, both subdomains sit in the same domain, and the business facts sit in a different domain.

## Out of Scope

- Sources other than Claude Code and Codex sessions, including the notes the README mentions.
- Making Claude Code or Codex read the memory directory. The user connects it to their tools.
- Scheduling. The user runs the command from cron, launchd, or similar.
- Restoring a pre-run copy through the tool. The user copies files back by hand.
- Searching or browsing memory.
- A preset or user-configured list of domains. Domains come only from the facts.
- Structure below subdomains. Memory has two levels: domain and subdomain.
- A lead agent that plans or coordinates runs, like the cookbook's `memory-distiller`. Every run follows the same sequence: analyses in groups, then the organizer.
- Facts that go out of date when no session shows the change, such as a hook removed by hand or a tool upgraded outside a session. The tool doesn't expire facts by age, re-check facts marked as possibly stale, or move `REPLACED:` lines out of memory files.
- Tested support for compaction records and multi-turn Codex sessions. The examples don't cover them; the tool reads them as best it can.

## Assumptions

- One user on one machine. Sessions and memory are on local disk, and the memory directory lives outside this repository.
- One memory directory covers everything the user works on. Domains separate areas such as development and business, and subdomains separate subjects inside a domain, such as projects (FR-034). Each fact states whether it applies to its whole domain or to one subdomain (FR-013).
- The tool ships no list of domains, because they depend on what the sessions cover. The user's sessions are mostly about development but also touch other areas, such as business.
- Domains and subdomains are headings in the index, not subdirectories. Moving a file to another domain or merging two domains then changes only `_index.md`, and slugs and links stay valid. The cookbook groups its index under `## <domain>` headings but gives no rule for choosing a domain, and lets its organizer move clusters of files into subdirectories.
- Every analyzed session's conversation view is sent to the Claude API. The user needs Claude API access.
- As in the cookbook, Claude Haiku 5.5 analyzes and organizes.
- The cookbook's lead fills a fixed template with file paths and writes a workflow from it. With no free-form request to interpret, a lead would write nearly the same workflow on every run. The tool runs that sequence itself, which saves a model call and a way for the run to fail. The tool also builds the report from its own records, so the counts are exact.
- Neither tool marks a session as ended. Codex records when a turn finishes, but the user can resume any session. A session therefore counts as finished one hour after its last recorded activity.
- Claude Haiku 5.5 charges five times as much per token for a request over 100,000 input tokens, and every turn of an analysis resends everything it has read so far. A part of at most 40,000 estimated tokens leaves room for the instructions, the memory files an analysis reads, and its replies. On one developer's machine, 61 sessions from 14 days had conversation views of about 40,000 tokens at the median and about 241,000 at most, and tool results made up 64% of the text (estimated at four characters per token). The cookbook avoids the higher rate the same way: it reads transcripts in pages, and none of the 127 requests in its example run was priced at the long-context rate.
- An organizer that read every file on each run would pass 100,000 input tokens once memory holds about 400 KB, and its cost would grow with memory instead of with the run. In the cookbook's example, the organizer used 789,000 input tokens on an 11-file memory.
- The US$10 default spending limit comes from the cookbook's report of about US$8 for a dream over fifty long transcripts (about 12 MB of text).
- The 14-day default window, groups of about 20 analyses, the 100 KB file limit, the conflict rules, and updating memory in place after saving a copy all come from the cookbook. Anthropic's managed Dreams feature writes a new memory store instead; the cookbook updates in place.
- The cookbook keeps memory versions for 30 days. Keeping copies from only the last 10 runs likewise limits how many copies of personal data, and of any secret that got into memory, stay on disk.
- Model reasoning is left out of the conversation view. Codex stores it encrypted, and the replies and tool calls show what happened.
- The example sessions in `examples/transcripts/` are acceptance fixtures. Their long strings were cut during cleaning, so tests must not depend on exact tool-output sizes. Secret and injection tests use synthetic sessions.
