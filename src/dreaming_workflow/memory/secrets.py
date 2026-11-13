"""Credential patterns the store refuses to write into memory.

Results name the credential family only, so a match never carries the
credential's value into a refusal, log, or report.
"""

import re
from enum import StrEnum


class CredentialFamily(StrEnum):
    ANTHROPIC = "anthropic-api-key"
    OPENAI = "openai-api-key"
    GITHUB = "github-token"
    AWS = "aws-access-key-id"
    GOOGLE = "google-api-key"
    SLACK = "slack-token"
    STRIPE = "stripe-secret-key"
    NPM = "npm-token"
    PRIVATE_KEY = "private-key"
    JSON_WEB_TOKEN = "json-web-token"
    BEARER = "bearer-token"
    URL_PASSWORD = "url-with-password"


_TOKEN = r"[A-Za-z0-9_-]"

# Lengths are lower bounds a little under each issuer's documented format, so
# shortened or newer variants still match while ordinary words don't. The
# OpenAI pattern also requires a digit so a long hyphenated slug isn't flagged.
_PATTERNS: tuple[tuple[CredentialFamily, re.Pattern[str]], ...] = (
    (CredentialFamily.ANTHROPIC, re.compile(rf"\bsk-ant-{_TOKEN}{{32,}}")),
    (
        CredentialFamily.OPENAI,
        re.compile(rf"\bsk-(?!ant-)(?={_TOKEN}*[0-9]){_TOKEN}{{32,}}"),
    ),
    (
        CredentialFamily.GITHUB,
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})"),
    ),
    (CredentialFamily.AWS, re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (CredentialFamily.GOOGLE, re.compile(rf"\bAIza{_TOKEN}{{35}}")),
    (CredentialFamily.SLACK, re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    (CredentialFamily.STRIPE, re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}")),
    (CredentialFamily.NPM, re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    (
        CredentialFamily.PRIVATE_KEY,
        re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    ),
    (
        CredentialFamily.JSON_WEB_TOKEN,
        re.compile(rf"\beyJ{_TOKEN}{{10,}}\.{_TOKEN}{{10,}}\.{_TOKEN}{{10,}}"),
    ),
    (
        CredentialFamily.BEARER,
        re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE),
    ),
    (
        CredentialFamily.URL_PASSWORD,
        re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@[^\s/@]+"),
    ),
)


def find_credentials(text: str) -> list[CredentialFamily]:
    """Return the families of credentials found in `text`, never the matches."""
    return [family for family, pattern in _PATTERNS if pattern.search(text)]
