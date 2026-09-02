"""Build and validate the one-time branch-push request for the Vue image probe.

GitHub does not dispatch a new workflow that is absent from the default branch.
The probe therefore uses one unique, non-merge commit on the research branch.
That commit may add only the canonical request below.  The request is bound to
its sole parent (the fully checked correction HEAD), and rerun attempts fail
closed before Docker is reached.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from trimem_multi_swe_image_probe import (
    BENCHMARK_ID,
    EXPECTED_BASE_COMMIT,
    EXPECTED_IMAGE,
    EXPECTED_TAG,
    INSTANCE_ID,
    REPOSITORY,
)


EXPECTED_EVENT = "push"
EXPECTED_REF = "refs/heads/codex/trimem-coder-v1"
EXPECTED_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
REQUEST_PATH = (
    "artifacts/trimem_v1/probe_requests/"
    "MULTI_SWE_VUE_IMAGE_PROBE_REQUEST_001.json"
)
REQUEST_ID = "TRIMEM_MULTI_SWE_VUE_IMAGE_PROBE_EXEC_001"
REQUEST_SCHEMA = "trimem/multi-swe-vue-image-probe-request/1.0"
EXPECTED_PHASE = "MULTI_SWE_PREBUILT_IMAGE_CONTRACT_PROBE"
WORKFLOW_PATH = ".github/workflows/ci-trimem-multi-swe-contract.yml"
PREFLIGHT_PATH = "scripts/trimem_multi_swe_probe_request.py"
PROBE_PATH = "scripts/trimem_multi_swe_image_probe.py"
FREEZE_PATH = "artifacts/trimem_v1/freeze.json"
MANIFEST_PATH = "configs/trimem_v1/grader_smoke_manifest.json"
IMAGE_LOCK_PATH = "artifacts/trimem_v1/grader_image_lock.json"
TARGET_SET_SHA256 = "01f9e41f1ce3f285c651c3bc857a1f7422ed7e0f9ccfb451b42aedf9a4aef52e"
EXPECTED_DIGEST = EXPECTED_IMAGE.rsplit("@", 1)[1]
TARGET_IDS = (
    "multi_swe_bench_mini--vuejs__core-8911--gold",
    "multi_swe_bench_mini--vuejs__core-8911--noop-baseline",
)
EXECUTION_SCOPE = (
    "One credential-free metadata-only Vue image probe; no grading, patch "
    "application, official tests, model/API calls, DEV, or HELDOUT."
)
HARD_CAPS = {
    "api_calls": 0,
    "grader_containers": 0,
    "grader_executions": 0,
    "image_contract_probe_containers": 1,
    "image_pulls": 1,
    "input_tokens": 0,
    "model_calls": 0,
    "official_tests": 0,
    "output_tokens": 0,
    "paid_model_calls": 0,
    "patch_applications": 0,
    "task_arm_runs": 0,
    "total_usd": 0.0,
}
MATERIAL_PATHS = (
    FREEZE_PATH,
    MANIFEST_PATH,
    IMAGE_LOCK_PATH,
    WORKFLOW_PATH,
    PREFLIGHT_PATH,
    PROBE_PATH,
)
FORBIDDEN_SECRET_NAMES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "GOOGLE_API_KEY",
        "MODEL_API_KEY",
        "OPENAI_API_KEY",
        "UPSTAGE_API_KEY",
    }
)
HEX40 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


class ProbeRequestError(ValueError):
    """The prospective request or one-time push contract differed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeRequestError(message)


def _reject_constant(value: str) -> None:
    raise ProbeRequestError(f"non-finite JSON number is forbidden: {value}")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ProbeRequestError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def strict_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeRequestError(f"{label} is not strict UTF-8 JSON") from exc
    _require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def canonical_bytes(value: Any, *, trailing_lf: bool = False) -> bytes:
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProbeRequestError("probe request is not canonical JSON") from exc
    return raw + (b"\n" if trailing_lf else b"")


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _run_git(repository: Path, *args: str, text: bool = True) -> str | bytes:
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=repository,
            capture_output=True,
            text=text,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProbeRequestError("git verification could not complete") from exc
    if result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        raise ProbeRequestError("git verification failed: " + stderr.strip())
    return result.stdout


def _commit_bytes(repository: Path, commit: str, path: str) -> bytes:
    raw = _run_git(repository, "show", f"{commit}:{path}", text=False)
    assert isinstance(raw, bytes)
    return raw


