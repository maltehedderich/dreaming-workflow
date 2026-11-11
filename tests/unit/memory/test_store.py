import stat
from pathlib import Path

import pytest

from dreaming_workflow.memory import FileLines, MemoryStore, Refusal

BODY = "# uv\n\n- Python work uses uv.\n"


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def create(
    store: MemoryStore,
    slug: str = "uv-python",
    *,
    description: str = "How Python work runs through uv.",
    body: str = BODY,
    subdomain: str | None = None,
    index_sentence: str = "Python work uses uv.",
) -> str | Refusal:
    return store.create_file(
        slug, description, body, "Development", subdomain, index_sentence
    )


@pytest.fixture
def memory(tmp_path: Path) -> Path:
    return tmp_path / "memory"


def test_create_file_writes_frontmatter_body_and_index_entry(memory: Path) -> None:
    store = MemoryStore(memory)

    version = create(store)
    create(
        store,
        "mailarkiv-identity",
        subdomain="mailarkiv",
        index_sentence="Password rules.",
    )

    assert isinstance(version, str)
    assert (memory / "uv-python.md").read_text() == (
        "---\nname: uv-python\ndescription: How Python work runs through uv.\n---\n"
        + BODY
    )
    assert (memory / "_index.md").read_text() == (
        "# Memory index\n\n"
        "## Development\n\n"
        "- [[uv-python]] — Python work uses uv.\n\n"
        "### mailarkiv\n\n"
        "- [[mailarkiv-identity]] — Password rules.\n"
    )


def test_create_file_creates_private_memory_directory_and_files(memory: Path) -> None:
    create(MemoryStore(memory))

    assert mode_of(memory) == 0o700
    assert mode_of(memory / "uv-python.md") == 0o600
    assert mode_of(memory / "_index.md") == 0o600


def test_existing_slug_is_refused(memory: Path) -> None:
    store = MemoryStore(memory)
    create(store)
    before = (memory / "uv-python.md").read_bytes()

    result = create(store, body="# Replaced\n")

    assert isinstance(result, Refusal)
    assert (memory / "uv-python.md").read_bytes() == before


def test_multi_line_index_sentence_is_refused(memory: Path) -> None:
    result = create(MemoryStore(memory), index_sentence="First line.\nSecond line.")

    assert isinstance(result, Refusal)
    assert not memory.exists()


@pytest.mark.parametrize(
    "slug", ["../outside", "/etc/passwd", "Upper", "_index", "a" * 81]
)
def test_invalid_slug_is_refused(memory: Path, slug: str) -> None:
    assert isinstance(create(MemoryStore(memory), slug), Refusal)
    assert not memory.exists()


def test_empty_description_is_refused(memory: Path) -> None:
    assert isinstance(create(MemoryStore(memory), description=" "), Refusal)
    assert not memory.exists()


def test_index_with_syntax_error_refuses_new_files(memory: Path) -> None:
    memory.mkdir()
    (memory / "_index.md").write_text("## Development\n\nhand-written prose\n")

    result = create(MemoryStore(memory))

    assert isinstance(result, Refusal)
    assert "line 3" in result.reason
    assert not (memory / "uv-python.md").exists()


def test_read_file_returns_line_ranges_and_version(memory: Path) -> None:
    memory.mkdir()
    (memory / "notes.md").write_text("one\ntwo\nthree\nfour\n")
    store = MemoryStore(memory)

    whole = store.read_file("notes")
    middle = store.read_file("notes", start_line=2, max_lines=2)
    tail = store.read_file("notes", start_line=4)

    assert isinstance(whole, FileLines)
    assert whole.content == "one\ntwo\nthree\nfour\n"
    assert whole.total_lines == 4
    assert middle == FileLines(
        content="two\nthree\n", version=whole.version, total_lines=4
    )
    assert isinstance(tail, FileLines)
    assert tail.content == "four\n"


def test_read_file_returns_stubs_and_files_without_frontmatter(memory: Path) -> None:
    memory.mkdir()
    (memory / "old-notes.md").write_text("MOVED TO [[notes]]\n")
    (memory / "hand-written.md").write_text("# Notes I wrote myself\n")
    store = MemoryStore(memory)

    stub = store.read_file("old-notes")
    hand_written = store.read_file("hand-written")

    assert isinstance(stub, FileLines)
    assert stub.content == "MOVED TO [[notes]]\n"
    assert isinstance(hand_written, FileLines)
    assert hand_written.content == "# Notes I wrote myself\n"


def test_read_file_refuses_missing_files_and_bad_ranges(memory: Path) -> None:
    memory.mkdir()
    (memory / "notes.md").write_text("one\n")
    store = MemoryStore(memory)

    assert isinstance(store.read_file("missing"), Refusal)
    assert isinstance(store.read_file("notes", start_line=0), Refusal)
    assert isinstance(store.read_file("notes", max_lines=0), Refusal)


def test_read_file_refuses_symbolic_links(memory: Path, tmp_path: Path) -> None:
    memory.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("not memory\n")
    (memory / "linked.md").symlink_to(outside)

    assert isinstance(MemoryStore(memory).read_file("linked"), Refusal)


def test_read_index_of_empty_memory_is_empty(memory: Path) -> None:
    assert MemoryStore(memory).read_index() == ""
