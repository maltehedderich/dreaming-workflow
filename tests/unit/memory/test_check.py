from collections.abc import Callable
from pathlib import Path

import pytest

from dreaming_workflow.memory import FormatRule, FormatViolation, check_format
from tests.support.memory import (
    fact,
    memory_file_text,
    seeded_memory,
    write_index,
    write_memory_file,
    write_stub,
)

FACT = fact("Python work uses uv.")
INDEX = "_index.md"

type Setup = Callable[[Path], None]


def valid_memory(memory: Path) -> None:
    """Two listed files: a clean starting point that each case breaks in one way."""
    write_memory_file(memory, "uv-python", f"# uv\n\n{FACT}")
    write_memory_file(memory, "ctx7-setup", f"# ctx7\n\n{FACT}")
    write_index(
        memory,
        {
            "Development": {
                None: [("uv-python", "Python uses uv."), ("ctx7-setup", "ctx7.")]
            }
        },
    )


def write(memory: Path, name: str, text: str) -> None:
    (memory / name).write_text(text)


def bad_file_name(memory: Path) -> None:
    write(memory, "Notes.md", memory_file_text("notes", FACT))


def no_frontmatter(memory: Path) -> None:
    write(memory, "uv-python.md", f"# uv\n\n{FACT}")


def invalid_yaml(memory: Path) -> None:
    write(memory, "uv-python.md", f"---\nname: [uv-python\n---\n{FACT}")


def frontmatter_list(memory: Path) -> None:
    write(memory, "uv-python.md", f"---\n- uv-python\n---\n{FACT}")


def unclosed_frontmatter(memory: Path) -> None:
    write(memory, "uv-python.md", f"---\nname: uv-python\ndescription: uv.\n{FACT}")


def extra_key(memory: Path) -> None:
    write(
        memory,
        "uv-python.md",
        f"---\nname: uv-python\ndescription: uv.\ntags: python\n---\n{FACT}",
    )


def other_name(memory: Path) -> None:
    write(memory, "uv-python.md", memory_file_text("python-uv", FACT))


def empty_description(memory: Path) -> None:
    write(memory, "uv-python.md", f"---\nname: uv-python\ndescription: ''\n---\n{FACT}")


def too_large(memory: Path) -> None:
    write(memory, "uv-python.md", padded_to(100_001))


def link_to_nothing(memory: Path) -> None:
    write_memory_file(memory, "uv-python", f"# uv\n\n{FACT}\nSee [[missing]].\n")


def stub_marker_with_content(memory: Path) -> None:
    write_memory_file(memory, "uv-python", f"# uv\n\n{FACT}\nMOVED TO [[ctx7-setup]]\n")


def stub_cycle(memory: Path) -> None:
    write_stub(memory, "a", "b")
    write_stub(memory, "b", "a")


def index_deleted(memory: Path) -> None:
    (memory / INDEX).unlink()


def index_prose(memory: Path) -> None:
    with (memory / INDEX).open("a") as index:
        index.write("\nSome prose the user added.\n")


def unlisted_file(memory: Path) -> None:
    write_memory_file(memory, "unlisted", f"# Unlisted\n\n{FACT}")


def listed_twice(memory: Path) -> None:
    write_index(
        memory,
        {
            "Development": {
                None: [
                    ("uv-python", "Python uses uv."),
                    ("ctx7-setup", "ctx7."),
                    ("uv-python", "Again."),
                ]
            }
        },
    )


def stub_listed(memory: Path) -> None:
    write_stub(memory, "docs-lookup", "ctx7-setup")
    write_index(
        memory,
        {
            "Development": {
                None: [
                    ("uv-python", "Python uses uv."),
                    ("ctx7-setup", "ctx7."),
                    ("docs-lookup", "Old docs."),
                ]
            }
        },
    )


def listed_without_file(memory: Path) -> None:
    write_index(
        memory,
        {
            "Development": {
                None: [
                    ("uv-python", "Python uses uv."),
                    ("ctx7-setup", "ctx7."),
                    ("ghost", "Gone."),
                ]
            }
        },
    )


def domain_twice(memory: Path) -> None:
    write_index(
        memory,
        {
            "Development": {None: [("uv-python", "Python uses uv.")]},
            "development": {None: [("ctx7-setup", "ctx7.")]},
        },
    )