def _material(repository: Path, commit: str) -> dict[str, bytes]:
    kind = str(_run_git(repository, "cat-file", "-t", commit)).strip()
    _require(kind == "commit", "correction_head is not a Git commit")
    return {path: _commit_bytes(repository, commit, path) for path in MATERIAL_PATHS}


def _expected_vue_rows() -> list[dict[str, Any]]:
    common = {
        "base_commit": EXPECTED_BASE_COMMIT,
        "benchmark_id": BENCHMARK_ID,
        "dataset_revision": "d0fab3ccc7dff232fcaac234cf8af9a2efeaccf6",
        "instance_id": INSTANCE_ID,
        "language": "typescript",
        "repository": REPOSITORY,
        "source_row_sha256": (
            "d6e0f336551a9b39f5227561ef1a04b079b276d325e228df2e4492d08166d439"
        ),
    }
    return [
        {
            **common,
            "expected_resolved": True,
            "order_index": 4,
            "probe": "GOLD",
            "target_id": TARGET_IDS[0],
        },
        {
            **common,
            "expected_resolved": False,
            "order_index": 5,
            "probe": "NOOP_BASELINE",
            "target_id": TARGET_IDS[1],
        },
    ]


def _validate_frozen_target(raw: Mapping[str, bytes]) -> None:
    manifest = strict_json_object(raw[MANIFEST_PATH], label=MANIFEST_PATH)
    _require(
        manifest.get("schema") == "trimem/grader-smoke-manifest/1.0",
        "grader-smoke manifest schema differs",
    )
    _require(
        manifest.get("target_set_sha256") == TARGET_SET_SHA256,
        "frozen target-set identity differs",
    )
    targets = manifest.get("targets")
    _require(isinstance(targets, list), "grader-smoke manifest targets are missing")
    vue_rows = [
        row
        for row in targets
        if isinstance(row, dict)
        and row.get("benchmark_id") == BENCHMARK_ID
        and row.get("instance_id") == INSTANCE_ID
    ]
    _require(vue_rows == _expected_vue_rows(), "exact frozen Vue GOLD/NOOP rows differ")

    image_lock = strict_json_object(raw[IMAGE_LOCK_PATH], label=IMAGE_LOCK_PATH)
    _require(
        image_lock.get("schema") == "trimem/grader-image-lock/1.2"
        and image_lock.get("status") == "FROZEN",
        "grader image lock is not frozen",
    )
    locked = image_lock.get("targets")
    rows = [
        row
        for row in locked
        if isinstance(row, dict)
        and row.get("benchmark_id") == BENCHMARK_ID
        and row.get("instance_id") == INSTANCE_ID
    ] if isinstance(locked, list) else []
    _require(len(rows) == 1, "exact frozen Vue image row is missing or duplicated")
    row = rows[0]
    _require(
        row.get("image") == EXPECTED_IMAGE
        and row.get("expected_digest") == EXPECTED_DIGEST
        and row.get("harness_image_tag") == EXPECTED_TAG
        and row.get("target_ids") == list(TARGET_IDS),
        "exact frozen Vue digest/tag/target binding differs",
    )

    freeze = strict_json_object(raw[FREEZE_PATH], label=FREEZE_PATH)
    _require(freeze.get("schema") == "trimem/freeze/1.0", "freeze schema differs")
    files = freeze.get("files")
    _require(isinstance(files, dict), "freeze inventory is missing")
    for path in MATERIAL_PATHS:
        if path == FREEZE_PATH:
            continue
        committed = raw[path]
        _require(
            files.get(path)
            == {
                "bytes": len(committed),
                "sha256": hashlib.sha256(committed).hexdigest(),
            },
            f"freeze closure mismatch for {path}",
        )


