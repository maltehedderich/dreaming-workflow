"""Memory tools the agents call. ADK shows each function's docstring to the model.

ADK's Claude model sends a result's `content` string alone when it has one, so
no result uses that key; every other result goes to the model as JSON.
"""

import json
from collections.abc import Callable

from dreaming_workflow.agents.budget import ContextGuard
from dreaming_workflow.memory import MemoryStore, Refusal, SearchResult, Slug, Writer
from dreaming_workflow.sessions.view import estimate_tokens

type ToolResult = dict[str, object]
type ToolFunction = Callable[..., ToolResult]


def refused(reason: str) -> ToolResult:
    # ADK marks the tool result as an error for the Messages API when `is_error` is set.
    return {"status": "refused", "reason": reason, "is_error": True}


def _refused(refusal: Refusal) -> ToolResult:
    return refused(refusal.reason)


def _estimate(result: ToolResult) -> int:
    return estimate_tokens(json.dumps(result))


class _Results:
    """Counts each tool result toward the invocation's projected prompt.

    Reads that would take the prompt past the read budget are refused.
    """

    def __init__(self, guard: ContextGuard) -> None:
        self._guard = guard

    def sent(self, result: ToolResult) -> ToolResult:
        self._guard.add_pending(_estimate(result))
        return result

    def read(self, result: ToolResult, what: str, hint: str = "") -> ToolResult:
        tokens = _estimate(result)
        room = self._guard.room_for_read(tokens)
        if room is None:
            return self.sent(result)
        return self.sent(
            refused(
                f"{what} is about {tokens:,} tokens, and this conversation has room "
                f"for about {room:,} more. {hint}Finish with what you have."
            )
        )

    def refusal(self, refusal: Refusal) -> ToolResult:
        return self.sent(_refused(refusal))

    def done(self, result: Refusal | None) -> ToolResult:
        if isinstance(result, Refusal):
            return self.refusal(result)
        return self.sent({"status": "ok"})


def analyzer_tools(
    store: MemoryStore,
    writer: Writer,
    guard: ContextGuard,
    on_write: Callable[[Slug], None],
) -> list[ToolFunction]:
    """The analyzer's tools for one part.

    Writes go to the store as `writer`. Every result counts toward `guard`'s
    projected prompt, and reads that would pass its budget are refused.
    `on_write` receives each slug the analysis writes.
    """
    return _shared_tools(
        store, writer, _Results(guard), on_read=_ignore, on_write=on_write
    )


def organizer_tools(
    store: MemoryStore, guard: ContextGuard, on_read: Callable[[Slug], None]
) -> list[ToolFunction]:
    """The organizer's tools: the analyzer's six plus whole-file and index changes.

    `on_read` receives each slug whose content `read_file` returned.
    """
    results = _Results(guard)
    writer = Writer.organizer()

    def replace_file(slug: str, content: str, version: str) -> ToolResult:
        """Replace a whole memory file, frontmatter included.

        Refused if the file changed since the read_file call that returned
        `version`; read it again and retry. Every citation you remove must
        still be in another file, and you can't add a citation that no memory
        file holds.

        Args:
          slug: The file's slug.
          content: The file's complete new content, starting with frontmatter.
          version: The version token from your latest read_file of this file.

        Returns:
          {"status": "ok", "version": <token>}
        """
        result = store.replace_file(slug, content, version, writer)
        if isinstance(result, Refusal):
            return results.refusal(result)
        return results.sent({"status": "ok", "version": result})

    def retire_file(slug: str, into: str) -> ToolResult:
        """Retire a file after merging it into another.

        The file's whole content becomes "MOVED TO [[into]]", so links to it
        still lead to the facts, and its index entry is removed. Refused unless
        every citation in the file is already in another file: move its facts
        into `into` first. Also re-points a retired file that the index still lists.

        Args:
          slug: The file to retire.
          into: The existing, unretired file that now holds its facts.

        Returns:
          {"status": "ok"}
        """
        return results.done(store.retire_file(slug, into))

    def set_index_entry(
        slug: str, domain: str, subdomain: str | None, sentence: str
    ) -> ToolResult:
        """List a file in the index, or move and rewrite its entry.

        Creates headings as needed, reusing a heading whose name matches
        ignoring case, and removes every heading left without entries. Removes
        any other listing of the slug.

        Args:
          slug: An existing, unretired file.
          domain: The domain heading, such as "Development".
          subdomain: The subdomain heading within the domain, or null to list
            the file for the whole domain.
          sentence: One sentence for the entry, on a single line.

        Returns:
          {"status": "ok"}
        """
        return results.done(store.set_index_entry(slug, domain, subdomain, sentence))

    def rename_domain(name: str, new_name: str) -> ToolResult:
        """Rename a domain, or merge it into another.

        If `new_name` already exists, all entries and subdomains move into it,
        subdomains with matching names are merged, and the old heading goes.
        Every heading matching `name` is included, so renaming a domain to its
        own name joins duplicate headings.

        Args:
          name: The domain to rename, as the index spells it.
          new_name: Its new name, or the domain to merge it into.

        Returns:
          {"status": "ok"}
        """
        return results.done(store.rename_domain(name, new_name))

    def move_subdomain(
        domain: str, subdomain: str, to_domain: str, to_subdomain: str | None
    ) -> ToolResult:
        """Move or rename a subdomain.

        With `to_subdomain` null, its entries become domain-wide entries of
        `to_domain`. A target subdomain that already exists is merged with it.
        Moving a subdomain to its own place joins duplicate headings.

        Args:
          domain: The domain the subdomain is in.
          subdomain: The subdomain to move.
          to_domain: The domain to move it to; created if missing.
          to_subdomain: Its new name, or null to make its entries domain-wide.

        Returns:
          {"status": "ok"}
        """
        return results.done(
            store.move_subdomain(domain, subdomain, to_domain, to_subdomain)
        )

    return [
        *_shared_tools(store, writer, results, on_read=on_read, on_write=_ignore),
        replace_file,
        retire_file,
        set_index_entry,
        rename_domain,
        move_subdomain,
    ]


