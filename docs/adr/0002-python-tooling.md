# 2. Python 3.15, uv, mise, ruff, ty, and pytest

- **Status**: Accepted
- **Date**: 2026-11-11

## Context

`dream` is a single-user Python command-line tool for macOS and Linux. It needs a Python version that its three runtime dependencies support, one way to install and run it, and checks that people and CI run the same way.

## Decision

**Python 3.15.** It gets security fixes until October 2031, a year longer than 3.14. UTF-8 mode is on by default, so reading transcripts doesn't depend on the system locale. On 2026-11-11 the full locked tree installed on CPython 3.15.2. Every package has a 3.15 wheel except PyYAML 6.0.3, which uv builds from its sdist in seconds; the pure-Python parser it falls back to is fast enough for frontmatter.

**uv** manages dependencies. `pyproject.toml` pins each direct dependency exactly, `uv.lock` locks the whole tree, and `uv_build` builds the package from `src/`.

**mise** pins Python and uv (`mise.toml`, with exact versions and checksums in `mise.lock`), and its tasks are the only interface for checks: `setup`, `format`, `lint`, `typecheck`, `test`, `check`, and `eval`. CI runs `mise run setup` and `mise run check` through `jdx/mise-action`, pinned to a commit SHA. `UV_PYTHON_PREFERENCE=only-system` makes uv use the Python that mise installed.

**ruff** lints and formats, with the `ANN` and `PYI` rule groups added to the defaults, because ty doesn't report missing annotations.

**ty** type-checks `src` and `tests`, set up as ty's mypy migration guide recommends for strict checking: the off-by-default rules `dynamic-function-decorator-return`, `missing-type-argument`, `possibly-unresolved-reference`, and `unsound-return-statement` are errors. ty exits non-zero on warnings too, so any diagnostic fails `check`. `Any`, `cast`, and `# ty: ignore[...]` are allowed only in `agents/claude_model.py`, where ADK's model interface requires them, each with a comment giving the reason. ty is in beta and ships almost daily (0.0.96 through 0.0.101 between 2026-11-03 and 2026-11-11), and an upgrade can add diagnostics. So it is pinned exactly at 0.0.101, and each upgrade is its own change.

**pytest** runs four layers:

| Layer | Uses | In `mise run test` |
| --- | --- | --- |
| Unit | Pure functions and temporary directories | yes |
| Contract | The real `anthropic` SDK and ADK `Runner` against a fake Messages API | yes |
| Integration | Full `dream` runs with a scripted model, real ADK, real files | yes |
| Eval | The real Claude API | no: `mise run eval`, by hand |

Evals carry the `eval` marker, and the default options deselect it. They need credentials, cost money, and vary between runs, so they stay out of the default suite and CI.

## Alternatives considered

- **Python 3.14**: every package has a wheel, but security support ends a year earlier.
- **mypy `--strict`**: the reference checker, stable, with strict mode built in. ty fits the Astral toolchain the project already uses for uv and ruff.
- **pyright**: another separate toolchain.
- **click** for the CLI: ADK already ships it, but `argparse` from the standard library handles one command with a handful of options.

## Consequences

- PyYAML's sdist build fetches its build requirements at install time, outside `uv.lock` and the dependency audit. uv caches the built wheel.
- ty upgrades and ruff upgrades may need code changes; each lands as its own change with `mise run check` green.
- Windows isn't supported; the tool relies on `fcntl` and POSIX file modes.
