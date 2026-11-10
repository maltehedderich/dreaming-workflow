# Repository Guidelines

## Engineering Policy

Read [the engineering constitution](.specify/memory/constitution.md) before planning or implementing changes. This project adopted shared **version 1.0.0** (ratified 2026-11-06) on 2026-11-10 as its authoritative engineering policy. It overrides conflicting repository guidance. Check changes against its principles and record exceptions in the plan's Complexity Tracking section.

## Tooling

This is a Python command-line tool with no frontend.

- uv manages dependencies in `pyproject.toml` and locks them in `uv.lock`. Run code with `uv run` and add packages with `uv add`. Don't use pip, poetry, or `python -m venv`.
- `mise run` is the only interface for checks, so CI, docs, and people all use the same commands. mise pins the Python and uv versions. Use the standard task names `setup`, `lint`, `format`, `typecheck`, `test`, and `check`. CI gates on `check`.

## Required checks

There is no code yet, so no checks are configured. The change that adds the first code also adds `pyproject.toml`, `mise.toml`, the tasks above, and a CI workflow, and lists each task's commands and test layer in a table here.

- For documentation-only changes, review affected text against the constitution, check local links, and verify that scope and acceptance behavior agree across documents. These checks are sufficient while runtime behavior is unchanged.
- When adding tooling, document its exact required check commands here in the same change. Feature plans must identify the checks that apply and the layer each runs at.
- Report checks run and any that could not run, with the reason and remaining risk. Do not report an unconfigured check as passed.

## Personal data

Transcripts and memory files contain personal data. Never commit them or write their contents to logs. Use synthetic transcripts and memory files in tests, fixtures, and docs.

## Code comments

Use clear names and simple code. Comment only on non-obvious decisions, constraints, invariants, safety rules, or public contracts. Keep comments short and self-contained; put longer rationale in maintained documentation. Update or delete stale comments when changing the code.

Do not reference feature specs, plans, task lists, or their numbered requirements and scenarios in code comments (including tests). Those documents may be deleted, and identifiers such as `FR-003` are reused across features. State the relevant behavior or reason directly. Links to maintained documentation or external standards may supplement an explanation, but must not replace it.

## Writing

These rules apply to everything you write: docs, UI copy, comments, commit messages, and replies.

- Write for a specific reader and put the main point first, so it lands on the first read.
- Use ordinary words, short sentences, and concrete nouns. Use a technical term only when it adds needed precision.
- Back claims with names, numbers, examples, comparisons, or observed behavior from the source material. Never invent specifics or hide missing substance behind vague language.
- Cut throat-clearing, stacked hedges, empty adjectives, repetition, and clever phrasing. Stop when the work is done, without a summary, moral, or generic closing.
- Keep a human voice: no corporate tone, platform formulas, motivational filler, or repetitive AI-style sentence patterns.
- Tighten every non-trivial draft before you return it. Cut words that don't change the meaning, and keep the author's intent and useful nuance.

Commit messages follow Conventional Commits with a scope, such as `fix(memory): …`.
