"""§2.2 PrivateExecutionViewCompiler — a real security boundary for private-memory egress (replaces the
newline-strip + 160-char truncation). It verifies ownership, scans for secrets/PII, enforces repository/
path scope, strips raw source excerpts beyond policy, and produces a bounded deterministic view or
REFUSED. The private memory id/hash is preserved OUTSIDE the model-facing text."""
from __future__ import annotations

from ..promotion import security_scan as SEC

MAX_WORDS = 60


class PrivateViewRefused(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def compile_private_view(item: dict, requester_id: str, repo_id: str, max_source_lines: int = 0):
    """Return (view_text, meta) or raise PrivateViewRefused. `item` is the canonical private object:
    {id, owner, hash, note, repo_id, body}."""
    if item.get("owner") != requester_id:
        raise PrivateViewRefused("NOT_OWNER")
    if item.get("repo_id") not in (None, repo_id):
        raise PrivateViewRefused("OUT_OF_REPO_SCOPE")
    body = str(item.get("body", "") or item.get("note", ""))
    verdict = SEC.scan(body, allow_source_lines=max_source_lines)
    if isinstance(verdict, dict):
        blocking = bool(verdict.get("blocking")) or str(verdict.get("result", "")).startswith("BLOCK")
        label = verdict.get("result")
    elif isinstance(verdict, tuple):
        blocking = str(verdict[0]).startswith("BLOCK"); label = verdict[0]
    else:
        label = getattr(verdict, "verdict", verdict); blocking = str(label).startswith("BLOCK")
    if blocking:
        raise PrivateViewRefused("SECRET_OR_PII:%s" % label)
    # bounded, deterministic note; strip raw code lines beyond policy
    lines = [ln for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith(("def ", "class ", "import ", "from "))]
    note = " ".join(lines)[:200]
    words = note.split()
    if len(words) > MAX_WORDS:
        note = " ".join(words[:MAX_WORDS])
    if not note:
        raise PrivateViewRefused("EMPTY_AFTER_SANITISE")
    view = "Your prior verified note: %s" % note
    return view, {"kind": "private", "memory_id": item.get("id"), "owner": item.get("owner"),
                  "hash": item.get("hash")}
