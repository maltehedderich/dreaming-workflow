# Shared Engineering Constitution

## Core Principles

### I. User Value, YAGNI, and Bounded Scope

_Rationale: Speculative work costs delay and carry even when the guess is right._

- Every change MUST serve a current user, operator, or maintainer need. Deliver the smallest complete change that satisfies it.
- Bug fixes MUST stay focused on the defect; unrelated cleanup is separate work.
- Generalize only for current variation: parameters, options, generic types, base classes, and extension points MUST serve at least two current callers or variants. Extracting a well-named function to separate intention from implementation is always allowed; inline wrappers that add neither a name nor a boundary. When an abstraction accumulates flags for diverging callers, inline it again.
- Add configuration only for a concrete present requirement. Hypothetical consumers or future scale do not justify complexity.
- Follow established codebase patterns. A second way to do something already done requires an ADR and a plan to converge.

### II. Modular Architecture

_Rationale: Modules give most of the benefits of services without the operational cost._

- Default to a modular monolith: cohesive modules within one deployable application.
- Define modules around business capabilities as complexity grows, keeping presentation, domain logic, and data access distinct within each. Small applications may use a simpler structure.
- Modules MUST expose clear contracts and keep implementation details private. Access another module's behavior and data only through its declared interface. A shared database is allowed; each table MUST have exactly one owning module, and only that module writes to it.
- A separately deployed frontend or native client is allowed. Other services need a distinct current purpose or a demonstrated need for independent scaling, security isolation, or deployment, and the plan MUST justify the boundary against its operational cost.
- Interface adapters (HTTP, CLI, MCP, background jobs) MUST reuse the owning application's business operations and authorization rules and contain only protocol and presentation concerns.

### III. Explicit Contracts and Failures

_Rationale: Precise types and loud failures catch bugs early instead of letting them corrupt data silently._

- Represent distinct states and values distinctly: narrow unions or enums instead of open strings or combinations of boolean flags, explicit nullability, and domain types where mixing up values is a credible bug.
- Type escape hatches such as `any`, unchecked casts, and untyped maps MUST stay in the narrowest scope and state their reason where used.
- Code at trust boundaries MUST parse untrusted input into precise types once. Inner code relies on those types and on established internal contracts; validation, error handling, and fallbacks MUST address failures that can occur in the current system.
- Code MUST NOT swallow errors or substitute defaults that hide a failure. Fail fast and visibly, with enough context to diagnose the cause.
- Every network call MUST have a timeout, and network and asynchronous boundaries MUST define failure behavior. Retried operations MUST be idempotent where duplicate effects would be harmful.
- Contract changes MUST update affected consumers together or use expand, migrate, contract.

### IV. Security and Privacy by Default

_Rationale: Security and privacy failures are often irreversible, so safe must be the default._

- Secrets and personal data MUST NOT appear in the repository, logs, error reports, or analytics.
- Authorization MUST be enforced server-side on every operation and deny by default. Credentials get only the permissions they need.
- Keep dependencies few. Each one is code you run with full trust and must keep updated. Prefer the standard library, the platform, and existing dependencies. Add a new one only when it replaces substantial or hard-to-get-right code, such as cryptography, parsing, or protocol handling.
- Before adding a dependency, confirm it is the intended package and is maintained. Choose a version with no known vulnerabilities and pin it.

### V. Test According to Risk

_Rationale: Tests exist for justified confidence at reasonable cost; a test that lies or flakes is worse than none._

