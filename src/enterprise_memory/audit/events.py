"""Immutable audit ledger (handoff §7, §21). Every add/search/read/injection/promotion/rejection/
deprecation/deletion/permission-denial is an append-only event with a content hash."""
from __future__ import annotations
import hashlib
import json

EVENT_TYPES = ("add", "search", "read", "injection", "promotion", "rejection",
               "deprecation", "deletion", "permission_denied", "outcome")


class AuditLedger:
    def __init__(self):
        self._events = []

    def emit(self, event_type: str, actor: str, subject: str, detail: dict, seq_time: int) -> dict:
        assert event_type in EVENT_TYPES, "unknown event type %s" % event_type
        prev = self._events[-1]["hash"] if self._events else "genesis"
        body = {"seq": len(self._events), "type": event_type, "actor": actor, "subject": subject,
                "detail": detail, "t": seq_time, "prev": prev}
        body["hash"] = "sha256:" + hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:24]
        self._events.append(body)
        return body

    def events(self, event_type=None):
        return [e for e in self._events if event_type is None or e["type"] == event_type]

    def completeness(self) -> float:
        """Hash-chain integrity: every event links to its predecessor."""
        prev = "genesis"
        for e in self._events:
            if e["prev"] != prev:
                return 0.0
            prev = e["hash"]
        return 1.0
