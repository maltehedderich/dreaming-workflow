import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.support.examples import CLAUDE_CODE_PROJECTS, CODEX_SESSIONS

_CREDENTIAL_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_IDENTITY_TOKEN",
    "ANTHROPIC_IDENTITY_TOKEN_FILE",
    "ANTHROPIC_FEDERATION_RULE_ID",
    "ANTHROPIC_ORGANIZATION_ID",
)


@pytest.fixture(autouse=True)
def isolated_environment(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Keep run state in the test's directory, and keep tests away from real credentials."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    if request.node.get_closest_marker("eval") is None:
        for name in _CREDENTIAL_VARIABLES:
            monkeypatch.delenv(name, raising=False)
        empty_config = tmp_path_factory.mktemp("anthropic-config")
        monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(empty_config))
    yield


@dataclass(frozen=True)
class ExampleSessions:
    claude_code: Path
    codex: Path


@pytest.fixture
def example_sessions(tmp_path: Path) -> ExampleSessions:
    """Copies of the example session directories, so tests can't change the originals."""
    claude_code = tmp_path / "claude-code-projects"
    codex = tmp_path / "codex-sessions"
    shutil.copytree(CLAUDE_CODE_PROJECTS, claude_code)
    shutil.copytree(CODEX_SESSIONS, codex)
    return ExampleSessions(claude_code=claude_code, codex=codex)
