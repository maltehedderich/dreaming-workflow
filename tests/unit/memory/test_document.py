import hashlib
from datetime import UTC, datetime

import pytest

from dreaming_workflow.memory.document import (
    Citation,
    DocumentError,
    MemoryFile,
    Slug,
    citations,
    conflict_lines,
    is_stub,
    links,
    parse_memory_file,
    parse_slug,
    render_memory_file,
    version_of,
)
from dreaming_workflow.sessions import Tool

SLUG = Slug("ctx7-setup")


@pytest.mark.parametrize("text", ["a", "uv-python", "ctx7-setup", "a1-b2-c3", "a" * 80])
def test_valid_slugs(text: str) -> None:
    assert parse_slug(text) == text


@pytest.mark.parametrize(
    "text", ["", "A", "a_b", "-a", "a-", "a--b", "a.md", "../x", "a" * 81]
)
def test_invalid_slugs(text: str) -> None:
    assert parse_slug(text) is None


def test_render_then_parse_round_trips() -> None:
    body = "# Context7 CLI\n\n- ctx7 is called as bare `ctx7`.\n"
    description = "How ctx7 is installed: read before fetching docs."

    data = render_memory_file(SLUG, description, body, metadata={"origin": "test"})
    parsed = parse_memory_file(SLUG, data)

    assert parsed == MemoryFile(
        slug=SLUG,
        description=description,
        metadata={"origin": "test"},
        body=body,
        version=hashlib.sha256(data).hexdigest()[:12],
    )


def test_rendered_file_starts_with_frontmatter() -> None:
    data = render_memory_file(SLUG, "What ctx7 is.", "# ctx7\n")

    assert data == b"---\nname: ctx7-setup\ndescription: What ctx7 is.\n---\n# ctx7\n"


def test_long_description_stays_on_one_line() -> None:
    description = "word " * 60 + "end"

    data = render_memory_file(SLUG, description, "")

    assert data.decode().splitlines()[2] == f"description: {description}"


@pytest.mark.parametrize(
    ("data", "error"),
    [
        (b"\xff\xfe", DocumentError.NOT_UTF8),
        (b"# No frontmatter\n", DocumentError.FRONTMATTER_MISSING),
        (b"", DocumentError.FRONTMATTER_MISSING),
        (b"---\nname: ctx7-setup\n", DocumentError.FRONTMATTER_INVALID),
        (b"---\nname: [unclosed\n---\n", DocumentError.FRONTMATTER_INVALID),
        (b"---\n- a list\n---\n", DocumentError.FRONTMATTER_INVALID),
        (
            b"---\nname: ctx7-setup\ndescription: d\nmetadata: text\n---\n",
            DocumentError.FRONTMATTER_INVALID,
        ),
        (
            b"---\nname: ctx7-setup\ndescription: d\ntags: [a]\n---\n",
            DocumentError.FRONTMATTER_KEY,
        ),
        (b"---\ndescription: d\n---\n", DocumentError.NAME_MISMATCH),
        (b"---\nname: other\ndescription: d\n---\n", DocumentError.NAME_MISMATCH),
        (b"---\nname: ctx7-setup\n---\n", DocumentError.DESCRIPTION_MISSING),
        (
            b"---\nname: ctx7-setup\ndescription: '  '\n---\n",
            DocumentError.DESCRIPTION_MISSING,
        ),
    ],
)
def test_parse_errors(data: bytes, error: DocumentError) -> None:
    assert parse_memory_file(SLUG, data) is error


def test_version_is_the_sha256_prefix() -> None:
    # SHA-256 of "abc" is ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad.
    assert version_of(b"abc") == "ba7816bf8f01"


@pytest.mark.parametrize(
    "data", [b"MOVED TO [[ctx7-setup]]", b"MOVED TO [[ctx7-setup]]\n"]
)
def test_stub(data: bytes) -> None:
    assert is_stub(data)


@pytest.mark.parametrize(
    "data",
    [
        b"MOVED TO [[ctx7-setup]]\n\nmore text\n",
        b"See MOVED TO [[ctx7-setup]]\n",
        b"MOVED TO [[Not A Slug]]\n",
        b"MOVED TO [[ctx7-setup]]\n\n",
    ],
)
def test_not_a_stub(data: bytes) -> None:
    assert not is_stub(data)


def test_links() -> None:
    text = "See [[uv-python]] and [[ctx7-setup]]; [[Not A Slug]] and [single] aren't links."

    assert links(text) == ["uv-python", "ctx7-setup"]


CITED_AT = datetime(2026, 10, 17, 9, 21, tzinfo=UTC)
CITATION_TEXT = (
    "[source: claude-code 90f95193-2c91-4a42-a506-930d4c964c45"
    " · /Users/dev/Projects · 2026-10-17 09:21 UTC]"
)


def test_citation_renders_in_the_contract_syntax() -> None:
    citation = Citation(
        Tool.CLAUDE_CODE,
        "90f95193-2c91-4a42-a506-930d4c964c45",
        "/Users/dev/Projects",
        CITED_AT,
    )

    assert citation.render() == CITATION_TEXT
    assert citations(f"- ctx7 is installed. {CITATION_TEXT} [scope: Development]") == {
        citation
    }


def test_citations_are_equal_only_when_all_four_fields_match() -> None:
    base = Citation(Tool.CODEX, "s1", "/p", CITED_AT)

    assert base == Citation(Tool.CODEX, "s1", "/p", CITED_AT)
    assert base != Citation(Tool.CLAUDE_CODE, "s1", "/p", CITED_AT)
    assert base != Citation(Tool.CODEX, "s2", "/p", CITED_AT)
    assert base != Citation(Tool.CODEX, "s1", "/q", CITED_AT)
    assert base != Citation(
        Tool.CODEX, "s1", "/p", datetime(2026, 10, 17, 9, 22, tzinfo=UTC)
    )


def test_citations_finds_each_distinct_citation() -> None:
    text = (
        "- CONFLICT: [source: codex s1 · /Users/dev/Projects/app · 2026-11-06 20:02 UTC]"
        " says A; [source: claude-code s2 · /Users/dev · 2026-11-07 08:00 UTC] says B.\n"
        "- Again [source: codex s1 · /Users/dev/Projects/app · 2026-11-06 20:02 UTC]\n"
        "- Not a citation [source: codex s3 · /p · 2026-11-06 UTC]\n"
    )

    assert citations(text) == {
        Citation(
            Tool.CODEX,
            "s1",
            "/Users/dev/Projects/app",
            datetime(2026, 11, 6, 20, 2, tzinfo=UTC),
        ),
        Citation(
            Tool.CLAUDE_CODE,
            "s2",
            "/Users/dev",
            datetime(2026, 11, 7, 8, 0, tzinfo=UTC),
        ),
    }


def test_conflict_lines_are_the_stripped_conflict_list_items() -> None:
    text = (
        "# Notes\n\n  - CONFLICT: A says x; B says y.\n- A fact.\nNo - CONFLICT: here\n"
    )

    assert conflict_lines(text) == {"- CONFLICT: A says x; B says y."}
