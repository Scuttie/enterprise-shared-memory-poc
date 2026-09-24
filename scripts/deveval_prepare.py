"""Pinned, metadata-only DevEval native preparation; never print task payloads.

This prepares infrastructure controls, not a model benchmark score. Selected
repositories/tasks must stay excluded from later evaluated target cohorts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import time
import urllib.request
import subprocess
import sys
import importlib.util
import xml.etree.ElementTree as ET
import re

GITHUB_COMMIT = "c1653455e0a18480a29aa07ba51636070f113316"
HF_COMMIT = "16ff740d87f5fa97567d6dffd4bcbf299231211c"
SOURCE_BYTES = 916746365
SOURCE_SHA256 = "c7e501a0a812197d227fee189740bc22a323011d2251e46d53e4bb854af4555f"
MIN_FREE_BYTES = 10 * 1024**3
SEED = "deveval-native-reference-controls-001"
PROJECTS = (
    "Communications/IMAPClient", "Internet/Jinja2",
    "Software-Development/Faker", "Text-Processing/mistune", "Utilities/PyJWT",
)
UPSTREAM_FILES = {
    "README.md": "33771d43b8f076d6293b37c0cec5de1f59d3d77aa285175f7c5dc5e0804df557",
    "pass_k.py": "8105684db06d24fa395b4e81a61e8e757e1c6e1502a18bacf27a45dfb15d0333",
    "utils.py": "398c7f05e26efd590b68af60dd35824be1a9470b58544a8b169d63ee9605c0f8",
    "check_source_code.py": "72a6809f4bd258958831966a2665a683124b73af17d4365d54140188a22891fd",
    "run_pass_k.sh": "dd0a4968047b42326f1cda639d95362e2c3d4b6f648215f9dd6d30eb7b461a52",
    "requirement.txt": "946c2a7f257ac2e0ace4c100b5b2843d5544604f3165130b41d47fbc8625f122",
    "environment.txt": "9eba42c5b08ba6d9795f5d6561bae384b6f00b4fa4b7677287e592b034c28ceb",
    "data.tar.gz": "eb516d7c3f3baeb4cc21514b793d7c847a9029f038132978a582998efc29af4e",
}


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def reference(path):
    p = Path(path).resolve()
    return {"path": str(p), "sha256": file_sha(p), "bytes": p.stat().st_size}


def write_new(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical(value)
    if p.exists():
        if p.read_bytes() != payload:
            raise ValueError("EXISTING_RECEIPT_DIFFERS")
        return
    with p.open("xb") as stream:
        stream.write(payload)


def download(url, destination, expected_sha, expected_bytes=None):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if file_sha(destination) != expected_sha:
            raise ValueError("EXISTING_DOWNLOAD_HASH_MISMATCH")
        return reference(destination)
    required = MIN_FREE_BYTES + (expected_bytes or 0)
    if shutil.disk_usage(destination.parent).free < required:
        raise ValueError("DISK_RESERVE")
    temporary = destination.with_suffix(destination.suffix + ".partial")
    if temporary.exists():
        raise ValueError("PARTIAL_DOWNLOAD_REQUIRES_EXPLICIT_RECOVERY")
    started, last, count = time.monotonic(), time.monotonic(), 0
    request = urllib.request.Request(url, headers={"User-Agent": "DevEval-native-preparation"})
    with urllib.request.urlopen(request, timeout=90) as response, temporary.open("xb") as stream:
        for block in iter(lambda: response.read(1024 * 1024), b""):
            stream.write(block)
            count += len(block)
            if expected_bytes is not None and count > expected_bytes:
                raise ValueError("DOWNLOAD_SIZE_EXCEEDED")
            if time.monotonic() - last > 20:
                print(json.dumps({"stage": "download", "bytes": count, "expected_bytes": expected_bytes}), flush=True)
                last = time.monotonic()
    if (expected_bytes is not None and count != expected_bytes) or file_sha(temporary) != expected_sha:
        raise ValueError("DOWNLOAD_INTEGRITY_MISMATCH")
    temporary.replace(destination)
    print(json.dumps({"stage": "download_complete", "bytes": count, "seconds": round(time.monotonic()-started, 3)}), flush=True)
    return reference(destination)


def safe_relative(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name or "\x00" in name:
        raise ValueError("UNSAFE_ARCHIVE_PATH")
    return p


def fetch_metadata(root):
    root = Path(root).resolve()
    upstream = root / "upstream"
    upstream.mkdir(parents=True, exist_ok=True)
    refs = {}
    for name, sha in UPSTREAM_FILES.items():
        refs[name] = download(f"https://raw.githubusercontent.com/seketeam/DevEval/{GITHUB_COMMIT}/{name}", upstream/name, sha)
    with tarfile.open(upstream/"data.tar.gz", "r:gz") as archive:
        members = archive.getmembers()
        if len(members) != 1 or members[0].name != "data.jsonl" or not members[0].isfile() or members[0].size > 10*1024**2:
            raise ValueError("UNEXPECTED_METADATA_ARCHIVE")
        payload = archive.extractfile(members[0]).read()
    data = upstream/"data.jsonl"
    if data.exists() and data.read_bytes() != payload:
        raise ValueError("METADATA_CHANGED")
    data.write_bytes(payload)
    rows = [json.loads(line) for line in payload.splitlines() if line.strip()]
    if len(rows) != 1825 or len({r["namespace"] for r in rows}) != len(rows):
        raise ValueError("METADATA_ENROLLMENT_MISMATCH")
    selected = select_controls(rows)
    selection = {"schema": "deveval-native-control-selection/1", "policy": "METADATA_ONLY_PRE_OUTCOME_TWO_PER_PREDECLARED_PORTABLE_PROJECT", "seed": SEED,
        "github_commit": GITHUB_COMMIT, "hf_commit": HF_COMMIT, "upstream_references": refs,
        "metadata_reference": reference(data), "total_tasks": len(rows), "total_projects": len({r["project_path"] for r in rows}),
        "task_count": len(selected), "projects": list(PROJECTS), "controls": [project_row(r) for r in selected],
        "target_evaluation_exclusion": "ALL_SELECTED_CONTROL_TASKS_AND_THEIR_REPOSITORIES",
        "model_calls": 0, "selection_used_outcomes": False,
        "license": {"dataset_card": "CC-BY-4.0", "github_repository_license_metadata": None, "upstream_project_licenses_require_separate_preservation": True}}
    write_new(root/"selection.json", selection)
    return selection


def select_controls(rows):
    selected = []
    for project in PROJECTS:
        eligible = [r for r in rows if r["project_path"] == project and r.get("dependency", {}).get("cross_file") and r.get("tests")]
        eligible.sort(key=lambda r: hashlib.sha256((SEED+"\0"+r["namespace"]).encode()).hexdigest())
        if len(eligible) < 2:
            raise ValueError("INSUFFICIENT_CROSS_FILE_CONTROL_TASKS")
        selected.extend(eligible[:2])
    return selected


def project_row(row):
    return {"task_id": row["namespace"], "project": row["project_path"], "task_sha256": hashlib.sha256(canonical(row)).hexdigest(),
        "type": row["type"], "declared_test_selectors": len(row["tests"]),
        "dependency_counts": {k: len(v) for k,v in row.get("dependency", {}).items()},
        "completion_path_sha256": hashlib.sha256(row["completion_path"].encode()).hexdigest()}


def fetch_source(root):
    root = Path(root).resolve()
    archive = root/"Source_Code.tar.gz"
    return download(f"https://huggingface.co/datasets/LJ0815/DevEval/resolve/{HF_COMMIT}/Source_Code.tar.gz", archive, SOURCE_SHA256, SOURCE_BYTES)


def extract_selected(root, destination):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    archive_path = root/"Source_Code.tar.gz"
    if file_sha(archive_path) != SOURCE_SHA256:
        raise ValueError("SOURCE_ARCHIVE_HASH_MISMATCH")
    selection = json.loads((root/"selection.json").read_text())
    if selection["projects"] != list(PROJECTS):
        raise ValueError("SELECTION_PROJECT_MISMATCH")
    if destination.exists():
        raise ValueError("EXTRACTION_DESTINATION_MUST_BE_FRESH")
    destination.mkdir(parents=True)
    prefixes = tuple("Source_Code/"+p+"/" for p in PROJECTS)
    rows, total, count, unsafe = [], 0, 0, []
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            if not member.name.startswith(prefixes):
                continue
            rel = safe_relative(member.name)
            target = destination.joinpath(*rel.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                unsafe.append({"path": member.name, "kind": member.type.decode("ascii", errors="replace")})
                continue
            total += member.size
            if total > 2*1024**3 or shutil.disk_usage(destination).free < MIN_FREE_BYTES + member.size:
                raise ValueError("EXTRACTION_DISK_RESERVE")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                shutil.copyfileobj(archive.extractfile(member), stream)
            target.chmod(member.mode & 0o777)
            rows.append({"path": member.name, "bytes": member.size, "sha256": file_sha(target)})
            count += 1
    if unsafe:
        raise ValueError("SELECTED_ARCHIVE_CONTAINS_LINK_OR_SPECIAL_ENTRY")
    if not all((destination/"Source_Code"/p/"setup.py").is_file() for p in PROJECTS):
        raise ValueError("MISSING_PROJECT_SETUP")
    receipt = {"schema": "deveval-selected-source-extraction/1", "archive_reference": reference(archive_path),
        "selection_reference": reference(root/"selection.json"), "destination": str(destination), "file_count": count,
        "file_bytes": total, "files": rows, "links_extracted": 0}
    write_new(root/"extraction.json", receipt)
    return {k:v for k,v in receipt.items() if k != "files"}


NEGATIVE_MARKER = "DEV_EVAL_NATIVE_NEGATIVE_CONTROL"


def xml_counts(path):
    """Return counts only; failure bodies and testcase names remain private."""
    if not Path(path).is_file():
        return {"available": False, "tests": None, "failures": None, "errors": None, "skipped": None, "negative_marker_seen": False,
            "confirmed_negative_failure_nodes": 0, "confirmed_negative_error_nodes": 0, "unconfirmed_error_nodes": 0}
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    pattern = re.compile(r"(?m)^\s*(?:E\s+)?AssertionError:\s*" + re.escape(NEGATIVE_MARKER) + r"\s*$")
    failures, errors = list(root.iter("failure")), list(root.iter("error"))
    confirmed_failures = sum(bool(pattern.search("".join(n.itertext()))) for n in failures)
    confirmed_errors = sum(bool(pattern.search("".join(n.itertext()))) for n in errors)
    return {"available": True, **{key: sum(int(s.attrib.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors", "skipped")},
        "negative_marker_seen": confirmed_failures + confirmed_errors > 0,
        "confirmed_negative_failure_nodes": confirmed_failures, "confirmed_negative_error_nodes": confirmed_errors,
        "unconfirmed_error_nodes": len(errors)-confirmed_errors}


def is_generated_build_metadata(path):
    parts = PurePosixPath(path).parts
    return ".pytest_cache" in parts or any(part.endswith(".egg-info") for part in parts)


def control_worker(request_path):
    """Private subprocess entry: exact pinned evaluator, opaque request/log files."""
    request = json.loads(Path(request_path).read_text())
    evaluator = Path(request["evaluator"])
    if file_sha(evaluator) != UPSTREAM_FILES["pass_k.py"]:
        raise ValueError("EVALUATOR_HASH_MISMATCH")
    spec = importlib.util.spec_from_file_location("deveval_pinned_pass_k", evaluator)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    row = request["task"]
    source = Path(request["source_root"])
    target = source.joinpath(*safe_relative(row["completion_path"]).parts)
    before = file_sha(target)
    args = argparse.Namespace(source_code_root=source)
    started = time.monotonic()
    try:
        if request["arm"] == "reference":
            result = module.execution_tests(args, row)
        elif request["arm"] == "assertion_negative":
            row = dict(row, completion=f'raise AssertionError("{NEGATIVE_MARKER}")\n')
            result = module.check_correctness(args, row)
        else:
            raise ValueError("UNKNOWN_CONTROL_ARM")
        error_type = None
    except BaseException as error:
        result, error_type = "InfrastructureException", type(error).__name__
    after = file_sha(target)
    receipt = {"schema": "deveval-native-control-cell/1", "task_id": row["namespace"], "project": row["project_path"],
        "arm": request["arm"], "official_result": result, "exception_type": error_type,
        "elapsed_seconds": time.monotonic()-started, "source_file_before_sha256": before, "source_file_after_sha256": after,
        "source_restored": before == after, "junit": xml_counts(request["junit"]), "test_selector_count": len(row["tests"]),
        "evaluator_reference": reference(evaluator), "request_reference": reference(request_path)}
    write_new(request["receipt"], receipt)
    return receipt


def preflight(root, pristine, run_root):
    """Execute no models. The native environment must already have dependencies."""
    root, pristine, run_root = Path(root).resolve(), Path(pristine).resolve(), Path(run_root).resolve()
    if sys.version_info[:3] != (3, 9, 18):
        raise ValueError("PYTHON_VERSION_MISMATCH")
    selection = json.loads((root/"selection.json").read_text())
    metadata = root/"upstream/data.jsonl"
    if file_sha(metadata) != selection["metadata_reference"]["sha256"]:
        raise ValueError("METADATA_CHANGED")
    rows = [json.loads(line) for line in metadata.read_bytes().splitlines() if line.strip()]
    tasks = select_controls(rows)
    if [project_row(r) for r in tasks] != selection["controls"]:
        raise ValueError("CONTROL_SELECTION_CHANGED")
    extracted = json.loads((root/"extraction.json").read_text())
    for item in extracted["files"]:
        if file_sha(pristine.joinpath(*safe_relative(item["path"]).parts)) != item["sha256"]:
            raise ValueError("PRISTINE_SOURCE_CHANGED")
    if run_root.exists():
        raise ValueError("CONTROL_RUN_MUST_BE_FRESH")
    run_root.mkdir(parents=True)
    source = run_root/"Source_Code"
    shutil.copytree(pristine/"Source_Code", source)
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["NLTK_DATA"] = str(run_root/"nltk_data")
    receipts = []
    for index, task in enumerate(tasks):
        for arm in ("reference", "assertion_negative"):
            cell = run_root/f"{index+1:02d}-{arm}"
            cell.mkdir()
            request = {"evaluator": str(root/"upstream/pass_k.py"), "task": task, "arm": arm,
                "source_root": str(source), "junit": str(cell/"junit.xml"), "receipt": str(cell/"receipt.json")}
            write_new(cell/"request.json", request)
            cell_env = dict(env, PYTEST_ADDOPTS="--junitxml="+str(cell/"junit.xml"))
            command = [sys.executable, "-B", str(Path(__file__).resolve()), "--worker-request", str(cell/"request.json")]
            started = time.monotonic()
            with (cell/"stdout.log").open("xb") as stdout, (cell/"stderr.log").open("xb") as stderr:
                process = subprocess.Popen(command, cwd=cell, env=cell_env, stdout=stdout, stderr=stderr, start_new_session=True)
                try:
                    returncode = process.wait(timeout=85)
                except subprocess.TimeoutExpired:
                    import signal
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    returncode = -9
            if (cell/"receipt.json").is_file():
                result = json.loads((cell/"receipt.json").read_text())
                result["receipt_reference"] = reference(cell/"receipt.json")
            else:
                result = {"task_id": task["namespace"], "project": task["project_path"], "arm": arm, "official_result": "InfrastructureException", "source_restored": False}
            result.update({"worker_returncode": returncode, "worker_wall_seconds": time.monotonic()-started,
                "stdout_reference": reference(cell/"stdout.log"), "stderr_reference": reference(cell/"stderr.log")})
            receipts.append(result)
            print(json.dumps({"stage": "control", "ordinal": index+1, "arm": arm, "official_result": result["official_result"], "restored": result["source_restored"]}), flush=True)
            if not result["source_restored"]:
                raise ValueError("CONTROL_SOURCE_RESTORE_FAILED")
    pristine_changes, working_changes, generated_changes = [], [], []
    for item in extracted["files"]:
        original = pristine.joinpath(*safe_relative(item["path"]).parts)
        current = run_root.joinpath(*safe_relative(item["path"]).parts)
        if file_sha(original) != item["sha256"]:
            pristine_changes.append(item["path"])
        if file_sha(current) != item["sha256"]:
            (generated_changes if is_generated_build_metadata(item["path"]) else working_changes).append(item["path"])
    positives = [r for r in receipts if r["arm"] == "reference"]
    negatives = [r for r in receipts if r["arm"] == "assertion_negative"]
    positive_pass = sum(r["official_result"] == "Pass" for r in positives)
    negative_confirmed = sum(r["official_result"] == "Error" and r["junit"]["negative_marker_seen"] and r["junit"]["unconfirmed_error_nodes"] == 0 for r in negatives)
    summary = {"schema": "deveval-native-preflight/1", "status": "PASS" if positive_pass == 10 and negative_confirmed == 10 and not pristine_changes and not working_changes else "INCOMPLETE_OR_FAILED_CONTROLS",
        "selection_reference": reference(root/"selection.json"), "extraction_reference": reference(root/"extraction.json"),
        "helper_reference": reference(__file__), "python": sys.version, "python_executable": sys.executable,
        "reference_pass": positive_pass, "reference_total": len(positives), "negative_confirmed_assertion_failures": negative_confirmed,
        "negative_total": len(negatives), "pristine_archive_files_unchanged": not pristine_changes,
        "working_source_and_tests_unchanged": not working_changes, "working_non_generated_files_changed_count": len(working_changes),
        "working_generated_metadata_changed_count": len(generated_changes), "working_generated_metadata_changed_paths": generated_changes,
        "model_calls": 0, "docker_calls": 0, "privilege_escalations": 0, "cells": receipts,
        "limitations": ["Infrastructure control cohort selected for five portable repositories; not representative benchmark accuracy.", "Official evaluator's Error is coarse; a negative requires exact AssertionError marker. The same deliberate assertion in a test fixture can be reported by JUnit as error rather than failure; unrelated errors are not accepted.", "Generated pytest cache and egg-info metadata changes are recorded separately; pristine files and non-generated working source/tests are hash-checked.", "PYTEST_ADDOPTS adds JUnit output; official evaluator and test selectors unchanged.", "Native same-user execution is not an untrusted-code security sandbox.", "Dependency recall@k archive/parser has not been provisioned."]}
    write_new(run_root/"preflight.json", summary)
    return {k:v for k,v in summary.items() if k != "cells"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path)
    p.add_argument("--fetch-source", action="store_true")
    p.add_argument("--extract-to", type=Path)
    p.add_argument("--preflight-pristine", type=Path)
    p.add_argument("--preflight-run", type=Path)
    p.add_argument("--worker-request", type=Path)
    args = p.parse_args()
    if args.worker_request:
        control_worker(args.worker_request)
        return
    if args.root is None:
        p.error("--root is required")
    if args.preflight_run:
        if not args.preflight_pristine:
            p.error("--preflight-pristine is required")
        print(json.dumps(preflight(args.root, args.preflight_pristine, args.preflight_run)), flush=True)
        return
    selection = fetch_metadata(args.root)
    print(json.dumps({"stage": "metadata_ready", "tasks": selection["total_tasks"], "controls": selection["task_count"], "projects": selection["projects"]}), flush=True)
    if args.fetch_source:
        print(json.dumps(fetch_source(args.root)), flush=True)
    if args.extract_to:
        print(json.dumps(extract_selected(args.root, args.extract_to)), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "ERROR", "exception_type": type(error).__name__}), flush=True)
        raise SystemExit(1)
