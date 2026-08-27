"""R22 §5 — build the exact memory payload for each frozen v2 arm and hash it.

O0 memory disabled; O1 neutral scaffold (no content); O2 shuffled/deranged source; O3 full precedent (oracle-only,
may include source gold diff — never searchable/selectable for product); O4 issue card; O5 stage semantic;
O6 stage dual. Every injection persists exact text, UTF-8 byte hash, source/user/stage, token count, position.
"""
from __future__ import annotations

import hashlib

ARMS = ["O0", "O1", "O2", "O3", "O4", "O5", "O6"]
MEMORY_ENABLED = {"O0": False, "O1": False, "O2": True, "O3": True, "O4": True, "O5": True, "O6": True}
HISTORICAL_CONTENT = {"O0": False, "O1": False, "O2": True, "O3": True, "O4": True, "O5": True, "O6": True}


def _tok(s):
    return max(len(s.split()), len(s) // 4)


def build_payload(arm, *, target_id, source_id, source_user, target_user, stage,
                  source_card="", source_semantic="", source_episodic="", source_full_precedent=""):
    """Return the injection dict (or an empty O0/O1 marker). Raises on target==source leakage inputs."""
    if source_user == target_user and MEMORY_ENABLED[arm]:
        raise ValueError("source_user == target_user")
    if arm == "O0":
        text = ""
    elif arm == "O1":
        text = "[neutral stage scaffold: think step by step for the current stage; no historical example]"
    elif arm == "O2":
        text = "[shuffled precedent from unrelated source %s]\n%s" % (source_id, source_semantic or source_card)
    elif arm == "O3":
        text = "[full related precedent %s]\n%s" % (source_id, source_full_precedent)
    elif arm == "O4":
        text = "[related issue card %s]\n%s" % (source_id, source_card)
    elif arm == "O5":
        text = "[stage-semantic recipe for %s]\n%s" % (stage, source_semantic)
    elif arm == "O6":
        text = "[stage dual for %s]\nRECIPE: %s\nPRECEDENT: %s" % (stage, source_semantic, source_episodic)
    else:
        raise ValueError("unknown arm %s" % arm)
    return {
        "arm": arm, "target_id": target_id, "source_id": source_id if MEMORY_ENABLED[arm] else None,
        "source_user": source_user if MEMORY_ENABLED[arm] else None, "target_user": target_user,
        "stage": stage, "text": text, "byte_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "token_count": _tok(text), "historical_content": HISTORICAL_CONTENT[arm],
        "memory_enabled": MEMORY_ENABLED[arm],
    }
