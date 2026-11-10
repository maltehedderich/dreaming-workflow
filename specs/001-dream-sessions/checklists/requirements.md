# Specification Quality Checklist: Dream over Claude Code and Codex sessions

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-11-10
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Two clarifications were resolved with the user on 2026-11-10. First, runs follow a fixed sequence: analyses in groups of at most 20, then one organizer pass (FR-010). The user first chose a lead agent that writes each run's workflow, then switched after seeing that the lead would write nearly the same workflow every run. Second, the tool keeps a record of handled sessions and skips unchanged ones (FR-005).
- The spec names Claude Code, Codex, their session locations, the JSONL format, the Claude API, `ANTHROPIC_API_KEY`, `ant auth login`, and the cookbook's models. These are the inputs, the external dependency, and the user-facing contract, not implementation choices. The spec leaves out ADK, Python, the Anthropic SDK, and the model connector, which belong in the plan.
- The reader is a developer who uses Claude Code and Codex, so developer terms count as plain language for this audience.
- SC-001, SC-002, SC-004, SC-006, and SC-012 depend on model output. They are measured over repeated runs and can't be checked by deterministic tests alone. The plan has to define how each is evaluated.
- The example sessions don't cover compaction or multi-turn Codex sessions. The spec lists them as out of scope for testing.
- Revised on 2026-11-10 after a comparison with the cookbook. Large sessions are analyzed in parts instead of failing (FR-008, FR-010). Fact sources name the project and a time, not only a date, and each fact states its scope (FR-013). Analyses also record failed approaches, how facts were checked, and what may go stale (FR-012). Memory content counts as untrusted (FR-014). The organizer works from the files the run changed (FR-018). A spending limit caps each run (FR-033). Pre-run copies live outside memory, and only the last 10 are kept (FR-027). The 40,000-token part size, the 400,000-token skip threshold, the US$10 default limit, and keeping 10 copies are first estimates for the plan to confirm.
- Revised on 2026-11-10 after a review of how memory handles outdated facts. A file waits for the organizer until a pass that received it succeeds, and the organizer runs without new sessions when files are waiting (FR-011, FR-018). Before this, a failed organizer left contradictions that no later pass would see. A replaced fact stays in a `REPLACED:` line, and FR-020 now protects facts rather than lines (FR-019, FR-020). User Story 2 adds scenarios for a correction whose old fact sits in a file with a different name and for recovery after a failed organizer. Facts that go stale without a session showing it are out of scope.
- Revised on 2026-11-10 to organize memory by domain. The user wants areas such as development and business, with projects as subdomains inside development, but no fixed list, because the areas depend on what the sessions cover. Analyses file each new file under a domain and subdomain, reusing existing ones first (FR-034). The organizer merges duplicate domains and subdomains and re-files entries (FR-035). A fact's scope is now its whole domain or one subdomain instead of all projects or one project (FR-013). Subdomains are `### <subdomain>` headings in the index, and the format check covers them (FR-021). User Story 1 adds scenarios 11 and 12, User Story 2 adds scenario 9, and SC-012 measures the result.
