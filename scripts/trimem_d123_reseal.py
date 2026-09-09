"""Build and verify the credential-free D1.23 EXEC-022 activation seal.

D1.23 turns the already verified D1.22 recovery into *request-creation*
readiness.  This module seals source files and the immutable exact-head CI
receipt only.  It never creates the ``_022`` sentinel, grants execution
authority, reads credentials, pulls an image, starts a runner/container, calls
a model/API, runs a grader, or mutates Git/GitHub state.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

import trimem_development_trigger_d122 as d122
import trimem_development_trigger_d123 as d123


ROOT = Path(__file__).resolve().parents[1]

D122_BASELINE_HEAD = "cfa79b2406f174bd152eb873e98018725947d349"
EXPECTED_AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_exec_022_activation_amendment.json"
)
EXPECTED_INVENTORY_PATH = (
    "artifacts/trimem_v1/development_exec_022_activation_inventory.json"
)
EXPECTED_REPORT_PATH = "reports/TRIMEM_D123_EXEC_022_ACTIVATION.md"
EXPECTED_EVIDENCE_PATH = (
    "tests/fixtures/trimem_d123/d122_remote_ci_evidence.json"
)
EXPECTED_EVIDENCE_BYTES = 2_090
EXPECTED_EVIDENCE_SHA256 = (
    "0abfc20181ca47e4ada3e1bb847ff91347d1f8d99844157cbb2e5e7e623b9e6a"
)
EXPECTED_STATUS = "READY_FOR_EXEC_022_REQUEST"
EXPECTED_ENDPOINT = "TRIMEM_V1_READY_FOR_EXEC_022_REQUEST"

AMENDMENT_PATH = ROOT.joinpath(*PurePosixPath(EXPECTED_AMENDMENT_PATH).parts)
INVENTORY_PATH = ROOT.joinpath(*PurePosixPath(EXPECTED_INVENTORY_PATH).parts)
EVIDENCE_PATH = ROOT.joinpath(*PurePosixPath(EXPECTED_EVIDENCE_PATH).parts)
FREEZE_PATH = ROOT.joinpath(*PurePosixPath(d123.FREEZE_PATH).parts)


class D123ResealError(ValueError):
    """The D1.22 baseline, CI evidence, source scope, or authority seal differs."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise D123ResealError(message)