def _ignore(_slug: Slug) -> None:
    pass


def _shared_tools(
    store: MemoryStore,
    writer: Writer,
    results: _Results,
    *,
    on_read: Callable[[Slug], None],
    on_write: Callable[[Slug], None],
) -> list[ToolFunction]:
    """The six tools both agents get, in the contract's order."""

    def written(slug: str, result: str | Refusal) -> ToolResult:
        if isinstance(result, Refusal):
            return results.refusal(result)
        # The store accepted the slug, so it is valid.
        on_write(Slug(slug))
        return results.sent({"status": "ok", "version": result})

    def read_index() -> ToolResult:
        """Read the memory index, _index.md.

        The index lists every memory file under its domain and, if it has one,
        its subdomain, with one sentence about what the file covers. Read it
        before writing so you reuse existing files, domains, and subdomains.

        Returns:
          {"status": "ok", "text": <the index, or "" if memory is empty>}
        """
        content = store.read_index()
        if isinstance(content, Refusal):
            return results.refusal(content)
        return results.read({"status": "ok", "text": content}, "The index")

    def search_memory(text: str) -> ToolResult:
        """Find lines in memory files that contain some text, ignoring case.

        Use it to check whether memory already holds a fact before reading
        whole files.

        Args:
          text: Literal text to look for, such as a tool name or identifier.

        Returns:
          {"status": "ok", "matches": [{"slug": <slug>, "line": <number>,
          "excerpt": <the line, cut to 300 characters>}], "truncated": <true if
          there were more than 50 matches>}
        """
        result = store.search_memory(text)
        if isinstance(result, Refusal):
            return results.refusal(result)
        return results.read(_search_result(result), "The search result")

    def read_file(
        slug: str, start_line: int = 1, max_lines: int | None = None
    ) -> ToolResult:
        """Read a memory file, or a range of its lines.

        Args:
          slug: The file's slug, its name without ".md", such as "uv-python".
          start_line: First line to return, counting from 1.
          max_lines: How many lines to return; null returns the rest of the file.

        Returns:
          {"status": "ok", "text": <text>, "version": <token>, "total_lines": <count>}
        """
        result = store.read_file(slug, start_line, max_lines)
        if isinstance(result, Refusal):
            return results.refusal(result)
        returned = results.read(
            {
                "status": "ok",
                "text": result.content,
                "version": result.version,
                "total_lines": result.total_lines,
            },
            "That part of the file",
            hint="Read fewer lines with start_line and max_lines, or ",
        )
        if returned["status"] == "ok":
            # The store accepted the slug, so it is valid.
            on_read(Slug(slug))
        return returned

    def create_file(
        slug: str,
        description: str,
        body: str,
        domain: str,
        subdomain: str | None,
        index_sentence: str,
    ) -> ToolResult:
        """Create a new memory file and list it in the index.

        Refused if the slug already exists; read that file and edit it instead.

        Args:
          slug: Lowercase letters and digits in hyphen-separated groups, at most
            80 characters, such as "uv-python". The file becomes "<slug>.md".
          description: What the file covers and when to read it.
          body: Markdown after the frontmatter: a heading, then one list item per fact.
          domain: Index domain, such as "Development". An existing domain whose
            name matches, ignoring case, is reused.
          subdomain: Index subdomain within the domain, or null to list the file
            for the whole domain.
          index_sentence: One sentence for the index entry, on a single line.

        Returns:
          {"status": "ok", "version": <token>}
        """
        return written(
            slug,
            store.create_file(
                slug, description, body, domain, subdomain, index_sentence, writer
            ),
        )

    def edit_file(slug: str, old_text: str, new_text: str) -> ToolResult:
        """Replace text in a memory file.

        `old_text` must occur exactly once in the file's current content; copy
        it from read_file, with enough surrounding text to make it unique.

        Args:
          slug: The file's slug.
          old_text: The exact text to replace.
          new_text: The text to put in its place.

        Returns:
          {"status": "ok", "version": <token>}
        """
        return written(slug, store.edit_file(slug, old_text, new_text, writer))

    def append_to_file(slug: str, text: str) -> ToolResult:
        """Add text to the end of a memory file, such as new facts.

        A newline is added first if the file doesn't end with one.

        Args:
          slug: The file's slug.
          text: The text to add.

        Returns:
          {"status": "ok", "version": <token>}
        """
        return written(slug, store.append_to_file(slug, text, writer))

    return [
        read_index,
        search_memory,
        read_file,
        create_file,
        edit_file,
        append_to_file,
    ]


def _search_result(result: SearchResult) -> ToolResult:
    return {
        "status": "ok",
        "matches": [
            {"slug": match.slug, "line": match.line, "excerpt": match.excerpt}
            for match in result.matches
        ],
        "truncated": result.truncated,
    }
