"""In-memory MemoryBackend fake (handoff §6): lexical-overlap search + exact metadata filtering.
Lets the full governance/experiment layer run with no Mem0/vector service. Supports logical vs
physical deletion honestly."""
from __future__ import annotations
import re
from .base import MemoryBackend


def _tok(s):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def _match(md, flt):
    """Exact/subset metadata match. List values: membership; scalars: equality."""
    for k, v in (flt or {}).items():
        mv = md.get(k)
        if isinstance(v, (list, tuple, set)):
            if isinstance(mv, (list, tuple, set)):
                if not (set(mv) & set(v)):
                    return False
            elif mv not in v:
                return False
        else:
            if mv != v:
                return False
    return True


class InMemoryBackend(MemoryBackend):
    def __init__(self):
        # namespace -> {memory_id -> {"text","metadata","deleted"}}
        self._store = {}

    def _ns(self, namespace):
        return self._store.setdefault(namespace, {})

    def add(self, namespace, memory_id, text, metadata):
        self._ns(namespace)[memory_id] = {"text": text, "metadata": dict(metadata or {}), "deleted": False}
        return memory_id

    def search(self, namespace, query, top_k, metadata_filter):
        q = _tok(query)
        out = []
        for mid, rec in self._ns(namespace).items():
            if rec["deleted"]:
                continue                       # search invisibility for logically-deleted
            if not _match(rec["metadata"], metadata_filter):
                continue
            score = len(q & _tok(rec["text"])) / (len(q) + 1)
            out.append({"memory_id": mid, "text": rec["text"], "metadata": rec["metadata"], "score": score})
        out.sort(key=lambda r: -r["score"])
        return out[:top_k]

    def get(self, namespace, memory_id):
        rec = self._ns(namespace).get(memory_id)
        if not rec or rec["deleted"]:
            return None
        return {"memory_id": memory_id, "text": rec["text"], "metadata": rec["metadata"]}

    def update(self, namespace, memory_id, text, metadata):
        rec = self._ns(namespace).get(memory_id)
        if rec and not rec["deleted"]:
            rec["text"] = text
            rec["metadata"] = dict(metadata or {})

    def delete(self, namespace, memory_id, physical=False):
        ns = self._ns(namespace)
        rec = ns.get(memory_id)
        if not rec:
            return {"logical": False, "physical": False}
        if physical:
            del ns[memory_id]
            return {"logical": True, "physical": True}
        rec["deleted"] = True                  # logical deletion -> search-invisible, still present
        return {"logical": True, "physical": False}

    def list(self, namespace, metadata_filter):
        return [{"memory_id": mid, "metadata": rec["metadata"]}
                for mid, rec in self._ns(namespace).items()
                if not rec["deleted"] and _match(rec["metadata"], metadata_filter)]

    def health(self):
        return {"backend": "in_memory", "namespaces": len(self._store),
                "items": sum(len(v) for v in self._store.values())}
