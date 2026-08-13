"""Typed index records and validated-search result types (P2 / P2.1). The vector index (Qdrant) and Mem0
hold ONLY a reference payload (ids + hashes + governance metadata) plus an embedding vector — never
authoritative content. Every field a caller consumes is re-loaded from PostgreSQL; the index text is used
solely to compute the embedding and is never returned to a caller nor injected into a coding model."""
from __future__ import annotations
import hashlib
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

# deterministic namespace so a given (object_kind, version_id, version) always maps to the same point id
_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")

INDEX_SCHEMA_VERSION = 1

PRIVATE = "private"
SHARED = "shared"

# physically separate collections — never one collection with a scope column
PRIVATE_COLLECTION = "enterprise_private_v1"
SHARED_COLLECTION = "enterprise_shared_v1"
PRIVATE_ALIAS = "enterprise_private_current"
SHARED_ALIAS = "enterprise_shared_current"

BASE_COLLECTION = {PRIVATE: PRIVATE_COLLECTION, SHARED: SHARED_COLLECTION}
ALIAS = {PRIVATE: PRIVATE_ALIAS, SHARED: SHARED_ALIAS}


class ObjectType(str, Enum):
    PRIVATE_EPISODE = "private_episode"
    CONTRACT_VERSION = "contract_version"


class RejectionReason(str, Enum):
    SCOPE_MISMATCH = "scope_mismatch"                # payload scope != requested scope
    SCHEMA_VERSION_UNKNOWN = "schema_version_unknown"  # payload index_schema_version not supported
    WRONG_OBJECT_KIND = "wrong_object_kind"          # payload object_kind wrong for the scope
    WRONG_ORG = "wrong_org"                          # payload/canonical org != caller org
    NOT_OWNER = "not_owner"                          # private episode not owned by the caller
    NOT_IN_POSTGRES = "not_in_postgres"              # candidate object no longer exists canonically
    NO_READ_PERMISSION = "no_read_permission"        # repository permission denies read
    WRONG_REPOSITORY = "wrong_repository"            # payload repository != canonical repository
    VERSION_MISMATCH = "version_mismatch"            # payload version != canonical version
    CONTRACT_MISMATCH = "contract_mismatch"          # payload contract_id != canonical contract_id
    HASH_MISMATCH = "hash_mismatch"                  # payload content hash != canonical hash (stale index)
    NOT_CURRENT_VERSION = "not_current_version"      # contract version not the contract's current version
    DEPRECATED = "deprecated"                        # governance_state not promoted (deprecated/quarantined)
    NOT_VALID_YET = "not_valid_yet"                  # canonical valid_from in the future
    EXPIRED = "expired"                              # canonical valid_until in the past
    SUPERSEDED = "superseded"                        # another version supersedes this one
    PATH_REQUIRED = "path_required"                  # object has a path restriction but no path was requested
    PATH_SCOPE_MISMATCH = "path_scope_mismatch"      # requested path not covered by the contract path scope
    RETRIEVAL_HASH_MISMATCH = "retrieval_hash_mismatch"  # payload retrieval-text hash != recomputed hash


def sha256_hex(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def point_id(object_kind: str, version_id: str, version: int) -> str:
    """Deterministic point id. Reindexing the same object/version reuses the same id (idempotent upsert)."""
    return str(uuid.uuid5(_NS, "%s:%s:%d" % (object_kind, version_id, int(version))))


@dataclass(frozen=True)
class IndexRecord:
    """Reference projection of a canonical object. `text` is embedded, never persisted in the payload."""
    scope: str                         # PRIVATE | SHARED -> selects the physical collection
    object_kind: str                   # ObjectType value
    canonical_id: str                  # contract_id (contract) OR episode id (private)
    canonical_version_id: str          # version id (contract) OR episode id (private)
    canonical_version_number: int
    canonical_content_hash: str
    org_id: str
    text: str                          # embed source ONLY — never persisted, never returned
    owner_user_id: Optional[str] = None
    repository_id: Optional[str] = None
    contract_id: Optional[str] = None
    governance_state: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    path_scope: Optional[List[str]] = None
    indexed_at: Optional[str] = None
    index_schema_version: int = INDEX_SCHEMA_VERSION

    @property
    def pid(self) -> str:
        return point_id(self.object_kind, self.canonical_version_id, self.canonical_version_number)

    @property
    def retrieval_text_hash(self) -> str:
        return sha256_hex(self.text)

    def payload(self) -> dict:
        """The reference payload actually persisted in the vector store. NO canonical text."""
        return {"index_schema_version": self.index_schema_version, "scope": self.scope,
                "object_kind": self.object_kind, "canonical_id": self.canonical_id,
                "canonical_version_id": self.canonical_version_id,
                "canonical_version_number": self.canonical_version_number,
                "canonical_content_hash": self.canonical_content_hash, "org_id": self.org_id,
                "owner_user_id": self.owner_user_id, "repository_id": self.repository_id,
                "contract_id": self.contract_id, "governance_state": self.governance_state,
                "valid_from": self.valid_from, "valid_until": self.valid_until,
                "path_scope": self.path_scope, "retrieval_text_hash": self.retrieval_text_hash,
                "indexed_at": self.indexed_at}


@dataclass(frozen=True)
class Candidate:
    pid: str
    score: float
    payload: dict


@dataclass(frozen=True)
class ValidatedHit:
    object_kind: str
    canonical_id: str
    canonical_version_id: str
    org_id: str
    content_hash: str
    score: float
    canonical: dict                    # canonical_json loaded from PostgreSQL (the authoritative content)
    version_number: int = 1
    contract_id: Optional[str] = None


@dataclass
class SearchResult:
    hits: List[ValidatedHit] = field(default_factory=list)
    rejections: List[Tuple[str, RejectionReason]] = field(default_factory=list)

    def reject(self, pid: str, reason: RejectionReason):
        self.rejections.append((pid, reason))

    def reasons(self) -> List[str]:
        return [r.value for _, r in self.rejections]
