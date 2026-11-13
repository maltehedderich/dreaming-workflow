from dreaming_workflow.memory import Slug
from dreaming_workflow.memory.index import (
    Index,
    IndexEditError,
    IndexParseError,
    parse_index,
    render_index,
)


def parse(text: str) -> Index:
    index = parse_index(text)
    assert not isinstance(index, IndexParseError)
    return index


SPLIT_DEVELOPMENT = """# Memory index

## Development

- [[uv-python]] — Python work uses uv.

### mailarkiv

- [[mailarkiv-identity]] — Password rules.

## Software development

- [[ctx7-setup]] — How ctx7 is called.

### Mailarkiv

- [[mailarkiv-imports]] — How mail is imported.

### alpha

- [[alpha-build]] — How alpha builds.

## Business

- [[service-pricing]] — How services are priced.
"""


def test_set_entry_moves_an_entry_and_removes_the_heading_it_left_empty() -> None:
    index = parse(SPLIT_DEVELOPMENT)

    error = index.set_entry(
        Slug("alpha-build"), "Development", "alpha", "How the alpha app builds."
    )

    assert error is None
    assert render_index(index) == (
        "# Memory index\n\n"
        "## Development\n\n"
        "- [[uv-python]] — Python work uses uv.\n\n"
        "### mailarkiv\n\n"
        "- [[mailarkiv-identity]] — Password rules.\n\n"
        "### alpha\n\n"
        "- [[alpha-build]] — How the alpha app builds.\n\n"
        "## Software development\n\n"
        "- [[ctx7-setup]] — How ctx7 is called.\n\n"
        "### Mailarkiv\n\n"
        "- [[mailarkiv-imports]] — How mail is imported.\n\n"
        "## Business\n\n"
        "- [[service-pricing]] — How services are priced.\n"
    )


def test_set_entry_rewrites_an_entry_in_place() -> None:
    index = parse(SPLIT_DEVELOPMENT)

    index.set_entry(Slug("uv-python"), "development", None, "Python runs through uv.")

    assert render_index(index) == SPLIT_DEVELOPMENT.replace(
        "Python work uses uv.", "Python runs through uv."
    )


def test_set_entry_adds_an_unlisted_slug_and_removes_duplicates() -> None:
    index = parse("## Development\n\n- [[uv-python]] — One.\n- [[uv-python]] — Two.\n")

    index.set_entry(Slug("uv-python"), "Development", None, "Python uses uv.")
    index.set_entry(Slug("notes"), "Home", None, "Notes about the house.")

    assert render_index(index) == (
        "# Memory index\n\n"
        "## Development\n\n- [[uv-python]] — Python uses uv.\n\n"
        "## Home\n\n- [[notes]] — Notes about the house.\n"
    )


def test_set_entry_refuses_multi_line_names_and_sentences() -> None:
    index = parse(SPLIT_DEVELOPMENT)

    assert (
        index.set_entry(Slug("uv-python"), "Dev\nelopment", None, "Uv.")
        is IndexEditError.INVALID_NAME
    )
    assert (
        index.set_entry(Slug("uv-python"), "Development", None, "One.\nTwo.")
        is IndexEditError.INVALID_SENTENCE
    )
    assert render_index(index) == SPLIT_DEVELOPMENT


def test_remove_entry_removes_every_listing_and_empty_headings() -> None:
    index = parse(SPLIT_DEVELOPMENT)

    index.remove_entry(Slug("service-pricing"))
    index.remove_entry(Slug("alpha-build"))

    assert "Business" not in render_index(index)
    assert "### alpha" not in render_index(index)
    assert index.slugs() == [
        "uv-python",
        "mailarkiv-identity",
        "ctx7-setup",
        "mailarkiv-imports",
    ]


def test_rename_domain_merges_into_an_existing_domain_and_its_subdomains() -> None:
    index = parse(SPLIT_DEVELOPMENT)

    error = index.rename_domain("Software development", "Development")

    assert error is None
    assert render_index(index) == (
        "# Memory index\n\n"
        "## Development\n\n"
        "- [[uv-python]] — Python work uses uv.\n"
        "- [[ctx7-setup]] — How ctx7 is called.\n\n"
        "### mailarkiv\n\n"
        "- [[mailarkiv-identity]] — Password rules.\n"
        "- [[mailarkiv-imports]] — How mail is imported.\n\n"
        "### alpha\n\n"
        "- [[alpha-build]] — How alpha builds.\n\n"
        "## Business\n\n"
        "- [[service-pricing]] — How services are priced.\n"
    )


