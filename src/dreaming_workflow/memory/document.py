import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import NewType

import yaml

from dreaming_workflow.sessions import Tool

Slug = NewType("Slug", str)

MAX_SLUG_LENGTH = 80
_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_SLUG_PATTERN = re.compile(_SLUG)
_LINK_PATTERN = re.compile(rf"\[\[({_SLUG})\]\]")
_STUB_PATTERN = re.compile(rf"MOVED TO \[\[({_SLUG})\]\]\n?")
_STUB_LINE = re.compile(r"^[ \t]*MOVED TO \[\[", re.MULTILINE)
_CITATION_TIME = "%Y-%m-%d %H:%M"
_CITATION_PATTERN = re.compile(
    r"\[source: (claude-code|codex) ([^\s\]·]+) · ([^\]\n]+?) · "
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC\]"
)
_CONFLICT_PREFIX = "- CONFLICT:"
_FRONTMATTER_KEYS = frozenset({"name", "description", "metadata"})
_FENCE = "---"


def parse_slug(text: str) -> Slug | None:
    if len(text) > MAX_SLUG_LENGTH or not _SLUG_PATTERN.fullmatch(text):
        return None
    return Slug(text)


class DocumentError(StrEnum):
    NOT_UTF8 = "not-utf8"
    FRONTMATTER_MISSING = "frontmatter-missing"
    FRONTMATTER_INVALID = "frontmatter-invalid"
    FRONTMATTER_KEY = "frontmatter-key"
    NAME_MISMATCH = "name-mismatch"
    DESCRIPTION_MISSING = "description-missing"


@dataclass(frozen=True)
class MemoryFile:
    slug: Slug
    description: str
    metadata: Mapping[str, object] | None
    body: str
    version: str


def version_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _frontmatter(text: str) -> tuple[dict[object, object], str] | DocumentError:
    """Split text into its frontmatter mapping and the body after it."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\n") != _FENCE:
        return DocumentError.FRONTMATTER_MISSING
    closing = next(
        (
            number
            for number in range(1, len(lines))
            if lines[number].rstrip("\n") == _FENCE
        ),
        None,
    )
    if closing is None:
        return DocumentError.FRONTMATTER_INVALID
    try:
        frontmatter = yaml.safe_load("".join(lines[1:closing]))
    except yaml.YAMLError:
        return DocumentError.FRONTMATTER_INVALID
    if not isinstance(frontmatter, dict):
        return DocumentError.FRONTMATTER_INVALID
    # Copied into a precisely typed mapping; YAML gives keys and values of any type.
    mapping: dict[object, object] = {}
    mapping.update(frontmatter)
    return mapping, "".join(lines[closing + 1 :])


def _field_errors(slug: Slug, frontmatter: dict[object, object]) -> list[DocumentError]:
    errors: list[DocumentError] = []
    if any(key not in _FRONTMATTER_KEYS for key in frontmatter):
        errors.append(DocumentError.FRONTMATTER_KEY)
    if frontmatter.get("name") != slug:
        errors.append(DocumentError.NAME_MISMATCH)
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append(DocumentError.DESCRIPTION_MISSING)
    metadata = frontmatter.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append(DocumentError.FRONTMATTER_INVALID)
    return errors


def frontmatter_errors(slug: Slug, data: bytes) -> list[DocumentError]:
    """Every frontmatter problem of a file that isn't a stub, in a fixed order."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [DocumentError.NOT_UTF8]
    split = _frontmatter(text)
    if isinstance(split, DocumentError):
        return [split]
    return _field_errors(slug, split[0])


def parse_memory_file(slug: Slug, data: bytes) -> MemoryFile | DocumentError:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return DocumentError.NOT_UTF8
    split = _frontmatter(text)
    if isinstance(split, DocumentError):
        return split
    frontmatter, body = split
    errors = _field_errors(slug, frontmatter)
    if errors:
        return errors[0]
    description = frontmatter["description"]
    metadata = frontmatter.get("metadata")
    # _field_errors checked both types.
    assert isinstance(description, str)
    assert metadata is None or isinstance(metadata, dict)
    return MemoryFile(
        slug=slug,
        description=description,
        metadata=metadata,
        body=body,
        version=version_of(data),
    )


def render_memory_file(
    slug: Slug,
    description: str,
    body: str,
    metadata: Mapping[str, object] | None = None,
) -> bytes:
    frontmatter: dict[str, object] = {"name": slug, "description": description}
    if metadata is not None:
        frontmatter["metadata"] = dict(metadata)
    # A very wide line limit keeps long descriptions on one line.
    dumped = yaml.safe_dump(
        frontmatter, sort_keys=False, allow_unicode=True, width=1_000_000
    )
    return f"{_FENCE}\n{dumped}{_FENCE}\n{body}".encode()


def stub_target(data: bytes) -> Slug | None:
    """The slug a stub points to, or None if the data isn't a stub."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    match = _STUB_PATTERN.fullmatch(text)
    return None if match is None else Slug(match.group(1))


def is_stub(data: bytes) -> bool:
    return stub_target(data) is not None


def render_stub(target: Slug) -> bytes:
    return f"MOVED TO [[{target}]]\n".encode()


def has_stub_line(text: str) -> bool:
    """True if a line starts with the stub marker `MOVED TO [[`."""
    return _STUB_LINE.search(text) is not None


def links(text: str) -> list[Slug]:
    return [Slug(match) for match in _LINK_PATTERN.findall(text)]


@dataclass(frozen=True)
class Citation:
    """Where a fact came from. Equal when tool, session, project, and minute match."""

    tool: Tool
    session_id: str
    project_dir: str
    at: datetime

    def render(self) -> str:
        return (
            f"[source: {self.tool} {self.session_id} · {self.project_dir} · "
            f"{self.at.astimezone(UTC):{_CITATION_TIME}} UTC]"
        )


def citations(text: str) -> set[Citation]:
    found: set[Citation] = set()
    for tool, session_id, project_dir, at in _CITATION_PATTERN.findall(text):
        try:
            minute = datetime.strptime(at, _CITATION_TIME).replace(tzinfo=UTC)
        except ValueError:
            continue
        found.add(Citation(Tool(tool), session_id, project_dir, minute))
    return found


def conflict_lines(text: str) -> set[str]:
    return {
        stripped
        for line in text.splitlines()
        if (stripped := line.strip()).startswith(_CONFLICT_PREFIX)
    }
