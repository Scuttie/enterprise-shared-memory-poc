"""Artifact record types + content-addressed key layout (P4 §8)."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from typing import Optional

# ---- artifact classes (only these; never raw credentials or unrestricted private source dumps)
REPOSITORY_SNAPSHOT = "repository_snapshot"
SANITIZED_MODEL_REQUEST = "sanitized_model_request"
SANITIZED_MODEL_RESPONSE = "sanitized_model_response"
PARSED_PATCH = "parsed_patch"
APPLIED_PATCH = "applied_patch"
PUBLIC_TEST_OUTPUT = "public_test_output"
SANDBOX_RESULT = "sandbox_result"
PROMOTION_EVIDENCE = "promotion_evidence"
AUDIT_EXPORT = "audit_export"

ARTIFACT_CLASSES = frozenset({
    REPOSITORY_SNAPSHOT, SANITIZED_MODEL_REQUEST, SANITIZED_MODEL_RESPONSE, PARSED_PATCH, APPLIED_PATCH,
    PUBLIC_TEST_OUTPUT, SANDBOX_RESULT, PROMOTION_EVIDENCE, AUDIT_EXPORT})

# ---- durable lifecycle states
PENDING_UPLOAD = "PENDING_UPLOAD"
AVAILABLE = "AVAILABLE"
UPLOAD_FAILED = "UPLOAD_FAILED"
DELETE_REQUESTED = "DELETE_REQUESTED"
LOGICALLY_DELETED = "LOGICALLY_DELETED"
PHYSICAL_DELETE_PENDING = "PHYSICAL_DELETE_PENDING"
PHYSICALLY_CONFIRMED = "PHYSICALLY_CONFIRMED"
DELETE_FAILED = "DELETE_FAILED"

SERVABLE_STATES = frozenset({AVAILABLE})
HIDDEN_STATES = frozenset({DELETE_REQUESTED, LOGICALLY_DELETED, PHYSICAL_DELETE_PENDING,
                           PHYSICALLY_CONFIRMED, DELETE_FAILED})


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_key(org_id, artifact_class: str, content_hash: str) -> str:
    """Tenant-prefixed, content-addressed key. A caller may NOT supply an arbitrary key."""
    if artifact_class not in ARTIFACT_CLASSES:
        raise ValueError("unknown artifact_class %r" % (artifact_class,))
    return "org/%s/%s/sha256/%s" % (org_id, artifact_class, content_hash)


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    org_id: str
    object_key: str
    content_hash: str
    byte_size: Optional[int]
    content_type: Optional[str]
    artifact_class: str
    deletion_state: str
    retention_class: str
    retain_until: Optional[str]
    legal_hold: bool
    created_by: Optional[str]
    created_at: Optional[str]

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}