def test_rename_domain_to_a_new_name_keeps_its_place() -> None:
    index = parse(SPLIT_DEVELOPMENT)

    index.rename_domain("business", "Work")

    assert [domain.name for domain in index.domains] == [
        "Development",
        "Software development",
        "Work",
    ]


def test_rename_domain_joins_duplicate_headings() -> None:
    index = parse(
        "## Development\n\n- [[a]] — A.\n\n## Business\n\n- [[b]] — B.\n\n"
        "## development\n\n- [[c]] — C.\n"
    )

    index.rename_domain("Development", "Development")

    assert render_index(index) == (
        "# Memory index\n\n## Development\n\n- [[a]] — A.\n- [[c]] — C.\n\n"
        "## Business\n\n- [[b]] — B.\n"
    )


def test_rename_domain_changes_only_the_spelling_when_names_match() -> None:
    index = parse(SPLIT_DEVELOPMENT)

    index.rename_domain("Business", "business")

    assert [domain.name for domain in index.domains][-1] == "business"


def test_rename_domain_refuses_an_unknown_domain() -> None:
    index = parse(SPLIT_DEVELOPMENT)

    assert index.rename_domain("Hobbies", "Home") is IndexEditError.DOMAIN_NOT_FOUND
    assert render_index(index) == SPLIT_DEVELOPMENT


def test_move_subdomain_without_a_target_makes_its_entries_domain_wide() -> None:
    index = parse(SPLIT_DEVELOPMENT)

    error = index.move_subdomain("Software development", "alpha", "Development", None)

    assert error is None
    development, software, _ = index.domains
    assert [entry.slug for entry in development.entries] == [
        "uv-python",
        "alpha-build",
    ]
    assert [s.name for s in software.subdomains] == ["Mailarkiv"]


def test_move_subdomain_merges_into_a_matching_subdomain() -> None:
    index = parse(SPLIT_DEVELOPMENT)

    index.move_subdomain(
        "Software development", "Mailarkiv", "Development", "mailarkiv"
    )

    development = index.domains[0]
    assert [s.name for s in development.subdomains] == ["mailarkiv"]
    assert [entry.slug for entry in development.subdomains[0].entries] == [
        "mailarkiv-identity",
        "mailarkiv-imports",
    ]


def test_move_subdomain_renames_in_place_within_its_domain() -> None:
    index = parse(SPLIT_DEVELOPMENT)

    index.move_subdomain(
        "Software development", "alpha", "Software development", "Alpha app"
    )

    assert [s.name for s in index.domains[1].subdomains] == ["Mailarkiv", "Alpha app"]


def test_move_subdomain_creates_a_missing_target_domain() -> None:
    index = parse(SPLIT_DEVELOPMENT)

    index.move_subdomain("Software development", "alpha", "Projects", "alpha")

    assert [domain.name for domain in index.domains][-1] == "Projects"
    assert index.domains[-1].subdomains[0].name == "alpha"


def test_move_subdomain_refuses_unknown_headings() -> None:
    index = parse(SPLIT_DEVELOPMENT)

    assert (
        index.move_subdomain("Hobbies", "alpha", "Development", None)
        is IndexEditError.DOMAIN_NOT_FOUND
    )
    assert (
        index.move_subdomain("Development", "beta", "Development", None)
        is IndexEditError.SUBDOMAIN_NOT_FOUND
    )
    assert render_index(index) == SPLIT_DEVELOPMENT


def test_heading_matches_ignore_case_and_extra_whitespace() -> None:
    index = parse(SPLIT_DEVELOPMENT)

    assert index.rename_domain("  SOFTWARE   development ", "development") is None
    assert (
        index.move_subdomain(" DEVELOPMENT", "MAILARKIV ", "development", None) is None
    )

    assert [domain.name for domain in index.domains] == ["Development", "Business"]
    assert [entry.slug for entry in index.domains[0].entries] == [
        "uv-python",
        "ctx7-setup",
        "mailarkiv-identity",
        "mailarkiv-imports",
    ]
