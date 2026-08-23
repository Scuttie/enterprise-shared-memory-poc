"""§7 transactional outbox: a Postgres transaction writes canonical state AND an outbox row atomically;
an indexing worker drains the outbox to Qdrant idempotently. This in-memory reference captures the
idempotency + poison-quarantine semantics; the production impl uses a Postgres `outbox_events` table."""
from __future__ import annotations

EVENT_TYPES = ("PRIVATE_EPISODE_INDEX", "CONTRACT_INDEX", "CONTRACT_DEPRECATE", "CONTRACT_DELETE",
               "CONTRACT_SUPERSEDE", "REINDEX")


class InMemoryOutbox:
    def __init__(self, max_attempts: int = 5):
        self._events = []
        self._processed = set()          # idempotency keys already applied
        self._quarantine = []
        self._max = max_attempts

    def publish(self, event_type: str, key: str, payload: dict):
        assert event_type in EVENT_TYPES, event_type
        self._events.append({"type": event_type, "key": key, "payload": payload, "attempts": 0})

    def drain(self, apply_fn):
        """apply_fn(event) -> None on success, may raise to trigger retry/quarantine. Idempotent by key."""
        applied = 0
        remaining = []
        for ev in self._events:
            if ev["key"] in self._processed:
                continue                 # already indexed -> idempotent skip
            try:
                apply_fn(ev)
                self._processed.add(ev["key"])
                applied += 1
            except Exception as e:
                ev["attempts"] += 1
                if ev["attempts"] >= self._max:
                    ev["error"] = str(e)
                    self._quarantine.append(ev)      # poison-event quarantine
                else:
                    remaining.append(ev)
        self._events = remaining
        return {"applied": applied, "pending": len(remaining), "quarantined": len(self._quarantine)}

    @property
    def quarantined(self):
        return list(self._quarantine)
