import threading
from dataclasses import dataclass
from pathlib import Path

from dreaming_workflow.atomic import write_atomic
from dreaming_workflow.memory.document import (
    DocumentError,
    Slug,
    parse_memory_file,
    parse_slug,
    render_memory_file,
    version_of,
)
from dreaming_workflow.memory.index import (
    IndexEditError,
    IndexParseError,
    parse_index,
    render_index,
)

INDEX_FILE = "_index.md"
FILE_MODE = 0o600
DIRECTORY_MODE = 0o700


@dataclass(frozen=True)
class Refusal:
    """Why the store didn't do what an agent asked. The reason is written for the model."""

    reason: str


@dataclass(frozen=True)
class FileLines:
    content: str
    version: str
    total_lines: int


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
}


class MemoryStore:
    """The only code that reads or writes the memory directory.

    Agents reach files by slug only. Every write goes through `write_atomic`
    under the target's lock, so concurrent analyses can't lose each other's changes.
    """

    def __init__(self, memory_dir: Path) -> None:
        self._memory_dir = memory_dir.absolute()
        self._locks_guard = threading.Lock()
        self._slug_locks: dict[Slug, threading.Lock] = {}
        self._index_lock = threading.Lock()

    @property
    def memory_dir(self) -> Path:
        return self._memory_dir

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

    def create_file(
        self,
        slug_text: str,
        description: str,
        body: str,
        domain: str,
        subdomain: str | None,
        index_sentence: str,
    ) -> str | Refusal:
        """Create `<slug>.md` and list it in the index. Returns the new version."""
        target = self._file_path(slug_text)
        if isinstance(target, Refusal):
            return target
        slug, path = target
        if len(index_sentence.splitlines()) > 1:
            return Refusal("The index sentence must fit on one line.")
        data = render_memory_file(slug, description, body)
        parsed = parse_memory_file(slug, data)
        if isinstance(parsed, DocumentError):
            return Refusal(_DOCUMENT_ERROR_REASONS[parsed])
        index_path = self._confined(INDEX_FILE)
        if isinstance(index_path, Refusal):
            return index_path
        with self._slug_lock(slug), self._index_lock:
            if path.exists():
                return Refusal(f"{slug} already exists. Read it and edit it instead.")
            index_text = (
                index_path.read_text(encoding="utf-8") if index_path.exists() else ""
            )
            index = parse_index(index_text)
            if isinstance(index, IndexParseError):
                return Refusal(
                    f"{INDEX_FILE} has a syntax error on line {index.line}, "
                    "so no file can be added to it now."
                )
            edit_error = index.add_entry(slug, domain, subdomain, index_sentence)
            if edit_error is not None:
                return Refusal(_INDEX_EDIT_REASONS[edit_error])
            self._ensure_memory_dir()
            write_atomic(path, data, FILE_MODE)
            write_atomic(index_path, render_index(index).encode(), FILE_MODE)
        return parsed.version

    def _ensure_memory_dir(self) -> None:
        if self._memory_dir.exists():
            return
        self._memory_dir.mkdir(mode=DIRECTORY_MODE, parents=True)
        # mkdir applies the umask; set the mode explicitly.
        self._memory_dir.chmod(DIRECTORY_MODE)
