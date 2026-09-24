"""Import genuine historical DEV source knowledge for the SK hynix pilot.

This is a projection of the existing public merged-PR bank, not a source of
verified procedures. It rechecks chronology and ancestry from cached public
evidence, and uses the legacy reader's exact bounded source content in both
memory arms. No model, network, grader, or frozen artifact is modified here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import trimem_dev_activation_executor as legacy
import trimem_dev_activation_source_bank as historical
from enterprise_memory.trimem.skill_memory import SkillMemoryStore


class SourceBankImportError(ValueError):
    """A source projection failed to retain its genuine provenance or scope."""


@dataclass(frozen=True)
class ValidatedSourceBank:
    repository_root: Path
    contract: legacy.ExecutionContract
    targets_by_id: Mapping[str, Mapping[str, Any]]
    payloads_by_memory_id: Mapping[str, bytes]
    titles_by_memory_id: Mapping[str, str]
    report: Mapping[str, Any]


def load_validated_source_bank(repository_root: Path = ROOT) -> ValidatedSourceBank:
    """Rebuild the public source bank using hash-verified chronology evidence.

    All source facts must predate their target problem and the source fix must
    be an ancestor of its target base commit. The rebuilt manifest and payloads
    must equal the existing frozen bank. These checks do not treat a PR merge
    as a passing test run or as support for Gate B skill promotion.
    """
    root = Path(repository_root).resolve()
    plan, development, _grader, _specs = historical.load_committed_contracts(root)
    chronology_path = root / historical.CHRONOLOGY_PATH
    chronology = historical.strict_json_load(chronology_path)
    evidence = historical.evidence_blobs_from_cache(chronology_path, chronology)
    rebuilt, payloads = historical.build_oracle_source_bank(
        plan, development, chronology, evidence,
        chronology_raw_sha256=historical.file_sha256(chronology_path),
    )
    contract = legacy.load_execution_contract(root, require_tracked=False)
    manifest_path = root / contract.source_bank_manifest_path
    committed = historical.strict_json_load(manifest_path)
    if historical.canonical_bytes(rebuilt) != historical.canonical_bytes(committed):
        raise SourceBankImportError("rebuilt source bank differs from frozen public evidence")
    if rebuilt["covered_target_count"] != len(development["targets"]):
        raise SourceBankImportError("source chronology and ancestry do not cover every DEV target")
    raw_by_id: dict[str, bytes] = {}
    for record in rebuilt["records"]:
        raw = payloads[record["payload_path"]]
        path = manifest_path.parent / record["payload_path"]
        if path.read_bytes() != raw:
            raise SourceBankImportError("committed source payload differs from rebuilt evidence")
        raw_by_id[record["memory_id"]] = raw
    titles = {
        source["source_task_id"]: source["source_public_row"]["title"]
        for source in chronology["sources"]
    }
    report = {
        "schema": "skhynix/historical-source-bank-validation/1.0",
        "status": "PASS",
        "scientific_role": "EXPLORATORY_DEV_PILOT_WITH_EXISTING_POST_DEV_ORACLE_SOURCES",
        "source_bank_manifest_sha256": historical.file_sha256(manifest_path),
        "source_bank_snapshot_sha256": rebuilt["snapshot_sha256"],
        "chronology_cache_sha256": historical.file_sha256(chronology_path),
        "development_target_set_sha256": development["target_set_sha256"],
        "covered_target_count": rebuilt["covered_target_count"],
        "source_record_count": rebuilt["record_count"],
        "chronology_and_ancestor_checks": "REBUILT_AND_EQUAL_TO_FROZEN_BANK",
        "source_evidence_label": "HISTORICAL_MERGED_PR_KNOWLEDGE_NOT_TESTED_PROCEDURE",
        "source_ci_results_observed": False,
        "verified_skill_count": 0,
        "imported_episode_count": 0,
        "model_calls": 0,
        "official_grader_calls": 0,
        "network_calls": 0,
    }
    return ValidatedSourceBank(
        root, contract,
        {row["target_id"]: row for row in development["targets"]}, raw_by_id,
        {row["memory_id"]: titles[row["source_task_id"]] for row in rebuilt["records"]},
        report,
    )


def _validate_task(task: Any, bank: ValidatedSourceBank) -> Mapping[str, Any]:
    target = bank.targets_by_id.get(task.task_id)
    if target is None or (task.repository, task.commit) != (
        target["repository"], target["base_commit"],
    ):
        raise SourceBankImportError("task is outside the validated DEV repository/revision scope")
    assignment = bank.contract.assignments_by_target[task.task_id]
    actual_instruction = hashlib.sha256(task.instruction.encode("utf-8")).hexdigest()
    if actual_instruction != assignment["target_public_instruction_sha256"]:
        raise SourceBankImportError("task public instruction differs from the validated DEV projection")
    return target


def build_legacy_source_store(task: Any, *, bank: ValidatedSourceBank | None = None,
                              repository_root: Path = ROOT
                              ) -> legacy.ManifestBackedDiagnosticSourceBankStore:
    """Create the existing M2 source store without reusing an execution request.

    Only the read-only source projection is reused. New callers own their run
    contract, namespaces, model calls, outcomes, and execution authorization.
    """
    bank = bank or load_validated_source_bank(repository_root)
    _validate_task(task, bank)
    contract = bank.contract
    assignment = contract.assignments_by_target[task.task_id]
    ids = [str(row["memory_id"]) for row in assignment["candidates"]]
    # The legacy store expects this exact provenance hash; these are source
    # projection fields, with no old C1 execution identity or approval request.
    view_hash = legacy._canonical_hash({
        "source_bank_manifest_sha256": contract.source_bank_manifest_sha256,
        "source_bank_snapshot_sha256": contract.source_bank_snapshot_sha256,
        "target_id": task.task_id,
        "assignment": assignment,
        "records": [contract.records_by_memory_id[item] for item in ids],
    })
    projection = {
        "target_id": task.task_id,
        "experiment_id": task.org_id,
        "source_bank": {
            "read_only": True,
            "mutation_allowed": False,
            "manifest_raw_sha256": contract.source_bank_manifest_sha256,
            "snapshot_sha256": contract.source_bank_snapshot_sha256,
            "candidate_memory_ids": ids,
            "target_view_sha256": view_hash,
        },
    }
    return legacy.ManifestBackedDiagnosticSourceBankStore(
        contract=contract, request=projection, task=task,
        repository_root=bank.repository_root,
        payload_bytes=bank.payloads_by_memory_id,
    )


def build_seeded_store(output_path: str | Path, task: Any, *,
                       bank: ValidatedSourceBank | None = None,
                       repository_root: Path = ROOT
                       ) -> tuple[SkillMemoryStore, dict[str, Any]]:
    """Create a fresh SQLite store containing the same source content as M2.

    Target-bound revision means the *historical fact's applicability* was
    checked by ancestry; it does not assert that source code is unchanged.
    The existing execution view explicitly requires current-checkout checks.
    Its exact bytes become RepositoryKnowledge.content; the skill controller's
    normal outer JSON envelope is additional and must be accounted separately.
    """
    bank = bank or load_validated_source_bank(repository_root)
    target = _validate_task(task, bank)
    legacy_store = build_legacy_source_store(task, bank=bank)
    path = Path(output_path)
    if str(output_path) != ":memory:" and path.exists():
        raise FileExistsError("refusing to overwrite an existing SK hynix source store")
    store = SkillMemoryStore(output_path)
    entries = []
    try:
        for memory_id, raw in sorted(legacy_store.execution_views.items()):
            record = bank.contract.records_by_memory_id[memory_id]
            knowledge = store.put_repository_knowledge(
                org_id=task.org_id, repository=task.repository,
                title=bank.titles_by_memory_id[memory_id],
                content=raw.decode("utf-8"), revision=task.commit,
                language=target["language"],
            )
            if knowledge.content.encode("utf-8") != raw:
                raise SourceBankImportError("SK hynix content differs from existing M2 source view")
            entries.append({
                "memory_id": memory_id, "knowledge_id": knowledge.knowledge_id,
                "source_task_id": record["source_task_id"],
                "source_commit": record["source_commit"],
                "applicable_target_revision": task.commit,
                "chronology_and_version_evidence_sha256": record["chronology_and_version_evidence_sha256"],
                "shared_source_content_sha256": hashlib.sha256(raw).hexdigest(),
                "shared_source_content_bytes": len(raw),
                "knowledge_content_hash": knowledge.content_hash,
            })
        snapshot = store.snapshot(
            org_id=task.org_id, user_id=task.user_id, repository=task.repository,
            revision=task.commit, language=target["language"],
        )
        report = {
            "schema": "skhynix/historical-source-seed/1.0",
            "target_id": task.task_id,
            "language": target["language"],
            "source_evidence_label": bank.report["source_evidence_label"],
            "source_bank_snapshot_sha256": bank.report["source_bank_snapshot_sha256"],
            "seed_snapshot_sha256": snapshot.content_hash,
            "repository_knowledge_count": len(snapshot.repository_knowledge),
            "knowledge_relation_count": len(snapshot.knowledge_edges),
            "verified_skill_count": len(snapshot.skills),
            "imported_episode_count": len(snapshot.episodes),
            "source_content_identical_to_existing_m2": True,
            "wire_envelope": "STANDARD_SKHYNIX_REPOSITORY_SEMANTIC_JSON",
            "l3_effect_claim_allowed": False,
            "entries": entries,
        }
        return store, report
    except BaseException:
        store.close()
        raise
