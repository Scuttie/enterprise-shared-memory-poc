"""Frozen public workflow projection from an actual Gate B promotion.

Private authority and attestations are hash-checked, never decoded or copied.
An exact public runtime certificate permits only the portable RED/GREEN test
workflow at an evaluation base. Source episodes and skill ownership stay intact;
the projection does not establish correctness of any target repair.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from enterprise_memory.trimem.retrieval import MemoryKind, MemoryRecord
from enterprise_memory.trimem.skill_memory import MemorySnapshot, ProcedureTemplate, Skill, canonical_hash
import trimem_skhynix_codex_learning as learning

SCHEMA = "skhynix/native-learned-bank/2.0"
PROJECTION_SCHEMA = "skhynix/frozen-public-workflow-projection/1.0"
PUBLIC_PYTHON = "/opt/miniconda3/envs/testbed/bin/python"
SMOKE_ARGV = [PUBLIC_PYTHON, "bin/test", "sympy/core/tests/test_basic.py", "--no-colors", "--no-subprocess"]
NAMED_SMOKE_TEST = "test_structure"
NAMED_SMOKE_ARGV = [*SMOKE_ARGV, "-k", NAMED_SMOKE_TEST]
NAMED_COMPATIBILITY_SCHEMA = "skhynix/public-workflow-compatibility/2.0"
NAMED_COMPATIBILITY_EVIDENCE_SCHEMA = "skhynix/public-workflow-compatibility-evidence/2.0"
MULTI_SOURCE_COMPATIBILITY_SCHEMA = "skhynix/public-workflow-compatibility/3.0"
MULTI_SOURCE_COMPATIBILITY_EVIDENCE_SCHEMA = "skhynix/public-workflow-compatibility-evidence/3.0"
POLICY = {
    "scope": "PORTABLE_PUBLIC_RED_GREEN_VERIFICATION_WORKFLOW_ONLY",
    "target_runtime_prerequisites_verified": True,
    "target_fix_correctness_verified": False,
    "source_episode_revisions_rebound": False,
    "source_skill_owner_rebound": False,
    "private_episode_copy_count": 0,
    "authority_revocation_policy": "FAIL_CLOSED_ON_ANY_FROZEN_AUTHORITY_BYTE_CHANGE",
    "limitation": "Public runner and Python compatibility does not verify a target repair or implementation assumptions.",
}


class SkillBankError(learning.LearnedBankError):
    pass


def _ref(path: Path) -> dict:
    path = Path(path).absolute()
    value = {"path": str(path), "sha256": learning.file_sha(path)}
    _checked_ref(value)
    return value


def _checked_ref(value: Any, *, authority: bool = False) -> Path:
    if (not isinstance(value, dict) or not isinstance(value.get("path"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", value.get("sha256", ""))):
        raise SkillBankError("invalid frozen evidence reference")
    path = Path(value["path"])
    if (not path.is_absolute() or not path.is_file()
            or any(part.is_symlink() for part in (path, *path.parents))):
        raise SkillBankError("frozen evidence is absent, relative or linked")
    if authority and any(Path(str(path) + suffix).exists()
                         and Path(str(path) + suffix).stat().st_size > 0 for suffix in ("-wal", "-journal")):
        raise SkillBankError("frozen authority has an active journal or changed state")
    if learning.file_sha(path) != value["sha256"]:
        raise SkillBankError("frozen evidence reference hash differs")
    return path


def _verify_authority(export: dict, skill: Skill, base: dict) -> None:
    """Read a shared skill and support metadata only, without opening private payloads."""
    reference = export["authority_db"]
    path = _checked_ref(reference, authority=True)
    connection = None
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise SkillBankError("promoted authority schema differs")
        row = connection.execute(
            "SELECT record_id,kind,org_id,owner_user_id,repository,revision,payload,content_hash,revoked "
            "FROM memory_records WHERE record_id=? AND kind='skill'", (skill.skill_id,),
        ).fetchone()
        expected = asdict(skill)
        expected.pop("content_hash")
        if (row is None or row["kind"] != "skill" or row["org_id"] != skill.org_id
                or row["owner_user_id"] is not None or row["repository"] is not None
                or row["revision"] is not None or row["revoked"] != 0
                or row["content_hash"] != skill.content_hash
                or learning.canonical(json.loads(row["payload"])) != learning.canonical(expected)
                or canonical_hash(json.loads(row["payload"])) != skill.content_hash):
            raise SkillBankError("exported skill does not match the current shared authority row")
        # json_extract returns only a declared task identity scalar. Private
        # episode payloads, action text and verifier bodies never leave SQLite.
        supports = connection.execute(
            "SELECT s.episode_id,e.record_id,e.kind,e.org_id,e.owner_user_id,e.repository,e.revision,"
            "e.content_hash,e.revoked,json_extract(e.payload,'$.evidence.task_id') AS task_id "
            "FROM skill_support s LEFT JOIN memory_records e ON e.record_id=s.episode_id "
            "WHERE s.skill_id=? ORDER BY s.episode_id", (skill.skill_id,),
        ).fetchall()
        provenance = {record["source"]["task_id"]: record["source"] for record in base["records"]}
        if (len(supports) != skill.support_count or len(supports) < 2
                or any(row["record_id"] != row["episode_id"] or row["kind"] != "episode"
                       or row["org_id"] != skill.org_id or row["revoked"] != 0
                       or not isinstance(row["owner_user_id"], str) or not row["owner_user_id"]
                       or not isinstance(row["content_hash"], str)
                       or not re.fullmatch(r"sha256:[0-9a-f]{64}", row["content_hash"])
                       or row["task_id"] not in provenance
                       or provenance[row["task_id"]]["repository"] != row["repository"]
                       or provenance[row["task_id"]]["revision"] != row["revision"]
                       or provenance[row["task_id"]]["contributor_id"] != row["owner_user_id"]
                       for row in supports)
                or len({row["owner_user_id"] for row in supports}) != skill.contributor_count
                or sorted(row["task_id"] for row in supports) != export["training_task_ids"]
                or canonical_hash([row["content_hash"] for row in supports]) != skill.evidence_set_hash):
            raise SkillBankError("promoted authority support metadata or evidence aggregate differs")
    except (sqlite3.Error, TypeError, ValueError) as exc:
        if isinstance(exc, SkillBankError):
            raise
        raise SkillBankError("promoted authority cannot verify the exported public skill") from exc
    finally:
        if connection is not None:
            connection.close()
        _checked_ref(reference, authority=True)


def _promotion(reference: dict, base: dict) -> tuple[dict, Skill]:
    from trimem_skhynix_codex_procedures import procedure_profile, load_declaration
    export = learning.read(_checked_ref(reference))
    try:
        profile = procedure_profile(export.get("procedure_id"))
        fields = dict(export["promoted_skill"])
        fields["template"] = ProcedureTemplate(**fields["template"])
        skill = Skill(**fields)
        payload = asdict(skill)
        payload.pop("content_hash")
        training = export["training_task_ids"]
        runners = export["training_runner_sha256"]
        view = skill.execution_view()
        valid = (export.get("schema") == profile["export_schema"]
            and export.get("status") == "ACTUALLY_PROMOTED_BY_GATE_B"
            and skill.template == profile["template"]
            and export.get("verified_skill_count") == 1
            and type(skill.support_count) is int and skill.support_count >= 2
            and type(skill.contributor_count) is int and 2 <= skill.contributor_count <= skill.support_count
            and export.get("contributor_count") == skill.contributor_count
            and training == sorted(set(training)) and len(training) == skill.support_count
            and set(training) <= set(base["training_task_ids"])
            and not set(training) & set(base["evaluation_task_ids"])
            and export.get("authority_org_id") == skill.org_id
            and canonical_hash(payload) == skill.content_hash
            and re.fullmatch(r"sha256:[0-9a-f]{64}", skill.evidence_set_hash)
            and export.get("public_execution_view") == view
            and export.get("public_execution_view_sha256") == learning.sha(view.encode())
            and export.get("public_execution_view_bytes") == len(view.encode())
            and 0 < len(view.encode()) <= 12_000
            and len(runners) == 1 and re.fullmatch(r"[0-9a-f]{64}", runners[0])
            and export.get("target_fix_validated") is False
            and export.get("source_revisions_rebound") is False
            and export.get("same_public_payload_required_for_memory_arms") is True
            and export.get("model_api_calls") == 0)
    except (KeyError, TypeError, ValueError) as exc:
        raise SkillBankError("invalid promoted public skill") from exc
    if not valid:
        raise SkillBankError("promoted public skill hash, scope or verification differs")
    _verify_authority(export, skill, base)
    declaration_path = _checked_ref(export["declaration"])
    declaration = load_declaration(declaration_path, export["declaration"]["sha256"])
    if (export.get("declaration_sha256") != export["declaration"]["sha256"]
            or declaration["procedure_id"] != export["procedure_id"]
            or declaration["authority_org_id"] != skill.org_id
            or declaration["training_task_ids"] != training):
        raise SkillBankError("promoted declaration provenance differs")
    attestations = export.get("attestations", [])
    if len(attestations) != skill.support_count or len({row.get("path") for row in attestations}) != len(attestations):
        raise SkillBankError("promoted private attestation reference count differs")
    for reference in attestations:
        _checked_ref(reference)
        if not re.fullmatch(r"[0-9a-f]{64}", reference.get("attestation_sha256", "")):
            raise SkillBankError("private attestation canonical digest differs")
    return export, skill


def _compatibility(references: list[dict], targets: list[dict], export: dict) -> dict[str, dict]:
    from trimem_skhynix_codex_procedures import (
        MULTI_SOURCE_PROCEDURE_ID, NAMED_PROCEDURE_ID, named_runner_outcome,
    )
    expected = {row["task_id"]: row for row in targets}
    observed = {}
    if len(references) != len(expected):
        raise SkillBankError("public compatibility target count differs")
    for reference in references:
        receipt = learning.read(_checked_ref(reference))
        target = receipt.get("target", {})
        task_id = target.get("task_id")
        public = receipt.get("public_test", {})
        image_name = "swebench/sweb.eval.x86_64." + str(task_id).rsplit("--", 1)[-1].replace("__", "_1776_")
        if (task_id not in expected or task_id in observed or target != expected[task_id]
                or target.get("language") != "python"
                or receipt.get("runner_sha256") not in export["training_runner_sha256"]
                or receipt.get("python_executable") != PUBLIC_PYTHON
                or receipt.get("python_version") != "3.9.20"
                or receipt.get("clean_checkout_before_after") is not True
                or type(receipt.get("solver_actions_used")) is not int or receipt["solver_actions_used"] != 0
                or public.get("argv") != SMOKE_ARGV
                or type(public.get("exit_code")) is not int or public["exit_code"] != 0
                or type(public.get("passed_count")) is not int or public["passed_count"] <= 0
                or not re.fullmatch(re.escape(image_name) + r"@sha256:[0-9a-f]{64}",
                                    receipt.get("source_image", ""))):
            raise SkillBankError("public workflow compatibility scope, runner or result differs")
        evidence = learning.read(_checked_ref(receipt.get("evidence_ref")))
        result = evidence.get("result", evidence)
        output = str(result.get("stdout", "")) + "\n" + str(result.get("stderr", ""))
        counts = [int(value) for value in re.findall(r"\b(\d+) passed\b", output)]
        version = evidence.get("python_version_result", {})
        if (evidence.get("target") != target or evidence.get("argv") != SMOKE_ARGV
                or any(evidence.get(key) != receipt[key] for key in (
                    "runner_sha256", "python_executable", "python_version", "source_image",
                    "clean_checkout_before_after", "solver_actions_used"))
                or evidence.get("python_version_argv") != [PUBLIC_PYTHON, "-c", "import platform; print(platform.python_version())"]
                or type(version.get("exit_code")) is not int or version["exit_code"] != 0
                or str(version.get("stdout", "")).strip() != "3.9.20"
                or version.get("timed_out") is True or version.get("output_truncated") is True
                or type(result.get("exit_code")) is not int or result["exit_code"] != 0
                or result.get("timed_out") is True or result.get("output_truncated") is True
                or not counts or counts[-1] != public["passed_count"]
                or any(int(value) > 0 for value in re.findall(r"\b(\d+) failed\b", output))
                or public.get("observation_sha256") != learning.sha(learning.canonical(result))):
            raise SkillBankError("public compatibility claim differs from its hashed observation")
        if export["procedure_id"] in (NAMED_PROCEDURE_ID, MULTI_SOURCE_PROCEDURE_ID):
            multi_source = export["procedure_id"] == MULTI_SOURCE_PROCEDURE_ID
            certificate_schema = MULTI_SOURCE_COMPATIBILITY_SCHEMA if multi_source else NAMED_COMPATIBILITY_SCHEMA
            evidence_schema = (MULTI_SOURCE_COMPATIBILITY_EVIDENCE_SCHEMA if multi_source
                               else NAMED_COMPATIBILITY_EVIDENCE_SCHEMA)
            named = receipt.get("named_public_test", {})
            named_evidence = evidence.get("named_public_test", {})
            named_result = named_evidence.get("result", {})
            if (receipt.get("schema") != certificate_schema or evidence.get("schema") != evidence_schema or
                    (multi_source and (receipt.get("procedure_id") != MULTI_SOURCE_PROCEDURE_ID or
                                       evidence.get("procedure_id") != MULTI_SOURCE_PROCEDURE_ID)) or
                    named.get("test_name") != NAMED_SMOKE_TEST or named.get("argv") != NAMED_SMOKE_ARGV or
                    type(named.get("exit_code")) is not int or named["exit_code"] != 0 or
                    type(named.get("passed_count")) is not int or named["passed_count"] != 1 or
                    named_evidence.get("test_name") != NAMED_SMOKE_TEST or
                    named_evidence.get("argv") != NAMED_SMOKE_ARGV or
                    named.get("observation_sha256") != learning.sha(learning.canonical(named_result)) or
                    not named_runner_outcome(named_result, NAMED_SMOKE_ARGV)):
                raise SkillBankError("named public compatibility differs from its one-test observation")
        observed[task_id] = receipt
    return observed


def _compose(base: dict, base_ref: dict, export_ref: dict, compatibility_refs: list[dict]) -> dict:
    manifest = copy.deepcopy(base)
    manifest.update(schema=SCHEMA, base_observation_bank=base_ref, promoted_export=export_ref,
        compatibility_receipts=compatibility_refs, skill_projection=copy.deepcopy(POLICY),
        gate_b={"status": "ACTUALLY_PROMOTED_BY_GATE_B", "verified_skill_count": 1,
                "support_scope": "ONLY_PREDECLARED_NEW_TRAINING_SESSIONS"})
    return manifest


def _validate_manifest(manifest: dict) -> tuple[dict, dict, Skill, dict[str, dict]]:
    base = learning.read(_checked_ref(manifest["base_observation_bank"]))
    targets = learning._validate_observation_manifest(base)
    export, skill = _promotion(manifest["promoted_export"], base)
    receipts = _compatibility(manifest["compatibility_receipts"], targets, export)
    if manifest != _compose(base, manifest["base_observation_bank"], manifest["promoted_export"],
                            manifest["compatibility_receipts"]):
        raise SkillBankError("schema2 bank changed observations, split or projection policy")
    return base, export, skill, receipts


def freeze_skill_bank(base_observation_bank: Path, promoted_export: Path,
                      compatibility_paths: list[Path], output: Path) -> dict:
    output = Path(output).absolute()
    if output.exists():
        raise SkillBankError("refusing to overwrite a frozen skill bank")
    base_ref, export_ref = _ref(base_observation_bank), _ref(promoted_export)
    base = learning.read(Path(base_ref["path"]))
    references = sorted((_ref(path) for path in compatibility_paths), key=lambda row: row["path"])
    manifest = _compose(base, base_ref, export_ref, references)
    _validate_manifest(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(learning.canonical(manifest) + b"\n")
    return {"path": str(output), "sha256": learning.file_sha(output),
            "verified_skills": 1, "training_tasks": len(base["training_task_ids"]),
            "shared_records": len(base["records"]), "evaluation_tasks": len(base["evaluation_targets"])}


def load_skill_bank(path: Path, expected_sha256: str, task: Any) -> learning.FrozenLearnedBank:
    manifest = learning.read(_checked_ref({"path": str(Path(path).absolute()), "sha256": expected_sha256}))
    base, _export, _skill, _receipts = _validate_manifest(manifest)
    reference = manifest["base_observation_bank"]
    bank = learning.load_frozen_bank(Path(reference["path"]), reference["sha256"], task)
    return learning.FrozenLearnedBank(Path(path).absolute(), expected_sha256, manifest, bank.target)


def skill_for_bank(bank: learning.FrozenLearnedBank) -> Skill:
    actual = learning.read(_checked_ref({"path": str(bank.path), "sha256": bank.sha256}))
    if actual != bank.manifest:
        raise SkillBankError("retained skill bank manifest differs")
    _base, _export, skill, receipts = _validate_manifest(actual)
    if receipts.get(bank.target["task_id"], {}).get("target") != bank.target:
        raise SkillBankError("target has no exact public workflow compatibility")
    return skill


def runtime_certificate_for_bank(bank: learning.FrozenLearnedBank) -> dict:
    """Return the checked exact-target public runtime certificate for broker binding."""
    actual = learning.read(_checked_ref({"path": str(bank.path), "sha256": bank.sha256}))
    if actual != bank.manifest:
        raise SkillBankError("retained skill bank manifest differs")
    _base, _export, _skill, receipts = _validate_manifest(actual)
    receipt = receipts.get(bank.target["task_id"])
    if receipt is None or receipt.get("target") != bank.target:
        raise SkillBankError("target has no exact public workflow compatibility")
    return copy.deepcopy(receipt)


def skill_bank_report(bank: learning.FrozenLearnedBank) -> dict:
    skill = skill_for_bank(bank)
    return {"schema": SCHEMA, "source_evidence_label": "ACTUAL_NATIVE_TRAINING_AND_PROMOTED_PUBLIC_WORKFLOW",
        "frozen_bank_sha256": bank.sha256, "records": len(bank.records),
        "training_gate_a_episode_count": bank.manifest["gate_a"]["episode_count"],
        "training_task_ids": bank.manifest["training_task_ids"], "verified_skill_count": 1,
        "verified_skill_payload_count": 1, "source_skill_content_hash": skill.content_hash,
        "source_skill_org_id": skill.org_id, "imported_episode_count": 0,
        "target_version_applicability_verified": False, "application_policy": learning.APPLICATION,
        "same_shared_payload_between_memory_arms": True, "online_learning": False,
        "workflow_projection": copy.deepcopy(POLICY)}


def semantic_skill_record(task: Any, bank: learning.FrozenLearnedBank, skill: Skill, graph_hash: str) -> MemoryRecord:
    export = learning.read(_checked_ref(bank.manifest["promoted_export"]))
    sources = [row["source"] for row in bank.records if row["source"]["task_id"] in export["training_task_ids"]]
    if {row["task_id"] for row in sources} != set(export["training_task_ids"]):
        raise SkillBankError("promoted workflow lacks its original shared training provenance")
    sources.sort(key=lambda row: row["task_id"])
    source, view = sources[0], skill.execution_view()
    metadata = {"source_task_id": source["task_id"], "source_task_ids": export["training_task_ids"],
        "source_dataset_id": "native-codex-training", "source_repository": source["repository"],
        "source_commit": source["revision"], "source_commits": [row["revision"] for row in sources],
        "source_timestamp": skill.promoted_at, "bank_type": "ORG_SEMANTIC",
        "verification_evidence_sha256": bank.manifest["promoted_export"]["sha256"],
        "provenance_sha256": learning.sha(learning.canonical(sources)),
        "payload_sha256": learning.sha(view.encode()), "permission_scope": "PUBLIC_READ",
        "tenant_scope": "BENCHMARK_ISOLATED", "version_scope": "EXACT_SOURCE_COMMIT", "path_scope": "**",
        "quarantined": False, "target_derived": False, "namespace": task.org_id,
        "graph_id": graph_hash, "canonical_node_hash": skill.content_hash,
        "source_skill_org_id": skill.org_id, "source_skill_content_hash": skill.content_hash,
        "workflow_projection": copy.deepcopy(POLICY)}
    return MemoryRecord(skill.skill_id, MemoryKind.ORG_SEMANTIC, view, view, task.org_id,
        repository=task.repository, version=source["revision"],
        coverage=("operation", "precondition", "verification"), metadata=metadata)


class FrozenSkillProjectionStore:
    """Read-only exact-target overlay; the underlying authority rules stay intact."""
    def __init__(self, base_store, task, bank: learning.FrozenLearnedBank):
        self.base_store, self.bank = base_store, bank
        self.scope = {"org_id": task.org_id, "user_id": task.user_id, "repository": task.repository,
                      "revision": task.commit, "language": bank.target["language"]}
        if learning._task_descriptor(task.public_payload()) != bank.target:
            raise SkillBankError("workflow projection task identity differs")
        skill_for_bank(bank)

    def snapshot(self, *, org_id, user_id, repository, revision="", language="") -> MemorySnapshot:
        scope = dict(org_id=org_id, user_id=user_id, repository=repository, revision=revision, language=language)
        if scope != self.scope:
            raise SkillBankError("workflow projection query scope differs")
        skill = skill_for_bank(self.bank)
        base = self.base_store.snapshot(**scope)
        if any(row.skill_id == skill.skill_id for row in base.skills):
            raise SkillBankError("projected skill already exists in the cell authority")
        skills = tuple(sorted((*base.skills, skill), key=lambda row: row.skill_id))
        digest = canonical_hash({"schema": PROJECTION_SCHEMA, "scope": scope,
            "base_snapshot_sha256": base.content_hash, "frozen_bank_sha256": self.bank.sha256,
            "skills": [row.content_hash for row in skills], "policy": POLICY})
        return MemorySnapshot(skills, base.repository_knowledge, base.episodes, digest, base.knowledge_edges)

    def close(self):
        self.base_store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-observation-bank", required=True, type=Path)
    parser.add_argument("--promoted-export", required=True, type=Path)
    parser.add_argument("--compatibility", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(freeze_skill_bank(args.base_observation_bank, args.promoted_export,
                                       args.compatibility, args.output)))


if __name__ == "__main__":
    main()
