"""Deterministic PoC security/privacy scanner (handoff §5.1/§6). Detects secrets/PII/high-entropy/
raw-source-excerpts. A BLOCK_* result forbids shared promotion + shared indexing. NOT full enterprise
DLP — a bounded, testable PoC scanner."""
from __future__ import annotations
import math
import re

PASS = "PASS"
BLOCK_SECRET = "BLOCK_SECRET"
BLOCK_PII = "BLOCK_PII"
REVIEW_HIGH_ENTROPY = "REVIEW_HIGH_ENTROPY"
REVIEW_SOURCE_EXCERPT = "REVIEW_SOURCE_EXCERPT"

_SECRET = [
    ("pem_private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("generic_api_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9\._\-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("password_assignment", re.compile(r"(?i)\b(?:password|passwd|pwd|secret)\s*[:=]\s*['\"]?[^\s'\"]{6,}")),
    ("dotenv_line", re.compile(r"(?m)^\s*[A-Z][A-Z0-9_]{2,}=\S+")),
    ("env_dump", re.compile(r"(?i)\b(?:os\.environ|printenv|export)\b.{0,40}(?:KEY|TOKEN|SECRET|PASSWORD)")),
]
_PII = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("phone", re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)\d{3,4}[\s\-]\d{4}(?!\d)")),
]
# fictional-benchmark markers that must stay distinguishable from real-looking secrets
_FAKE_MARKERS = ("FAKE", "EXAMPLE", "FICTIONAL", "sk-fake", "test-token", "ORCHID", "MAPLE")


def _entropy(s):
    if not s:
        return 0.0
    from collections import Counter
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in Counter(s).values())


def scan(text: str, allow_source_lines: int = 8):
    text = text or ""
    findings = []
    for name, rx in _SECRET:
        for m in rx.findall(text):
            snippet = m if isinstance(m, str) else (m[0] if m else "")
            if any(tag.lower() in snippet.lower() or tag.lower() in text.lower()[:0] for tag in _FAKE_MARKERS) and name in ("generic_api_key",):
                continue
            findings.append((BLOCK_SECRET, name))
    for name, rx in _PII:
        if rx.search(text):
            findings.append((BLOCK_PII, name))
    # high-entropy standalone tokens (>= 24 chars, entropy > 4.0), excluding obvious hashes-with-context
    for tok in re.findall(r"[A-Za-z0-9+/_\-]{24,}", text):
        if any(f in tok for f in _FAKE_MARKERS):
            continue
        if _entropy(tok) > 4.0 and not tok.startswith("sha256:"):
            findings.append((REVIEW_HIGH_ENTROPY, tok[:12] + "…"))
            break
    # excessive raw source excerpt (many code-ish lines)
    codey = sum(1 for ln in text.splitlines() if re.search(r"[;{}]|def |class |import |=>|::", ln))
    if codey > allow_source_lines:
        findings.append((REVIEW_SOURCE_EXCERPT, "%d code-like lines" % codey))
    # verdict: any BLOCK_* dominates
    for cls in (BLOCK_SECRET, BLOCK_PII):
        if any(f[0] == cls for f in findings):
            return {"result": cls, "findings": findings, "blocking": True}
    for cls in (REVIEW_HIGH_ENTROPY, REVIEW_SOURCE_EXCERPT):
        if any(f[0] == cls for f in findings):
            return {"result": cls, "findings": findings, "blocking": False}
    return {"result": PASS, "findings": [], "blocking": False}


def is_promotable(text: str):
    r = scan(text)
    return (not r["blocking"], r)
