import pytest

from dreaming_workflow.memory.secrets import CredentialFamily, find_credentials
from tests.support.examples import CONTEXT7_CHECK

# Every fake credential is joined from fragments at run time, so no file in the
# repository holds a string that matches a credential pattern.
ALNUM = "A1b2C3d4E5f6G7h8"


def fake(*fragments: str) -> str:
    return "".join(fragments)


FAKE_CREDENTIALS = {
    CredentialFamily.ANTHROPIC: fake("sk", "-ant-", "api03-", ALNUM * 5),
    CredentialFamily.OPENAI: fake("sk", "-proj-", ALNUM * 4),
    CredentialFamily.GITHUB: fake("gh", "p_", ALNUM * 3),
    CredentialFamily.AWS: fake("AK", "IA", "Q2W3E4R5T6Y7U8I9"),
    CredentialFamily.GOOGLE: fake("AI", "za", "Sy", (ALNUM * 3)[:33]),
    CredentialFamily.SLACK: fake("xo", "xb-", "1234567890-", ALNUM),
    CredentialFamily.STRIPE: fake("sk", "_live_", ALNUM * 2),
    CredentialFamily.NPM: fake("np", "m_", (ALNUM * 3)[:36]),
    CredentialFamily.PRIVATE_KEY: fake("-----BEGIN ", "RSA PRIVATE", " KEY-----"),
    CredentialFamily.JSON_WEB_TOKEN: fake(
        "ey", "JhbGciOiJIUzI1NiJ9", ".", "eyJzdWIiOiIxMjM0NTY3ODkwIn0", ".", ALNUM
    ),
    CredentialFamily.BEARER: fake("Authorization: Bea", "rer ", ALNUM * 2),
    CredentialFamily.URL_PASSWORD: fake(
        "postgres://", "app:", "hunter2", "@db.local/app"
    ),
}


def test_every_family_has_a_fake_credential() -> None:
    assert set(FAKE_CREDENTIALS) == set(CredentialFamily)


@pytest.mark.parametrize("family", list(CredentialFamily))
def test_fake_credential_is_detected(family: CredentialFamily) -> None:
    text = f"The setup used {FAKE_CREDENTIALS[family]} for the service."

    assert find_credentials(text) == [family]


@pytest.mark.parametrize(
    "text",
    [
        "Fixed in commit 3f2a9c1e0b7d4a65c8e1f2a3b4c5d6e7f8091a2b.",
        "Request ID 1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed failed.",
        f"[source: claude-code {CONTEXT7_CHECK} · /Users/dev/Projects · 2026-10-17 09:21 UTC]",
        'Run `ctx7 docs /vercel/next.js "routing"` to fetch docs.',
        "See https://docs.example.com:8443/guide/setup for details.",
        "The slug is sk-learn-compat-layer-notes-for-python.",
        "Send a bearer token in the Authorization header.",
    ],
)
def test_ordinary_text_is_not_a_credential(text: str) -> None:
    assert find_credentials(text) == []


def test_result_holds_family_names_not_values() -> None:
    value = FAKE_CREDENTIALS[CredentialFamily.GITHUB]

    [family] = find_credentials(f"token {value}")

    assert value not in family
    assert family == "github-token"
