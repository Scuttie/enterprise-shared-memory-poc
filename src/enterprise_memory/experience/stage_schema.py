"""R22 §5,§7 — StageMemoryRecord: stage-aligned executable memory (clean-room, no upstream code).

A single source issue yields several stage records (COMPREHEND/REPRODUCE/LOCALIZE/EDIT/VERIFY). Each record captures
one *transition* (state -> attempted action -> feedback -> successful action -> verification) plus the trigger
signatures used for retrieval. Target-task information is FORBIDDEN and enforced by a sentinel.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional

from .schema import GovernanceState

SCHEMA_VERSION = "stage_memory/1.0.0"


class Stage(str, Enum):
    COMPREHEND = "COMPREHEND"
    REPRODUCE = "REPRODUCE"
    LOCALIZE = "LOCALIZE"
    EDIT = "EDIT"
    VERIFY = "VERIFY"


# Any of these keys appearing anywhere in a compiled record/view is a hard error: R22 must never carry target-task
# answers, outcomes, or experiment arms into memory (§5 forbidden fields, §21 hard stops).
FORBIDDEN_TARGET_KEYS = frozenset({
    "target_task_id", "target_instance_id", "target_patch", "target_tests", "target_test_patch",
    "target_outcome", "target_result", "experiment_arm", "arm", "future_result", "gold_patch",
    "fail_to_pass", "pass_to_pass", "hidden_test",
})


@dataclass
class StageIdentity:
    memory_id: str
    source_task_id: str
    source_repository: str
    source_commit: str
    source_user_id: str
    source_timestamp: str
    source_outcome: str            # "resolved" | "unresolved" (source grader verdict)
    verifier_hash: str


@dataclass
class StageTrigger:
    issue_type: str = ""
    error_signature: str = ""
    stack_trace_signature: str = ""
    failing_test_signature: str = ""
    language: str = ""
    framework: str = ""
    dependency_versions: List[str] = field(default_factory=list)
    affected_paths: List[str] = field(default_factory=list)
    affected_symbols: List[str] = field(default_factory=list)
    affected_apis: List[str] = field(default_factory=list)
    violated_contract: str = ""
    code_graph_entities: List[str] = field(default_factory=list)


@dataclass
class StageTransition:
    observation_before: str = ""
    attempted_action: str = ""
    environment_feedback: str = ""
    failure_reason: str = ""
    successful_action: str = ""
    observation_after: str = ""


@dataclass
class StageAction:
    operation_type: str = ""            # e.g. defensive_copy, guard_clause, api_migration, add_regression_test
    target_role: str = ""               # which symbol/role the operation applies to
    ordered_steps: List[str] = field(default_factory=list)
    edit_template: str = ""
    ast_edit_pattern: str = ""
    preconditions: List[str] = field(default_factory=list)
    non_applicability: List[str] = field(default_factory=list)
    side_effects: List[str] = field(default_factory=list)
    rollback_condition: str = ""


@dataclass
class StageVerification:
    command_type: str = ""
    source_test_evidence: str = ""
    expected_observation: str = ""
    regression_scope: str = ""


@dataclass
class StageGovernance:
    confidence: float = 0.0
    state: GovernanceState = GovernanceState.CANDIDATE
    valid_from: str = ""
    valid_until: str = ""
    supersedes: Optional[str] = None
    provenance_hashes: List[str] = field(default_factory=list)


@dataclass
class StageRawEvidence:
    trajectory_artifact_id: str = ""
    patch_artifact_id: str = ""
    test_artifact_id: str = ""


@dataclass
class StageMemoryRecord:
    identity: StageIdentity
    stage: Stage
    trigger: StageTrigger = field(default_factory=StageTrigger)
    transition: StageTransition = field(default_factory=StageTransition)
    action: StageAction = field(default_factory=StageAction)
    verification: StageVerification = field(default_factory=StageVerification)
    governance: StageGovernance = field(default_factory=StageGovernance)
    raw_evidence: StageRawEvidence = field(default_factory=StageRawEvidence)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stage"] = self.stage.value
        d["governance"]["state"] = self.governance.state.value
        return d

    @staticmethod
    def from_dict(d: dict) -> "StageMemoryRecord":
        gov = dict(d.get("governance", {}))
        gov["state"] = GovernanceState(gov.get("state", "candidate"))
        return StageMemoryRecord(
            identity=StageIdentity(**d["identity"]),
            stage=Stage(d["stage"]),
            trigger=StageTrigger(**d.get("trigger", {})),
            transition=StageTransition(**d.get("transition", {})),
            action=StageAction(**d.get("action", {})),
            verification=StageVerification(**d.get("verification", {})),
            governance=StageGovernance(**gov),
            raw_evidence=StageRawEvidence(**d.get("raw_evidence", {})),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )


def assert_no_target_leakage(obj) -> None:
    """Recursively reject any forbidden target-task key (by key name) anywhere in a record/view dict."""
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if str(k).lower() in FORBIDDEN_TARGET_KEYS:
                    raise ValueError("target-leakage sentinel: forbidden key %r" % k)
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
    walk(obj if isinstance(obj, (dict, list, tuple)) else {})


def record_hash(rec: StageMemoryRecord) -> str:
    """Deterministic content hash over the compiled record (governance volatile fields excluded)."""
    d = rec.to_dict()
    d["governance"] = {k: d["governance"][k] for k in ("confidence", "supersedes") if k in d["governance"]}
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()
