"""R23 §6/§7 — SemanticSubtaskAtom + ObservedSubtaskNode schemas (R23-A0/G0 foundation). Deterministic hashing;
UNKNOWN for unsupported fields (never fabricated). Credential-free; no model calls here."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional

SCHEMA_VERSION = "r23/semantic_subtask_atom/1.0.0"
PROCESS_STAGES = ["ANALYZE", "REPRODUCE", "EDIT", "VERIFY"]
OPERATIONS = ["ADD", "REMOVE", "REPLACE", "DELEGATE", "PROPAGATE_ARGUMENT", "ADD_GUARD", "UPDATE_CALL_SITE",
              "MIGRATE_API", "UPDATE_IMPORT", "CHANGE_STATE_TRANSITION", "ADD_REGRESSION_TEST", "OTHER"]
UNKNOWN = "UNKNOWN"
# canonical deterministic views (same input -> same bytes)
VIEWS = ["WHOLE_ISSUE_CARD", "STAGE_INTENT_VIEW", "SEMANTIC_ATOM_VIEW", "SEMANTIC_EPISODIC_VIEW", "ORACLE_RAW_SOURCE_VIEW"]
# ORACLE_RAW_SOURCE_VIEW is oracle-diagnostic only: never indexed/retrieved, never a product candidate.


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def content_hash(obj) -> str:
    return hashlib.sha256(_canon(obj).encode()).hexdigest()


@dataclass
class Entities:
    language: str = UNKNOWN
    framework: str = UNKNOWN
    package: str = UNKNOWN
    api: List[str] = field(default_factory=list)
    symbol: List[str] = field(default_factory=list)
    error_signature: List[str] = field(default_factory=list)
    failing_test_signature: List[str] = field(default_factory=list)


@dataclass
class SemanticSubtaskAtom:
    atom_id: str
    source_task_id: str
    source_repository: str
    source_commit: str
    process_stage: str                      # one of PROCESS_STAGES
    local_objective: str
    operation: str                          # one of OPERATIONS
    schema_version: str = SCHEMA_VERSION
    source_issue_id: str = UNKNOWN
    source_fix_available_at: str = UNKNOWN
    source_author_id: str = UNKNOWN
    source_outcome: str = UNKNOWN           # SUCCESS | FAILURE | UNKNOWN  (bank policy keys off this)
    trigger: str = UNKNOWN
    preconditions: List[str] = field(default_factory=list)
    observed_failure: str = UNKNOWN
    entities: Entities = field(default_factory=Entities)
    operation_arguments: dict = field(default_factory=dict)
    invariant_to_preserve: str = UNKNOWN
    predecessor_atom_ids: List[str] = field(default_factory=list)
    required_artifacts: List[str] = field(default_factory=list)
    non_applicable_when: List[str] = field(default_factory=list)
    verification_procedure: str = UNKNOWN
    evidence_refs: dict = field(default_factory=dict)      # trajectory spans / source hunks / tests / tool obs
    abstraction_confidence: float = 0.0
    unknown_fields: List[str] = field(default_factory=list)
    content_hash: str = ""
    provenance_hash: str = ""

    def validate(self):
        assert self.process_stage in PROCESS_STAGES, "bad stage %r" % self.process_stage
        assert self.operation in OPERATIONS, "bad operation %r" % self.operation
        assert 0.0 <= self.abstraction_confidence <= 1.0
        return self

    def finalize(self, provenance: dict):
        self.validate()
        body = {k: v for k, v in asdict(self).items() if k not in ("content_hash", "provenance_hash")}
        self.content_hash = content_hash(body)
        self.provenance_hash = content_hash(provenance)
        return self


@dataclass
class ObservedSubtaskNode:
    """§7.1 — target decomposition node. NEVER contains target gold/test/FAIL_TO_PASS/verdict/future trajectory."""
    node_id: str
    stage: str
    objective: str
    query_text: str
    evidence_keywords: List[str] = field(default_factory=list)
    observed_entities: dict = field(default_factory=dict)
    predicted_operation_family: str = UNKNOWN
    preconditions: List[str] = field(default_factory=list)
    predecessors: List[str] = field(default_factory=list)
    completion_evidence: str = UNKNOWN
    status: str = "PENDING"
    graph_hash: str = ""

    def validate(self):
        assert self.stage in PROCESS_STAGES
        blob = _canon(asdict(self)).lower()
        for banned in ("fail_to_pass", "pass_to_pass", "gold_patch", "test_patch"):
            assert banned not in blob, "observed node must not carry target answer fields (%s)" % banned
        return self
