"""Guard rails for `dejavu add`: secret detection and duplicate detection."""

from __future__ import annotations

import difflib
import re

# Things that must never end up in a knowledge base. A false positive is far cheaper
# than a leaked credential, so these patterns lean towards over-matching.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}")),
    ("Private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}")),
    ("Basic auth in URL", re.compile(r"https?://[^/\s:@]+:[^/\s@]+@")),
    (
        "Hard-coded secret assignment",
        re.compile(
            r"""(?ix)
            \b(?:api[_-]?key|secret|password|passwd|token|client[_-]?secret)
            \s*[:=]\s*
            ['"][^'"\s]{12,}['"]
            """
        ),
    ),
]

DUPLICATE_TITLE_RATIO = 0.75


def find_secrets(text: str) -> list[str]:
    """Return the names of the secret kinds found.

    The matched values themselves are deliberately not returned, so they cannot leak
    into logs or error messages.
    """
    found: list[str] = []
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text) and name not in found:
            found.append(name)
    return found


def title_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def find_duplicate(title: str, candidates: list[tuple[str, str]]) -> tuple[str, str] | None:
    """Find a near-duplicate title. `candidates` is a list of (uid, title)."""
    best: tuple[float, tuple[str, str]] | None = None
    for uid, other in candidates:
        ratio = title_similarity(title, other)
        if ratio >= DUPLICATE_TITLE_RATIO and (best is None or ratio > best[0]):
            best = (ratio, (uid, other))
    return best[1] if best else None


_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}")


def suggest_keywords(title: str, body: str, limit: int = 8) -> list[str]:
    """A deliberately modest fallback when no keywords are given.

    Not relying on automatic extraction is itself a design decision: the instructions
    tell Claude to hand-pick 5-10 keywords. This only exists so a bare `dejavu add` is
    not left with nothing.
    """
    seen: list[str] = []
    for token in _WORD.findall(f"{title} {body}"):
        low = token.lower()
        if low not in seen:
            seen.append(low)
        if len(seen) >= limit:
            break
    return seen
