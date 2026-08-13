"""Deterministic sanitizer for model requests/responses (P4 §12). Detects API tokens, private keys, .env
content, bearer/JWT strings, and Git installation credentials. A raw request/response is never persisted
until it has passed through this sanitizer. The Solar API key never appears in output."""
from __future__ import annotations
import re

_PATTERNS = [
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("github_pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("github_installation", re.compile(r"ghs_[A-Za-z0-9]{20,}")),
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key", re.compile(r"-----BEGIN[ A-Z]*PRIVATE KEY-----[\s\S]*?-----END[ A-Z]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("bearer", re.compile(r"[Bb]earer\s+[A-Za-z0-9._\-]{16,}")),
    ("env_secret", re.compile(r"(?m)^[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*\s*=\s*\S+$")),
]


def sanitize(text: str):
    """Return (sanitized_text, status) where status is 'clean' or 'redacted'."""
    if not text:
        return text, "clean"
    s = text
    hit = False
    for name, pat in _PATTERNS:
        s2 = pat.sub("[REDACTED:%s]" % name, s)
        if s2 != s:
            hit = True
            s = s2
    return s, ("redacted" if hit else "clean")


def contains_secret(text: str) -> bool:
    _, status = sanitize(text or "")
    return status == "redacted"
