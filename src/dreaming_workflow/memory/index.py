import re
from collections.abc import Iterator
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


# Index edits find headings and entries by identity: two headings may hold
# equal data while the index is being repaired, so dataclass equality would
# pick the wrong one.
@dataclass(eq=False)
class Subdomain:
    name: str
    entries: list[IndexEntry] = field(default_factory=list)


@dataclass(eq=False)
class Domain:
    name: str
    entries: list[IndexEntry] = field(default_factory=list)
    subdomains: list[Subdomain] = field(default_factory=list)


@dataclass(frozen=True)
class DomainHeading:
    name: str


@dataclass(frozen=True)
class SubdomainHeading:
    name: str


type IndexLine = DomainHeading | SubdomainHeading | IndexEntry


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
    DOMAIN_NOT_FOUND = "domain-not-found"
    SUBDOMAIN_NOT_FOUND = "subdomain-not-found"


def same_name(a: str, b: str) -> bool:
    """Heading names match case-insensitively after collapsing whitespace."""
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def _is_single_line(text: str) -> bool:
    return bool(text.strip()) and len(text.splitlines()) == 1


def _valid_names(domain: str, subdomain: str | None) -> bool:
    return _is_single_line(domain) and (subdomain is None or _is_single_line(subdomain))


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
        if not _valid_names(domain, subdomain):
            return IndexEditError.INVALID_NAME
        if not _is_single_line(sentence):
            return IndexEditError.INVALID_SENTENCE
        self._entries_under(domain, subdomain).append(
            IndexEntry(slug=slug, sentence=sentence.strip())
        )
        return None

    def set_entry(
        self, slug: Slug, domain: str, subdomain: str | None, sentence: str
    ) -> IndexEditError | None:
        """List `slug` under the given headings with `sentence`.

        An entry already under those headings is rewritten in place; any other
        listing of the slug is removed. Headings left empty are removed.
        """
        if not _valid_names(domain, subdomain):
            return IndexEditError.INVALID_NAME
        if not _is_single_line(sentence):
            return IndexEditError.INVALID_SENTENCE
        target = self._entries_under(domain, subdomain)
        kept = next((entry for entry in target if entry.slug == slug), None)
        if kept is None:
            kept = IndexEntry(slug=slug, sentence=sentence.strip())
            target.append(kept)
        kept.sentence = sentence.strip()
        self._remove_entries(slug, keep=kept)
        self.remove_empty_headings()
        return None

    def remove_entry(self, slug: Slug) -> None:
        """Remove every listing of `slug`, then every heading left without entries."""
        self._remove_entries(slug, keep=None)
        self.remove_empty_headings()

    def rename_domain(self, name: str, new_name: str) -> IndexEditError | None:
        """Rename the domain `name`, merging it into `new_name` if that exists.

        Every domain heading matching `name` is merged, so this also joins
        duplicate headings. Subdomains with matching names are merged.
        """
        if not _is_single_line(new_name):
            return IndexEditError.INVALID_NAME
        sources = [d for d in self.domains if same_name(d.name, name)]
        if not sources:
            return IndexEditError.DOMAIN_NOT_FOUND
        target = next(
            (d for d in self.domains if same_name(d.name, new_name)), sources[0]
        )
        if any(source is target for source in sources):
            target.name = new_name.strip()
        for source in sources:
            if source is not target:
                _merge_domain(source, target)
        self.domains = [
            d for d in self.domains if d is target or all(d is not s for s in sources)
        ]
        self.remove_empty_headings()
        return None

    def move_subdomain(
        self, domain: str, subdomain: str, to_domain: str, to_subdomain: str | None
    ) -> IndexEditError | None:
        """Move or rename a subdomain; with `to_subdomain` None its entries become domain-wide.

        Every heading matching `domain` › `subdomain` moves. A target subdomain
        whose name matches an existing one is merged into it.
        """
        if not _valid_names(to_domain, to_subdomain):
            return IndexEditError.INVALID_NAME
        parents = [d for d in self.domains if same_name(d.name, domain)]
        if not parents:
            return IndexEditError.DOMAIN_NOT_FOUND
        sources = [
            (parent, s)
            for parent in parents
            for s in parent.subdomains
            if same_name(s.name, subdomain)
        ]
        if not sources:
            return IndexEditError.SUBDOMAIN_NOT_FOUND
        target_domain = self._domain(to_domain)
        if to_subdomain is None:
            for parent, source in sources:
                target_domain.entries.extend(source.entries)
                _drop_subdomain(parent, source)
            self.remove_empty_headings()
            return None
        target = next(
            (s for s in target_domain.subdomains if same_name(s.name, to_subdomain)),
            None,
        )
        if target is None:
            first_parent, first = sources[0]
            if first_parent is target_domain:
                target = first
            else:
                target = Subdomain(name=to_subdomain.strip())
                target_domain.subdomains.append(target)
        if any(source is target for _, source in sources):
            target.name = to_subdomain.strip()
        for parent, source in sources:
            if source is not target:
                target.entries.extend(source.entries)
                _drop_subdomain(parent, source)
        self.remove_empty_headings()
        return None

    def remove_empty_headings(self) -> None:
        for domain in self.domains:
            domain.subdomains = [s for s in domain.subdomains if s.entries]
        self.domains = [d for d in self.domains if d.entries or d.subdomains]

    def _domain(self, name: str) -> Domain:
        """The first domain matching `name`, appended if there is none."""
        found = next((d for d in self.domains if same_name(d.name, name)), None)
        if found is None:
            found = Domain(name=name.strip())
            self.domains.append(found)
        return found

    def _entries_under(self, domain: str, subdomain: str | None) -> list[IndexEntry]:
        """The entry list for the headings, creating headings that don't exist."""
        target_domain = self._domain(domain)
        if subdomain is None:
            return target_domain.entries
        target = next(
            (s for s in target_domain.subdomains if same_name(s.name, subdomain)),
            None,
        )
        if target is None:
            target = Subdomain(name=subdomain.strip())
            target_domain.subdomains.append(target)
        return target.entries

    def _remove_entries(self, slug: Slug, keep: IndexEntry | None) -> None:
        def kept(entries: list[IndexEntry]) -> list[IndexEntry]:
            return [e for e in entries if e.slug != slug or e is keep]

        for domain in self.domains:
            domain.entries = kept(domain.entries)
            for subdomain in domain.subdomains:
                subdomain.entries = kept(subdomain.entries)


