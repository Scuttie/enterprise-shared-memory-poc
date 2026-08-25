"""R22 §2 — per-cell idempotent checkpoint store (resume runs only missing cells)."""
from __future__ import annotations

import json
import os


class CheckpointStore:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._done = {}
        if os.path.isfile(path):
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line:
                    r = json.loads(line)
                    self._done[r["cell_key"]] = r

    @staticmethod
    def key(target_id: str, arm: str) -> str:
        return "%s::%s" % (target_id, arm)

    def has(self, target_id: str, arm: str) -> bool:
        return self.key(target_id, arm) in self._done

    def missing(self, cells):
        return [(t, a) for (t, a) in cells if not self.has(t, a)]

    def append(self, record: dict):
        k = record["cell_key"]
        if k in self._done:
            raise ValueError("duplicate cell %s (non-idempotent)" % k)
        self._done[k] = record
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    def all(self):
        return list(self._done.values())
