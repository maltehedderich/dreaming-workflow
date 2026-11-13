import hashlib
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dreaming_workflow.atomic import write_atomic
from dreaming_workflow.memory.document import (
    Citation,
    DocumentError,
    Slug,
    citations,
    conflict_lines,
    is_stub,
    parse_memory_file,
    parse_slug,
    render_memory_file,
    render_stub,
    version_of,
)
from dreaming_workflow.memory.index import (
    Index,
    IndexEditError,
    IndexParseError,
    parse_index,
    render_index,
)
from dreaming_workflow.memory.secrets import find_credentials
from dreaming_workflow.sessions import Tool

INDEX_FILE = "_index.md"
FILE_MODE = 0o600
DIRECTORY_MODE = 0o700
MAX_SEARCH_MATCHES = 50
EXCERPT_LENGTH = 300
CREDENTIAL_REASON = "Refer to the credential by name instead of writing its value."
_MINUTE = "%Y-%m-%d %H:%M"


def _minute(at: datetime) -> datetime:
    return at.astimezone(UTC).replace(second=0, microsecond=0)


@dataclass(frozen=True)
class Refusal:
    """Why the store didn't do what an agent asked. The reason is written for the model."""

    reason: str


@dataclass(frozen=True)
class FileLines:
    content: str
    version: str
    total_lines: int


@dataclass(frozen=True)
class SearchMatch:
    slug: Slug
    line: int
    excerpt: str


@dataclass(frozen=True)
class SearchResult:
    matches: tuple[SearchMatch, ...]
    truncated: bool


@dataclass(frozen=True)
class MemorySnapshot:
    """Memory's state at one moment, for comparing the start and end of a run."""

    hashes: Mapping[Slug, str]
    stubs: frozenset[Slug]
    conflicts: frozenset[str]


@dataclass(frozen=True)
class CitationScope:
    """What an analysis may cite: its own session, at a minute inside its part."""

    tool: Tool
    session_id: str
    project_dir: str
    first_at: datetime
    last_at: datetime

    def allows(self, citation: Citation) -> bool:
        return (
            citation.tool == self.tool
            and citation.session_id == self.session_id
            and citation.project_dir == self.project_dir
            and _minute(self.first_at) <= citation.at <= _minute(self.last_at)
        )

    def refusal(self, citation: Citation) -> Refusal:
        return Refusal(
            f"{citation.render()} isn't a citation of this part. Cite "
            f"[source: {self.tool} {self.session_id} · {self.project_dir} · "
            "<YYYY-MM-DD HH:MM> UTC] with the minute of the message that shows "
            f"the fact, from {_minute(self.first_at):{_MINUTE}} to "
            f"{_minute(self.last_at):{_MINUTE}} UTC."
        )


@dataclass(frozen=True)
class Writer:
    """Who asks for a write; the citation rules depend on it.

    An analysis carries the scope it may cite. The organizer, with no scope,
    may only add citations that memory already holds.
    """

    scope: CitationScope | None

    @classmethod
    def organizer(cls) -> Writer:
        return cls(None)

    @classmethod
    def analysis(
        cls,
        tool: Tool,
        session_id: str,
        project_dir: str,
        first_at: datetime,
        last_at: datetime,
    ) -> Writer:
        return cls(CitationScope(tool, session_id, project_dir, first_at, last_at))


_DOCUMENT_ERROR_REASONS = {
    DocumentError.NOT_UTF8: "The file isn't valid UTF-8.",
    DocumentError.FRONTMATTER_MISSING: "The file must start with YAML frontmatter.",
    DocumentError.FRONTMATTER_INVALID: "The frontmatter must be a valid YAML mapping.",
    DocumentError.FRONTMATTER_KEY: "Frontmatter may only hold name, description, and metadata.",
    DocumentError.NAME_MISMATCH: "Frontmatter name must equal the slug.",
    DocumentError.DESCRIPTION_MISSING: "The description must not be empty.",
}

