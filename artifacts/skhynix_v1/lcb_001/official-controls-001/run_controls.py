"""Reproduce two old model candidates against pinned official tasks, silently.

All problem/test/candidate bytes stay in the dedicated external work directory.
Only fingerprints, source identities, aggregate verdicts and timings are reported.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

SPLIT_SHA256 = "a960fee4bd549dcec2bda5828b657b4b2cd6af76198485030c33a4a55e5a75c9"
SOURCE_SHA256 = "9468d8ff1799a2891d36d78904746b08bd568e2f4f7399606a8086f882e2dd38"
CONTROL_CODES = {
    "abc372_a": "9dce8959501f494ddcac5d9b0a16b73ef69ca9722affd8fa49d49bd9e4688ca2",
    "3593": "7fb8a36c9c6d5ff0e56b770ea066ff32a6961656973fbe5327e230a75ad92d62",
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def checked_json(path, sha):
    raw = Path(path).read_bytes()
    if digest(raw) != sha:
        raise ValueError("Pinned metadata changed")
    return json.loads(raw)


def write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def ref(path):
    return {"path": str(path), "sha256": file_hash(path), "bytes": path.stat().st_size}


def run(args):
    started = time.perf_counter()
    repo, data, reports, work = [Path(getattr(args, key)).resolve() for key in ("repository", "data_root", "report_root", "work_root")]
    work.mkdir(parents=True, exist_ok=False)
    reports.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(repo / "scripts"))
    import trimem_lcb_grade as grader

    split_path = repo / "configs/skhynix_v1/lcb_001_public_split.json"
    source_path = repo / "artifacts/livecodebench_r11/source_solves.json"
    split = checked_json(split_path, SPLIT_SHA256)
    saved = checked_json(source_path, SOURCE_SHA256)
    public_ref = split["public_tasks_reference"]
    public_raw = (data / public_ref["path"]).read_bytes()
    if digest(public_raw) != public_ref["sha256"]:
        raise ValueError("Public enrollment changed")
    public = {row["task_id"]: row for line in public_raw.splitlines() if line for row in [json.loads(line)]}
    families = {public[identity]["family_id"] for identity in CONTROL_CODES}
    pilot_families = {public[identity]["family_id"] for identity in split["train_pilot_ids"]}
    if families & pilot_families:
        raise ValueError("Control family intersects frozen training pilot")
    exclusions = sorted(identity for identity, row in public.items() if row["family_id"] in families)
    if any(identity not in split["train_ids"] or public[identity]["split"] != "train" for identity in exclusions):
        raise ValueError("A control family is outside TRAIN")

    with grader.quiet_grader():
        runtime = grader.load_official_runtime(args.official_repo, raw_rows=True)
    samples, metadata, positive = [], [], []
    verified_files = set()
    for identity, code_sha in CONTROL_CODES.items():
        row = public[identity]
        source = row["source_reference"]
        raw_path = data / source["file"]
        if str(raw_path) not in verified_files:
            if file_hash(raw_path) != source["sha256"]:
                raise ValueError("Official raw source checksum differs")
            verified_files.add(str(raw_path))
        raw_line = None
        with raw_path.open("rb") as stream:
            for number, line in enumerate(stream, 1):
                if number == source["line"]:
                    raw_line = line
                    break
        if raw_line is None or digest(raw_line) != source["row_sha256"]:
            raise ValueError("Official row checksum differs")
        with grader.quiet_grader():
            problem = runtime.problem_class(**grader.parse_json(raw_line))
            if problem.question_id != identity:
                raise ValueError("Official task identity differs")
            sample = problem.get_evaluation_sample()
        code = saved[identity]["code"]
        if saved[identity].get("passed") is not True or digest(code.encode()) != code_sha or len(code) >= 6000:
            raise ValueError("Old candidate fingerprint or complete-code condition differs")
        output = "```python\n" + code + "\n```"
        if runtime.extract(output, runtime.style) != code:
            raise ValueError("Official extraction changed saved candidate bytes")
        sample_row = {"question_id": identity, "sample": sample}
        sample_path = work / (identity + "-official-sample.json.gz")
        envelope = {"schema": grader.SAMPLE_SCHEMA, "samples": [sample_row], "provenance": {
            "source_reference": source, "dataset_revision": split["source_revision"], "official_commit": grader.UPSTREAM_COMMIT}}
        write_new(sample_path, gzip.compress(canonical(envelope), mtime=0))
        samples.append(sample_row)
        positive.append({"question_id": identity, "output": output})
        metadata.append({"question_id": identity, "split": row["split"], "family_id": row["family_id"],
            "contest_date": row["contest_date"], "interface": "FUNCTIONAL" if row["starter_code"] else "STDIN",
            "source_reference": source, "old_candidate_json_pointer": "/" + identity + "/code",
            "old_candidate_sha256": code_sha, "old_candidate_characters": len(code),
            "historical_reported_pass": True, "new_official_sample_reference": ref(sample_path)})
        print(json.dumps({"stage": "CONTROL_INPUT_VERIFIED", "question_id": identity}), flush=True)

    dataset_path = work / "official-controls.json.gz"
    write_new(dataset_path, gzip.compress(canonical({"schema": grader.SAMPLE_SCHEMA, "samples": samples}), mtime=0))
    enroll = list(CONTROL_CODES)
    runs = []
    for label, predictions in (("saved-positive", positive), ("invalid-syntax-negative", [
            {"question_id": identity, "output": "```python\ndef deliberately_invalid(\n```"} for identity in enroll])):
        prediction_path = work / (label + "-predictions.json")
        write_new(prediction_path, canonical({"schema": grader.PREDICTION_SCHEMA,
            "expected_question_ids": enroll, "predictions": predictions}))
        report_path = reports / (label + "-report.json")
        command = [sys.executable, str(repo / "scripts/trimem_lcb_grade.py"), "--predictions", str(prediction_path),
            "--dataset-json", str(dataset_path), "--dataset-sha256", file_hash(dataset_path),
            "--official-repo", args.official_repo, "--output", str(report_path), "--workers", "1", "--timeout", "6"]
        result = subprocess.run(command, capture_output=True, timeout=600)
        write_new(reports / (label + "-stdout.json"), result.stdout)
        write_new(reports / (label + "-stderr.txt"), result.stderr)
        if not report_path.is_file():
            raise RuntimeError("Control grader produced no report")
        report = json.loads(report_path.read_bytes())
        runs.append({"label": label, "returncode": result.returncode, "report_reference": ref(report_path),
            "status": report["status"], "counts": report["counts"], "timings": report["timings"],
            "results": [{key: value for key, value in row.items() if key in {"question_id", "status", "passed", "error_type", "extracted_code_sha256"}}
                for row in report["results"]]})
        print(json.dumps({"stage": "CONTROL_GRADED", "label": label, "counts": report["counts"]}), flush=True)
    passed = (all(run["returncode"] == 0 and run["status"] == "COMPLETE" and run["counts"]["infra_errors"] == 0 for run in runs)
        and runs[0]["counts"]["passed"] == 2 and runs[1]["counts"]["passed"] == 0)
    receipt = {"schema": "trimem/lcb-official-infrastructure-controls/1.0", "status": "PASS" if passed else "FAILED",
        "purpose": "OFFICIAL_TASK_INFRASTRUCTURE_CONTROL_NOT_MODEL_ACCURACY_OR_MEMORY_TRAINING",
        "split_reference": ref(split_path), "old_candidate_source_reference": ref(source_path),
        "control_driver_reference": ref(Path(__file__).resolve()), "grader_reference": ref(repo / "scripts/trimem_lcb_grade.py"),
        "official_commit": grader.UPSTREAM_COMMIT, "control_tasks": metadata,
        "exclude_from_all_model_training_and_memory_capture": exclusions,
        "pilot_changed": False, "model_calls": 0, "memory_writes": 0,
        "private_test_content_printed": False, "candidate_content_printed": False,
        "runs": runs, "overall_seconds": time.perf_counter() - started}
    write_new(reports / "control-receipt.json", canonical(receipt))
    print(json.dumps({"status": receipt["status"], "receipt_reference": ref(reports / "control-receipt.json")}), flush=True)
    return 0 if passed else 2


def main():
    parser = argparse.ArgumentParser()
    for key in ("repository", "data-root", "report-root", "work-root", "official-repo"):
        parser.add_argument("--" + key, required=True)
    try:
        return run(parser.parse_args())
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error_type": type(exc).__name__}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
