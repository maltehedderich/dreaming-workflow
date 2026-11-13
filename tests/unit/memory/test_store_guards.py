import hashlib
import threading
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from dreaming_workflow.memory import MemoryStore, Refusal, SearchResult, Writer
from dreaming_workflow.sessions import Tool
from tests.support.memory import (
    OTHER_SESSION_ID,
    PART_END,
    PART_START,
    analysis_writer,
    fact,
    source,
)

CREDENTIAL_REASON = "Refer to the credential by name instead of writing its value."
SLUG = "uv-python"


def fake_key() -> str:
    # Joined at run time so the repository holds no string shaped like a key.
    return "".join(("sk", "-ant-", "api03-", "Q1w2E3r4T5y6U7i8" * 4))


def create(
    store: MemoryStore,
    slug: str = SLUG,
    body: str = "# uv\n\n" + fact("Python work uses uv."),
    writer: Writer | None = None,
    description: str = "How Python work runs through uv.",
) -> str | Refusal:
    return store.create_file(
        slug,
        description,
        body,
        "Development",
        None,
        "Python work uses uv.",
        writer or analysis_writer(),
    )


def hashes(directory: Path) -> dict[str, str]:
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


@pytest.fixture
def memory(tmp_path: Path) -> Path:
    return tmp_path / "memory"


@pytest.fixture
def store(memory: Path) -> MemoryStore:
    store = MemoryStore(memory)
    assert isinstance(create(store), str)
    return store


type Write = Callable[[MemoryStore, str], str | Refusal]

WRITES: dict[str, Write] = {
    "create": lambda store, slug: create(store, slug),
    "edit": lambda store, slug: store.edit_file(
        slug, "uses uv.", "uses uv only.", analysis_writer()
    ),
    "append": lambda store, slug: store.append_to_file(
        slug, fact("uv pins Python."), analysis_writer()
    ),
}


@pytest.mark.parametrize("write", WRITES.values(), ids=WRITES.keys())
@pytest.mark.parametrize("slug", ["../x", "/etc/x", "a" * 81])
def test_slugs_that_could_leave_memory_are_refused(
    store: MemoryStore, memory: Path, write: Write, slug: str
) -> None:
    before = hashes(memory.parent)

    assert isinstance(write(store, slug), Refusal)
    assert hashes(memory.parent) == before


@pytest.mark.parametrize("write", WRITES.values(), ids=WRITES.keys())
def test_symbolic_link_slug_is_refused_and_its_target_unchanged(
    store: MemoryStore, memory: Path, tmp_path: Path, write: Write
) -> None:
    target = tmp_path / "outside.md"
    target.write_text("---\nname: linked\ndescription: x\n---\n- uses uv.\n")
    (memory / "linked.md").symlink_to(target)
    before = target.read_bytes()

    assert isinstance(write(store, "linked"), Refusal)
    assert target.read_bytes() == before


@pytest.mark.parametrize(
    "write",
    [
        lambda store: create(store, "keys", body=f"- The key is {fake_key()}.\n"),
        lambda store: create(store, "keys", description=f"Key {fake_key()}"),
        lambda store: store.edit_file(SLUG, "uses uv.", fake_key(), analysis_writer()),
        lambda store: store.append_to_file(SLUG, fake_key(), analysis_writer()),
    ],
    ids=["create-body", "create-description", "edit", "append"],
)
def test_credential_is_refused_and_nothing_written(
    store: MemoryStore, memory: Path, write: Callable[[MemoryStore], str | Refusal]
) -> None:
    before = hashes(memory)

    assert write(store) == Refusal(CREDENTIAL_REASON)
    assert hashes(memory) == before


