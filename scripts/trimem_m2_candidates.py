"""Freeze and verify the preregistered four-bundle M2 development search.

Selection uses only the committed development stream outcomes after every
candidate has completed the same 12 targets.  Policy parameters and prompt
suffixes are generated before execution and cannot be edited by this selector.
The post-development command writes a *proposal* outside the tracked config;
held-out execution remains closed until an operator commits a hash-linked
``selected_m2.json`` and a new freeze is approved separately.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from enterprise_memory.trimem.runtime_lock import DECOMPOSITION_PROMPT, RuntimeLock  # noqa: E402
from enterprise_memory.trimem.production_lifecycle import _parse_policy_manifest  # noqa: E402
from enterprise_memory.trimem.retrieval import RetrievalConfig  # noqa: E402


BASE_POLICY = ROOT / "configs/trimem_v1/m2_policy.json"
CANDIDATE_DIR = ROOT / "configs/trimem_v1/m2_candidates"
BUNDLE_PATH = ROOT / "configs/trimem_v1/m2_candidate_bundles.json"
SELECTED_PATH = ROOT / "configs/trimem_v1/selected_m2.json"
CANDIDATE_IDS = ("baseline", "precision", "recall", "balanced")
SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")


class CandidateContractError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_value(value: Any) -> str:
    return "sha256:" + digest_bytes(canonical_bytes(value))


def read_json(path: Path) -> dict[str, Any]:
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=strict_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateContractError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CandidateContractError(f"JSON root is not an object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


PROMPT_SUFFIXES = {
    "baseline": "",
    "precision": (
        "\nPrefer the smallest evidence-supported "
        "DAG. Add a subtask only when a concrete repository observation proves a distinct "
        "operation, precondition, invariant, or dependency.\n"
    ),
    "recall": (
        "\nEnumerate every evidence-supported semantic "
        "operation, precondition, invariant, and dependency needed for the public task; retain "
        "distinct nodes when their verification evidence differs.\n"
    ),
    "balanced": (
        "\nBuild a compact dependency-complete semantic "
        "DAG, merging equivalent work while preserving separately verifiable operations and "
        "explicit prerequisite edges.\n"
    ),
}


def _set(document: dict[str, Any], dotted: str, value: Any) -> None:
    node: dict[str, Any] = document
    parts = dotted.split(".")
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            raise CandidateContractError(f"base policy lacks {dotted}")
        node = child
    node[parts[-1]] = value


CANDIDATE_PATCHES: Mapping[str, Mapping[str, Any]] = {
    "baseline": {},
    "precision": {
        "retrieval.context_budget_bytes": 8000,
        "retrieval.embedding_weight": 0.75,
        "retrieval.lexical_weight": 0.25,
        "retrieval.episode_complete_threshold": 0.9,
        "retrieval.max_task_injections": 2,
        "retrieval.min_confidence": 0.45,
        "retrieval.min_margin": 0.08,
        "double_dqn.gamma": 0.98,
        "double_dqn.learning_rate": 0.0015,
        "double_dqn.target_sync_interval": 8,
        "double_dqn.epsilon_start": 0.2,
        "double_dqn.epsilon_end": 0.03,
        "reward.failure_outcome": -1.2,
        "reward.negative_transfer": -0.75,
        "reward.context_cost_coefficient": -0.08,
        "reward.token_cost_coefficient": -0.08,
        "reward.stale_conflict_coefficient": -0.75,
        "reward.subtask_completion_coefficient": 0.25,
        "consolidation.capacities.episodic_per_user": 75,
        "consolidation.capacities.user_semantic_per_user": 75,
        "consolidation.capacities.organisation_semantic": 750,
        "graph_topology.edge_weights.APPLIED": 1.6,
        "graph_topology.edge_weights.DEPENDS_ON": 1.5,
        "graph_topology.edge_weights.OBSERVED": 0.9,
        "graph_topology.edge_weights.TOUCHES": 0.85,
        "graph_topology.edge_weights.VERIFIED_BY": 1.6,
    },
    "recall": {
        "retrieval.embedding_weight": 0.55,
        "retrieval.lexical_weight": 0.45,
        "retrieval.episode_complete_threshold": 0.65,
        "retrieval.min_confidence": 0.1,
        "retrieval.min_margin": 0.0,
        "retrieval.ppr_damping": 0.9,
        "retrieval.ppr_iterations": 40,
        "double_dqn.gamma": 0.995,
        "double_dqn.learning_rate": 0.0025,
        "double_dqn.target_sync_interval": 12,
        "double_dqn.epsilon_start": 0.35,
        "double_dqn.epsilon_end": 0.08,
        "reward.failure_outcome": -0.9,
        "reward.negative_transfer": -0.4,
        "reward.context_cost_coefficient": -0.03,
        "reward.token_cost_coefficient": -0.03,
        "reward.storage_cost_coefficient": -0.01,
        "reward.subtask_completion_coefficient": 0.3,
        "consolidation.capacities.episodic_per_user": 125,
        "consolidation.capacities.user_semantic_per_user": 150,
        "consolidation.capacities.organisation_semantic": 1250,
        "graph_topology.edge_weights.OBSERVED": 1.25,
        "graph_topology.edge_weights.TOUCHES": 1.25,
        "graph_topology.edge_weights.CALLS": 1.2,
        "graph_topology.edge_weights.PRODUCED": 1.4,
    },
    "balanced": {
        "retrieval.context_budget_bytes": 10000,
        "retrieval.embedding_weight": 0.68,
        "retrieval.lexical_weight": 0.32,
        "retrieval.episode_complete_threshold": 0.78,
        "retrieval.min_confidence": 0.28,
        "retrieval.min_margin": 0.03,
        "retrieval.ppr_damping": 0.87,
        "retrieval.ppr_iterations": 36,
        "double_dqn.hidden_dim": 80,
        "double_dqn.replay_capacity": 2304,
        "double_dqn.learning_rate": 0.0018,
        "double_dqn.target_sync_interval": 9,
        "reward.failure_outcome": -1.05,
        "reward.negative_transfer": -0.6,
        "reward.context_cost_coefficient": -0.06,
        "reward.latency_cost_coefficient": -0.025,
        "reward.subtask_completion_coefficient": 0.25,
        "consolidation.capacities.user_semantic_per_user": 125,
        "graph_topology.edge_weights.DECOMPOSES_TO": 1.6,
        "graph_topology.edge_weights.DEPENDS_ON": 1.35,
        "graph_topology.edge_weights.VERIFIED_BY": 1.45,
    },
}


def candidate_documents(base: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if base.get("schema") != "trimem/m2-policy/1.0":
        raise CandidateContractError("base M2 policy schema mismatch")
    documents: dict[str, dict[str, Any]] = {}
    for candidate_id in CANDIDATE_IDS:
        document = deepcopy(dict(base))
        for field, value in CANDIDATE_PATCHES[candidate_id].items():
            _set(document, field, value)
        documents[candidate_id] = document
    if len({digest_value(document) for document in documents.values()}) != len(CANDIDATE_IDS):
        raise CandidateContractError("candidate full policies are not distinct")
    return documents


def runtime_lock_for(candidate_id: str) -> RuntimeLock:
    try:
        suffix = PROMPT_SUFFIXES[candidate_id]
    except KeyError as exc:
        raise CandidateContractError(f"unknown M2 candidate: {candidate_id}") from exc
    return RuntimeLock(decomposer_prompt=DECOMPOSITION_PROMPT + suffix)


def build_bundle(base: Mapping[str, Any], documents: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    rows = []
    for order_index, candidate_id in enumerate(CANDIDATE_IDS):
        path = CANDIDATE_DIR / f"{candidate_id}.json"
        lock = runtime_lock_for(candidate_id)
        rows.append({
            "candidate_id": candidate_id,
            "order_index": order_index,
            "full_policy_path": path.relative_to(ROOT).as_posix(),
            "full_policy_file_sha256": digest_bytes(
                (json.dumps(documents[candidate_id], ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
            ),
            "full_policy_manifest_sha256": digest_value(documents[candidate_id]),
            "decomposition_prompt_suffix": PROMPT_SUFFIXES[candidate_id],
            "decomposition_prompt_suffix_sha256": digest_bytes(PROMPT_SUFFIXES[candidate_id].encode("utf-8")),
            "runtime_lock_manifest": lock.to_manifest(),
            "runtime_lock_sha256": "sha256:" + lock.content_hash,
        })
    return {
        "schema": "trimem/m2-candidate-bundles/1.0",
        "status": "FROZEN_BEFORE_DEVELOPMENT_RESULTS",
        "base_policy_path": BASE_POLICY.relative_to(ROOT).as_posix(),
        "base_policy_file_sha256": digest_bytes(BASE_POLICY.read_bytes()),
        "base_policy_manifest_sha256": digest_value(base),
        "candidate_order": list(CANDIDATE_IDS),
        "candidates": rows,
        "development_contract": {
            "targets_per_candidate": 12,
            "candidate_task_arm_runs": 48,
            "same_order_and_source_evidence": True,
            "one_fresh_durable_namespace_per_candidate": True,
            "heldout_results_visible_during_selection": False,
            "selection_order": [
                "resolved_count descending",
                "actual_total_tokens ascending",
                "actual_usd ascending",
                "candidate_id ascending",
            ],
            "component_ablation_claim": "PROHIBITED",
        },
    }


def build_predevelopment_selection() -> dict[str, Any]:
    return {
        "schema": "trimem/selected-m2/1.0",
        "status": "PRE_DEVELOPMENT",
        "candidate_bundle_path": BUNDLE_PATH.relative_to(ROOT).as_posix(),
        "selected_candidate_id": "PENDING_DEVELOPMENT",
        "selected_full_policy_path": "PENDING_DEVELOPMENT",
        "selected_full_policy_file_sha256": "PENDING_DEVELOPMENT",
        "selected_runtime_lock_sha256": "PENDING_DEVELOPMENT",
        "selected_checkpoint_path": "PENDING_DEVELOPMENT",
        "selected_checkpoint_file_sha256": "PENDING_DEVELOPMENT",
        "selected_checkpoint_digest": "PENDING_DEVELOPMENT",
        "development_selection_evidence_path": "PENDING_DEVELOPMENT",
        "development_selection_evidence_sha256": "PENDING_DEVELOPMENT",
        "heldout_execution": "PROHIBITED_UNTIL_NEW_COMMIT_FREEZE_AND_APPROVAL",
    }


def generate() -> None:
    base = read_json(BASE_POLICY)
    documents = candidate_documents(base)
    for candidate_id, document in documents.items():
        write_json(CANDIDATE_DIR / f"{candidate_id}.json", document)
    write_json(BUNDLE_PATH, build_bundle(base, documents))
    if not SELECTED_PATH.exists() or read_json(SELECTED_PATH).get("status") == "PRE_DEVELOPMENT":
        write_json(SELECTED_PATH, build_predevelopment_selection())


def load_bundle() -> dict[str, Any]:
    bundle = read_json(BUNDLE_PATH)
    if bundle.get("schema") != "trimem/m2-candidate-bundles/1.0" or bundle.get("status") != "FROZEN_BEFORE_DEVELOPMENT_RESULTS":
        raise CandidateContractError("M2 candidate bundle is not frozen before results")
    base = read_json(BASE_POLICY)
    documents = candidate_documents(base)
    expected = build_bundle(base, documents)
    if bundle != expected:
        raise CandidateContractError("M2 candidate bundle drift")
    for candidate_id, expected_document in documents.items():
        path = CANDIDATE_DIR / f"{candidate_id}.json"
        observed_document = read_json(path)
        if observed_document != expected_document:
            raise CandidateContractError(f"M2 candidate full policy drift: {candidate_id}")
        # Exercise the exact production parser and the stricter public retrieval
        # constructor. A syntactically frozen but non-executable candidate must
        # never survive the pre-EXEC gate.
        _parse_policy_manifest(observed_document, digest_value(observed_document))
        retrieval = observed_document["retrieval"]
        RetrievalConfig(
            min_confidence=float(retrieval["min_confidence"]),
            min_margin=float(retrieval["min_margin"]),
            episode_complete_threshold=float(retrieval["episode_complete_threshold"]),
            max_episodic_per_node=int(retrieval["max_episodic_per_active_node"]),
            max_semantic_per_node=int(retrieval["max_semantic_per_active_node"]),
            max_task_injections=int(retrieval["max_task_injections"]),
            context_budget_bytes=int(retrieval["context_budget_bytes"]),
            embedding_dimensions=int(retrieval["embedding_dimensions"]),
            embedding_weight=float(retrieval["embedding_weight"]),
            lexical_weight=float(retrieval["lexical_weight"]),
            ppr_damping=float(retrieval["ppr_damping"]),
            ppr_iterations=int(retrieval["ppr_iterations"]),
        )
    return bundle


def candidate_row(candidate_id: str) -> dict[str, Any]:
    rows = load_bundle().get("candidates", [])
    matches = [row for row in rows if isinstance(row, dict) and row.get("candidate_id") == candidate_id]
    if len(matches) != 1:
        raise CandidateContractError(f"candidate row is not unique: {candidate_id}")
    return dict(matches[0])


def load_candidate_policy(candidate_id: str) -> dict[str, Any]:
    row = candidate_row(candidate_id)
    path = ROOT / row["full_policy_path"]
    document = read_json(path)
    if digest_bytes(path.read_bytes()) != row["full_policy_file_sha256"] or digest_value(document) != row["full_policy_manifest_sha256"]:
        raise CandidateContractError(f"candidate policy hash mismatch: {candidate_id}")
    return document


def select_development_candidate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_id: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        candidate_id = row.get("candidate_id")
        if candidate_id not in CANDIDATE_IDS or candidate_id in by_id:
            raise CandidateContractError("development selection has duplicate/unknown candidate")
        for name in ("resolved_count", "actual_total_tokens"):
            if type(row.get(name)) is not int or row[name] < 0:
                raise CandidateContractError(f"candidate {candidate_id} has invalid {name}")
        if row.get("completed_target_count") != 12 or row.get("final_resume_cursor") != 12:
            raise CandidateContractError(f"candidate {candidate_id} did not complete the frozen development stream")
        try:
            cost = Decimal(str(row.get("actual_usd")))
        except (InvalidOperation, ValueError) as exc:
            raise CandidateContractError(f"candidate {candidate_id} has invalid actual_usd") from exc
        if not cost.is_finite() or cost < 0:
            raise CandidateContractError(f"candidate {candidate_id} has invalid actual_usd")
        row["actual_usd"] = format(cost, "f")
        by_id[str(candidate_id)] = row
    if set(by_id) != set(CANDIDATE_IDS):
        raise CandidateContractError("selection requires all four preregistered candidate summaries")
    ordered = sorted(
        by_id.values(),
        key=lambda row: (-row["resolved_count"], row["actual_total_tokens"], Decimal(row["actual_usd"]), row["candidate_id"]),
    )
    return {
        "schema": "trimem/development-m2-selection/1.0",
        "status": "SELECTED_PENDING_COMMIT_FREEZE_AND_HELDOUT_APPROVAL",
        "selection_rule": load_bundle()["development_contract"]["selection_order"],
        "ranked_candidates": ordered,
        "selected_candidate_id": ordered[0]["candidate_id"],
    }


def _git_tracked(path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return False
    return subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative], cwd=ROOT,
        capture_output=True, text=True, check=False,
    ).returncode == 0


def _validate_frozen_selection(value: Mapping[str, Any], *, require_tracked: bool) -> dict[str, Any]:
    value = dict(value)
    candidate_id = value.get("selected_candidate_id")
    row = candidate_row(str(candidate_id))
    expected = {
        "selected_full_policy_path": row["full_policy_path"],
        "selected_full_policy_file_sha256": row["full_policy_file_sha256"],
        "selected_runtime_lock_sha256": row["runtime_lock_sha256"],
        "heldout_execution": "PENDING_SEPARATE_EXEC_APPROVAL",
    }
    for name, observed in expected.items():
        if value.get(name) != observed:
            raise CandidateContractError(f"selected M2 binding mismatch: {name}")
    for path_field, hash_field in (
        ("selected_checkpoint_path", "selected_checkpoint_file_sha256"),
        ("development_selection_evidence_path", "development_selection_evidence_sha256"),
    ):
        path = ROOT / str(value.get(path_field, ""))
        if ROOT.resolve() not in path.resolve().parents or not path.is_file():
            raise CandidateContractError(f"selected M2 artifact is missing: {path_field}")
        if require_tracked and not _git_tracked(path):
            raise CandidateContractError(f"selected M2 artifact is not git-tracked: {path_field}")
        if digest_bytes(path.read_bytes()) != str(value.get(hash_field, "")).removeprefix("sha256:"):
            raise CandidateContractError(f"selected M2 artifact hash mismatch: {path_field}")
    checkpoint = read_json(ROOT / value["selected_checkpoint_path"])
    if digest_value(checkpoint.get("payload")) != checkpoint.get("digest") or checkpoint.get("digest") != value.get("selected_checkpoint_digest"):
        raise CandidateContractError("selected DQN checkpoint digest mismatch")
    selection = read_json(ROOT / value["development_selection_evidence_path"])
    recalculated = select_development_candidate(selection.get("candidate_summaries", []))
    if selection.get("selection") != recalculated or recalculated["selected_candidate_id"] != candidate_id:
        raise CandidateContractError("selected M2 is not reproduced by frozen development evidence")
    return value


def validate_selected_m2(*, require_frozen: bool) -> dict[str, Any]:
    value = read_json(SELECTED_PATH)
    if value.get("schema") != "trimem/selected-m2/1.0":
        raise CandidateContractError("selected M2 schema mismatch")
    bundle = load_bundle()
    if value.get("candidate_bundle_path") != BUNDLE_PATH.relative_to(ROOT).as_posix():
        raise CandidateContractError("selected M2 candidate bundle path drift")
    if value.get("status") == "PRE_DEVELOPMENT":
        if require_frozen:
            raise CandidateContractError("selected M2 is still PRE_DEVELOPMENT")
        if value != build_predevelopment_selection():
            raise CandidateContractError("PRE_DEVELOPMENT selected M2 placeholder drift")
        return value
    if value.get("status") != "FROZEN_AFTER_DEVELOPMENT":
        raise CandidateContractError("selected M2 status is invalid")
    return _validate_frozen_selection(value, require_tracked=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--select-summary", type=Path)
    parser.add_argument("--promote-proposal", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if sum(bool(item) for item in (args.write, args.verify, args.select_summary, args.promote_proposal)) != 1:
            raise CandidateContractError(
                "choose exactly one of --write, --verify, --select-summary, or --promote-proposal"
            )
        if args.write:
            generate()
            bundle = load_bundle()
            validate_selected_m2(require_frozen=False)
            print(json.dumps({"bundle_sha256": digest_value(bundle), "status": "PASS"}, sort_keys=True))
        elif args.verify:
            bundle = load_bundle()
            selected = validate_selected_m2(require_frozen=False)
            print(json.dumps({"bundle_sha256": digest_value(bundle), "selected_status": selected["status"], "status": "PASS"}, sort_keys=True))
        elif args.select_summary:
            if args.output is None:
                raise CandidateContractError("--select-summary requires --output")
            source = read_json(args.select_summary.resolve())
            result = select_development_candidate(source.get("candidate_summaries", []))
            write_json(args.output.resolve(), result)
            print(json.dumps(result, sort_keys=True))
        else:
            proposal = read_json(args.promote_proposal.resolve())
            if proposal.get("schema") != "trimem/selected-m2/1.0" or proposal.get("status") != "FROZEN_AFTER_DEVELOPMENT":
                raise CandidateContractError("post-development selection proposal schema/status mismatch")
            _validate_frozen_selection(proposal, require_tracked=False)
            write_json(SELECTED_PATH, proposal)
            print(json.dumps({
                "selected_candidate_id": proposal["selected_candidate_id"],
                "status": "PROMOTED_PENDING_GIT_COMMIT_FREEZE_AND_HELDOUT_APPROVAL",
            }, sort_keys=True))
    except (CandidateContractError, OSError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