def _merge_domain(source: Domain, target: Domain) -> None:
    target.entries.extend(source.entries)
    for subdomain in source.subdomains:
        match = next(
            (s for s in target.subdomains if same_name(s.name, subdomain.name)), None
        )
        if match is None:
            target.subdomains.append(subdomain)
        else:
            match.entries.extend(subdomain.entries)


def _drop_subdomain(parent: Domain, subdomain: Subdomain) -> None:
    parent.subdomains = [s for s in parent.subdomains if s is not subdomain]


def _parse_entry(line: str) -> IndexEntry | None:
    match = _ENTRY_PATTERN.fullmatch(line)
    if match is None:
        return None
    slug = parse_slug(match.group(1))
    if slug is None:
        return None
    return IndexEntry(slug=slug, sentence=match.group(2))


def _heading_name(line: str, prefix: str) -> str | None:
    if not line.startswith(prefix):
        return None
    return line.removeprefix(prefix).strip()


def scan_index(text: str) -> Iterator[tuple[int, IndexLine | None]]:
    """Yield each line that isn't blank or the title, with its 1-based number.

    None marks a line that isn't a heading or an entry.
    """
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or (number == 1 and line == TITLE):
            continue
        if (name := _heading_name(line, _SUBDOMAIN_PREFIX)) is not None:
            yield number, SubdomainHeading(name) if name else None
        elif (name := _heading_name(line, _DOMAIN_PREFIX)) is not None:
            yield number, DomainHeading(name) if name else None
        else:
            yield number, _parse_entry(line)


def parse_index(text: str) -> Index | IndexParseError:
    index = Index()
    domain: Domain | None = None
    subdomain: Subdomain | None = None
    for number, line in scan_index(text):
        match line:
            case None:
                return IndexParseError(number, IndexSyntaxError.SYNTAX)
            case SubdomainHeading(name=name):
                if domain is None:
                    return IndexParseError(number, IndexSyntaxError.SUBDOMAIN_ORPHAN)
                subdomain = Subdomain(name=name)
                domain.subdomains.append(subdomain)
            case DomainHeading(name=name):
                domain = Domain(name=name)
                subdomain = None
                index.domains.append(domain)
            case IndexEntry():
                if domain is None:
                    return IndexParseError(number, IndexSyntaxError.SYNTAX)
                (subdomain or domain).entries.append(line)
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