def canonical_bytes(value: Any) -> bytes:
    """Return the only accepted representation for generated D1.23 JSON."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _relative_path(value: str) -> Path:
    pure = PurePosixPath(value)
    require(
        not pure.is_absolute()
        and ".." not in pure.parts
        and bool(pure.parts),
        f"unsafe repository path: {value}",
    )
    return ROOT.joinpath(*pure.parts)


def _working_bytes(relative: str) -> bytes:
    path = _relative_path(relative)
    require(path.is_file() and not path.is_symlink(), f"file is absent: {relative}")
    return path.read_bytes()


def _git(*args: str, text: bool = False) -> subprocess.CompletedProcess[Any]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=text,
        )
    except subprocess.CalledProcessError as exc:
        raise D123ResealError("Git command failed") from exc


def _git_text(*args: str) -> str:
    raw = _git(*args).stdout
    try:
        return raw.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise D123ResealError("Git returned non-UTF-8 text") from exc


def _git_lines(*args: str) -> list[str]:
    value = _git_text(*args)
    return [] if not value else value.splitlines()


def _commit_bytes(commit: str, relative: str) -> bytes:
    return _git("cat-file", "blob", f"{commit}:{relative}").stdout


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise D123ResealError(f"non-finite JSON constant: {value}")


def _strict_json(raw: bytes, *, label: str) -> dict[str, Any]:
    require(
        not raw.startswith(b"\xef\xbb\xbf")
        and b"\x00" not in raw
        and b"\r" not in raw,
        f"noncanonical JSON encoding: {label}",
    )
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D123ResealError(f"invalid JSON: {label}") from exc
    require(isinstance(value, dict), f"JSON document is not an object: {label}")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"file is absent: {path}")
    return _strict_json(path.read_bytes(), label=str(path))


def _validate_trigger_constants() -> None:
    expected: dict[str, Any] = {
        "AMENDMENT_PATH": EXPECTED_AMENDMENT_PATH,
        "BASELINE_SOURCE_HEAD": D122_BASELINE_HEAD,
        "INVENTORY_PATH": EXPECTED_INVENTORY_PATH,
        "REMOTE_CI_EVIDENCE_PATH": EXPECTED_EVIDENCE_PATH,
        "REPORT_PATH": EXPECTED_REPORT_PATH,
        "SENTINEL_PATH": (
            "artifacts/trimem_v1/exec_requests/"
            "DEVELOPMENT_TUNING_EXEC_REQUEST_022.json"
        ),
    }
    for name, value in expected.items():
        require(getattr(d123, name, None) == value, f"D1.23 constant differs: {name}")
    require(
        getattr(d123, "AMENDMENT_STATUS", None) == EXPECTED_STATUS,
        "D1.23 status is not READY_FOR_EXEC_022_REQUEST",
    )
    require(
        getattr(d123, "AMENDMENT_ENDPOINT", None) == EXPECTED_ENDPOINT,
        "D1.23 endpoint differs",
    )
    require(
        getattr(d123, "REMOTE_CI_EVIDENCE_BYTES", None)
        == EXPECTED_EVIDENCE_BYTES
        and getattr(d123, "REMOTE_CI_EVIDENCE_SHA256", None)
        == EXPECTED_EVIDENCE_SHA256,
        "D1.23 evidence identity constants differ",
    )


def validate_d122_baseline() -> dict[str, Any]:
    """Validate the cryptographically exact D1.22 source commit and its seal."""

    _validate_trigger_constants()
    require(
        _git_text("rev-parse", f"{D122_BASELINE_HEAD}^{{commit}}")
        == D122_BASELINE_HEAD,
        "immutable D1.22 baseline commit is unavailable",
    )
    head = _git_text("rev-parse", "HEAD")
    require(
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", D122_BASELINE_HEAD, head],
            cwd=ROOT,
            check=False,
            capture_output=True,
        ).returncode
        == 0,
        "current source does not descend from immutable D1.22 baseline",
    )
    # Validate the D1.22 source directly at the immutable commit.  Do not call
    # ``validate_recovery_source`` here: its historical no-``_022`` guard also
    # inspects the checkout and would incorrectly reject a later, exact
    # sentinel-only child accepted by D1.23 check mode.
    d122.validate_previous_request(ROOT)
    d122.validate_failure_fixture(ROOT)
    changes = d122._validate_recovery_diff(ROOT, D122_BASELINE_HEAD)
    d122._validate_preserved_science(ROOT, D122_BASELINE_HEAD)
    d122._validate_documents(ROOT, D122_BASELINE_HEAD)
    qdrant = d122.validate_qdrant_source_contract()
    baseline = {
        "changed_paths": changes,
        "current_execution_actuals": dict(d122.ZERO_CURRENT_EXECUTION_ACTUALS),
        "endpoint": d122.AMENDMENT_ENDPOINT,
        "historical_execution_actuals": deepcopy(
            d122.HISTORICAL_EXECUTION_ACTUALS
        ),
        "qdrant_nofile_contract": qdrant,
        "request_021_attempt_one_consumed": True,
        "request_021_rerun_allowed": False,
        "request_022_creation_authorized": False,
        "request_022_execution_authorized": False,
        "source_head": D122_BASELINE_HEAD,
        "status": "PASS",
    }
    require(
        baseline.get("status") == "PASS"
        and baseline.get("source_head") == D122_BASELINE_HEAD
        and baseline.get("endpoint") == d122.AMENDMENT_ENDPOINT
        and baseline.get("request_021_attempt_one_consumed") is True
        and baseline.get("request_021_rerun_allowed") is False
        and baseline.get("request_022_creation_authorized") is False
        and baseline.get("request_022_execution_authorized") is False,
        "immutable D1.22 recovery seal differs",
    )
    frozen_paths = (
        d122.AMENDMENT_PATH,
        d122.INVENTORY_PATH,
        d122.FAILURE_FIXTURE_PATH,
        d122.REPORT_PATH,
        d122.RESEAL_PATH,
        d122.TRIGGER_PATH,
        d122.QDRANT_REHEARSAL_PATH,
        d122.FREEZE_PATH,
    )
    blobs = {path: sha256(_commit_bytes(D122_BASELINE_HEAD, path)) for path in frozen_paths}
    return {
        "baseline_blobs_sha256": dict(sorted(blobs.items())),
        "endpoint": baseline["endpoint"],
        "source_head": D122_BASELINE_HEAD,
        "status": "PASS",
    }


def validate_remote_ci_evidence() -> dict[str, Any]:
    """Validate the immutable credential-free PASS receipt byte-for-byte."""

    raw = _working_bytes(EXPECTED_EVIDENCE_PATH)
    value = _strict_json(raw, label=EXPECTED_EVIDENCE_PATH)
    require(
        d123.validate_remote_ci_evidence(ROOT) == value,
        "D1.23 trigger rejected the D1.22 exact-head CI receipt",
    )
    require(
        len(raw) == EXPECTED_EVIDENCE_BYTES
        and sha256(raw) == EXPECTED_EVIDENCE_SHA256
        and raw
        == json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode(
            "utf-8"
        )
        + b"\n",
        "D1.22 exact-head remote-CI evidence identity differs",
    )
    required_workflows = value.get("required_workflows")
    topology = value.get("topology_rehearsal")
    require(
        value.get("schema") == "trimem/d122-exact-head-remote-ci-evidence/1.0"
        and value.get("status") == "PASS"
        and value.get("exact_head") == D122_BASELINE_HEAD
        and value.get("credential_access") is False
        and value.get("benchmark_execution_runs") == 0
        and value.get("model_api_calls") == 0
        and value.get("paid_model_calls") == 0
        and isinstance(required_workflows, Mapping)
        and set(required_workflows)
        == {
            ".github/workflows/ci-trimem-dev-toolchain.yml",
            ".github/workflows/ci-trimem-e2e.yml",
            ".github/workflows/ci-trimem-grader-loader.yml",
            ".github/workflows/ci-trimem-harness-lock.yml",
            ".github/workflows/ci-trimem-multi-swe-contract.yml",
            ".github/workflows/ci-trimem.yml",
        }
        and all(
            isinstance(record, Mapping)
            and record.get("attempt") == 1
            and record.get("conclusion") == "success"
            and isinstance(record.get("run_id"), int)
            and record.get("run_id", 0) > 0
            for record in required_workflows.values()
        ),
        "D1.22 exact-head remote-CI PASS boundary differs",
    )
    require(
        isinstance(topology, Mapping)
        and topology.get("status") == "PASS"
        and topology.get("collections") == 12
        and topology.get("namespaces") == 6
        and topology.get("payload_indexes") == 72
        and topology.get("cleanup_absent") is True
        and topology.get("hostconfig_nofile") == {"hard": 65_535, "soft": 65_535}
        and topology.get("pid1_nofile") == {"hard": 65_535, "soft": 65_535}
        and topology.get("observed_repo_digest")
        == (
            "qdrant/qdrant@sha256:"
            "241edb9d7778327516ef218f8c74e1bd61b5ea42cd4f193cb8d0896199705636"
        )
        and topology.get("qdrant_version") == "1.12.4"
        and topology.get("benchmark_image_pulls") == 0
        and topology.get("grader_containers") == 0
        and topology.get("model_calls") == 0
        and topology.get("official_grader_runs") == 0
        and topology.get("paid_model_calls") == 0
        and topology.get("tokens") == 0
        and topology.get("total_usd") == 0.0,
        "D1.22 Qdrant topology rehearsal PASS boundary differs",
    )
    return deepcopy(value)


def validate_no_exec_022() -> None:
    """Reject both committed and working-tree `_022` sentinels."""

    sentinel = d123.SENTINEL_PATH
    additions = _git_lines(
        "log", "--format=%H", "--diff-filter=A", "HEAD", "--", sentinel
    )
    require(not additions, "EXEC `_022` already exists in source history")
    require(not _relative_path(sentinel).exists(), "working-tree EXEC `_022` exists")


def _source_boundary(*, allow_sentinel_child: bool) -> tuple[str, str | None]:
    """Return the source commit and an optional exact sentinel-only child."""

    head = _git_text("rev-parse", "HEAD")
    if not allow_sentinel_child:
        validate_no_exec_022()
        return head, None
    execution_head = d123.validate_optional_exec_022_boundary(ROOT)
    if execution_head is None:
        return head, None
    parents = _git_lines("rev-list", "--parents", "-n", "1", execution_head)
    require(
        len(parents) == 1 and len(parents[0].split()) == 2,
        "EXEC `_022` sentinel child parent differs",
    )
    return parents[0].split()[1], execution_head


def _observed_changed_paths(
    *, source_head: str, include_working_tree: bool
) -> dict[str, str]:
    """Collect the baseline-to-working-source path set without following renames."""

    observed: dict[str, str] = {}
    diff_args = [
        "diff",
        "--name-status",
        "--no-renames",
        D122_BASELINE_HEAD,
    ]
    if not include_working_tree:
        diff_args.append(source_head)
    diff_args.append("--")
    for line in _git_lines(*diff_args):
        fields = line.split("\t")
        require(len(fields) == 2, "D1.23 diff contains a rename/copy")
        status, relative = fields
        require(status in {"A", "M"}, f"forbidden D1.23 path status: {line}")
        require(relative not in observed, f"duplicate D1.23 changed path: {relative}")
        observed[relative] = status
    if not include_working_tree:
        require(
            not _git("status", "--porcelain=v1", "-z", "--").stdout,
            "sentinel-child checkout has working-tree drift",
        )
        return observed
    untracked_raw = _git("ls-files", "--others", "--exclude-standard", "-z", "--").stdout
    try:
        untracked = untracked_raw.decode("utf-8", errors="strict").split("\x00")
    except UnicodeDecodeError as exc:
        raise D123ResealError("Git returned a non-UTF-8 untracked path") from exc
    for relative in filter(None, untracked):
        require(relative not in observed, f"duplicate D1.23 changed path: {relative}")
        observed[relative] = "A"
    return observed


def validate_changed_path_scope(
    *,
    source_head: str,
    include_working_tree: bool,
    allow_unwritten_generated: bool,
) -> dict[str, str]:
    allowed = set(d123.ALLOWED_ACTIVATION_PATHS)
    required = dict(d123.REQUIRED_ACTIVATION_CHANGES)
    generated = {
        EXPECTED_AMENDMENT_PATH,
        EXPECTED_INVENTORY_PATH,
        d123.FREEZE_PATH,
    }
    observed = _observed_changed_paths(
        source_head=source_head,
        include_working_tree=include_working_tree,
    )
    escaped = sorted(set(observed) - allowed)
    require(not escaped, f"D1.23 changed paths escape allowlist: {escaped}")
    for path, status in required.items():
        if allow_unwritten_generated and path in generated and path not in observed:
            continue
        require(
            observed.get(path) == status,
            f"required D1.23 change is missing or has wrong status: {path}",
        )
    return observed


def implementation_sha256(*, source_head: str | None = None) -> dict[str, str]:
    paths = set(d123.IMPLEMENTATION_SEAL_PATHS)
    require(paths, "D1.23 implementation seal path set is empty")
    require(
        paths <= set(d123.ALLOWED_ACTIVATION_PATHS),
        "D1.23 implementation seal escapes changed-path allowlist",
    )
    if source_head is None:
        return {path: sha256(_working_bytes(path)) for path in sorted(paths)}
    result: dict[str, str] = {}
    for path in sorted(paths):
        raw = _commit_bytes(source_head, path)
        require(
            _working_bytes(path) == raw,
            f"D1.23 implementation working bytes differ: {path}",
        )
        result[path] = sha256(raw)
    return result


def _frozen_science() -> dict[str, Any]:
    return {
        "arms": list(d123.EXPECTED_STREAM_ORDER),
        "expected_usd": 10.8,
        "grader_containers": 72,
        "hard_cap_usd": 50.0,
        "model_id": d123.MODEL_ID,
        "paid_model_call_cap": 1_873,
        "reasoning_effort": d123.REASONING_EFFORT,
        "scientific_generation_call_cap": 1_872,
        "targets": 12,
        "task_arm_runs": 72,
        "unchanged": [
            "model",
            "pricing",
            "prompts",
            "tools",
            "parsers",
            "targets",
            "target order",
            "arms",
            "stream order",
            "budgets",
            "grader locks",
            "image locks",
        ],
    }


def build_artifacts(
    *,
    source_head: str | None = None,
    source_changed_paths: Sequence[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build both deterministic documents without producing side effects."""

    _validate_trigger_constants()
    baseline = validate_d122_baseline()
    evidence = validate_remote_ci_evidence()
    implementation = implementation_sha256(source_head=source_head)
    if source_changed_paths is None:
        checked_out = _git_text("rev-parse", "HEAD")
        inferred = set(
            _observed_changed_paths(
                source_head=checked_out,
                include_working_tree=True,
            )
        )
        inferred.update(
            {EXPECTED_AMENDMENT_PATH, EXPECTED_INVENTORY_PATH, d123.FREEZE_PATH}
        )
        changed_paths = sorted(inferred)
    else:
        changed_paths = sorted(source_changed_paths)
    authority = {
        "development_execution_authorized": False,
        "external_execution_approval_received": False,
        "request_021_attempt_one_consumed": True,
        "request_021_attempt_two_allowed": False,
        "request_021_rerun_allowed": False,
        "request_022_creation_authorized": True,
        "request_022_created_in_source": False,
        "request_022_execution_authorized": False,
        "required_external_authorization": d123.REQUIRED_EXTERNAL_AUTHORIZATION,
        "sentinel_contains_execution_authority": False,
    }
    activation = {
        "benchmark_execution_performed": False,
        "credential_free": True,
        "evidence_path": EXPECTED_EVIDENCE_PATH,
        "evidence_sha256": EXPECTED_EVIDENCE_SHA256,
        "exact_verified_head": D122_BASELINE_HEAD,
        "request_creation_ready": True,
        "source_only": True,
        "status": "PASS",
    }
    amendment = {
        "activation": activation,
        "authority_boundary": authority,
        "canary_execution_actuals": deepcopy(d122.CANARY_EXECUTION_ACTUALS),
        "classification": d123.AMENDMENT_CLASSIFICATION,
        "consumed_execution_actuals": deepcopy(d122.HISTORICAL_EXECUTION_ACTUALS),
        "current_execution_actuals": deepcopy(d122.ZERO_CURRENT_EXECUTION_ACTUALS),
        "d122_baseline_head": D122_BASELINE_HEAD,
        "endpoint": d123.AMENDMENT_ENDPOINT,
        "frozen_partial_outcome": _strict_json(
            _commit_bytes(D122_BASELINE_HEAD, d122.FAILURE_FIXTURE_PATH),
            label="immutable D1.22 failure fixture",
        )["frozen_partial_outcome"],
        "frozen_scientific_identity": _frozen_science(),
        "historical_d122": baseline,
        "implementation_sha256": implementation,
        "pass_at_1": None,
        "performance_measured": False,
        "remote_ci_evidence": evidence,
        "remote_ci_evidence_sha256": EXPECTED_EVIDENCE_SHA256,
        "schema": d123.AMENDMENT_SCHEMA,
        "scientific_execution_actuals": deepcopy(d122.SCIENTIFIC_EXECUTION_ACTUALS),
        "scientific_status": d122.SCIENTIFIC_STATUS,
        "status": d123.AMENDMENT_STATUS,
    }
    inventory = {
        "allowed_changed_paths": sorted(d123.ALLOWED_ACTIVATION_PATHS),
        "classification": d123.AMENDMENT_CLASSIFICATION,
        "documents": {
            "activation_amendment": EXPECTED_AMENDMENT_PATH,
            "d122_failure_fixture": d122.FAILURE_FIXTURE_PATH,
            "d122_remote_ci_evidence": EXPECTED_EVIDENCE_PATH,
            "report": EXPECTED_REPORT_PATH,
        },
        "endpoint": d123.AMENDMENT_ENDPOINT,
        "historical_d122": baseline,
        "implementation_sha256": implementation,
        "remote_ci_evidence_sha256": EXPECTED_EVIDENCE_SHA256,
        "schema": d123.INVENTORY_SCHEMA,
        "source_changed_paths": changed_paths,
        "status": d123.AMENDMENT_STATUS,
    }
    canonical_bytes(amendment)
    canonical_bytes(inventory)
    return amendment, inventory


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_all() -> None:
    source_head, execution_head = _source_boundary(allow_sentinel_child=False)
    require(execution_head is None, "source writer cannot run after EXEC `_022`")
    observed = validate_changed_path_scope(
        source_head=source_head,
        include_working_tree=True,
        allow_unwritten_generated=True,
    )
    # The two JSON documents may not exist on the first write.  Predict their
    # final additions/modification so the inventory produced before the writes
    # is identical to the inventory recomputed immediately afterward.
    final_changed_paths = set(observed)
    final_changed_paths.update(
        {EXPECTED_AMENDMENT_PATH, EXPECTED_INVENTORY_PATH, d123.FREEZE_PATH}
    )
    amendment, inventory = build_artifacts(
        source_changed_paths=sorted(final_changed_paths)
    )
    _write_json(AMENDMENT_PATH, amendment)
    _write_json(INVENTORY_PATH, inventory)
    import trimem_freeze

    trimem_freeze.write_freeze(ROOT)
    validate_changed_path_scope(
        source_head=source_head,
        include_working_tree=True,
        allow_unwritten_generated=False,
    )


