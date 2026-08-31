#!/usr/bin/env python3
"""Fail-closed aggregate for the frozen R23 official-grader smoke set.

The expected target set comes only from the committed smoke manifest. Missing,
duplicate, unexpected, malformed, non-terminal, condition-inconsistent, or
raw-evidence-incomplete shards all make the command fail. A complete campaign
still fails the viability gate unless every target discriminates GOLD from
NOOP. The JSON report is written before the non-zero exit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from r23_gradeability_prepare import DEFAULT_MANIFEST, ManifestError, validate_manifest  # noqa: E402


ART = ROOT / "artifacts" / "r23"
DEFAULT_OUT = ART / "gradeability_results.json"
TARGET_SCHEMA = "r23/gradeability_target/1.0.0"
TERMINAL_LABELS = {"GRADEABLE", "UNGRADEABLE_GOLD", "UNGRADEABLE_NOOP"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _norm(path: Path) -> str:
    return str(path).replace("\\", "/")


def _find_evidence(download_dir: Path, relpath: str) -> tuple[Path | None, str | None]:
    relpath = relpath.replace("\\", "/").lstrip("/")
    basename = Path(relpath).name
    matches = [path for path in download_dir.rglob(basename) if path.is_file() and _norm(path).endswith(relpath)]
    if not matches:
        return None, f"missing evidence file: {relpath}"
    if len(matches) > 1:
        return None, f"duplicate downloaded evidence path: {relpath} ({len(matches)} copies)"
    return matches[0], None


def _validate_evidence(download_dir: Path, summary: dict) -> list[str]:
    iid = summary.get("instance_id", "<unknown>")
    evidence = summary.get("raw_evidence")
    if not isinstance(evidence, list):
        return [f"{iid}: raw_evidence must be a list"]
    errors: list[str] = []
    relpaths: list[str] = []
    for meta in evidence:
        if not isinstance(meta, dict):
            errors.append(f"{iid}: malformed evidence metadata")
            continue
        relpath = meta.get("relpath")
        if not isinstance(relpath, str) or not relpath.startswith("artifacts/r23/grader_run/"):
            errors.append(f"{iid}: invalid evidence relpath {relpath!r}")
            continue
        relpaths.append(relpath)
        path, find_error = _find_evidence(download_dir, relpath)
        if find_error:
            errors.append(f"{iid}: {find_error}")
            continue
        assert path is not None
        if meta.get("bytes") != path.stat().st_size:
            errors.append(f"{iid}: evidence byte-count mismatch: {relpath}")
        if meta.get("sha256") != _sha256_file(path):
            errors.append(f"{iid}: evidence SHA-256 mismatch: {relpath}")

    duplicates = sorted(path for path, count in Counter(relpaths).items() if count > 1)
    if duplicates:
        errors.append(f"{iid}: duplicate evidence metadata paths: {duplicates}")
    required_suffixes = [
        f"/{iid}/dataset.json",
        f"/{iid}/image_pull_stdout.log",
        f"/{iid}/image_pull_stderr.log",
        f"/{iid}/image_inspect_stdout.log",
        f"/{iid}/image_inspect_stderr.log",
        f"/{iid}/gold/prediction.jsonl",
        f"/{iid}/gold/harness_stdout.log",
        f"/{iid}/gold/harness_stderr.log",
        f"/{iid}/noop/prediction.jsonl",
        f"/{iid}/noop/harness_stdout.log",
        f"/{iid}/noop/harness_stderr.log",
    ]
    for suffix in required_suffixes:
        if sum(path.endswith(suffix) for path in relpaths) != 1:
            errors.append(f"{iid}: required raw evidence missing or duplicate: *{suffix}")
    for condition in ("gold", "noop"):
        cell = summary.get(condition) or {}
        report_path = cell.get("report_path")
        if not isinstance(report_path, str) or report_path not in relpaths:
            errors.append(f"{iid}: {condition} official report is not preserved in raw_evidence")
    return errors


def _expected_label(gold: dict, noop: dict) -> str:
    if not gold.get("infra_ok") or not noop.get("infra_ok"):
        return "INFRA_FAILURE"
    if not gold.get("resolved"):
        return "UNGRADEABLE_GOLD"
    if noop.get("resolved"):
        return "UNGRADEABLE_NOOP"
    return "GRADEABLE"


def _validate_conditions(summary: dict, target: dict, manifest: dict) -> list[str]:
    iid = target["instance_id"]
    errors: list[str] = []
    if summary.get("schema") != TARGET_SCHEMA:
        errors.append(f"{iid}: wrong target schema")
    if summary.get("repository_key") != target["repository_key"]:
        errors.append(f"{iid}: repository_key mismatch")
    if summary.get("paid_model_calls") != 0:
        errors.append(f"{iid}: paid/model calls must equal zero")
    if summary.get("dataset_revision") != manifest["dataset"]["revision_sha"]:
        errors.append(f"{iid}: dataset revision mismatch")
    if summary.get("dataset_parquet_sha256") != manifest["dataset"]["parquet_sha256"]:
        errors.append(f"{iid}: dataset parquet SHA-256 mismatch")
    if summary.get("dataset_row_sha256") != target["dataset_row_sha256"]:
        errors.append(f"{iid}: dataset row SHA-256 mismatch")
    if summary.get("image_expected_ref") != target["image_ref"]:
        errors.append(f"{iid}: frozen image ref mismatch")
    if summary.get("image_expected_digest") != target["image_digest"]:
        errors.append(f"{iid}: frozen image digest mismatch")
    if summary.get("image_digest_verified") is not True:
        errors.append(f"{iid}: image digest was not verified")
    if target["image_ref"] not in (summary.get("image_observed_repo_digests") or []):
        errors.append(f"{iid}: observed RepoDigests lack frozen image ref")

    gold = summary.get("gold")
    noop = summary.get("noop")
    if not isinstance(gold, dict) or not isinstance(noop, dict):
        errors.append(f"{iid}: GOLD and NOOP condition records are both required")
        return errors
    noop_hash = manifest["conditions"][1]["patch_sha256"]
    checks = (
        (gold.get("condition") == "GOLD", "GOLD condition name mismatch"),
        (noop.get("condition") == "NOOP", "NOOP condition name mismatch"),
        (gold.get("patch_sha256") == target["gold_patch_sha256"], "GOLD patch hash mismatch"),
        (noop.get("patch_sha256") == noop_hash, "NOOP patch hash mismatch"),
    )
    for passed, message in checks:
        if not passed:
            errors.append(f"{iid}: {message}")
    for name, cell in (("GOLD", gold), ("NOOP", noop)):
        if cell.get("returncode") != 0:
            errors.append(f"{iid}: {name} harness returncode is not zero")
        if cell.get("report_found") is not True:
            errors.append(f"{iid}: {name} official report missing")
        if cell.get("completed") is not True:
            errors.append(f"{iid}: {name} did not complete")
        if cell.get("empty_patch") is not False:
            errors.append(f"{iid}: {name} hit the empty-patch short circuit")
        if cell.get("infra_ok") is not True:
            errors.append(f"{iid}: {name} infrastructure not healthy")
    expected_label = _expected_label(gold, noop)
    if summary.get("label") != expected_label:
        errors.append(f"{iid}: label {summary.get('label')!r} inconsistent with conditions ({expected_label})")
    return errors


def aggregate(download_dir: os.PathLike[str] | str, manifest_path: os.PathLike[str] | str = DEFAULT_MANIFEST) -> dict:
    download_dir = Path(download_dir).resolve()
    manifest = validate_manifest(manifest_path)
    expected_records = {target["instance_id"]: target for target in manifest["targets"]}
    expected = list(expected_records)

    by_id: dict[str, list[tuple[Path, dict]]] = defaultdict(list)
    malformed_files: list[str] = []
    for path in sorted(download_dir.rglob("grade_*.json")):
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            malformed_files.append(f"{_norm(path)}: {exc}")
            continue
        iid = summary.get("instance_id") if isinstance(summary, dict) else None
        if not isinstance(iid, str):
            malformed_files.append(f"{_norm(path)}: missing string instance_id")
            continue
        if path.name != f"grade_{iid}.json":
            malformed_files.append(f"{_norm(path)}: filename does not match instance_id {iid}")
        by_id[iid].append((path, summary))

    observed = sorted(by_id)
    missing = sorted(set(expected) - set(observed))
    unexpected = sorted(set(observed) - set(expected))
    duplicates = {iid: len(records) for iid, records in sorted(by_id.items()) if len(records) > 1}
    condition_errors: list[str] = []
    evidence_errors: list[str] = []
    per_target_label: dict[str, str] = {}
    for iid in expected:
        records = by_id.get(iid, [])
        if len(records) != 1:
            continue
        summary = records[0][1]
        label = summary.get("label")
        per_target_label[iid] = label if isinstance(label, str) else "UNKNOWN"
        condition_errors.extend(_validate_conditions(summary, expected_records[iid], manifest))
        evidence_errors.extend(_validate_evidence(download_dir, summary))

    label_counts = dict(sorted(Counter(per_target_label.values()).items()))
    terminal_count = sum(count for label, count in label_counts.items() if label in TERMINAL_LABELS)
    audit_complete = not any(
        (missing, unexpected, duplicates, malformed_files, condition_errors, evidence_errors)
    ) and terminal_count == len(expected)
    viability_pass = audit_complete and label_counts == {"GRADEABLE": len(expected)}
    return {
        "schema": "r23/gradeability_aggregate/1.0.0",
        "expected_target_set": expected,
        "expected_target_count": len(expected),
        "observed_target_set": observed,
        "observed_target_count": len(observed),
        "missing_targets": missing,
        "unexpected_targets": unexpected,
        "duplicate_targets": duplicates,
        "malformed_files": malformed_files,
        "condition_errors": condition_errors,
        "evidence_errors": evidence_errors,
        "label_counts": label_counts,
        "per_target_label": per_target_label,
        "audit_complete": audit_complete,
        "benchmark_grader_viability": "PASS" if viability_pass else ("FAIL" if audit_complete else "INCOMPLETE"),
        "paid_model_calls": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-dir", required=True)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    out_path = Path(args.out).resolve()
    try:
        result = aggregate(args.download_dir, args.manifest)
    except ManifestError as exc:
        result = {
            "schema": "r23/gradeability_aggregate/1.0.0",
            "audit_complete": False,
            "benchmark_grader_viability": "INCOMPLETE",
            "manifest_error": str(exc),
            "paid_model_calls": 0,
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "R23 GRADEABILITY: expected=%s observed=%s missing=%s duplicate=%s complete=%s viability=%s"
        % (
            result.get("expected_target_count", 0),
            result.get("observed_target_count", 0),
            len(result.get("missing_targets", [])),
            len(result.get("duplicate_targets", {})),
            result.get("audit_complete", False),
            result.get("benchmark_grader_viability", "INCOMPLETE"),
        )
    )
    return 0 if result.get("benchmark_grader_viability") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