def build_request_document(repository: Path, *, correction_head: str) -> dict[str, Any]:
    """Build the one valid request for an already committed correction HEAD."""

    _require(HEX40.fullmatch(correction_head) is not None, "correction_head is invalid")
    raw = _material(repository, correction_head)
    _validate_frozen_target(raw)
    payload: dict[str, Any] = {
        "actual_execution_authorized": True,
        "bindings": {
            "freeze_sha256": _sha256(raw[FREEZE_PATH]),
            "grader_image_lock_sha256": _sha256(raw[IMAGE_LOCK_PATH]),
            "grader_smoke_manifest_sha256": _sha256(raw[MANIFEST_PATH]),
            "preflight_sha256": _sha256(raw[PREFLIGHT_PATH]),
            "probe_sha256": _sha256(raw[PROBE_PATH]),
            "target_set_sha256": TARGET_SET_SHA256,
            "workflow_sha256": _sha256(raw[WORKFLOW_PATH]),
        },
        "branch_ref": EXPECTED_REF,
        "correction_head": correction_head,
        "execution_scope": EXECUTION_SCOPE,
        "external_approval_required": False,
        "frozen_target": {
            "base_commit": EXPECTED_BASE_COMMIT,
            "benchmark_id": BENCHMARK_ID,
            "expected_digest": EXPECTED_DIGEST,
            "harness_image_tag": EXPECTED_TAG,
            "image": EXPECTED_IMAGE,
            "instance_id": INSTANCE_ID,
            "repository": REPOSITORY,
            "target_ids": list(TARGET_IDS),
        },
        "hard_caps": dict(HARD_CAPS),
        "model_secret_required": False,
        "one_time": True,
        "phase": EXPECTED_PHASE,
        "repository": EXPECTED_REPOSITORY,
        "request_id": REQUEST_ID,
        "request_path": REQUEST_PATH,
        "schema": REQUEST_SCHEMA,
        "workflow_path": WORKFLOW_PATH,
    }
    return {
        **payload,
        "request_sha256": _sha256(canonical_bytes(payload)),
    }


def validate_request_document(
    repository: Path,
    raw: bytes,
    *,
    expected_correction_head: str,
) -> dict[str, Any]:
    value = strict_json_object(raw, label="Vue image probe request")
    expected = build_request_document(
        repository,
        correction_head=expected_correction_head,
    )
    _require(
        isinstance(value.get("request_sha256"), str)
        and SHA256.fullmatch(value["request_sha256"]) is not None,
        "probe request hash is invalid",
    )
    _require(value == expected, "probe request content differs")
    _require(
        raw == canonical_bytes(expected, trailing_lf=True),
        "probe request bytes are not canonical LF JSON",
    )
    return value


def _validate_event(
    event: Mapping[str, Any], environ: Mapping[str, str]
) -> tuple[str, str]:
    _require(environ.get("GITHUB_EVENT_NAME") == EXPECTED_EVENT, "event is not push")
    _require(environ.get("GITHUB_RUN_ATTEMPT") == "1", "probe rerun attempt is forbidden")
    _require(environ.get("GITHUB_REF") == EXPECTED_REF, "GITHUB_REF differs")
    _require(environ.get("GITHUB_REPOSITORY") == EXPECTED_REPOSITORY, "repository differs")
    _require(event.get("ref") == EXPECTED_REF, "push ref differs")
    _require(event.get("created") is False, "branch-creation push is forbidden")
    _require(event.get("deleted") is False, "branch-deletion push is forbidden")
    _require(event.get("forced") is False, "forced push is forbidden")
    before, after = event.get("before"), event.get("after")
    _require(
        isinstance(before, str) and HEX40.fullmatch(before) is not None,
        "before SHA is invalid",
    )
    _require(
        isinstance(after, str) and HEX40.fullmatch(after) is not None,
        "after SHA is invalid",
    )
    _require(before != after, "before and after SHAs must differ")
    _require(environ.get("GITHUB_SHA") == after, "GITHUB_SHA differs from push after")
    _require(
        event.get("size") == 1 and event.get("distinct_size") == 1,
        "push must contain one commit",
    )
    head = event.get("head_commit")
    _require(isinstance(head, dict) and head.get("id") == after, "head_commit differs")
    _require(head.get("added") == [REQUEST_PATH], "head_commit must add only the probe request")
    _require(
        head.get("modified") == [] and head.get("removed") == [],
        "head_commit changed another path",
    )
    commits = event.get("commits")
    _require(isinstance(commits, list) and len(commits) == 1, "push commit list differs")
    _require(
        isinstance(commits[0], dict)
        and commits[0].get("id") == after
        and commits[0].get("added") == [REQUEST_PATH]
        and commits[0].get("modified") == []
        and commits[0].get("removed") == [],
        "push commit payload is not marker-only",
    )
    return before, after


