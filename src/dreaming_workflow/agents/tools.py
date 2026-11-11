"""Memory tools the agents call. ADK shows each function's docstring to the model.

ADK's Claude model sends a result's `content` string alone when it has one, so
no result uses that key; every other result goes to the model as JSON.
"""

from collections.abc import Callable

from dreaming_workflow.memory import MemoryStore, Refusal, Slug

type ToolResult = dict[str, object]
type ToolFunction = Callable[..., ToolResult]


def refused(reason: str) -> ToolResult:
    # ADK marks the tool result as an error for the Messages API when `is_error` is set.
    return {"status": "refused", "reason": reason, "is_error": True}


def _refused(refusal: Refusal) -> ToolResult:
    return refused(refusal.reason)


def analyzer_tools(
    store: MemoryStore, on_write: Callable[[Slug], None]
) -> list[ToolFunction]:
    """The analyzer's tools. `on_write` receives each slug the analysis writes."""

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
            return _refused(content)
        return {"status": "ok", "text": content}

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
            return _refused(result)
        return {
            "status": "ok",
            "text": result.content,
            "version": result.version,
            "total_lines": result.total_lines,
        }

    def create_file(
        slug: str,
        description: str,
        body: str,
        domain: str,
        subdomain: str | None,
        index_sentence: str,
    ) -> ToolResult:
        """Create a new memory file and list it in the index.

        Refused if the slug already exists; read that file instead.

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
        result = store.create_file(
            slug, description, body, domain, subdomain, index_sentence
        )
        if isinstance(result, Refusal):
            return _refused(result)
        # The store accepted the slug, so it is valid.
        on_write(Slug(slug))
        return {"status": "ok", "version": result}

    return [read_index, read_file, create_file]
