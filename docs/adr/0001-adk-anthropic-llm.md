# 1. Run agents on ADK with ADK's Claude API model

- **Status**: Accepted
- **Date**: 2026-11-11

## Context

The project reimplements Anthropic's dreaming cookbook on Google's Agent Development Kit (ADK), with Claude as the model. ADK 2.14 reaches Claude through the official `anthropic` SDK in two classes in `google.adk.models.anthropic_llm`:

- `AnthropicLlm` calls the Claude API directly.
- `Claude`, its subclass, calls Claude on Vertex AI.

`LiteLlm` also reaches the Claude API, but it adds the `litellm` dependency and doesn't resolve `ant auth login` profiles. The `anthropic` SDK resolves `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_PROFILE`, workload identity, and the active `ant auth login` profile, in that order.

An earlier draft of this record assumed that ADK reached Claude only through Vertex AI, and the first code had its own `BaseLlm` subclass that converted between ADK's and Anthropic's types. That code is gone.

## Decision

ADK runs each agent: one `LlmAgent` under a `Runner` per session part, and one for the organizer. ADK supplies the tool-call loop and builds tool schemas from Python functions.

ADK's `AnthropicLlm` sends every model call through `AsyncAnthropic.messages.create` and does the conversion. `ClaudeModel` (`agents/claude_model.py`), a thin subclass, sets the model and output limit and changes two things:

- ADK sends a signed thinking block with empty text back as redacted thinking with the signature as its data. Claude Haiku 5.5 omits thinking text unless asked for summaries, and the API needs the block back unchanged. `ClaudeModel` restores the thinking block by overriding ADK's private `_build_anthropic_kwargs`. Real redacted thinking fails the part instead, so the two can't be confused.
- Refusals and truncated or unmappable replies raise `AgentFailure` with a reason from the failure enum.

The agents get adaptive thinking at medium effort through `AnthropicGenerateContentConfig`, and prompt caching through the app's `ContextCacheConfig`. Tools mark refusals with `is_error: true`, which ADK passes on as a tool error. Each client has a 300-second timeout and up to 3 retries.

Pinned versions: `google-adk` 2.14.0, `anthropic` 2.8.0, `pyyaml` 6.0.3.

## Consequences

ADK brings a large dependency tree. The lock has 55 runtime packages; `anthropic` and `pyyaml` alone would need 17. ADK's direct dependencies include FastAPI, Starlette, Uvicorn, websockets, OpenTelemetry, `google-genai`, `google-auth`, `cryptography`, and `watchdog`. This goes against the constitution's "keep dependencies few" (principle IV), and the plan records it as a deviation.

A hand-written tool loop on the `anthropic` SDK would cut the tree, but it would drop ADK, which is the reason the project exists. To limit the cost:

- The web server, Gemini clients, and other unused parts are never imported at runtime.
- Every package is pinned in `uv.lock`, and the lock is audited before changes to it are merged.
- ADK, not this project, maintains the conversion between its types and Anthropic's. `ClaudeModel` is the only code that touches ADK's model internals. A contract test runs the real ADK `Runner` against a fake Messages API and checks that thinking blocks (with text and with empty text), signatures, and `tool_use` IDs survive the round trip, so an ADK upgrade that changes the private method fails the test.

ADK's conversion shapes the tool results: it sends a result's `content` string alone when there is one, and serializes everything else as JSON with non-ASCII characters escaped. So no tool result has a `content` field, and memory text in languages other than English costs a few more tokens.

## Audit

On 2026-11-11, pip-audit 2.10.1 checked all 63 packages in `uv.lock` (runtime and dev, without the project itself) and found no known vulnerabilities:

```sh
tmp=$(mktemp -d)
uv export --frozen --format requirements-txt --no-emit-project > "$tmp/req.txt"
uvx pip-audit --disable-pip --require-hashes -r "$tmp/req.txt"
```

`--disable-pip --require-hashes` audits the exact locked versions without resolving them again.

PyYAML 6.0.3 has no wheel for Python 3.15, so uv builds it from its sdist. The build requirements it fetches for that are outside `uv.lock` and this audit.
