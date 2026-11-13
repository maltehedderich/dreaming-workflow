from datetime import timedelta
from pathlib import Path

import pytest

from dreaming_workflow.memory import MemoryStore, Refusal, Slug, Writer
from tests.support.memory import (
    OTHER_SESSION_ID,
    PART_START,
    analysis_writer,
    fact,
    source,
    write_index,
    write_memory_file,
    write_stub,
)

ORGANIZER = Writer.organizer()
CTX7_FACT = fact("ctx7 is called as bare ctx7.")
LATER = source(OTHER_SESSION_ID, PART_START + timedelta(minutes=5))
NPX_FACT = fact("ctx7 was called through npx.", LATER)


@pytest.fixture
def memory(tmp_path: Path) -> Path:
    """Two files on ctx7, each holding a fact the other doesn't."""
    memory = tmp_path / "memory"
    write_memory_file(memory, "ctx7-setup", f"# ctx7\n\n{CTX7_FACT}")
    write_memory_file(
        memory, "docs-lookup", f"# Docs\n\n{NPX_FACT}See [[ctx7-setup]].\n"
    )
    write_index(
        memory,
        {
            "Development": {
                None: [("ctx7-setup", "How ctx7 is set up."), ("docs-lookup", "Docs.")]
            }
        },
    )
    return memory


def read(store: MemoryStore, slug: str) -> tuple[str, str]:
    lines = store.read_file(slug)
    assert not isinstance(lines, Refusal)
    return lines.content, lines.version


def test_replace_file_with_the_current_version_replaces_it(memory: Path) -> None:
    store = MemoryStore(memory)
    content, version = read(store, "ctx7-setup")

    result = store.replace_file(
        "ctx7-setup", content.replace("# ctx7", "# Context7 CLI"), version, ORGANIZER
    )

    assert isinstance(result, str)
    assert result != version
    assert "# Context7 CLI" in (memory / "ctx7-setup.md").read_text()


def test_replace_file_with_a_stale_version_is_refused(memory: Path) -> None:
    store = MemoryStore(memory)
    content, version = read(store, "ctx7-setup")
    store.append_to_file("ctx7-setup", CTX7_FACT.replace("bare", "plain"), ORGANIZER)
    before = (memory / "ctx7-setup.md").read_bytes()

    result = store.replace_file("ctx7-setup", content, version, ORGANIZER)

    assert isinstance(result, Refusal)
    assert "changed since" in result.reason
    assert (memory / "ctx7-setup.md").read_bytes() == before


def test_replace_file_gives_a_hand_written_file_frontmatter(memory: Path) -> None:
    (memory / "notes.md").write_text("# Notes\n\n- Rotate the backup drive monthly.\n")
    store = MemoryStore(memory)
    content, version = read(store, "notes")

    result = store.replace_file(
        "notes",
        f"---\nname: notes\ndescription: House notes.\n---\n{content}",
        version,
        ORGANIZER,
    )

    assert isinstance(result, str)
    assert (memory / "notes.md").read_text().startswith("---\nname: notes\n")


def test_retire_file_is_refused_while_a_citation_lives_only_in_the_retiring_file(
    memory: Path,
) -> None:
    store = MemoryStore(memory)
    before = (memory / "docs-lookup.md").read_bytes()

    result = store.retire_file("docs-lookup", "ctx7-setup")

    assert isinstance(result, Refusal)
    assert LATER in result.reason
    assert (memory / "docs-lookup.md").read_bytes() == before
    assert "[[docs-lookup]]" in (memory / "_index.md").read_text()


def test_retire_file_succeeds_once_the_target_holds_every_citation(
    memory: Path,
) -> None:
    store = MemoryStore(memory)
    assert isinstance(store.append_to_file("ctx7-setup", NPX_FACT, ORGANIZER), str)

    result = store.retire_file("docs-lookup", "ctx7-setup")

    assert result is None
    assert (memory / "docs-lookup.md").read_text() == "MOVED TO [[ctx7-setup]]\n"
    assert "[[docs-lookup]]" not in (memory / "_index.md").read_text()
    stub, _ = read(store, "docs-lookup")
    assert stub == "MOVED TO [[ctx7-setup]]\n"


def test_retire_file_into_a_missing_file_a_stub_or_itself_is_refused(
    memory: Path,
) -> None:
    write_stub(memory, "old-docs", "ctx7-setup")
    store = MemoryStore(memory)

    for into in ("missing", "old-docs", "docs-lookup"):
        assert isinstance(store.retire_file("docs-lookup", into), Refusal), into
    assert isinstance(store.retire_file("missing", "ctx7-setup"), Refusal)


def test_retire_file_moves_a_listed_stub_out_of_the_index(memory: Path) -> None:
    write_stub(memory, "old-docs", "docs-lookup")
    write_index(
        memory,
        {"Development": {None: [("ctx7-setup", "Setup."), ("old-docs", "Old.")]}},
    )
    store = MemoryStore(memory)

    assert store.retire_file("old-docs", "ctx7-setup") is None

    assert (memory / "old-docs.md").read_text() == "MOVED TO [[ctx7-setup]]\n"
    assert "old-docs" not in (memory / "_index.md").read_text()


