import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

import yaml

Slug = NewType("Slug", str)

MAX_SLUG_LENGTH = 80
_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_SLUG_PATTERN = re.compile(_SLUG)
_LINK_PATTERN = re.compile(rf"\[\[({_SLUG})\]\]")
_STUB_PATTERN = re.compile(rf"MOVED TO \[\[{_SLUG}\]\]\n?")
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


def parse_memory_file(slug: Slug, data: bytes) -> MemoryFile | DocumentError:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return DocumentError.NOT_UTF8
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
    if any(key not in _FRONTMATTER_KEYS for key in frontmatter):
        return DocumentError.FRONTMATTER_KEY
    if frontmatter.get("name") != slug:
        return DocumentError.NAME_MISMATCH
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        return DocumentError.DESCRIPTION_MISSING
    metadata = frontmatter.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        return DocumentError.FRONTMATTER_INVALID
    return MemoryFile(
        slug=slug,
        description=description,
        metadata=metadata,
        body="".join(lines[closing + 1 :]),
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


def is_stub(data: bytes) -> bool:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return _STUB_PATTERN.fullmatch(text) is not None


def links(text: str) -> list[Slug]:
    return [Slug(match) for match in _LINK_PATTERN.findall(text)]
