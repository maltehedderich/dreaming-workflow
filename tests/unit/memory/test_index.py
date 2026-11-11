import pytest

from dreaming_workflow.memory.document import Slug
from dreaming_workflow.memory.index import (
    Index,
    IndexEditError,
    IndexParseError,
    IndexSyntaxError,
    parse_index,
    render_index,
)

# The index example from the memory format contract.
CONTRACT_EXAMPLE = """# Memory index

## Development

- [[ctx7-setup]] — How ctx7 is installed and called in Claude Code and Codex.
- [[uv-python]] — Python work uses uv, enforced by a hook in Claude Code and rules in Codex.

### mailarkiv

- [[mailarkiv-identity]] — Password rules in internal/identity.

## Business

- [[service-pricing]] — How services are priced.
"""


def parse(text: str) -> Index:
    index = parse_index(text)
    assert isinstance(index, Index)
    return index


def test_contract_example_round_trips_unchanged() -> None:
    assert render_index(parse(CONTRACT_EXAMPLE)) == CONTRACT_EXAMPLE


def test_contract_example_structure() -> None:
    index = parse(CONTRACT_EXAMPLE)

    development, business = index.domains
    assert development.name == "Development"
    assert [entry.slug for entry in development.entries] == ["ctx7-setup", "uv-python"]
    assert [s.name for s in development.subdomains] == ["mailarkiv"]
    assert [entry.slug for entry in development.subdomains[0].entries] == [
        "mailarkiv-identity"
    ]
    assert business.entries[0].sentence == "How services are priced."


def test_title_is_optional() -> None:
    text = "## Development\n\n- [[uv-python]] — Python work uses uv.\n"

    assert parse(text).slugs() == ["uv-python"]


def test_empty_text_is_an_empty_index() -> None:
    assert parse("").domains == []
    assert render_index(Index()) == "# Memory index\n"


@pytest.mark.parametrize(
    ("text", "line", "cause"),
    [
        ("# Memory index\n\n### mailarkiv\n", 3, IndexSyntaxError.SUBDOMAIN_ORPHAN),
        ("- [[uv-python]] — Before any domain.\n", 1, IndexSyntaxError.SYNTAX),
        ("## Development\n\nsome prose\n", 3, IndexSyntaxError.SYNTAX),
        (
            "## Development\n- [[uv-python]] - hyphen instead of em dash\n",
            2,
            IndexSyntaxError.SYNTAX,
        ),
        ("## Development\n- [[Bad Slug]] — Not a slug.\n", 2, IndexSyntaxError.SYNTAX),
        ("## Development\n- [[uv-python]] — \n", 2, IndexSyntaxError.SYNTAX),
        ("## Development\n\n# Memory index\n", 3, IndexSyntaxError.SYNTAX),
        ("## \n", 1, IndexSyntaxError.SYNTAX),
    ],
)
def test_parse_errors_carry_line_and_cause(
    text: str, line: int, cause: IndexSyntaxError
) -> None:
    assert parse_index(text) == IndexParseError(line, cause)


def test_add_entry_reuses_matching_domain_and_keeps_its_spelling() -> None:
    index = parse("## development\n\n- [[uv-python]] — Python work uses uv.\n")

    error = index.add_entry(
        Slug("ctx7-setup"), "  Development ", None, "How ctx7 is set up."
    )

    assert error is None
    assert render_index(index) == (
        "# Memory index\n\n"
        "## development\n\n"
        "- [[uv-python]] — Python work uses uv.\n"
        "- [[ctx7-setup]] — How ctx7 is set up.\n"
    )


def test_add_entry_matches_subdomain_ignoring_case_and_whitespace() -> None:
    index = parse(CONTRACT_EXAMPLE)

    index.add_entry(
        Slug("mailarkiv-mail"), "DEVELOPMENT", "MailArkiv", "How mail is stored."
    )

    [subdomain] = index.domains[0].subdomains
    assert subdomain.name == "mailarkiv"
    assert [entry.slug for entry in subdomain.entries] == [
        "mailarkiv-identity",
        "mailarkiv-mail",
    ]


def test_new_subdomain_lands_after_domain_wide_entries() -> None:
    index = parse("## Development\n\n- [[uv-python]] — Python work uses uv.\n")

    index.add_entry(
        Slug("agy-settings"), "Development", "antigravity", "Antigravity settings."
    )
    index.add_entry(Slug("ctx7-setup"), "Development", None, "How ctx7 is set up.")

    assert render_index(index) == (
        "# Memory index\n\n"
        "## Development\n\n"
        "- [[uv-python]] — Python work uses uv.\n"
        "- [[ctx7-setup]] — How ctx7 is set up.\n\n"
        "### antigravity\n\n"
        "- [[agy-settings]] — Antigravity settings.\n"
    )


def test_new_domain_is_appended() -> None:
    index = parse(CONTRACT_EXAMPLE)

    index.add_entry(Slug("garden"), "Home", None, "What grows where.")

    assert [domain.name for domain in index.domains] == [
        "Development",
        "Business",
        "Home",
    ]


def test_adding_a_listed_slug_is_refused() -> None:
    index = parse(CONTRACT_EXAMPLE)

    error = index.add_entry(Slug("uv-python"), "Business", None, "Another entry.")

    assert error is IndexEditError.SLUG_LISTED
    assert render_index(index) == CONTRACT_EXAMPLE


@pytest.mark.parametrize(
    ("domain", "subdomain", "sentence", "error"),
    [
        ("", None, "Sentence.", IndexEditError.INVALID_NAME),
        ("Dev\nelopment", None, "Sentence.", IndexEditError.INVALID_NAME),
        ("Development", "  ", "Sentence.", IndexEditError.INVALID_NAME),
        ("Development", None, "Two\nlines.", IndexEditError.INVALID_SENTENCE),
        ("Development", None, " ", IndexEditError.INVALID_SENTENCE),
    ],
)
def test_add_entry_refuses_bad_names_and_sentences(
    domain: str, subdomain: str | None, sentence: str, error: IndexEditError
) -> None:
    index = Index()

    assert index.add_entry(Slug("x"), domain, subdomain, sentence) is error
    assert index.domains == []
