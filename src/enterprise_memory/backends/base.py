"""MemoryBackend adapter interface (handoff §6). Mem0 is a REPLACEABLE retrieval substrate behind
this interface; an in-memory fake (in_memory.py) lets the whole experiment run with no external
service. Private and shared stores are physically/logically distinct namespaces and are searched
SEPARATELY (never one mixed search filtered afterwards)."""
from __future__ import annotations
import abc


class MemoryBackend(abc.ABC):
    """A namespaced vector-ish store. `namespace` distinguishes private vs shared and, for private,
    is scoped by org_id/user_id. Records carry arbitrary metadata used for deterministic filtering."""

    @abc.abstractmethod
    def add(self, namespace: str, memory_id: str, text: str, metadata: dict) -> str: ...

    @abc.abstractmethod
    def search(self, namespace: str, query: str, top_k: int, metadata_filter: dict) -> list:
        """Return [{memory_id, text, metadata, score}], filtered by metadata_filter (exact/契합)."""

    @abc.abstractmethod
    def get(self, namespace: str, memory_id: str) -> dict: ...

    @abc.abstractmethod
    def update(self, namespace: str, memory_id: str, text: str, metadata: dict) -> None: ...

    @abc.abstractmethod
    def delete(self, namespace: str, memory_id: str, physical: bool = False) -> dict:
        """Return {'logical': bool, 'physical': bool}. Do NOT claim physical deletion unless the
        backing store confirms it."""

    @abc.abstractmethod
    def list(self, namespace: str, metadata_filter: dict) -> list: ...

    @abc.abstractmethod
    def health(self) -> dict: ...