- Before implementation, identify credible failures by likelihood and harm, then choose the smallest verification effort that gives justified confidence. Brief notes are enough for small changes.
- Automate affected high-risk behavior and stable, valuable regression paths, especially payments, authentication, authorization, tenant isolation, data integrity, irreversible actions, retries, and public contracts. Bug fixes SHOULD start with a test that reproduces the defect.
- Cosmetic, trivial, or stable glue changes MAY rely on existing checks and review when the plan explains why that is sufficient.
- TDD is optional, for when uncertainty or logic complexity makes it useful. When used, follow Canon TDD: keep a test list, turn one item into a failing test, make all tests pass, refactor, repeat.
- Tests and checks MUST NOT be deleted, skipped, or weakened to make a change pass. Change a test only when the specified behavior changed, and say so in the change. Expected values MUST come from the specification or independent reasoning, never from running the code under test.
- Tests MUST assert observable behavior and public contracts and survive behavior-preserving refactors. Put each check at the lowest, fastest layer that would catch the failure; reserve end-to-end and UI automation for critical journeys and remove redundant checks.
- Use real collaborators for dependencies you own, such as your modules and database. Use test doubles for systems you do not control and for nondeterminism such as time.
- Use time-boxed exploratory testing when scripted checks leave material uncertainty about new or risky behavior. Automate repeatable findings worth protecting.
- Tests MUST be deterministic and isolated; keep the default suite fast enough to run on every change. Fix or delete flaky tests, or quarantine them with an owner and removal condition. Blanket retries and ignored failures are prohibited.
- Coverage and test counts are diagnostics, never delivery targets.

### VI. Small Batches, Fast Feedback

_Rationale: Small batches give fast feedback and cheap rollback. Internal quality sustains speed and is never traded for it._

- Deliver cross-layer work as vertical slices: narrow but complete paths through every affected layer, including verification, each demoable or verifiable on its own. Start with a walking skeleton, the thinnest path that proves the integration works. Slices govern delivery order, not code structure.
- Build shared foundations only as far as the next slice needs. Land preparatory refactoring as separate structural commits before the behavior change. A wide mechanical change that cannot land green as one slice uses expand, migrate, contract.
- The main branch MUST stay releasable: a failing build is fixed or reverted before other work continues. Unreleased behavior stays behind a flag or an unrouted entry point; remove the flag once the behavior is released.
- Run the project's required checks, as defined in `AGENTS.md`, for affected code. Report any check that could not run, the reason, and the remaining risk.
- Stop verification when required checks have passed and prioritized risks have credible evidence. Add further checks only when their confidence justifies their cost.
- A slice that changes a critical path is done only when its failures would be visible in production, for example in error tracking.
- Update affected contracts and documentation in the same change. Keep planning and review proportional to the change.

## Governance

- This constitution is the authoritative engineering policy for projects that adopt it and overrides conflicting repository guidance. `AGENTS.md` and other project documents define tooling, commands, and local details within it.
- MUST, MUST NOT, SHOULD, and MAY are used as defined in RFC 2119 and RFC 8174. Unmarked imperatives are SHOULD: a plan may deviate if it states why.
- Rules that tooling can check SHOULD be enforced in CI by type checkers, linters, module dependency rules, and tests. This document states intent; automated checks enforce it.
- Projects MAY add stricter or additional rules in a Project Addendum section at the end of their constitution. Weakening a shared MUST requires a recorded exception. Each project records the shared version it adopted.
- Specifications MUST define scope, exclusions, and observable acceptance behavior. Plans MUST check constitutional compliance and identify each required check and the layer it runs at. Task lists MUST contain only work needed for that scope and verification, ordered as slices that each end in verifiable behavior.
- Reviews MUST check compliance. Unjustified complexity or an unresolved MUST violation blocks merge.
- Any exception MUST be recorded in the plan's Complexity Tracking section with the concrete present need and the simpler alternative rejected. Choices explicitly allowed by this constitution are not exceptions. When the same exception recurs, amend the rule instead.
- Record decisions that outlast a single feature, such as a new dependency, service, or pattern, as a short architecture decision record (ADR) in the repository.
- Amendments MUST state their rationale and impact and update affected templates and guidance. Versioning is semantic: MAJOR for incompatible principle or governance changes, MINOR for new principles or materially expanded obligations, PATCH for clarification.

**Status**: Approved and ratified | **Version**: 1.0.0 | **Ratified**: 2026-11-06 | **Last Amended**: 2026-11-06
