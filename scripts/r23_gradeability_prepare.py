#!/usr/bin/env python3
"""Validate the frozen R23 grader-smoke manifest and emit its GitHub matrix.

This is the only source of the gradeability target matrix.  It performs no
network, Docker, grader, or model operation.  Any drift in the committed
benchmark locks, repository-stratified selection, image digest, or condition
contract is fatal before a matrix is emitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts" / "r23"
DEFAULT_MANIFEST = ART / "grader_smoke_manifest.json"
DEFAULT_BENCHMARK_LOCK = ART / "benchmark_lock.json"
DEFAULT_IMAGE_MANIFEST = ART / "image_manifest.json"
SCHEMA = "r23/grader_smoke_manifest/1.0.0"
SEED = "r23-grader-smoke-v1"
NOOP_R23_PATCH = (
    "diff --git a/.r23_noop b/.r23_noop\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/.r23_noop\n"
    "@@ -0,0 +1 @@\n"
    "+r23 gradeability noop\n"
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class ManifestError(ValueError):
    """The committed smoke manifest is not an exact frozen contract."""


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"top-level JSON must be an object: {path}")
    return value


def _lf_sha256(path: Path) -> str:
    try:
        raw = path.read_bytes().replace(b"\r\n", b"\n")
    except OSError as exc:
        raise ManifestError(f"cannot hash {path}: {exc}") from exc
    return hashlib.sha256(raw).hexdigest()


def repository_key(instance_id: str) -> str:
    if not isinstance(instance_id, str) or "-" not in instance_id:
        raise ManifestError(f"invalid SWE-bench instance_id: {instance_id!r}")
    return instance_id.rsplit("-", 1)[0]


def selection_score(repo_key: str, instance_id: str) -> str:
    preimage = f"{SEED}\0{repo_key}\0{instance_id}".encode("utf-8")
    return hashlib.sha256(preimage).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def validate_manifest(
    manifest_path: os.PathLike[str] | str = DEFAULT_MANIFEST,
    benchmark_lock_path: os.PathLike[str] | str = DEFAULT_BENCHMARK_LOCK,
    image_manifest_path: os.PathLike[str] | str = DEFAULT_IMAGE_MANIFEST,
) -> dict:
    manifest_path = Path(manifest_path)
    benchmark_lock_path = Path(benchmark_lock_path)
    image_manifest_path = Path(image_manifest_path)
    manifest = _load(manifest_path)
    benchmark = _load(benchmark_lock_path)
    images = _load(image_manifest_path)

    _require(manifest.get("schema") == SCHEMA, "wrong grader-smoke manifest schema")
    _require(manifest.get("freeze_status") == "FROZEN_PRE_EXECUTION", "manifest is not frozen before execution")
    _require(manifest.get("execution_status") == "PENDING_EXEC_APPROVAL", "execution status must remain pending")
    _require(
        manifest.get("benchmark_grader_viability") == "PENDING_OFFICIAL_GRADER_SMOKE",
        "grader viability must not be declared before execution",
    )
    _require(manifest.get("paid_model_calls") == 0, "manifest must declare zero paid/model calls")

    dataset = manifest.get("dataset") or {}
    for key, benchmark_key in (
        ("dataset_id", "dataset_id"),
        ("revision_sha", "revision_sha"),
        ("split", "split"),
        ("parquet_path", "parquet_path"),
        ("parquet_sha256", "parquet_sha256"),
    ):
        _require(dataset.get(key) == benchmark.get(benchmark_key), f"dataset {key} drifted from benchmark lock")
    _require(
        dataset.get("benchmark_lock_lf_sha256") == _lf_sha256(benchmark_lock_path),
        "benchmark_lock.json LF-normalized SHA-256 mismatch",
    )
    _require(
        dataset.get("image_manifest_lf_sha256") == _lf_sha256(image_manifest_path),
        "image_manifest.json LF-normalized SHA-256 mismatch",
    )
    _require(manifest.get("harness", {}).get("package") == "swebench", "official harness package is not locked")
    _require(manifest.get("harness", {}).get("version") == "5.0.2", "official harness version is not locked")
    _require(manifest.get("harness", {}).get("max_workers") == 1, "grader max_workers must be one per shard")
    _require(
        manifest.get("harness", {}).get("timeout_seconds_per_condition") == 1800,
        "per-condition timeout drifted",
    )

    conditions = manifest.get("conditions")
    _require(isinstance(conditions, list), "conditions must be a list")
    _require(all(isinstance(condition, dict) for condition in conditions), "each condition must be an object")
    _require([c.get("name") for c in conditions] == ["GOLD", "NOOP"], "conditions must be exactly GOLD + NOOP")
    _require([c.get("expected") for c in conditions] == ["RESOLVED", "UNRESOLVED_WITH_REPORT"],
             "GOLD/NOOP expected outcomes drifted")
    noop_hash = hashlib.sha256(NOOP_R23_PATCH.encode("utf-8")).hexdigest()
    _require(conditions[1].get("patch_sha256") == noop_hash, "NOOP patch hash mismatch")
    image_resolution = manifest.get("image_digest_resolution") or {}
    _require(
        image_resolution.get("docker_or_grader_executed_during_freeze") is False,
        "manifest freeze must precede Docker/grader execution",
    )
    _require(
        image_resolution.get("media_type") == "application/vnd.oci.image.index.v1+json",
        "registry digest media type drifted",
    )

    index = benchmark.get("per_instance_hash_index")
    _require(isinstance(index, dict), "benchmark lock lacks per_instance_hash_index")
    _require(len(index) == benchmark.get("row_count") == benchmark.get("unique_instance_ids") == 500,
             "benchmark target universe must be exactly 500 unique rows")
    image_names = images.get("image_names")
    _require(isinstance(image_names, dict) and set(image_names) == set(index), "image manifest target universe mismatch")

    strata: dict[str, list[str]] = defaultdict(list)
    for instance_id in index:
        strata[repository_key(instance_id)].append(instance_id)
    winners = {
        repo_key: min(ids, key=lambda iid: (selection_score(repo_key, iid), iid))
        for repo_key, ids in strata.items()
    }

    targets = manifest.get("targets")
    _require(isinstance(targets, list), "targets must be a list")
    _require(all(isinstance(target, dict) for target in targets), "each target must be an object")
    target_ids = [target.get("instance_id") for target in targets]
    repo_keys = [target.get("repository_key") for target in targets]
    _require(all(isinstance(iid, str) for iid in target_ids), "every target needs a string instance_id")
    _require(all(isinstance(repo, str) for repo in repo_keys), "every target needs a string repository_key")
    duplicate_ids = sorted(key for key, count in Counter(target_ids).items() if count > 1)
    duplicate_repos = sorted(key for key, count in Counter(repo_keys).items() if count > 1)
    _require(not duplicate_ids, f"duplicate target instance_ids: {duplicate_ids}")
    _require(not duplicate_repos, f"duplicate repository strata: {duplicate_repos}")
    _require(repo_keys == sorted(strata), "targets must be ordered one-per-repository by repository_key")
    _require(len(targets) == len(strata) == 12, "expected exactly one target for each of 12 repositories")

    for target in targets:
        iid = target.get("instance_id")
        repo_key = target.get("repository_key")
        _require(repo_key == repository_key(iid), f"repository_key mismatch for {iid}")
        _require(winners.get(repo_key) == iid, f"{iid} is not deterministic winner for {repo_key}")
        _require(target.get("selection_score_sha256") == selection_score(repo_key, iid), f"selection score mismatch for {iid}")
        _require(isinstance(target.get("repository"), str) and "/" in target["repository"], f"repository missing for {iid}")
        _require(HEX64.fullmatch(target.get("gold_patch_sha256", "")) is not None, f"gold patch hash invalid for {iid}")
        _require(HEX64.fullmatch(target.get("dataset_row_sha256", "")) is not None, f"row hash invalid for {iid}")
        _require(target["gold_patch_sha256"].startswith(index[iid]["gold"]), f"gold patch hash prefix drift for {iid}")
        _require(target.get("image_tag") == index[iid].get("image") == image_names.get(iid), f"image tag drift for {iid}")
        digest = target.get("image_digest", "")
        _require(DIGEST.fullmatch(digest) is not None, f"unfrozen image digest for {iid}")
        image_repo = target["image_tag"].rsplit(":", 1)[0]
        _require(target.get("image_ref") == f"{image_repo}@{digest}", f"digest image_ref mismatch for {iid}")

    selection = manifest.get("selection") or {}
    _require(selection.get("rule_name") == "repository_stratified_sha256_min_v1", "selection rule name mismatch")
    _require(selection.get("seed") == SEED, "selection seed mismatch")
    _require(selection.get("repository_count") == len(strata), "repository_count mismatch")
    _require(selection.get("target_count") == len(targets), "target_count mismatch")
    target_set = [{"repository_key": t["repository_key"], "instance_id": t["instance_id"]} for t in targets]
    target_set_hash = hashlib.sha256(
        json.dumps(target_set, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    _require(selection.get("target_set_sha256") == target_set_hash, "target set hash mismatch")
    return manifest


def matrix_from_manifest(manifest: dict) -> dict:
    return {
        "include": [
            {"instance_id": target["instance_id"], "repository_key": target["repository_key"]}
            for target in manifest["targets"]
        ]
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--benchmark-lock", default=str(DEFAULT_BENCHMARK_LOCK))
    parser.add_argument("--image-manifest", default=str(DEFAULT_IMAGE_MANIFEST))
    parser.add_argument("--github-output", help="append a matrix output to this GitHub Actions output file")
    parser.add_argument("--report", help="optional path for a credential-free validation report")
    args = parser.parse_args()
    manifest = validate_manifest(args.manifest, args.benchmark_lock, args.image_manifest)
    matrix = matrix_from_manifest(manifest)
    compact_matrix = json.dumps(matrix, separators=(",", ":"))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"matrix={compact_matrix}\n")
    report = {
        "schema": "r23/grader_smoke_prepare/1.0.0",
        "valid": True,
        "target_count": len(manifest["targets"]),
        "expected_target_set": [target["instance_id"] for target in manifest["targets"]],
        "matrix": matrix,
        "docker_executed": False,
        "grader_executed": False,
        "paid_model_calls": 0,
    }
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(compact_matrix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