def subdomain_twice(memory: Path) -> None:
    write(
        memory,
        INDEX,
        "# Memory index\n\n## Development\n\n"
        "### alpha\n\n- [[uv-python]] — Python uses uv.\n\n"
        "### Alpha\n\n- [[ctx7-setup]] — ctx7.\n",
    )


def empty_domain(memory: Path) -> None:
    with (memory / INDEX).open("a") as index:
        index.write("\n## Business\n")


def empty_subdomain(memory: Path) -> None:
    with (memory / INDEX).open("a") as index:
        index.write("\n### later\n")


def orphan_subdomain(memory: Path) -> None:
    write(
        memory,
        INDEX,
        "# Memory index\n\n### alpha\n\n- [[uv-python]] — Python uses uv.\n\n"
        "## Development\n\n- [[ctx7-setup]] — ctx7.\n",
    )


def padded_to(size: int) -> str:
    start = memory_file_text("uv-python", f"# uv\n\n{FACT}")
    return start + "x" * (size - len(start.encode()) - 1) + "\n"


@pytest.mark.parametrize(
    ("breaks", "expected"),
    [
        (bad_file_name, [("Notes.md", FormatRule.FILE_NAME)]),
        (no_frontmatter, [("uv-python.md", FormatRule.FRONTMATTER_MISSING)]),
        (invalid_yaml, [("uv-python.md", FormatRule.FRONTMATTER_INVALID)]),
        (frontmatter_list, [("uv-python.md", FormatRule.FRONTMATTER_INVALID)]),
        (unclosed_frontmatter, [("uv-python.md", FormatRule.FRONTMATTER_INVALID)]),
        (extra_key, [("uv-python.md", FormatRule.FRONTMATTER_KEY)]),
        (other_name, [("uv-python.md", FormatRule.NAME_MISMATCH)]),
        (empty_description, [("uv-python.md", FormatRule.DESCRIPTION_MISSING)]),
        (too_large, [("uv-python.md", FormatRule.FILE_TOO_LARGE)]),
        (link_to_nothing, [("uv-python.md", FormatRule.BROKEN_LINK)]),
        (stub_marker_with_content, [("uv-python.md", FormatRule.STUB_INVALID)]),
        (
            stub_cycle,
            [("a.md", FormatRule.STUB_CYCLE), ("b.md", FormatRule.STUB_CYCLE)],
        ),
        (index_deleted, [(INDEX, FormatRule.INDEX_MISSING)]),
        (index_prose, [(INDEX, FormatRule.INDEX_SYNTAX)]),
        (unlisted_file, [("unlisted.md", FormatRule.INDEX_ENTRY_MISSING)]),
        (listed_twice, [("uv-python.md", FormatRule.INDEX_ENTRY_DUPLICATE)]),
        (stub_listed, [("docs-lookup.md", FormatRule.INDEX_ENTRY_STUB)]),
        (listed_without_file, [("ghost.md", FormatRule.INDEX_ENTRY_DANGLING)]),
        (domain_twice, [(INDEX, FormatRule.INDEX_DOMAIN_DUPLICATE)]),
        (subdomain_twice, [(INDEX, FormatRule.INDEX_SUBDOMAIN_DUPLICATE)]),
        (empty_domain, [(INDEX, FormatRule.INDEX_HEADING_EMPTY)]),
        (empty_subdomain, [(INDEX, FormatRule.INDEX_HEADING_EMPTY)]),
        (orphan_subdomain, [(INDEX, FormatRule.INDEX_SUBDOMAIN_ORPHAN)]),
    ],
)
def test_each_rule_reports_exactly_its_violation(
    tmp_path: Path, breaks: Setup, expected: list[tuple[str, FormatRule]]
) -> None:
    memory = tmp_path / "memory"
    valid_memory(memory)
    breaks(memory)

    assert check_format(memory) == [
        FormatViolation(file, rule) for file, rule in expected
    ]


def test_every_rule_has_a_case() -> None:
    assert len(FormatRule) == 20


def test_valid_memory_has_no_violations(tmp_path: Path) -> None:
    valid_memory(tmp_path)

    assert check_format(tmp_path) == []