@pytest.mark.parametrize(
    "citation",
    [
        source(OTHER_SESSION_ID),
        source(tool=Tool.CODEX),
        source(project_dir="/Users/dev/Projects/other"),
        source(at=PART_START - timedelta(minutes=1)),
        source(at=PART_END + timedelta(minutes=1)),
    ],
    ids=["other-session", "other-tool", "other-project", "before-part", "after-part"],
)
def test_citation_outside_the_writers_part_is_refused(
    store: MemoryStore, memory: Path, citation: str
) -> None:
    before = hashes(memory)

    result = store.append_to_file(
        SLUG, fact("uv pins Python.", citation), analysis_writer()
    )

    assert isinstance(result, Refusal)
    assert hashes(memory) == before


def test_citations_at_the_first_and_last_minute_of_the_part_are_allowed(
    store: MemoryStore,
) -> None:
    text = fact("First.", source(at=PART_START)) + fact("Last.", source(at=PART_END))

    assert isinstance(store.append_to_file(SLUG, text, analysis_writer()), str)


def test_removing_the_only_copy_of_a_citation_is_refused(
    store: MemoryStore, memory: Path
) -> None:
    before = hashes(memory)

    result = store.edit_file(
        SLUG, f" {source()} [scope: Development]", "", analysis_writer()
    )

    assert isinstance(result, Refusal)
    assert hashes(memory) == before


def test_removing_a_citation_another_file_holds_is_allowed(
    store: MemoryStore, memory: Path
) -> None:
    assert isinstance(create(store, "python-tools"), str)

    result = store.edit_file(
        SLUG, f" {source()} [scope: Development]", "", analysis_writer()
    )

    assert isinstance(result, str)
    assert source() not in (memory / f"{SLUG}.md").read_text()


def test_a_stub_does_not_keep_a_removed_citation(
    store: MemoryStore, memory: Path
) -> None:
    (memory / "old-notes.md").write_text(f"MOVED TO [[{SLUG}]]\n")

    result = store.edit_file(
        SLUG, f" {source()} [scope: Development]", "", analysis_writer()
    )

    assert isinstance(result, Refusal)


def test_analysis_cannot_write_a_stub(store: MemoryStore, memory: Path) -> None:
    (memory / "notes.md").write_text("---\nname: notes\ndescription: Notes.\n---\n")
    current = (memory / "notes.md").read_text()

    result = store.edit_file(
        "notes", current, f"MOVED TO [[{SLUG}]]\n", analysis_writer()
    )

    assert isinstance(result, Refusal)
    assert (memory / "notes.md").read_text() == current


def test_edit_that_breaks_frontmatter_is_refused(store: MemoryStore) -> None:
    result = store.edit_file(SLUG, "name: uv-python", "name: other", analysis_writer())

    assert isinstance(result, Refusal)


@pytest.mark.parametrize("old_text", ["not in the file", "uv", ""])
def test_edit_needs_exactly_one_occurrence(
    store: MemoryStore, memory: Path, old_text: str
) -> None:
    before = hashes(memory)

    assert isinstance(store.edit_file(SLUG, old_text, "x", analysis_writer()), Refusal)
    assert hashes(memory) == before


def test_edit_and_append_refuse_missing_files(store: MemoryStore) -> None:
    assert isinstance(store.edit_file("missing", "a", "b", analysis_writer()), Refusal)
    assert isinstance(store.append_to_file("missing", "a", analysis_writer()), Refusal)


def test_append_adds_a_newline_first_if_needed(memory: Path) -> None:
    memory.mkdir()
    (memory / "notes.md").write_text(
        "---\nname: notes\ndescription: Notes.\n---\n# Notes"
    )
    store = MemoryStore(memory)

    assert isinstance(
        store.append_to_file("notes", "- A fact.\n", analysis_writer()), str
    )
    assert isinstance(
        store.append_to_file("notes", "- Another.", analysis_writer()), str
    )

    assert (memory / "notes.md").read_text().endswith("# Notes\n- A fact.\n- Another.")


