import re
from dataclasses import dataclass, field
from enum import StrEnum

from dreaming_workflow.memory.document import Slug, parse_slug

TITLE = "# Memory index"
_DOMAIN_PREFIX = "## "
_SUBDOMAIN_PREFIX = "### "
_ENTRY_PATTERN = re.compile(r"- \[\[([^\]]*)\]\] — (\S.*)")


@dataclass
class IndexEntry:
    slug: Slug
    sentence: str


@dataclass
class Subdomain:
    name: str
    entries: list[IndexEntry] = field(default_factory=list)


@dataclass
class Domain:
    name: str
    entries: list[IndexEntry] = field(default_factory=list)
    subdomains: list[Subdomain] = field(default_factory=list)


class IndexSyntaxError(StrEnum):
    SYNTAX = "syntax"
    SUBDOMAIN_ORPHAN = "subdomain-orphan"


@dataclass(frozen=True)
class IndexParseError:
    line: int
    cause: IndexSyntaxError


class IndexEditError(StrEnum):
    SLUG_LISTED = "slug-listed"
    INVALID_NAME = "invalid-name"
    INVALID_SENTENCE = "invalid-sentence"


def _same_name(a: str, b: str) -> bool:
    """Heading names match case-insensitively after collapsing whitespace."""
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def _is_single_line(text: str) -> bool:
    return bool(text.strip()) and len(text.splitlines()) == 1


@dataclass
class Index:
    domains: list[Domain] = field(default_factory=list)

    def slugs(self) -> list[Slug]:
        found: list[Slug] = []
        for domain in self.domains:
            found.extend(entry.slug for entry in domain.entries)
            for subdomain in domain.subdomains:
                found.extend(entry.slug for entry in subdomain.entries)
        return found

    def add_entry(
        self, slug: Slug, domain: str, subdomain: str | None, sentence: str
    ) -> IndexEditError | None:
        """Add an entry, reusing headings whose names match. Returns the error, if any."""
        if slug in self.slugs():
            return IndexEditError.SLUG_LISTED
        if not _is_single_line(domain) or (
            subdomain is not None and not _is_single_line(subdomain)
        ):
            return IndexEditError.INVALID_NAME
        if not _is_single_line(sentence):
            return IndexEditError.INVALID_SENTENCE
        entry = IndexEntry(slug=slug, sentence=sentence.strip())
        target_domain = next(
            (d for d in self.domains if _same_name(d.name, domain)), None
        )
        if target_domain is None:
            target_domain = Domain(name=domain.strip())
            self.domains.append(target_domain)
        if subdomain is None:
            target_domain.entries.append(entry)
            return None
        target_subdomain = next(
            (s for s in target_domain.subdomains if _same_name(s.name, subdomain)), None
        )
        if target_subdomain is None:
            target_subdomain = Subdomain(name=subdomain.strip())
            target_domain.subdomains.append(target_subdomain)
        target_subdomain.entries.append(entry)
        return None


def _parse_entry(line: str) -> IndexEntry | None:
    match = _ENTRY_PATTERN.fullmatch(line)
    if match is None:
        return None
    slug = parse_slug(match.group(1))
    if slug is None:
        return None
    return IndexEntry(slug=slug, sentence=match.group(2))


def parse_index(text: str) -> Index | IndexParseError:
    index = Index()
    domain: Domain | None = None
    subdomain: Subdomain | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if number == 1 and line == TITLE:
            continue
        if line.startswith(_SUBDOMAIN_PREFIX):
            if domain is None:
                return IndexParseError(number, IndexSyntaxError.SUBDOMAIN_ORPHAN)
            name = line.removeprefix(_SUBDOMAIN_PREFIX).strip()
            if not name:
                return IndexParseError(number, IndexSyntaxError.SYNTAX)
            subdomain = Subdomain(name=name)
            domain.subdomains.append(subdomain)
        elif line.startswith(_DOMAIN_PREFIX):
            name = line.removeprefix(_DOMAIN_PREFIX).strip()
            if not name:
                return IndexParseError(number, IndexSyntaxError.SYNTAX)
            domain = Domain(name=name)
            subdomain = None
            index.domains.append(domain)
        else:
            entry = _parse_entry(line)
            if entry is None or domain is None:
                return IndexParseError(number, IndexSyntaxError.SYNTAX)
            (subdomain or domain).entries.append(entry)
    return index


def _render_entries(entries: list[IndexEntry]) -> str:
    return "\n".join(f"- [[{entry.slug}]] — {entry.sentence}" for entry in entries)


def render_index(index: Index) -> str:
    blocks = [TITLE]
    for domain in index.domains:
        blocks.append(f"{_DOMAIN_PREFIX}{domain.name}")
        if domain.entries:
            blocks.append(_render_entries(domain.entries))
        for subdomain in domain.subdomains:
            blocks.append(f"{_SUBDOMAIN_PREFIX}{subdomain.name}")
            if subdomain.entries:
                blocks.append(_render_entries(subdomain.entries))
    return "\n\n".join(blocks) + "\n"
