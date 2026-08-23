"""P6/R19 §5-6: experience-card schema + the three projections.

Clean-room native model (no upstream code). One canonical ExperienceCardVersion is compiled from verified source
evidence; from it we derive a NEUTRAL retrieval projection (metadata only) and an EXECUTION view (actionable, gated).
The raw diff stays evidence and is never in the retrieval projection nor injected by default.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class GovernanceState(str, Enum):
    CANDIDATE = "candidate"
    PROBATION = "probation"
    PROMOTED = "promoted"
    DEPRECATED = "deprecated"
    QUARANTINED = "quarantined"
    DELETED = "deleted"


SEARCHABLE_STATES = {GovernanceState.PROMOTED, GovernanceState.PROBATION}


class Bank(str, Enum):
    HISTORICAL_VERIFIED = "HISTORICAL_VERIFIED"   # public issue+PR+verified merged patch (human experience)
    USER_SUCCESS = "USER_SUCCESS"                 # a source-user agent job whose patch passed the verifier


class Subtask(str, Enum):
    COMPREHENSION = "comprehension"
    LOCALIZATION = "localization"
    MODIFICATION = "modification"
    VALIDATION = "validation"


class SourceOutcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


# fields that must NEVER appear in the neutral retrieval projection (§6.3)
_RETRIEVAL_FORBIDDEN = frozenset({
    "patch_pattern", "ordered_actions", "repair_strategy",     # execution content
    "source_author_id", "source_user_identity",                # identity
    "source_verifier_hash", "evidence_hashes", "raw_diff",     # private provenance / evidence
    "source_outcome", "outcome_verdict",                       # verdict text
    "target_task_id", "target_repository", "hidden_tests",     # target-specific / hidden tests
})


def content_hash(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass
class SourceEvidence:
    """Input to the compiler. HISTORICAL_VERIFIED: public issue+PR+patch+tests. USER_SUCCESS: a verified agent job.
    NEVER contains the *target* task's gold patch or hidden tests — only the SOURCE's own resolved evidence."""
    bank: Bank
    source_type: str
    source_repository: str
    source_commit: Optional[str] = None
    source_issue_id: Optional[str] = None
    source_task_id: Optional[str] = None
    source_author_id: Optional[str] = None
    source_job_id: Optional[str] = None
    source_timestamp: Optional[str] = None
    source_outcome: SourceOutcome = SourceOutcome.UNKNOWN
    source_verifier_hash: Optional[str] = None
    # semantic content (already extracted/sanitised upstream of the compiler)
    symptom_signature: str = ""
    root_cause: str = ""
    fault_localization: str = ""
    affected_symbols: list = field(default_factory=list)
    affected_apis: list = field(default_factory=list)
    repository_convention: str = ""
    preconditions: str = ""
    non_applicability: str = ""
    repair_strategy: str = ""
    ordered_actions: list = field(default_factory=list)
    patch_pattern: str = ""
    validation_strategy: str = ""
    common_failure: str = ""
    version_scope: str = ""
    path_scope: str = ""
    language: str = ""
    framework: str = ""
    raw_diff: str = ""              # evidence only; never injected by default
    evidence_hashes: list = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ExperienceCardVersion:
    """Canonical, immutable version record (mirrors experience_card_versions)."""
    schema_version: int
    card_key: str
    bank: Bank
    source_type: str
    source_repository: str
    source_commit: Optional[str]
    source_issue_id: Optional[str]
    source_task_id: Optional[str]
    source_author_id: Optional[str]
    source_timestamp: Optional[str]
    source_outcome: SourceOutcome
    source_verifier_hash: Optional[str]
    symptom_signature: str
    root_cause: str
    fault_localization: str
    affected_symbols: list
    affected_apis: list
    repository_convention: str
    preconditions: str
    non_applicability: str
    repair_strategy: str
    ordered_actions: list
    patch_pattern: str
    validation_strategy: str
    common_failure: str
    version_scope: str
    path_scope: str
    language: str
    framework: str
    evidence_hashes: list
    confidence: float
    governance_state: GovernanceState
    content_hash: str

    def canonical_dict(self) -> dict:
        d = asdict(self)
        d["bank"] = self.bank.value
        d["source_outcome"] = self.source_outcome.value
        d["governance_state"] = self.governance_state.value
        return d
