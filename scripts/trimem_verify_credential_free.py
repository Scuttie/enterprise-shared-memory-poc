"""Verify any TriMem credential-free E2E bundle by content, not wall-clock hash."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from enterprise_memory.trimem.accounting import strict_json_loads  # noqa: E402
from enterprise_memory.trimem.runtime_lock import RuntimeLock  # noqa: E402


class CredentialFreeEvidenceError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise CredentialFreeEvidenceError(f"duplicate JSON key in {path}: {key}")
            value[key] = child
        return value
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
    if not isinstance(value, dict):
        raise CredentialFreeEvidenceError(f"JSON root is not an object: {path}")
    return value


def verify_event_chain(path: Path) -> str:
    previous, count = "0" * 64, 0
    blob_dir = path.parent / "blobs"

    def verify_refs(value: Any) -> None:
        if isinstance(value, Mapping):
            if {"sha256", "bytes", "media_type"}.issubset(value):
                blob = blob_dir / str(value["sha256"])
                if not blob.is_file() or len(blob.read_bytes()) != value["bytes"] or hashlib.sha256(blob.read_bytes()).hexdigest() != value["sha256"]:
                    raise CredentialFreeEvidenceError(f"blob reference mismatch: {blob}")
            for child in value.values():
                verify_refs(child)
        elif isinstance(value, list):
            for child in value:
                verify_refs(child)

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        try:
            row = strict_json_loads(line)
        except (json.JSONDecodeError, ValueError) as exc:
            raise CredentialFreeEvidenceError(
                f"event JSON is not strict: {path}"
            ) from exc
        if not isinstance(row, Mapping):
            raise CredentialFreeEvidenceError(f"event JSON root is invalid: {path}")
        count += 1
        body = {key: value for key, value in row.items() if key != "event_hash"}
        observed = hashlib.sha256(canonical(body)).hexdigest()
        if row.get("sequence") != count or row.get("previous_event_hash") != previous or row.get("event_hash") != observed:
            raise CredentialFreeEvidenceError(f"event chain mismatch: {path}")
        verify_refs(row.get("payload"))
        previous = observed
    if count == 0:
        raise CredentialFreeEvidenceError(f"empty event chain: {path}")
    return previous


def verify_checkpoint(path: Path, expected_tail: str) -> None:
    raw = path.read_bytes()
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file() or sidecar.read_text(encoding="utf-8").strip() != hashlib.sha256(raw).hexdigest():
        raise CredentialFreeEvidenceError(f"checkpoint byte/sidecar mismatch: {path}")
    try:
        checkpoint = strict_json_loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise CredentialFreeEvidenceError(
            f"checkpoint JSON is not strict: {path}"
        ) from exc
    if not isinstance(checkpoint, Mapping):
        raise CredentialFreeEvidenceError(f"checkpoint JSON root is invalid: {path}")
    if checkpoint.get("state") != "DONE" or checkpoint.get("evidence_event_hash") != expected_tail:
        raise CredentialFreeEvidenceError(f"checkpoint terminal/evidence binding mismatch: {path}")


def verify_bundle(base: Path) -> dict[str, Any]:
    bundle = read_json(base / "credential_free_e2e_bundle.json")
    claimed = bundle.get("bundle_hash")
    body = {key: value for key, value in bundle.items() if key != "bundle_hash"}
    if claimed != hashlib.sha256(canonical(body)).hexdigest():
        raise CredentialFreeEvidenceError("credential-free bundle hash mismatch")
    if bundle.get("status") != "PASS" or bundle.get("paid_model_calls") != 0 or bundle.get("official_grader_execution") is not False:
        raise CredentialFreeEvidenceError("credential-free execution boundary failed")
    if bundle.get("grader_execution_status") != "CREDENTIAL_FREE_INTERFACE_REPLAY_ONLY":
        raise CredentialFreeEvidenceError("credential-free grader mode is overstated")
    correctness = bundle.get("correctness", {})
    required_true = {
        "active_node_memory_only", "dependency_order_enforced",
        "exact_injected_bytes_equal_recorded_hash", "target_memory_present_in_actual_prompt",
    }
    if any(correctness.get(name) is not True for name in required_true):
        raise CredentialFreeEvidenceError("credential-free correctness proof is incomplete")
    if correctness.get("hidden_grader_payload_exposed_to_extractor") is not False or correctness.get("private_episode_identifiers_exposed_cross_user") is not False:
        raise CredentialFreeEvidenceError("credential-free privacy proof failed")
    lock = RuntimeLock()
    if bundle.get("runtime_lock") != lock.to_manifest() or bundle.get("runtime_lock_hash") != lock.content_hash:
        raise CredentialFreeEvidenceError("credential-free runtime/tool/parser lock drift")
    if bundle.get("dqn", {}).get("evaluation_exploration") is not False:
        raise CredentialFreeEvidenceError("credential-free evaluation used exploration")
    if bundle.get("source", {}).get("shared_promotion", {}).get("dqn_controlled_publication") is not False:
        raise CredentialFreeEvidenceError("DQN controlled shared publication")
    if bundle.get("target", {}).get("cross_user_transfer_bank") != "ORG_SEMANTIC":
        raise CredentialFreeEvidenceError("cross-user transfer bypassed reviewed org semantic")
    for directory, field in (
        ("source-json-extension", "source"), ("target-yaml-extension", "target")
    ):
        event_path = base / directory / "evidence/events.ndjson"
        tail = verify_event_chain(event_path)
        if tail != bundle[field]["evidence_tail_hash"]:
            raise CredentialFreeEvidenceError(f"{field} event tail mismatch")
        verify_checkpoint(base / directory / "checkpoints" / f"{directory}-M2.json", tail)
    frozen = read_json(base / "dqn_frozen_checkpoint.json")
    digest = frozen.get("digest")
    if digest != "sha256:" + hashlib.sha256(canonical(frozen.get("payload"))).hexdigest() or frozen.get("payload", {}).get("frozen") is not True:
        raise CredentialFreeEvidenceError("credential-free DQN frozen checkpoint mismatch")
    if bundle.get("dqn", {}).get("checkpoint_digest") != digest:
        raise CredentialFreeEvidenceError("bundle/DQN checkpoint digest mismatch")
    return {"bundle_hash": claimed, "paid_model_calls": 0, "official_grader_execution": False, "status": "PASS"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify_bundle(args.root.resolve()), sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
