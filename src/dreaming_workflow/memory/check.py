"""The memory format check: every rule of the memory format contract, by file."""

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from dreaming_workflow.memory.document import (
    DocumentError,
    Slug,
    frontmatter_errors,
    has_stub_line,
    links,
    parse_slug,
    stub_target,
)
from dreaming_workflow.memory.index import (
    DomainHeading,
    IndexEntry,
    SubdomainHeading,
    same_name,
    scan_index,
)

INDEX_FILE = "_index.md"
MAX_FILE_BYTES = 100_000


class FormatRule(StrEnum):
    FILE_NAME = "file-name"
    FRONTMATTER_MISSING = "frontmatter-missing"
    FRONTMATTER_INVALID = "frontmatter-invalid"
    FRONTMATTER_KEY = "frontmatter-key"
    NAME_MISMATCH = "name-mismatch"
    DESCRIPTION_MISSING = "description-missing"
    FILE_TOO_LARGE = "file-too-large"
    BROKEN_LINK = "broken-link"
    STUB_INVALID = "stub-invalid"
    STUB_CYCLE = "stub-cycle"
    INDEX_MISSING = "index-missing"
    INDEX_SYNTAX = "index-syntax"
    INDEX_ENTRY_MISSING = "index-entry-missing"
    INDEX_ENTRY_DUPLICATE = "index-entry-duplicate"
    INDEX_ENTRY_STUB = "index-entry-stub"
    INDEX_ENTRY_DANGLING = "index-entry-dangling"
    INDEX_DOMAIN_DUPLICATE = "index-domain-duplicate"
    INDEX_SUBDOMAIN_DUPLICATE = "index-subdomain-duplicate"
    INDEX_HEADING_EMPTY = "index-heading-empty"
    INDEX_SUBDOMAIN_ORPHAN = "index-subdomain-orphan"


@dataclass(frozen=True)
class FormatViolation:
    """A broken rule. `file` is a memory file's name, or `_index.md`.

    Rules about one index entry name the entry's file, even when it doesn't
    exist, so the report says which slug is affected.
    """

    file: str
    rule: FormatRule


_RULE_ORDER = {rule: position for position, rule in enumerate(FormatRule)}

_FRONTMATTER_RULES = {
    # A file that isn't UTF-8 has no readable frontmatter.
    DocumentError.NOT_UTF8: FormatRule.FRONTMATTER_INVALID,
    DocumentError.FRONTMATTER_MISSING: FormatRule.FRONTMATTER_MISSING,
    DocumentError.FRONTMATTER_INVALID: FormatRule.FRONTMATTER_INVALID,
    DocumentError.FRONTMATTER_KEY: FormatRule.FRONTMATTER_KEY,
    DocumentError.NAME_MISMATCH: FormatRule.NAME_MISMATCH,
    DocumentError.DESCRIPTION_MISSING: FormatRule.DESCRIPTION_MISSING,
}


def _file_name(slug: Slug) -> str:
    return f"{slug}.md"


@dataclass
class _Heading:
    name: str
    entries: int = 0
    subdomains: list[_Heading] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return self.entries == 0 and all(s.is_empty for s in self.subdomains)


def _read_files(memory_dir: Path, found: set[FormatViolation]) -> dict[Slug, bytes]:
    """Read every top-level memory file and stub, reporting badly named ones."""
    files: dict[Slug, bytes] = {}
    for path in sorted(memory_dir.glob("*.md")):
        # Memory tools never follow links, so the check doesn't either.
        if path.name == INDEX_FILE or path.is_symlink() or not path.is_file():
            continue
        slug = parse_slug(path.stem)
        if slug is None:
            found.add(FormatViolation(path.name, FormatRule.FILE_NAME))
            continue
        files[slug] = path.read_bytes()
    return files


def _check_files(
    files: dict[Slug, bytes], stubs: dict[Slug, Slug], found: set[FormatViolation]
) -> None:
    for slug, data in files.items():
        name = _file_name(slug)

        def add(rule: FormatRule, name: str = name) -> None:
            found.add(FormatViolation(name, rule))

        if len(data) > MAX_FILE_BYTES:
            add(FormatRule.FILE_TOO_LARGE)
        text = data.decode("utf-8", errors="replace")
        if any(link not in files for link in links(text)):
            add(FormatRule.BROKEN_LINK)
        if slug in stubs:
            continue
        if has_stub_line(text):
            add(FormatRule.STUB_INVALID)
        for error in frontmatter_errors(slug, data):
            add(_FRONTMATTER_RULES[error])


