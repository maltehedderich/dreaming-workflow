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

    def sent(result: ToolResult) -> ToolResult:
        guard.add_pending(_estimate(result))
        return result

    def within_budget(result: ToolResult, what: str, hint: str = "") -> ToolResult:
        tokens = _estimate(result)
        room = guard.room_for_read(tokens)
        if room is None:
            return sent(result)
        return sent(
            refused(
                f"{what} is about {tokens:,} tokens, and this conversation has room "
                f"for about {room:,} more. {hint}Finish with what you have."
            )
        )

    def written(slug: str, result: str | Refusal) -> ToolResult:
        if isinstance(result, Refusal):
            return sent(_refused(result))
        # The store accepted the slug, so it is valid.
        on_write(Slug(slug))
        return sent({"status": "ok", "version": result})

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
            return sent(_refused(content))
        return within_budget({"status": "ok", "text": content}, "The index")

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
            return sent(_refused(result))
        return within_budget(_search_result(result), "The search result")

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
            return sent(_refused(result))
        return within_budget(
            {
                "status": "ok",
                "text": result.content,
                "version": result.version,
                "total_lines": result.total_lines,
            },
            "That part of the file",
            hint="Read fewer lines with start_line and max_lines, or ",
        )

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