def check_all() -> dict[str, Any]:
    source_head, execution_head = _source_boundary(allow_sentinel_child=True)
    include_working_tree = execution_head is None
    observed = validate_changed_path_scope(
        source_head=source_head,
        include_working_tree=include_working_tree,
        allow_unwritten_generated=False,
    )
    amendment, inventory = build_artifacts(
        source_head=None if include_working_tree else source_head,
        source_changed_paths=sorted(observed),
    )
    amendment_raw = AMENDMENT_PATH.read_bytes()
    inventory_raw = INVENTORY_PATH.read_bytes()
    require(
        _read_json(AMENDMENT_PATH) == amendment
        and amendment_raw == canonical_bytes(amendment),
        "D1.23 amendment is stale or noncanonical",
    )
    require(
        _read_json(INVENTORY_PATH) == inventory
        and inventory_raw == canonical_bytes(inventory),
        "D1.23 inventory is stale or noncanonical",
    )
    import trimem_freeze

    trimem_freeze.check_freeze(ROOT)
    return {
        "benchmark_image_pulls": 0,
        "classification": d123.AMENDMENT_CLASSIFICATION,
        "endpoint": d123.AMENDMENT_ENDPOINT,
        "grader_containers": 0,
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "request_021_attempt_one_consumed": True,
        "request_021_rerun_allowed": False,
        "request_022_creation_authorized": True,
        "request_022_created": execution_head is not None,
        "request_022_execution_authorized": False,
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify the source-only D1.23 EXEC-022 activation seal"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.write:
            write_all()
        result = check_all()
    except (
        D123ResealError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