def _check_stub_cycles(stubs: dict[Slug, Slug], found: set[FormatViolation]) -> None:
    for start, target in stubs.items():
        seen = {start}
        current = target
        while current in stubs:
            if current in seen:
                found.add(FormatViolation(_file_name(start), FormatRule.STUB_CYCLE))
                break
            seen.add(current)
            current = stubs[current]


def _check_index(
    text: str,
    files: dict[Slug, bytes],
    stubs: dict[Slug, Slug],
    found: set[FormatViolation],
) -> None:
    def add(rule: FormatRule) -> None:
        found.add(FormatViolation(INDEX_FILE, rule))

    domains: list[_Heading] = []
    orphans: list[_Heading] = []
    domain: _Heading | None = None
    subdomain: _Heading | None = None
    listed: Counter[Slug] = Counter()
    for _, line in scan_index(text):
        match line:
            case None:
                add(FormatRule.INDEX_SYNTAX)
            case DomainHeading(name=name):
                domain = _Heading(name)
                subdomain = None
                domains.append(domain)
            case SubdomainHeading(name=name):
                subdomain = _Heading(name)
                if domain is None:
                    add(FormatRule.INDEX_SUBDOMAIN_ORPHAN)
                    orphans.append(subdomain)
                else:
                    domain.subdomains.append(subdomain)
            case IndexEntry(slug=slug):
                listed[slug] += 1
                heading = subdomain or domain
                if heading is None:
                    # An entry before any heading is outside the index's grammar.
                    add(FormatRule.INDEX_SYNTAX)
                else:
                    heading.entries += 1

    if _has_duplicate_names(domains):
        add(FormatRule.INDEX_DOMAIN_DUPLICATE)
    if any(_has_duplicate_names(d.subdomains) for d in domains):
        add(FormatRule.INDEX_SUBDOMAIN_DUPLICATE)
    headings = [*domains, *orphans, *(s for d in domains for s in d.subdomains)]
    if any(heading.is_empty for heading in headings):
        add(FormatRule.INDEX_HEADING_EMPTY)

    for slug, count in listed.items():
        name = _file_name(slug)
        if slug not in files:
            found.add(FormatViolation(name, FormatRule.INDEX_ENTRY_DANGLING))
        elif slug in stubs:
            found.add(FormatViolation(name, FormatRule.INDEX_ENTRY_STUB))
        if count > 1:
            found.add(FormatViolation(name, FormatRule.INDEX_ENTRY_DUPLICATE))
    for slug in files:
        if slug not in stubs and slug not in listed:
            found.add(FormatViolation(_file_name(slug), FormatRule.INDEX_ENTRY_MISSING))


def _has_duplicate_names(headings: list[_Heading]) -> bool:
    return any(
        same_name(a.name, b.name)
        for position, a in enumerate(headings)
        for b in headings[position + 1 :]
    )


def check_format(memory_dir: Path) -> list[FormatViolation]:
    """Check top-level `*.md` files and `_index.md`; other files are ignored.

    Returns the violations sorted by file, then by rule in contract order.
    """
    if not memory_dir.is_dir():
        return []
    found: set[FormatViolation] = set()
    files = _read_files(memory_dir, found)
    stubs = {
        slug: target
        for slug, data in files.items()
        if (target := stub_target(data)) is not None
    }
    _check_files(files, stubs, found)
    _check_stub_cycles(stubs, found)
    index_path = memory_dir / INDEX_FILE
    if index_path.is_file() and not index_path.is_symlink():
        index_text = index_path.read_bytes().decode("utf-8", errors="replace")
        _check_index(index_text, files, stubs, found)
    elif any(slug not in stubs for slug in files):
        found.add(FormatViolation(INDEX_FILE, FormatRule.INDEX_MISSING))
    return sorted(found, key=lambda v: (v.file, _RULE_ORDER[v.rule]))