_INDEX_EDIT_REASONS = {
    IndexEditError.SLUG_LISTED: "The index already lists this slug.",
    IndexEditError.INVALID_NAME: "Domain and subdomain names must be non-empty and on one line.",
    IndexEditError.INVALID_SENTENCE: "The index sentence must be non-empty and on one line.",
    IndexEditError.DOMAIN_NOT_FOUND: (
        "The index has no domain with that name. Read the index for the exact names."
    ),
    IndexEditError.SUBDOMAIN_NOT_FOUND: (
        "That domain has no subdomain with that name. "
        "Read the index for the exact names."
    ),
}

type IndexEdit = Callable[[Index], IndexEditError | None]


class MemoryStore:
    """The only code that reads or writes the memory directory.

    Agents reach files by slug only. Every write passes the guards in
    `_check_and_write` and goes through `write_atomic` under the target's lock,
    so concurrent analyses can't lose each other's changes.

    `before_first_write` runs once, before the first write. `on_analysis_write`
    receives the slug of each file an analysis writes; organizer writes don't
    call it.
    """

    def __init__(
        self,
        memory_dir: Path,
        *,
        before_first_write: Callable[[], None] | None = None,
        on_analysis_write: Callable[[Slug], None] | None = None,
    ) -> None:
        self._memory_dir = memory_dir.absolute()
        self._before_first_write = before_first_write
        self._on_analysis_write = on_analysis_write
        self._first_write_lock = threading.Lock()
        self._has_written = False
        self._locks_guard = threading.Lock()
        self._slug_locks: dict[Slug, threading.Lock] = {}
        self._index_lock = threading.Lock()
        # Held from checking citations in other files until the write lands,
        # so two writes can't each remove the other's last copy. Locks are
        # always taken in the order: slug, index, removal.
        self._removal_lock = threading.Lock()

    @property
    def memory_dir(self) -> Path:
        return self._memory_dir

    @property
    def has_written(self) -> bool:
        return self._has_written

    def _slug_lock(self, slug: Slug) -> threading.Lock:
        with self._locks_guard:
            return self._slug_locks.setdefault(slug, threading.Lock())

    def _confined(self, name: str) -> Path | Refusal:
        """Resolve a file name to a path that is a direct child of memory and not a link."""
        path = self._memory_dir / name
        if path.is_symlink():
            return Refusal(
                f"{name} is a symbolic link; memory tools don't follow links."
            )
        if path.resolve().parent != self._memory_dir.resolve():
            return Refusal(f"{name} isn't inside the memory directory.")
        return path

    def _file_path(self, slug_text: str) -> tuple[Slug, Path] | Refusal:
        slug = parse_slug(slug_text)
        if slug is None:
            return Refusal(
                "A slug is lowercase letters and digits in hyphen-separated groups, "
                "at most 80 characters, such as uv-python."
            )
        path = self._confined(f"{slug}.md")
        if isinstance(path, Refusal):
            return path
        return slug, path

    def _memory_files(self) -> Iterator[tuple[Slug, Path]]:
        """Memory files and stubs in slug order, skipping links and other names."""
        if not self._memory_dir.is_dir():
            return
        for path in sorted(self._memory_dir.glob("*.md")):
            slug = parse_slug(path.stem)
            if slug is not None and not path.is_symlink() and path.is_file():
                yield slug, path

    def read_index(self) -> str | Refusal:
        path = self._confined(INDEX_FILE)
        if isinstance(path, Refusal):
            return path
        if not path.exists():
            return ""
        return path.read_bytes().decode("utf-8", errors="replace")

    def read_file(
        self, slug_text: str, start_line: int = 1, max_lines: int | None = None
    ) -> FileLines | Refusal:
        target = self._file_path(slug_text)
        if isinstance(target, Refusal):
            return target
        slug, path = target
        if start_line < 1 or (max_lines is not None and max_lines < 1):
            return Refusal("start_line and max_lines must be 1 or more.")
        if not path.exists():
            return Refusal(f"There is no memory file {slug}.")
        data = path.read_bytes()
        lines = data.decode("utf-8", errors="replace").splitlines(keepends=True)
        end = None if max_lines is None else start_line - 1 + max_lines
        return FileLines(
            content="".join(lines[start_line - 1 : end]),
            version=version_of(data),
            total_lines=len(lines),
        )

    def search_memory(self, text: str) -> SearchResult | Refusal:
        """Find lines containing `text`, ignoring case, in memory files and stubs."""
        if not text.strip():
            return Refusal("Search for some text, not an empty string.")
        needle = text.casefold()
        matches: list[SearchMatch] = []
        for slug, path in self._memory_files():
            content = path.read_bytes().decode("utf-8", errors="replace")
            for number, line in enumerate(content.splitlines(), start=1):
                if needle not in line.casefold():
                    continue
                if len(matches) == MAX_SEARCH_MATCHES:
                    return SearchResult(tuple(matches), truncated=True)
                matches.append(SearchMatch(slug, number, line[:EXCERPT_LENGTH]))
        return SearchResult(tuple(matches), truncated=False)

    def create_file(
        self,
        slug_text: str,
        description: str,
        body: str,
        domain: str,
        subdomain: str | None,
        index_sentence: str,
        writer: Writer,
    ) -> str | Refusal:
        """Create `<slug>.md` and list it in the index. Returns the new version."""
        target = self._file_path(slug_text)
        if isinstance(target, Refusal):
            return target
        slug, path = target
        new_text = "\n".join(
            (description, body, domain, subdomain or "", index_sentence)
        )
        if find_credentials(new_text):
            return Refusal(CREDENTIAL_REASON)
        if len(index_sentence.splitlines()) > 1:
            return Refusal("The index sentence must fit on one line.")
        index_path = self._confined(INDEX_FILE)
        if isinstance(index_path, Refusal):
            return index_path
        data = render_memory_file(slug, description, body)
        with self._slug_lock(slug), self._index_lock:
            if path.exists() or path.is_symlink():
                return Refusal(f"{slug} already exists. Read it and edit it instead.")
            index = self._load_index(index_path)
            if isinstance(index, Refusal):
                return index
            edit_error = index.add_entry(slug, domain, subdomain, index_sentence)
            if edit_error is not None:
                return Refusal(_INDEX_EDIT_REASONS[edit_error])
            return self._check_and_write(
                slug,
                path,
                "",
                data,
                writer,
                also_write=(index_path, render_index(index).encode()),
            )

    def edit_file(
        self, slug_text: str, old_text: str, new_text: str, writer: Writer
    ) -> str | Refusal:
        """Replace the one occurrence of `old_text`. Returns the new version."""
        target = self._file_path(slug_text)
        if isinstance(target, Refusal):
            return target
        slug, path = target
        if find_credentials(new_text):
            return Refusal(CREDENTIAL_REASON)
        if not old_text:
            return Refusal("old_text must not be empty.")
        with self._slug_lock(slug):
            current = self._current_text(slug, path)
            if isinstance(current, Refusal):
                return current
            count = current.count(old_text)
            if count == 0:
                return Refusal(
                    f"old_text doesn't occur in {slug}. "
                    "Read the file and copy the text exactly."
                )
            if count > 1:
                return Refusal(
                    f"old_text occurs {count} times in {slug}. "
                    "Include more of the surrounding text so it occurs once."
                )
            result = current.replace(old_text, new_text, 1)
            return self._check_and_write(slug, path, current, result.encode(), writer)

    def append_to_file(
        self, slug_text: str, text: str, writer: Writer
    ) -> str | Refusal:
        """Add `text` at the end, after a newline if needed. Returns the new version."""
        target = self._file_path(slug_text)
        if isinstance(target, Refusal):
            return target
        slug, path = target
        if find_credentials(text):
            return Refusal(CREDENTIAL_REASON)
        if not text.strip():
            return Refusal("text must not be empty.")
        with self._slug_lock(slug):
            current = self._current_text(slug, path)
            if isinstance(current, Refusal):
                return current
            separator = "\n" if current and not current.endswith("\n") else ""
            result = current + separator + text
            return self._check_and_write(slug, path, current, result.encode(), writer)

    def replace_file(
        self, slug_text: str, content: str, version: str, writer: Writer
    ) -> str | Refusal:
        """Replace the whole file, if it hasn't changed since the read that returned `version`."""
        target = self._file_path(slug_text)
        if isinstance(target, Refusal):
            return target
        slug, path = target
        if find_credentials(content):
            return Refusal(CREDENTIAL_REASON)
        with self._slug_lock(slug):
            if not path.exists():
                return Refusal(
                    f"There is no memory file {slug}. Create it with create_file."
                )
            data = path.read_bytes()
            if version_of(data) != version:
                return Refusal(
                    f"{slug} changed since the read that returned this version. "
                    "Read it again, then replace it."
                )
            # Replacing is how a file that isn't valid UTF-8 gets repaired.
            current = data.decode("utf-8", errors="replace")
            return self._check_and_write(slug, path, current, content.encode(), writer)

    def retire_file(self, slug_text: str, into_text: str) -> Refusal | None:
        """Turn `slug` into a stub pointing to `into`, and remove its index entry.

        Refused unless every citation in `slug` survives in another file.
        """
        target = self._file_path(slug_text)
        if isinstance(target, Refusal):
            return target
        slug, path = target
        into_target = self._file_path(into_text)
        if isinstance(into_target, Refusal):
            return into_target
        into, into_path = into_target
        if into == slug:
            return Refusal("A file can't be retired into itself.")
        index_path = self._confined(INDEX_FILE)
        if isinstance(index_path, Refusal):
            return index_path
        with self._slug_lock(slug), self._index_lock:
            if not path.exists():
                return Refusal(f"There is no memory file {slug}.")
            if not into_path.exists():
                return Refusal(
                    f"There is no memory file {into}. Retire into an existing file."
                )
            if is_stub(into_path.read_bytes()):
                return Refusal(
                    f"{into} is retired itself. Retire into the file it points to."
                )
            index = self._load_index(index_path)
            if isinstance(index, Refusal):
                return index
            index.remove_entry(slug)
            current = path.read_bytes().decode("utf-8", errors="replace")
            with self._removal_lock:
                missing = citations(current) - self._citations_outside(slug)
                if missing:
                    example = min(citation.render() for citation in missing)
                    return Refusal(
                        f"{slug} holds {example}, and no other memory file does. "
                        f"Move its facts into {into} first."
                    )
                self._write(
                    path,
                    render_stub(into),
                    also_write=(index_path, render_index(index).encode()),
                )
        return None

    def set_index_entry(
        self, slug_text: str, domain: str, subdomain: str | None, sentence: str
    ) -> Refusal | None:
        """List an existing file under the given headings, moving its entry if needed."""
        target = self._file_path(slug_text)
        if isinstance(target, Refusal):
            return target
        slug, path = target
        if find_credentials("\n".join((domain, subdomain or "", sentence))):
            return Refusal(CREDENTIAL_REASON)
        with self._slug_lock(slug), self._index_lock:
            if not path.exists():
                return Refusal(
                    f"There is no memory file {slug}; the index lists only existing files."
                )
            if is_stub(path.read_bytes()):
                return Refusal(
                    f"{slug} is retired; the index doesn't list retired files."
                )
            return self._edit_index(
                lambda index: index.set_entry(slug, domain, subdomain, sentence)
            )

    def rename_domain(self, name: str, new_name: str) -> Refusal | None:
        if find_credentials(new_name):
            return Refusal(CREDENTIAL_REASON)
        with self._index_lock:
            return self._edit_index(lambda index: index.rename_domain(name, new_name))

    def move_subdomain(
        self, domain: str, subdomain: str, to_domain: str, to_subdomain: str | None
    ) -> Refusal | None:
        if find_credentials("\n".join((to_domain, to_subdomain or ""))):
            return Refusal(CREDENTIAL_REASON)
        with self._index_lock:
            return self._edit_index(
                lambda index: index.move_subdomain(
                    domain, subdomain, to_domain, to_subdomain
                )
            )

    def snapshot(self) -> MemorySnapshot:
        hashes: dict[Slug, str] = {}
        stubs: set[Slug] = set()
        conflicts: set[str] = set()
        for slug, path in self._memory_files():
            data = path.read_bytes()
            hashes[slug] = hashlib.sha256(data).hexdigest()
            if is_stub(data):
                stubs.add(slug)
            else:
                conflicts |= conflict_lines(data.decode("utf-8", errors="replace"))
        return MemorySnapshot(hashes, frozenset(stubs), frozenset(conflicts))

    def _load_index(self, index_path: Path) -> Index | Refusal:
        text = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
        index = parse_index(text)
        if isinstance(index, IndexParseError):
            return Refusal(
                f"{INDEX_FILE} has a syntax error on line {index.line}, "
                "so the index can't be changed now."
            )
        return index

    def _edit_index(self, edit: IndexEdit) -> Refusal | None:
        """Apply `edit` to the index and write it. The caller holds the index lock."""
        index_path = self._confined(INDEX_FILE)
        if isinstance(index_path, Refusal):
            return index_path
        index = self._load_index(index_path)
        if isinstance(index, Refusal):
            return index
        error = edit(index)
        if error is not None:
            return Refusal(_INDEX_EDIT_REASONS[error])
        self._write(index_path, render_index(index).encode(), None)
        return None

    def _current_text(self, slug: Slug, path: Path) -> str | Refusal:
        if not path.exists():
            return Refusal(
                f"There is no memory file {slug}. Create it with create_file."
            )
        try:
            return path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            return Refusal(f"{slug} isn't valid UTF-8, so it can't be edited.")

    def _check_and_write(
        self,
        slug: Slug,
        path: Path,
        old_text: str,
        result: bytes,
        writer: Writer,
        also_write: tuple[Path, bytes] | None = None,
    ) -> str | Refusal:
        """Apply the format and citation guards to a write, then make it.

        The caller has already checked the slug and scanned the new text for
        credentials, and holds the slug's lock.
        """
        scope = writer.scope
        if is_stub(result):
            return Refusal(
                "Only the organizer retires files; don't write a stub."
                if scope is not None
                else "Retire files with retire_file; don't write a stub."
            )
        parsed = parse_memory_file(slug, result)
        if isinstance(parsed, DocumentError):
            return Refusal(_DOCUMENT_ERROR_REASONS[parsed])
        before = citations(old_text)
        after = citations(result.decode("utf-8"))
        added = after - before
        removed = before - after
        if scope is not None:
            for citation in sorted(added, key=Citation.render):
                if not scope.allows(citation):
                    return scope.refusal(citation)
        if not removed and (scope is not None or not added):
            self._write(path, result, also_write)
        else:
            with self._removal_lock:
                elsewhere = self._citations_outside(slug)
                unknown = added - elsewhere if scope is None else set()
                if unknown:
                    example = min(citation.render() for citation in unknown)
                    return Refusal(
                        f"{example} isn't in any other memory file. The organizer "
                        "moves and rewrites facts with their sources; it doesn't "
                        "add sources."
                    )
                missing = removed - elsewhere
                if missing:
                    example = min(citation.render() for citation in missing)
                    return Refusal(
                        f"This change drops {example}, and no other memory file "
                        "holds it. Keep the citation, for example in a REPLACED: line."
                    )
                self._write(path, result, also_write)
        if scope is not None and self._on_analysis_write is not None:
            self._on_analysis_write(slug)
        return parsed.version

    def _citations_outside(self, slug: Slug) -> set[Citation]:
        found: set[Citation] = set()
        for other, path in self._memory_files():
            data = path.read_bytes()
            if other != slug and not is_stub(data):
                found |= citations(data.decode("utf-8", errors="replace"))
        return found

    def _write(
        self, path: Path, data: bytes, also_write: tuple[Path, bytes] | None
    ) -> None:
        self._prepare_first_write()
        write_atomic(path, data, FILE_MODE)
        if also_write is not None:
            write_atomic(also_write[0], also_write[1], FILE_MODE)

    def _prepare_first_write(self) -> None:
        with self._first_write_lock:
            if self._has_written:
                return
            if self._before_first_write is not None:
                self._before_first_write()
            self._ensure_memory_dir()
            self._has_written = True

    def _ensure_memory_dir(self) -> None:
        if self._memory_dir.exists():
            return
        self._memory_dir.mkdir(mode=DIRECTORY_MODE, parents=True)
        # mkdir applies the umask; set the mode explicitly.
        self._memory_dir.chmod(DIRECTORY_MODE)