def _validate_marker_commit(repository: Path, before: str, after: str) -> bytes:
    top = str(_run_git(repository, "rev-parse", "--show-toplevel")).strip()
    _require(Path(top).resolve() == repository.resolve(), "repository is not the Git top level")
    head = str(_run_git(repository, "rev-parse", "HEAD")).strip()
    _require(head == after, "checked-out HEAD differs from push after")
    parents = str(_run_git(repository, "rev-list", "--parents", "-n", "1", after)).strip().split()
    _require(
        parents == [after, before],
        "probe trigger must be one non-merge child of correction HEAD",
    )
    changes = str(
        _run_git(
            repository,
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "--no-renames",
            after,
        )
    ).splitlines()
    _require(changes == [f"A\t{REQUEST_PATH}"], "probe trigger commit must add only the request")
    history = str(_run_git(repository, "log", "--format=%H", before, "--", REQUEST_PATH)).strip()
    _require(not history, "probe request path already exists in branch history")
    tree = str(_run_git(repository, "ls-tree", after, "--", REQUEST_PATH)).strip()
    _require(
        re.fullmatch(rf"100644 blob [0-9a-f]{{40}}\t{re.escape(REQUEST_PATH)}", tree)
        is not None,
        "probe request must be a regular non-executable Git blob",
    )
    return _commit_bytes(repository, after, REQUEST_PATH)


def _validate_zero_secret_surface(
    repository: Path, commit: str, environ: Mapping[str, str]
) -> None:
    exposed = sorted(name for name in FORBIDDEN_SECRET_NAMES if name in environ)
    _require(not exposed, f"forbidden model/API secret is exposed: {exposed}")
    workflow = _commit_bytes(repository, commit, WORKFLOW_PATH).decode("utf-8")
    _require("secrets." not in workflow, "probe workflow references a secret")
    forbidden = sorted(name for name in FORBIDDEN_SECRET_NAMES if name in workflow)
    _require(not forbidden, f"probe workflow contains forbidden secret names: {forbidden}")
    _require("trimem_grader_smoke.py" not in workflow, "probe workflow references the grader")


def validate_branch_trigger(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    event = strict_json_object(event_path.resolve(strict=True).read_bytes(), label="push event")
    environment = os.environ if environ is None else environ
    before, after = _validate_event(event, environment)
    request_raw = _validate_marker_commit(repository, before, after)
    _validate_zero_secret_surface(repository, after, environment)
    request = validate_request_document(
        repository,
        request_raw,
        expected_correction_head=before,
    )
    return {
        "api_calls": 0,
        "correction_head": before,
        "grader_executions": 0,
        "image_contract_probe_containers": 1,
        "model_calls": 0,
        "official_tests": 0,
        "patch_applications": 0,
        "request_id": REQUEST_ID,
        "request_sha256": request["request_sha256"],
        "status": "PASS",
        "trigger_commit": after,
    }


def write_request(repository: Path) -> dict[str, Any]:
    """Exclusively create the request from one clean, committed correction HEAD."""

    repository = repository.resolve(strict=True)
    top = str(_run_git(repository, "rev-parse", "--show-toplevel")).strip()
    _require(Path(top).resolve() == repository, "repository is not the Git top level")
    ref = str(_run_git(repository, "symbolic-ref", "--quiet", "HEAD")).strip()
    _require(ref == EXPECTED_REF, "probe request may be written only on the research branch")
    head = str(_run_git(repository, "rev-parse", "HEAD")).strip()
    _require(HEX40.fullmatch(head) is not None, "repository HEAD is not a commit SHA")
    status = str(
        _run_git(repository, "status", "--porcelain=v1", "--untracked-files=all")
    )
    _require(not status, "probe request rendering requires a clean worktree")
    history = str(_run_git(repository, "log", "--format=%H", "HEAD", "--", REQUEST_PATH)).strip()
    _require(not history, "probe request path already exists in branch history")
    target = repository / REQUEST_PATH
    _require(not target.exists() and not target.is_symlink(), "probe request path already exists")
    document = build_request_document(repository, correction_head=head)
    raw = canonical_bytes(document, trailing_lf=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ProbeRequestError("refusing to overwrite the probe request") from exc
    return {
        "bytes": len(raw),
        "correction_head": head,
        "path": REQUEST_PATH,
        "request_id": REQUEST_ID,
        "request_sha256": document["request_sha256"],
        "status": "WROTE_ONE_TIME_PROBE_REQUEST",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--event-path", type=Path)
    mode.add_argument("--write-request", action="store_true")
    args = parser.parse_args()
    try:
        if args.write_request:
            report = write_request(args.repository)
        else:
            assert args.event_path is not None
            report = validate_branch_trigger(args.repository, args.event_path)
    except (OSError, ProbeRequestError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL_CLOSED"}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