def test_edits_from_two_writers_to_different_lines_both_land(
    store: MemoryStore, memory: Path
) -> None:
    other = analysis_writer(OTHER_SESSION_ID)
    other_fact = fact("uv lives in ~/.local/bin.", source(OTHER_SESSION_ID))
    assert isinstance(store.append_to_file(SLUG, other_fact, other), str)
    # Both writers read the file before either edits it.
    assert store.read_file(SLUG) is not None

    first = store.edit_file(
        SLUG, "Python work uses uv.", "All Python work uses uv.", analysis_writer()
    )
    second = store.edit_file(
        SLUG, "lives in ~/.local/bin.", "lives in ~/.cargo/bin.", other
    )

    assert isinstance(first, str)
    assert isinstance(second, str)
    text = (memory / f"{SLUG}.md").read_text()
    assert "All Python work uses uv." in text
    assert "lives in ~/.cargo/bin." in text


def test_concurrent_appends_all_land(store: MemoryStore, memory: Path) -> None:
    writers = [analysis_writer(), analysis_writer(OTHER_SESSION_ID)]
    citations = [source(), source(OTHER_SESSION_ID)]

    def append_facts(index: int) -> None:
        for number in range(20):
            line = fact(f"Fact {index}-{number}.", citations[index])
            assert isinstance(store.append_to_file(SLUG, line, writers[index]), str)

    threads = [threading.Thread(target=append_facts, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    text = (memory / f"{SLUG}.md").read_text()
    for index in range(2):
        for number in range(20):
            assert f"Fact {index}-{number}." in text


def test_search_is_case_insensitive_over_files_and_stubs(
    store: MemoryStore, memory: Path
) -> None:
    (memory / "old-notes.md").write_text(f"MOVED TO [[{SLUG}]]\n")

    result = store.search_memory("PYTHON WORK USES")
    stub = store.search_memory("moved to")

    assert isinstance(result, SearchResult)
    # Four frontmatter lines, the heading, and a blank line come before the fact.
    assert [(m.slug, m.line) for m in result.matches] == [(SLUG, 7)]
    assert not result.truncated
    assert isinstance(stub, SearchResult)
    assert [(m.slug, m.line, m.excerpt) for m in stub.matches] == [
        ("old-notes", 1, f"MOVED TO [[{SLUG}]]")
    ]


@pytest.mark.parametrize(("lines", "truncated"), [(50, False), (51, True)])
def test_search_returns_at_most_50_matches(
    memory: Path, lines: int, truncated: bool
) -> None:
    memory.mkdir()
    (memory / "notes.md").write_text("".join(f"- needle {n}\n" for n in range(lines)))

    result = MemoryStore(memory).search_memory("needle")

    assert isinstance(result, SearchResult)
    assert len(result.matches) == 50
    assert result.truncated is truncated


def test_search_cuts_excerpts_to_300_characters(memory: Path) -> None:
    memory.mkdir()
    (memory / "notes.md").write_text("needle " + "x" * 400 + "\n")

    result = MemoryStore(memory).search_memory("needle")

    assert isinstance(result, SearchResult)
    assert len(result.matches[0].excerpt) == 300


def test_search_skips_the_index_and_symbolic_links(
    store: MemoryStore, memory: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("uv-python outside\n")
    (memory / "linked.md").symlink_to(outside)

    result = store.search_memory("uv-python")

    assert isinstance(result, SearchResult)
    assert {m.slug for m in result.matches} == {SLUG}


def test_before_first_write_runs_once_before_memory_exists(memory: Path) -> None:
    calls: list[bool] = []
    store = MemoryStore(
        memory, before_first_write=lambda: calls.append(memory.exists())
    )

    assert isinstance(create(store, "../x"), Refusal)
    assert calls == []
    assert isinstance(create(store), str)
    assert isinstance(create(store, "python-tools"), str)
    assert isinstance(store.append_to_file(SLUG, "- More.\n", analysis_writer()), str)

    assert calls == [False]
    assert store.has_written
