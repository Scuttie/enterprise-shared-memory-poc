"""REALBENCH-R3 §7 — the ONE authoritative canonical memory object per verified source.

Every execution view (renderer B0..B9) is deterministic from this exact object; we never store separately
written per-format memories. Target values/names/tests are ABSENT by construction; source-specific constants
are marked (`source_constants`) so a renderer can refuse to emit them as target facts. Source code is kept
separately as `evidence`, not inside the canonical fact fields.
"""
from __future__ import annotations
import dataclasses
import hashlib
import json
from typing import Any

SCHEMA_VERSION = "r3-canon-1"


@dataclasses.dataclass(frozen=True)
class CanonicalActionMemory:
    # provenance / identity
    source_task_id: str
    source_user_id: str
    source_solution_hash: str
    source_evaluator_hash: str
    # domain
    task_family: str
    language: str
    libraries: tuple[str, ...]
    required_imports: tuple[str, ...]
    relevant_apis: tuple[str, ...]
    # contracts
    input_contract: str
    output_contract: str
    preconditions: tuple[str, ...]
    postconditions: tuple[str, ...]
    invariants: tuple[str, ...]
    applicability: str
    non_applicability: str
    # procedure / structure
    ordered_operations: tuple[str, ...]
    control_flow_pattern: str
    data_transformation: str
    # pitfalls / patterns
    common_failure: str
    positive_pattern: str
    negative_pattern: str
    # code-edit representations (source-independent, placeholder-only)
    generalized_ast_edit: tuple[str, ...]
    generalized_diff_template: str
    # verification
    verification_procedure: tuple[str, ...]
    # governance / evidence
    validity: str
    provenance: dict[str, Any]
    evidence: dict[str, Any]          # raw source code kept here, NOT in the fact fields
    governance_state: str
    # marked source-specific constants/identifiers that must NEVER render as target facts
    source_constants: tuple[str, ...]
    schema_version: str = SCHEMA_VERSION

    def fact_fields(self) -> dict[str, Any]:
        """The renderable fact surface (everything EXCEPT raw evidence + governance internals)."""
        d = dataclasses.asdict(self)
        d.pop("evidence", None)
        return d

    def canonical_hash(self) -> str:
        """Deterministic content hash over the fact surface (evidence excluded)."""
        payload = json.dumps(self.fact_fields(), sort_keys=True, ensure_ascii=False, default=list)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def assert_no_target_leakage(self, target_solution: str = "", target_tests: str = "") -> None:
        """Invariant guard (§7/§26): no target value/name/test may appear in the fact surface."""
        surface = json.dumps(self.fact_fields(), ensure_ascii=False, default=list)
        for needle in (target_solution, target_tests):
            if needle and needle.strip() and needle.strip() in surface:
                raise ValueError("target leakage into canonical fact surface")


def load(d: dict[str, Any]) -> CanonicalActionMemory:
    fields = {f.name for f in dataclasses.fields(CanonicalActionMemory)}
    tuple_fields = {"libraries", "required_imports", "relevant_apis", "preconditions", "postconditions",
                    "invariants", "ordered_operations", "generalized_ast_edit", "verification_procedure",
                    "source_constants"}
    kw = {}
    for k in fields:
        if k not in d:
            continue
        kw[k] = tuple(d[k]) if k in tuple_fields and d[k] is not None else d[k]
    return CanonicalActionMemory(**kw)