def test_contract_layout_and_index_examples_report_nothing(tmp_path: Path) -> None:
    write_memory_file(
        tmp_path,
        "ctx7-setup",
        "# Context7 CLI (ctx7)\n\n"
        "- ctx7 is installed globally and is called as bare `ctx7`. "
        "[source: claude-code 40726b6c-49a1-400e-ad5e-9192e635ceb6 · /Users/dev/Projects "
        "· 2026-10-17 09:36 UTC] [scope: Development]\n\nSee also [[uv-python]].\n",
        description="How the Context7 CLI (ctx7) is installed and called.",
    )
    for slug in ("uv-python", "mailarkiv-identity", "service-pricing"):
        write_memory_file(tmp_path, slug, f"# {slug}\n\n{FACT}")
    write_stub(tmp_path, "docs-lookup", "ctx7-setup")
    (tmp_path / "_index.md").write_text(
        "# Memory index\n\n"
        "## Development\n\n"
        "- [[ctx7-setup]] — How ctx7 is installed and called in Claude Code and Codex.\n"
        "- [[uv-python]] — Python work uses uv, enforced by a hook in Claude Code and "
        "rules in Codex.\n\n"
        "### mailarkiv\n\n"
        "- [[mailarkiv-identity]] — Password rules in internal/identity.\n\n"
        "## Business\n\n"
        "- [[service-pricing]] — How services are priced.\n"
    )

    assert check_format(tmp_path) == []


def test_other_files_and_subdirectories_are_ignored(tmp_path: Path) -> None:
    valid_memory(tmp_path)
    (tmp_path / "notes.txt").write_text("not memory")
    (tmp_path / "drafts").mkdir()
    (tmp_path / "drafts" / "Bad Name.md").write_text("no frontmatter")
    (tmp_path / "folder.md").mkdir()

    assert check_format(tmp_path) == []


def test_a_stub_leading_into_a_cycle_reports_too(tmp_path: Path) -> None:
    valid_memory(tmp_path)
    stub_cycle(tmp_path)
    write_stub(tmp_path, "c", "a")

    assert check_format(tmp_path) == [
        FormatViolation(f"{slug}.md", FormatRule.STUB_CYCLE) for slug in "abc"
    ]


def test_a_stub_pointing_to_a_stub_is_fine(tmp_path: Path) -> None:
    valid_memory(tmp_path)
    write_stub(tmp_path, "old", "older")
    write_stub(tmp_path, "older", "uv-python")

    assert check_format(tmp_path) == []


def test_a_stub_pointing_nowhere_is_a_broken_link(tmp_path: Path) -> None:
    valid_memory(tmp_path)
    write_stub(tmp_path, "old", "missing")

    assert check_format(tmp_path) == [FormatViolation("old.md", FormatRule.BROKEN_LINK)]


def test_file_size_limit_is_100000_bytes(tmp_path: Path) -> None:
    valid_memory(tmp_path)
    write(tmp_path, "uv-python.md", padded_to(100_000))

    assert (tmp_path / "uv-python.md").stat().st_size == 100_000
    assert check_format(tmp_path) == []


def test_domain_with_entries_only_in_subdomains_is_not_empty(tmp_path: Path) -> None:
    valid_memory(tmp_path)
    write_index(
        tmp_path,
        {
            "Development": {
                "alpha": [("uv-python", "Python uses uv.")],
                "beta": [("ctx7-setup", "ctx7.")],
            }
        },
    )

    assert check_format(tmp_path) == []


def test_one_file_can_break_several_rules(tmp_path: Path) -> None:
    valid_memory(tmp_path)
    write(tmp_path, "notes.md", "# Notes\n\nSee [[missing]].\n")

    assert check_format(tmp_path) == [
        FormatViolation("notes.md", FormatRule.FRONTMATTER_MISSING),
        FormatViolation("notes.md", FormatRule.BROKEN_LINK),
        FormatViolation("notes.md", FormatRule.INDEX_ENTRY_MISSING),
    ]


def test_missing_memory_directory_has_no_violations(tmp_path: Path) -> None:
    assert check_format(tmp_path / "missing") == []


def test_seeded_memory_breaks_the_rules_it_was_built_to_break(tmp_path: Path) -> None:
    seeded = seeded_memory(tmp_path / "memory")

    assert len(seeded.slugs) == 200
    assert check_format(seeded.path) == [
        FormatViolation("notes.md", FormatRule.FRONTMATTER_MISSING),
        FormatViolation("notes.md", FormatRule.INDEX_ENTRY_MISSING),
        FormatViolation("release-checklist.md", FormatRule.BROKEN_LINK),
        FormatViolation("shell-aliases.md", FormatRule.INDEX_ENTRY_MISSING),
    ]
