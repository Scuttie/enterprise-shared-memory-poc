"""Typed index records and validated-search result types (P2). The vector index (Qdrant) and Mem0 hold
ONLY a reference payload (ids + content_hash) plus an embedding vector — never authoritative content.
Every field a caller consumes is re-loaded from PostgreSQL; the index text is used solely to compute the
embedding and is never returned to a caller nor injected into a coding model."""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

# deterministic namespace so a given (object_type, object_id, version) always maps to the same point id
_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")

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
    NOT_IN_POSTGRES = "not_in_postgres"          # candidate object no longer exists canonically
    HASH_MISMATCH = "hash_mismatch"              # index stale vs the canonical content_hash
    WRONG_ORG = "wrong_org"                      # payload/loaded org != caller org (defence in depth)
    NOT_OWNER = "not_owner"                      # private episode not owned by the caller
    NOT_CURRENT_VERSION = "not_current_version"  # contract version superseded / not the current one
    DEPRECATED = "deprecated"                    # governance_state deprecated/deleted
    NO_READ_PERMISSION = "no_read_permission"    # repository permission denies read
    SCOPE_MISMATCH = "scope_mismatch"            # candidate payload scope != requested scope


def point_id(object_type: str, object_id: str, version: int) -> str:
    """Deterministic point id. Reindexing the same object/version reuses the same id (idempotent upsert)."""
    return str(uuid.uuid5(_NS, "%s:%s:%d" % (object_type, object_id, int(version))))


@dataclass(frozen=True)
class IndexRecord:
    """Everything needed to (a) embed and (b) index a reference. `text` is embedded, never stored raw."""
    scope: str                 # PRIVATE | SHARED  -> selects the physical collection
    object_type: str           # ObjectType value
    object_id: str             # private_episodes.id OR memory_contract_versions.id
    org_id: str
    content_hash: str
    text: str                  # used ONLY to compute the embedding vector; never persisted in the payload
    owner_user_id: Optional[str] = None
    repository_id: Optional[str] = None
    contract_id: Optional[str] = None
    version_number: int = 1

    @property
    def pid(self) -> str:
        return point_id(self.object_type, self.object_id, self.version_number)

    def payload(self) -> dict:
        """The reference payload actually persisted in the vector store. NO canonical text."""
        return {"scope": self.scope, "object_type": self.object_type, "object_id": self.object_id,
                "org_id": self.org_id, "owner_user_id": self.owner_user_id,
                "repository_id": self.repository_id, "contract_id": self.contract_id,
                "version_number": self.version_number, "content_hash": self.content_hash}


@dataclass(frozen=True)
class Candidate:
    pid: str
    score: float
    payload: dict


@dataclass(frozen=True)
class ValidatedHit:
    object_type: str
    object_id: str
    org_id: str
    content_hash: str
    score: float
    canonical: dict            # canonical_json loaded from PostgreSQL (the authoritative content)
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
