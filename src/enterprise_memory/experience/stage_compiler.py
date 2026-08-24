"""R22 §5,§9 — deterministic StageMemoryRecord compiler (no model calls).

Mechanical fields (repo/commit/paths/symbols/apis/test commands/grader result/timestamps) are filled from
SourceEvidence. Semantic fields (root cause / contract / operation) are left to a schema-constrained extractor
(stage_extractor, paid) and are recorded as UNKNOWN here when not deterministically derivable — never guessed.
Every record is hashed; the same source always compiles to the same content hash.
"""
from __future__ import annotations

import hashlib
from typing import List, Optional

from .schema import GovernanceState
from .stage_schema import (
    Stage, StageMemoryRecord, StageIdentity, StageTrigger, StageTransition, StageAction,
    StageVerification, StageGovernance, StageRawEvidence, record_hash, assert_no_target_leakage,
)

UNKNOWN = "UNKNOWN"


def _mem_id(source_task_id: str, stage: Stage) -> str:
    return "stg_" + hashlib.sha256(("%s|%s" % (source_task_id, stage.value)).encode()).hexdigest()[:20]


def compile_stage_record(
    *, source_task_id: str, source_repository: str, source_commit: str, source_user_id: str,
    source_timestamp: str, source_outcome: str, verifier_hash: str, stage: Stage,
    trigger: Optional[StageTrigger] = None, transition: Optional[StageTransition] = None,
    action: Optional[StageAction] = None, verification: Optional[StageVerification] = None,
    trajectory_artifact_id: str = "", patch_artifact_id: str = "", test_artifact_id: str = "",
    confidence: float = 0.0, provenance_hashes: Optional[List[str]] = None,
) -> StageMemoryRecord:
    identity = StageIdentity(
        memory_id=_mem_id(source_task_id, stage), source_task_id=source_task_id,
        source_repository=source_repository, source_commit=source_commit, source_user_id=source_user_id,
        source_timestamp=source_timestamp, source_outcome=source_outcome, verifier_hash=verifier_hash,
    )
    rec = StageMemoryRecord(
        identity=identity, stage=stage,
        trigger=trigger or StageTrigger(), transition=transition or StageTransition(),
        action=action or StageAction(), verification=verification or StageVerification(),
        raw_evidence=StageRawEvidence(trajectory_artifact_id=trajectory_artifact_id,
                                      patch_artifact_id=patch_artifact_id, test_artifact_id=test_artifact_id),
        governance=StageGovernance(confidence=confidence, state=GovernanceState.CANDIDATE,
                                   provenance_hashes=list(provenance_hashes or [])),
    )
    # a record with no meaningful core signal is refused (empty core field rejection, §9)
    core = (rec.trigger.error_signature or rec.trigger.failing_test_signature
            or rec.trigger.affected_symbols or rec.trigger.affected_paths)
    if not core:
        raise ValueError("empty core trigger — refuse to compile a signal-less stage record")
    assert_no_target_leakage(rec.to_dict())
    ch = record_hash(rec)
    rec.governance.provenance_hashes = sorted(set(rec.governance.provenance_hashes + [ch]))
    return rec


def coverage_report(records: List[StageMemoryRecord]) -> dict:
    by_stage = {s.value: 0 for s in Stage}
    missing_core = 0
    for r in records:
        by_stage[r.stage.value] += 1
        if not (r.action.operation_type and r.action.operation_type != UNKNOWN):
            missing_core += 1
    return {
        "records": len(records),
        "by_stage": by_stage,
        "missing_operation_type": missing_core,
        "missing_operation_fraction": round(missing_core / max(1, len(records)), 4),
    }
