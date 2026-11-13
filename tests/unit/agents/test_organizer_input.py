from pathlib import Path

import pytest

from dreaming_workflow.agents import OrganizerInput, select_input
from dreaming_workflow.agents.organizer import first_message
from dreaming_workflow.memory import FormatRule, FormatViolation, MemoryStore, Slug
from tests.support.memory import memory_file_text, write_memory_file

# Three characters per estimated token, so 30,000 characters is 10,000 tokens.
TEN_THOUSAND_TOKENS = 30_000


def write_sized(memory: Path, slug: str, tokens_in_thousands: int) -> None:
    """Write a file of about `tokens_in_thousands` × 1,000 estimated tokens."""
    size = tokens_in_thousands * TEN_THOUSAND_TOKENS // 10
    start = memory_file_text(slug, "")
    (memory / f"{slug}.md").write_text(start + "x" * (size - len(start)))


def slugs(*names: str) -> list[Slug]:
    return [Slug(name) for name in names]


def violation(slug: str, rule: FormatRule) -> FormatViolation:
    return FormatViolation(f"{slug}.md", rule)


@pytest.fixture
def memory(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    memory.mkdir()
    return memory


def test_violating_files_come_before_waiting_files(memory: Path) -> None:
    for slug in ("waiting-a", "waiting-b", "broken"):
        write_memory_file(memory, slug, "# Small\n")

    chosen = select_input(
        slugs("waiting-a", "waiting-b"),
        [violation("broken", FormatRule.BROKEN_LINK)],
        MemoryStore(memory),
    )

    assert chosen == OrganizerInput(
        received=tuple(slugs("broken", "waiting-a", "waiting-b")), gone=()
    )


def test_waiting_files_keep_oldest_first_order(memory: Path) -> None:
    for slug in ("c", "a", "b"):
        write_memory_file(memory, slug, "# Small\n")

    chosen = select_input(slugs("c", "a", "b"), [], MemoryStore(memory))

    assert chosen.received == ("c", "a", "b")


def test_a_file_both_waiting_and_violating_is_received_once(memory: Path) -> None:
    write_memory_file(memory, "a", "# Small\n")
    write_memory_file(memory, "b", "# Small\n")

    chosen = select_input(
        slugs("a", "b"),
        [
            violation("b", FormatRule.BROKEN_LINK),
            violation("b", FormatRule.INDEX_ENTRY_MISSING),
        ],
        MemoryStore(memory),
    )

    assert chosen.received == ("b", "a")


def test_files_past_the_40000_token_budget_stay_out(memory: Path) -> None:
    write_sized(memory, "first", 15)
    write_sized(memory, "second", 15)
    write_sized(memory, "third", 15)
    write_sized(memory, "small", 1)

    chosen = select_input(
        slugs("first", "second", "third", "small"), [], MemoryStore(memory)
    )

    assert chosen.received == ("first", "second")


def test_a_single_file_over_the_budget_is_still_received(memory: Path) -> None:
    write_sized(memory, "huge", 50)
    write_sized(memory, "next", 1)

    chosen = select_input(slugs("huge", "next"), [], MemoryStore(memory))

    assert chosen.received == ("huge",)


def test_a_waiting_slug_whose_file_was_deleted_is_dropped(memory: Path) -> None:
    write_memory_file(memory, "kept", "# Kept\n")

    chosen = select_input(slugs("deleted", "kept"), [], MemoryStore(memory))

    assert chosen == OrganizerInput(
        received=tuple(slugs("kept")), gone=tuple(slugs("deleted"))
    )


def test_violations_without_a_readable_file_are_not_received(memory: Path) -> None:
    write_memory_file(memory, "kept", "# Kept\n")

    chosen = select_input(
        [],
        [
            FormatViolation("Notes.md", FormatRule.FILE_NAME),
            FormatViolation("_index.md", FormatRule.INDEX_HEADING_EMPTY),
            violation("ghost", FormatRule.INDEX_ENTRY_DANGLING),
            violation("kept", FormatRule.INDEX_ENTRY_MISSING),
        ],
        MemoryStore(memory),
    )

    assert chosen == OrganizerInput(received=tuple(slugs("kept")), gone=())


def test_nothing_waiting_or_violating_receives_nothing(memory: Path) -> None:
    write_memory_file(memory, "kept", "# Kept\n")

    assert select_input([], [], MemoryStore(memory)) == OrganizerInput((), ())


def test_first_message_lists_received_files_with_their_rules_and_index_rules() -> None:
    message = first_message(
        slugs("notes", "uv-python"),
        [
            violation("notes", FormatRule.FRONTMATTER_MISSING),
            violation("notes", FormatRule.INDEX_ENTRY_MISSING),
            violation("not-received", FormatRule.BROKEN_LINK),
            FormatViolation("_index.md", FormatRule.INDEX_DOMAIN_DUPLICATE),
        ],
    )

    assert message == (
        "Received files (2), with their format violations:\n"
        "- notes: frontmatter-missing, index-entry-missing\n"
        "- uv-python\n"
        "\n"
        "Index violations: index-domain-duplicate"
    )


def test_first_message_with_nothing_received_points_to_the_index() -> None:
    assert first_message([], []) == (
        "No files were received. Work from the index alone.\n\nIndex violations: none"
    )