def test_organizer_may_not_add_a_citation_memory_doesnt_hold(memory: Path) -> None:
    store = MemoryStore(memory)
    unknown = source("5e55e55e-0000-4000-8000-0000000000ff")

    appended = store.append_to_file(
        "ctx7-setup", fact("Something new.", unknown), ORGANIZER
    )
    created = store.create_file(
        "new-file",
        "New.",
        "# New\n\n" + fact("Something new.", unknown),
        "Development",
        None,
        "New.",
        ORGANIZER,
    )

    assert isinstance(appended, Refusal)
    assert isinstance(created, Refusal)
    assert unknown in appended.reason
    assert "Something new" not in (memory / "ctx7-setup.md").read_text()
    assert not (memory / "new-file.md").exists()


def test_organizer_may_copy_a_citation_from_another_file(memory: Path) -> None:
    store = MemoryStore(memory)

    result = store.append_to_file("ctx7-setup", NPX_FACT, ORGANIZER)

    assert isinstance(result, str)


def test_organizer_may_not_drop_the_only_copy_of_a_citation(memory: Path) -> None:
    store = MemoryStore(memory)
    content, version = read(store, "docs-lookup")

    result = store.replace_file(
        "docs-lookup", content.replace(NPX_FACT, ""), version, ORGANIZER
    )

    assert isinstance(result, Refusal)


def test_organizer_may_not_write_a_stub(memory: Path) -> None:
    store = MemoryStore(memory)
    _, version = read(store, "docs-lookup")

    result = store.replace_file(
        "docs-lookup", "MOVED TO [[ctx7-setup]]\n", version, ORGANIZER
    )

    assert isinstance(result, Refusal)
    assert "retire_file" in result.reason


def test_organizer_writes_dont_mark_files_but_analysis_writes_do(
    memory: Path,
) -> None:
    marked: list[Slug] = []
    store = MemoryStore(memory, on_analysis_write=marked.append)

    store.append_to_file("ctx7-setup", NPX_FACT, ORGANIZER)
    content, version = read(store, "ctx7-setup")
    store.replace_file("ctx7-setup", content + "\n", version, ORGANIZER)
    store.set_index_entry("ctx7-setup", "Development", None, "Setup.")
    store.append_to_file("docs-lookup", CTX7_FACT, ORGANIZER)
    store.retire_file("docs-lookup", "ctx7-setup")
    assert marked == []

    store.append_to_file("ctx7-setup", fact("Analysis fact."), analysis_writer())
    assert marked == ["ctx7-setup"]


def test_refused_analysis_writes_dont_mark_files(memory: Path) -> None:
    marked: list[Slug] = []
    store = MemoryStore(memory, on_analysis_write=marked.append)

    result = store.append_to_file("ctx7-setup", NPX_FACT, analysis_writer())

    assert isinstance(result, Refusal)
    assert marked == []


def test_set_index_entry_is_refused_for_a_missing_file_or_a_stub(
    memory: Path,
) -> None:
    write_stub(memory, "old-docs", "ctx7-setup")
    store = MemoryStore(memory)
    before = (memory / "_index.md").read_text()

    missing = store.set_index_entry("missing", "Development", None, "Missing.")
    stub = store.set_index_entry("old-docs", "Development", None, "Old.")

    assert isinstance(missing, Refusal)
    assert isinstance(stub, Refusal)
    assert (memory / "_index.md").read_text() == before


def test_set_index_entry_moves_an_entry(memory: Path) -> None:
    store = MemoryStore(memory)

    assert store.set_index_entry("docs-lookup", "Development", "docs", "Docs.") is None

    assert (memory / "_index.md").read_text() == (
        "# Memory index\n\n## Development\n\n- [[ctx7-setup]] — How ctx7 is set up.\n\n"
        "### docs\n\n- [[docs-lookup]] — Docs.\n"
    )


def test_index_edits_on_a_broken_index_are_refused(memory: Path) -> None:
    (memory / "_index.md").write_text("## Development\n\nprose\n")
    store = MemoryStore(memory)

    result = store.rename_domain("Development", "Software")

    assert isinstance(result, Refusal)
    assert "line 3" in result.reason
    assert (memory / "_index.md").read_text() == "## Development\n\nprose\n"


def test_rename_domain_and_move_subdomain_refuse_unknown_headings(
    memory: Path,
) -> None:
    store = MemoryStore(memory)

    assert isinstance(store.rename_domain("Hobbies", "Home"), Refusal)
    assert isinstance(
        store.move_subdomain("Development", "alpha", "Development", None), Refusal
    )
    assert store.rename_domain("development", "Software development") is None
    assert "## Software development\n" in (memory / "_index.md").read_text()


def test_links_to_a_retired_slug_resolve_through_its_stub(memory: Path) -> None:
    store = MemoryStore(memory)
    store.append_to_file("ctx7-setup", NPX_FACT, ORGANIZER)
    store.retire_file("docs-lookup", "ctx7-setup")

    stub, _ = read(store, "docs-lookup")
    target = stub.removeprefix("MOVED TO [[").removesuffix("]]\n")
    facts, _ = read(store, target)

    assert NPX_FACT in facts
