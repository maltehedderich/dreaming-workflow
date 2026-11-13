"""Synthetic memory for tests: writers, citations, facts, files, and indexes."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dreaming_workflow.memory import Writer
from dreaming_workflow.memory.document import Citation
from dreaming_workflow.sessions import Tool

SESSION_ID = "5e55e55e-0000-4000-8000-0000000000a1"
OTHER_SESSION_ID = "5e55e55e-0000-4000-8000-0000000000b2"
PROJECT_DIR = "/Users/dev/Projects/app"
PART_START = datetime(2026, 11, 2, 10, 0, 12, tzinfo=UTC)
PART_END = datetime(2026, 11, 2, 10, 30, 45, tzinfo=UTC)


def analysis_writer(
    session_id: str = SESSION_ID,
    *,
    tool: Tool = Tool.CLAUDE_CODE,
    project_dir: str = PROJECT_DIR,
    first_at: datetime = PART_START,
    last_at: datetime = PART_END,
) -> Writer:
    return Writer.analysis(tool, session_id, project_dir, first_at, last_at)


def source(
    session_id: str = SESSION_ID,
    at: datetime = PART_START,
    *,
    tool: Tool = Tool.CLAUDE_CODE,
    project_dir: str = PROJECT_DIR,
) -> str:
    minute = at.replace(second=0, microsecond=0)
    return Citation(tool, session_id, project_dir, minute).render()


def fact(statement: str, citation: str | None = None) -> str:
    return f"- {statement} {citation or source()} [scope: Development]\n"


type IndexLayout = Mapping[str, Mapping[str | None, Sequence[tuple[str, str]]]]
"""Domain → subdomain (None for domain-wide entries) → (slug, sentence) entries."""


def memory_file_text(slug: str, body: str, description: str | None = None) -> str:
    return (
        f"---\nname: {slug}\ndescription: {description or f'Facts about {slug}.'}\n"
        f"---\n{body}"
    )


def write_memory_file(
    memory: Path, slug: str, body: str, description: str | None = None
) -> Path:
    memory.mkdir(parents=True, exist_ok=True)
    path = memory / f"{slug}.md"
    path.write_text(memory_file_text(slug, body, description))
    return path


def write_stub(memory: Path, slug: str, target: str) -> Path:
    memory.mkdir(parents=True, exist_ok=True)
    path = memory / f"{slug}.md"
    path.write_text(f"MOVED TO [[{target}]]\n")
    return path


def index_text(layout: IndexLayout) -> str:
    blocks = ["# Memory index"]
    for domain, subdomains in layout.items():
        blocks.append(f"## {domain}")
        ordered = sorted(subdomains.items(), key=lambda item: item[0] is not None)
        for subdomain, entries in ordered:
            if subdomain is not None:
                blocks.append(f"### {subdomain}")
            if entries:
                blocks.append(
                    "\n".join(
                        f"- [[{slug}]] — {sentence}" for slug, sentence in entries
                    )
                )
    return "\n\n".join(blocks) + "\n"


def write_index(memory: Path, layout: IndexLayout) -> Path:
    memory.mkdir(parents=True, exist_ok=True)
    path = memory / "_index.md"
    path.write_text(index_text(layout))
    return path


FILLER_PROJECT_DIR = "/Users/dev/Projects/filler"
FILLER_START = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
# Where each filler file goes, in turn: (domain, subdomain).
_FILLER_HEADINGS: tuple[tuple[str, str | None], ...] = (
    ("Development", None),
    ("Development", "alpha"),
    ("Development", "beta"),
    ("Business", None),
    ("Home", None),
)

CONTEXT7_CHECK_SESSION = "90f95193-2c91-4a42-a506-930d4c964c45"
CTX7_CACHE_SESSION = "c7c7c7c7-0000-4000-8000-000000000001"
CTX7_FRESH_SESSION = "c7c7c7c7-0000-4000-8000-000000000002"


@dataclass(frozen=True)
class SeededMemory:
    """A large synthetic memory and the slugs of its special cases."""

    path: Path
    filler: tuple[str, ...]
    # Two files on ctx7 whose facts disagree, from different sessions and times.
    ctx7_files: tuple[str, str]
    broken_link: str
    unlisted: str
    # No frontmatter and no index entry.
    hand_written: str
    docs_lookup: str

    @property
    def slugs(self) -> tuple[str, ...]:
        return (
            *self.filler,
            *self.ctx7_files,
            self.broken_link,
            self.unlisted,
            self.hand_written,
            self.docs_lookup,
        )


def _scope(domain: str, subdomain: str | None) -> str:
    return f"[scope: {domain}{f' › {subdomain}' if subdomain else ''}]"


def seeded_memory(path: Path, filler_files: int = 194) -> SeededMemory:
    """Write a deterministic memory of `filler_files` plus six named cases."""
    layout: dict[str, dict[str | None, list[tuple[str, str]]]] = {}

    def listed(slug: str, domain: str, subdomain: str | None, sentence: str) -> None:
        layout.setdefault(domain, {}).setdefault(subdomain, []).append((slug, sentence))

    filler: list[str] = []
    for number in range(1, filler_files + 1):
        slug = f"filler-{number:03d}"
        domain, subdomain = _FILLER_HEADINGS[number % len(_FILLER_HEADINGS)]
        citation = source(
            f"f111e111-0000-4000-8000-{number:012d}",
            FILLER_START + timedelta(minutes=number),
            project_dir=FILLER_PROJECT_DIR,
        )
        write_memory_file(
            path,
            slug,
            f"# Filler {number}\n\n- Filler fact {number}. {citation} "
            f"{_scope(domain, subdomain)}\n",
        )
        listed(slug, domain, subdomain, f"Filler fact {number}.")
        filler.append(slug)

    cache = source(
        CTX7_CACHE_SESSION,
        datetime(2026, 10, 5, 14, 2, tzinfo=UTC),
        project_dir="/Users/dev/Projects",
    )
    fresh = source(
        CTX7_FRESH_SESSION,
        datetime(2026, 10, 12, 8, 47, tzinfo=UTC),
        project_dir="/Users/dev/Projects",
    )
    write_memory_file(
        path,
        "ctx7-cli",
        f"# ctx7\n\n- ctx7 caches fetched docs for 24 hours. {cache} [scope: Development]\n",
    )
    listed("ctx7-cli", "Development", None, "How the ctx7 CLI behaves.")
    write_memory_file(
        path,
        "context7-usage",
        "# Context7\n\n- ctx7 fetches docs fresh on every call and keeps no cache. "
        f"{fresh} [scope: Development]\n",
    )
    listed("context7-usage", "Development", None, "Using Context7 from the shell.")

    write_memory_file(
        path,
        "release-checklist",
        "# Release checklist\n\n- Tag the release before publishing. "
        f"{source(CTX7_FRESH_SESSION, datetime(2026, 10, 12, 8, 50, tzinfo=UTC), project_dir='/Users/dev/Projects')} "
        "[scope: Development]\n\nSee [[deploy-steps]].\n",
    )
    listed("release-checklist", "Development", None, "Steps before a release.")

    write_memory_file(
        path,
        "shell-aliases",
        "# Shell aliases\n\n- `ll` lists files in long form. "
        f"{source(CTX7_CACHE_SESSION, datetime(2026, 10, 5, 14, 10, tzinfo=UTC), project_dir='/Users/dev/Projects')} "
        "[scope: Development]\n",
    )

    (path / "notes.md").write_text("# Notes\n\n- Rotate the backup drive monthly.\n")

    npx = Citation(
        Tool.CLAUDE_CODE,
        CONTEXT7_CHECK_SESSION,
        "/Users/dev/Projects",
        datetime(2026, 10, 17, 9, 19, tzinfo=UTC),
    ).render()
    write_memory_file(
        path,
        "docs-lookup",
        "# Docs lookup\n\n- Library docs are fetched with `npx ctx7@latest`. "
        f"{npx} [scope: Development]\n",
    )
    listed(
        "docs-lookup",
        "Development",
        None,
        "How to fetch library docs through Context7.",
    )

    write_index(path, layout)
    return SeededMemory(
        path=path,
        filler=tuple(filler),
        ctx7_files=("ctx7-cli", "context7-usage"),
        broken_link="release-checklist",
        unlisted="shell-aliases",
        hand_written="notes",
        docs_lookup="docs-lookup",
    )
