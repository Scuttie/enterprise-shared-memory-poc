"""Pinned, benchmark-specific official grader adapters for TriMem V1.

Importing performs no execution; construction performs only a read-only Git
revision check. ``grade`` is an EXEC operation reachable only from separately
approved workflows.
There is no arbitrary-command fallback and no image pull in this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from enterprise_memory.trimem.accounting import strict_json_loads  # noqa: E402
from enterprise_memory.trimem.grader import (  # noqa: E402
    GradeRequest,
    GradeResult,
    GraderInvocationFailure,
)
from trimem_multi_swe_report_semantics import (  # noqa: E402
    MultiSWEReportSemanticsError,
    validate_multi_swe_final_report_outcome,
    validate_multi_swe_report_semantics,
    validate_public_semantics_summary,
)
from trimem_atomic_evidence import atomic_write_bytes  # noqa: E402


SWE_HARNESS_REVISION = "7a21e05772954cc81471ae19d56f436cecf43c54"
MULTI_HARNESS_REVISION = "24f493f8a103e72312ded4f6b9c89f081d69cb09"
MULTI_ENTRYPOINT = ROOT / "scripts/trimem_multi_swe_entrypoint.py"
MULTI_FIX_PATCH_RUN_COMMAND = "bash -e /home/fix-run.sh"
MULTI_SWE_PREBUILT_EVALUATION: Mapping[str, object] = MappingProxyType({
    "mode": "instance_only",
    "force_build": False,
    "human_mode": True,
    "need_clone": False,
    "fix_patch_run_cmd": MULTI_FIX_PATCH_RUN_COMMAND,
})
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DIGEST_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")
TAGGED_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9._-]+$")
INSTANCE_ID = re.compile(r"^[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-[0-9]+$")
SAFE_ENV_KEYS = frozenset({
    "COMSPEC", "DOCKER_CONFIG", "HOME", "LANG", "LC_ALL", "PATH", "PATHEXT",
    "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "USERPROFILE", "WINDIR",
    "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
})
SECRET_ENV_NAME = re.compile(
    r"(?:OPENAI|TRIMEM|DATABASE|DB_|GITHUB|TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIAL)",
    re.IGNORECASE,
)


class OfficialGraderError(RuntimeError):
    pass


class _MaterializedPatchEvidenceError(OfficialGraderError):
    def __init__(self, message: str, evidence: Mapping[str, Any]):
        super().__init__(message)
        self.evidence = dict(evidence)


class _ActualTestEvidenceError(OfficialGraderError):
    """Validation failure that retains every raw reference captured beforehand."""

    def __init__(self, message: str, evidence: Mapping[str, Any]):
        super().__init__(message)
        self.evidence = dict(evidence)


class _PrivateInputPurgeError(OfficialGraderError):
    """Purge failure that retains identities captured before deletion failed."""

    def __init__(self, message: str, evidence: Sequence[Mapping[str, Any]]):
        super().__init__(message)
        self.evidence = [dict(row) for row in evidence]


OFFICIAL_EVIDENCE_SCHEMA = "trimem/official-grader-adapter-evidence/2.0"
OFFICIAL_IMAGE_EVIDENCE_SCHEMA = "trimem/official-image-evidence/2.0"
OFFICIAL_IMAGE_EVIDENCE_FIELDS = frozenset({
    "schema",
    "role",
    "image",
    "tag",
    "expected",
    "observed",
    "inspect_argv",
    "inspect_invocation_status",
    "inspect_exit_code",
    "inspect_restricted_raw_streams",
    "tag_argv",
    "tag_invocation_status",
    "tag_exit_code",
    "tag_restricted_raw_streams",
})
OFFICIAL_EVIDENCE_FIELDS = frozenset({
    "schema",
    "benchmark_id",
    "dataset_revision",
    "harness_revision",
    "source_row_sha256",
    "execution_contract",
    "execution_control_evidence",
    "image_evidence",
    "invocation_argv",
    "harness_invocation_status",
    "report_invocation_argv",
    "report_invocation_status",
    "harness_restricted_raw_streams",
    "report_restricted_raw_streams",
    "materialized_private_inputs",
    "materialized_patch_evidence",
    "restricted_raw_report",
    "test_output",
    "official_test_status",
    "container_exit_status",
    "container_exit_summary",
    "semantic_normalization",
    "adapter_status",
    "adapter_failure_stage",
    "adapter_primary_error",
    "adapter_secondary_evidence_failures",
    "official_final_report_resolved",
    "adapter_normalized",
    "scientific_resolved",
})


def adapter_evidence_envelope_contract() -> dict[str, Any]:
    """Canonical projection used to freeze the v2 evidence-envelope contract."""

    return {
        "schema": OFFICIAL_EVIDENCE_SCHEMA,
        "top_level_fields": [
            "_trimem", "failure_stage", "reason", "status", "task_id",
        ],
        "trimem_fields": sorted(OFFICIAL_EVIDENCE_FIELDS),
        "canonical_root": "_trimem",
        "compatibility_aliases": [],
        "failure_outcome_policy": {
            "adapter_normalized": False,
            "grade_result_resolved_authoritative": False,
            "scientific_resolved": None,
            "official_final_report_resolved": "BOOLEAN_WHEN_CAPTURED_ELSE_NULL",
        },
        "primary_error_policy": "PRIMARY_PRESERVED_SECONDARY_EVIDENCE_ERRORS_SEPARATE",
    }


@dataclass(frozen=True)
class FrozenOfficialTarget:
    target_id: str
    benchmark_id: str
    instance_id: str
    repository: str
    base_commit: str
    dataset_revision: str
    source_row_sha256: str
    image: str
    harness_image_tag: str
    harness_revision: str

    def __post_init__(self) -> None:
        if self.benchmark_id not in {"swebench_verified", "multi_swe_bench_mini", "multi_swe_bench_flash"}:
            raise ValueError("unsupported official benchmark")
        expected_revision = SWE_HARNESS_REVISION if self.benchmark_id == "swebench_verified" else MULTI_HARNESS_REVISION
        if self.harness_revision != expected_revision:
            raise ValueError("official harness revision mismatch")
        if not INSTANCE_ID.fullmatch(self.instance_id):
            raise ValueError("invalid committed instance ID")
        if not re.fullmatch(r"[0-9a-f]{40}", self.dataset_revision):
            raise ValueError("dataset revision must be an exact commit")
        if not SHA256.fullmatch(self.source_row_sha256):
            raise ValueError("source row requires an exact sha256")
        if not DIGEST_IMAGE.fullmatch(self.image):
            raise ValueError("grader image must be a digest reference")
        if not TAGGED_IMAGE.fullmatch(self.harness_image_tag) or "@" in self.harness_image_tag:
            raise ValueError("harness image tag is invalid")
        if not re.fullmatch(r"[0-9a-f]{40}", self.base_commit):
            raise ValueError("base commit must be exact")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise ValueError("repository slug is invalid")


@dataclass(frozen=True)
class HarnessInvocation:
    argv: tuple[str, ...]
    cwd: Path
    report_path: Path
    private_input_paths: tuple[Path, ...]
    test_output_path: Path
    test_status_path: Path
    report_argv: tuple[str, ...] = ()
    materialized_patch_path: Path | None = None
    container_exit_status_path: Path | None = None


Runner = Callable[..., subprocess.CompletedProcess[Any]]


class _RawBackedText(str):
    """Decoded process text that still retains the exact captured bytes.

    Production subprocesses are always launched with ``text=False``.  Keeping a
    string facade avoids mixing bytes into public/redaction code, while raw
    restricted evidence is written from ``raw_bytes`` without a decode/encode
    round trip.  Test runners that return strings remain supported and acquire
    the only byte representation they supplied: strict UTF-8.
    """

    raw_bytes: bytes

    def __new__(cls, value: object = b"") -> "_RawBackedText":
        if value is None:
            raw = b""
        elif isinstance(value, bytes):
            raw = value
        elif isinstance(value, str):
            raw = value.encode("utf-8")
        else:
            raw = str(value).encode("utf-8")
        instance = str.__new__(cls, raw.decode("utf-8", errors="replace"))
        instance.raw_bytes = raw
        return instance


def canonical_row_hash(row: Mapping[str, Any]) -> str:
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _strict_string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise OfficialGraderError(f"official test status field {name} is invalid")
    if len(set(value)) != len(value):
        raise OfficialGraderError(f"official test status field {name} is duplicated")
    return value


def _exact_int(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def _source_test_ids(row: Mapping[str, Any], name: str) -> list[str]:
    value = row.get(name)
    if isinstance(value, str):
        try:
            value = strict_json_loads(value)
        except (json.JSONDecodeError, ValueError) as exc:
            raise OfficialGraderError(f"source row field {name} is invalid JSON") from exc
    return _strict_string_list(value, f"source.{name}")


def validate_official_test_evidence(
    target: FrozenOfficialTarget,
    *,
    source_row: Mapping[str, Any],
    test_output_raw: bytes,
    test_status_raw: bytes,
    resolved: bool,
    final_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate actual harness test bytes/status; return only non-sensitive counts."""

    if not test_output_raw or not test_output_raw.strip():
        raise OfficialGraderError("official test output is empty")
    if not test_status_raw or not test_status_raw.strip():
        raise OfficialGraderError("official test status is empty")
    try:
        status = strict_json_loads(test_status_raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise OfficialGraderError("official test status is invalid JSON") from exc
    if not isinstance(status, Mapping):
        raise OfficialGraderError("official test status root is not an object")

    if target.benchmark_id == "swebench_verified":
        if set(status) != {target.instance_id}:
            raise OfficialGraderError("SWE official test status target set mismatch")
        instance = status[target.instance_id]
        if not isinstance(instance, Mapping):
            raise OfficialGraderError("SWE official instance test status is missing")
        tests = instance.get("tests_status")
        if not isinstance(tests, Mapping) or not {"FAIL_TO_PASS", "PASS_TO_PASS"} <= set(tests):
            raise OfficialGraderError("SWE official FAIL_TO_PASS/PASS_TO_PASS status is missing")

        expected: dict[str, list[str]] = {
            name: _source_test_ids(source_row, name)
            for name in ("FAIL_TO_PASS", "PASS_TO_PASS")
        }
        if not expected["FAIL_TO_PASS"]:
            raise OfficialGraderError("SWE source has no FAIL_TO_PASS tests")
        classified: dict[str, dict[str, list[str]]] = {}
        for name in ("FAIL_TO_PASS", "PASS_TO_PASS"):
            row = tests.get(name)
            if not isinstance(row, Mapping) or set(row) != {"success", "failure"}:
                raise OfficialGraderError(f"SWE official {name} status field set drift")
            success = _strict_string_list(row.get("success"), f"{name}.success")
            failure = _strict_string_list(row.get("failure"), f"{name}.failure")
            if set(success) & set(failure) or set(success) | set(failure) != set(expected[name]):
                raise OfficialGraderError(f"SWE official {name} classification is incomplete")
            classified[name] = {"success": success, "failure": failure}
        if classified["PASS_TO_PASS"]["failure"]:
            raise OfficialGraderError("SWE PASS_TO_PASS regression count is non-zero")
        computed_resolved = not classified["FAIL_TO_PASS"]["failure"]
        if (
            instance.get("patch_exists") is not True
            or instance.get("patch_is_None") is not False
            or instance.get("patch_successfully_applied") is not True
            or instance.get("infra_failure") is not False
            or instance.get("resolved") is not computed_resolved
            or computed_resolved is not resolved
        ):
            raise OfficialGraderError("SWE official test status/result mismatch")
        expected_spec = {
            name: sorted(expected[name]) for name in ("FAIL_TO_PASS", "PASS_TO_PASS")
        }
        return {
            "schema": "trimem/official-test-status-summary/1.0",
            "benchmark_id": target.benchmark_id,
            "source": "SWE_PER_INSTANCE_REPORT",
            "fail_to_pass_expected": len(expected["FAIL_TO_PASS"]),
            "fail_to_pass_classified": sum(
                len(classified["FAIL_TO_PASS"][kind]) for kind in ("success", "failure")
            ),
            "fail_to_pass_failures": len(classified["FAIL_TO_PASS"]["failure"]),
            "pass_to_pass_expected": len(expected["PASS_TO_PASS"]),
            "pass_to_pass_classified": sum(
                len(classified["PASS_TO_PASS"][kind]) for kind in ("success", "failure")
            ),
            "pass_to_pass_regressions": 0,
            "expected_test_spec_sha256": canonical_row_hash(expected_spec),
            "resolved": resolved,
        }

    if final_report is None:
        raise OfficialGraderError("Multi-SWE final report is required for semantic normalization")
    try:
        semantics = validate_multi_swe_report_semantics(
            instance_id=target.instance_id,
            source_row=source_row,
            status=status,
            final_report=final_report,
        )
    except MultiSWEReportSemanticsError as exc:
        raise OfficialGraderError(
            f"Multi-SWE two-stage report semantics failed [{exc.code}]: {exc}"
        ) from None
    if semantics.official_final_report_resolved is not resolved:
        raise OfficialGraderError("Multi-SWE final report outcome binding mismatch")
    return semantics.to_public_dict()


def validate_multi_swe_container_exit_status(
    target: FrozenOfficialTarget,
    *,
    raw: bytes,
    resolved: bool,
    test_summary: Mapping[str, Any],
    expected_patch: str,
) -> dict[str, Any]:
    """Bind the inner Docker StatusCode to exact full-domain test evidence.

    A nonzero test command is expected for some valid NOOP evaluations.  It is
    accepted only after the pinned report/test validator has proven complete
    source-row test-domain coverage and an unresolved result.  A resolved run
    must have exited zero.  Missing, malformed, or unbound status evidence is
    always fatal.
    """

    if target.benchmark_id == "swebench_verified":
        raise OfficialGraderError("Multi-SWE container exit evidence used for SWE-bench")
    try:
        value = strict_json_loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise OfficialGraderError("Multi-SWE container exit status is invalid JSON") from exc
    required = {
        "executed_image",
        "expected_image",
        "expected_tag",
        "image_id",
        "run_command",
        "schema",
        "status_code",
        "submitted_patch_bytes",
        "submitted_patch_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise OfficialGraderError("Multi-SWE container exit status field set drift")
    status_code = value.get("status_code")
    patch_raw = expected_patch.encode("utf-8")
    if (
        value.get("schema") != "trimem/multi-swe-container-exit-status/1.0"
        or value.get("expected_image") != target.image
        or value.get("executed_image") != target.image
        or value.get("expected_tag") != target.harness_image_tag
        or value.get("run_command") != MULTI_FIX_PATCH_RUN_COMMAND
        or not isinstance(value.get("image_id"), str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("image_id"))) is None
        or type(status_code) is not int
        or not 0 <= status_code <= 255
        or value.get("submitted_patch_bytes") != len(patch_raw)
        or value.get("submitted_patch_sha256") != hashlib.sha256(patch_raw).hexdigest()
    ):
        raise OfficialGraderError("Multi-SWE container exit status binding differs")
    if resolved and status_code != 0:
        raise OfficialGraderError("resolved Multi-SWE run has nonzero container exit status")
    try:
        validated_test_summary = validate_public_semantics_summary(test_summary)
    except MultiSWEReportSemanticsError as exc:
        if status_code != 0:
            raise OfficialGraderError(
                "nonzero Multi-SWE exit lacks full-domain unresolved test "
                f"evidence [{exc.code}]: {exc}"
            ) from None
        raise OfficialGraderError(
            f"Multi-SWE semantic summary failed [{exc.code}]: {exc}"
        ) from None
    if validated_test_summary["computed_resolved"] is not resolved:
        raise OfficialGraderError(
            "Multi-SWE container exit/result semantic summary binding differs"
        )
    if status_code != 0:
        if (
            resolved
            or validated_test_summary["computed_resolved"] is not False
            or validated_test_summary["official_final_report_resolved"] is not False
        ):
            raise OfficialGraderError(
                "nonzero Multi-SWE exit lacks full-domain unresolved test evidence"
            )
        acceptance = "NONZERO_ACCEPTED_AFTER_FULL_DOMAIN_UNRESOLVED_VALIDATION"
    else:
        acceptance = "ZERO_EXIT"
    return {
        "schema": "trimem/multi-swe-container-exit-summary/1.0",
        "acceptance": acceptance,
        "executed_image": target.image,
        "expected_tag": target.harness_image_tag,
        "image_id": value["image_id"],
        "run_command": MULTI_FIX_PATCH_RUN_COMMAND,
        "status_code": status_code,
        "submitted_patch_bytes": len(patch_raw),
        "submitted_patch_sha256": hashlib.sha256(patch_raw).hexdigest(),
    }


def minimal_subprocess_env(source: Mapping[str, str]) -> dict[str, str]:
    """Return only non-secret OS/Docker process prerequisites.

    Official harness code is pinned but external.  It never receives the model
    key, database URL, GitHub token, or any TRIMEM secret from the parent job.
    """
    result = {
        key: str(value)
        for key, value in source.items()
        if key.upper() in SAFE_ENV_KEYS and not SECRET_ENV_NAME.search(key)
    }
    result["PYTHONUNBUFFERED"] = "1"
    return result


def redact_text(value: str, secret_values: Sequence[str]) -> str:
    result = value if isinstance(value, str) else str(value)
    for secret in sorted({item for item in secret_values if len(item) >= 4}, key=len, reverse=True):
        result = result.replace(secret, "[REDACTED]")
    result = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", result)
    result = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED_OPENAI_KEY]", result)
    return result


def _write_json(path: Path, value: Any, *, lines: bool = False) -> None:
    if lines:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    else:
        raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_bytes(path, raw.encode("utf-8"))


def _parse_instance_number(instance_id: str) -> tuple[str, str, str]:
    repository, number = instance_id.rsplit("-", 1)
    org, repo = repository.split("__", 1)
    return org, repo, number


def _validated_multi_swe_prebuilt_evaluation() -> dict[str, object]:
    """Return the only supported Multi-SWE prebuilt-image execution flags."""

    expected = {
        "mode": "instance_only",
        "force_build": False,
        "human_mode": True,
        "need_clone": False,
        "fix_patch_run_cmd": MULTI_FIX_PATCH_RUN_COMMAND,
    }
    try:
        observed = dict(MULTI_SWE_PREBUILT_EVALUATION)
    except (TypeError, ValueError) as exc:
        raise ValueError("MULTI_SWE_PREBUILT_EVALUATION invariant mismatch") from exc
    if observed != expected:
        raise ValueError("MULTI_SWE_PREBUILT_EVALUATION invariant mismatch")
    return observed


def build_harness_invocation(
    target: FrozenOfficialTarget,
    *,
    row: Mapping[str, Any],
    patch: str,
    harness_root: Path,
    run_root: Path,
    model_name: str,
    python_binary: str = sys.executable,
) -> HarnessInvocation:
    """Materialize exact one-row input and return a fixed official harness argv."""
    if canonical_row_hash(row) != target.source_row_sha256:
        raise OfficialGraderError("dataset source row hash mismatch")
    run_root.mkdir(parents=True, exist_ok=False)
    if target.benchmark_id == "swebench_verified":
        if row.get("instance_id") != target.instance_id or row.get("repo") != target.repository:
            raise OfficialGraderError("SWE-bench row identity mismatch")
        if row.get("base_commit") != target.base_commit:
            raise OfficialGraderError("SWE-bench row base commit mismatch")
        dataset = run_root / "dataset.json"
        prediction = run_root / "prediction.jsonl"
        report_dir = run_root / "report"
        locked_row = dict(row)
        locked_row["image"] = target.harness_image_tag
        _write_json(dataset, [locked_row])
        _write_json(prediction, {
            "instance_id": target.instance_id,
            "model_patch": patch,
            "model_name_or_path": model_name,
        }, lines=True)
        run_id = hashlib.sha256(f"{target.target_id}:{model_name}".encode()).hexdigest()[:20]
        report_path = report_dir / f"{model_name}.{run_id}.json"
        instance_log_dir = (
            harness_root / "logs" / "run_evaluation" / run_id
            / model_name.replace("/", "__") / target.instance_id
        )
        return HarnessInvocation(
            argv=(
                python_binary, "-m", "swebench.harness.run_evaluation",
                "--dataset_name", str(dataset), "--split", "test",
                "--instance_ids", target.instance_id,
                "--predictions_path", str(prediction), "--max_workers", "1",
                "--timeout", "1800", "--run_id", run_id,
                "--report_dir", str(report_dir),
            ),
            cwd=harness_root,
            report_path=report_path,
            private_input_paths=(dataset, prediction),
            test_output_path=instance_log_dir / "test_output.txt",
            test_status_path=instance_log_dir / "report.json",
        )

    org, repo, number = _parse_instance_number(target.instance_id)
    row_org = row.get("org") or row.get("repo", {}).get("org") if isinstance(row.get("repo"), dict) else row.get("org")
    row_repo = row.get("repo") if isinstance(row.get("repo"), str) else row.get("repo", {}).get("repo")
    row_number = str(row.get("number") or row.get("pull_request", {}).get("number", ""))
    if (str(row_org), str(row_repo), row_number) != (org, repo, number):
        raise OfficialGraderError("Multi-SWE-bench row identity mismatch")
    base = str(row.get("base_commit") or row.get("base", {}).get("sha") or row.get("base_sha") or "")
    if base != target.base_commit:
        raise OfficialGraderError("Multi-SWE-bench row base commit mismatch")
    dataset, prediction = run_root / "dataset.jsonl", run_root / "prediction.jsonl"
    _write_json(dataset, dict(row), lines=True)
    _write_json(prediction, {"org": org, "repo": repo, "number": number, "fix_patch": patch}, lines=True)
    output_dir, log_dir, workdir, repo_dir = (
        run_root / "output", run_root / "logs", run_root / "work", run_root / "repos"
    )
    for path in (output_dir, log_dir, workdir, repo_dir):
        path.mkdir()
    prebuilt_evaluation = _validated_multi_swe_prebuilt_evaluation()
    config = {
        "workdir": str(workdir), "patch_files": [str(prediction)],
        "dataset_files": [str(dataset)], "output_dir": str(output_dir),
        "specifics": [f"{org}/{repo}:pr-{number}"], "skips": [], "repo_dir": str(repo_dir),
        "global_env": [], "clear_env": True, "stop_on_error": True,
        "max_workers": 1, "max_workers_build_image": 1, "max_workers_run_instance": 1,
        "log_dir": str(log_dir), "log_level": "DEBUG", "log_to_console": True,
        **prebuilt_evaluation,
    }
    config_path = run_root / "config.json"
    container_exit_status_path = run_root / "container-exit-status.json"
    _write_json(config_path, config)
    return HarnessInvocation(
        argv=(
            python_binary,
            str(MULTI_ENTRYPOINT),
            "--harness-root",
            str(harness_root),
            "--config",
            str(config_path),
            "--expected-image",
            target.image,
            "--expected-tag",
            target.harness_image_tag,
            "--exit-status-output",
            str(container_exit_status_path),
        ),
        cwd=harness_root,
        report_path=output_dir / "final_report.json",
        private_input_paths=(dataset, prediction, config_path),
        test_output_path=workdir / org / repo / "evals" / f"pr-{number}" / "fix-patch-run.log",
        test_status_path=workdir / org / repo / "evals" / f"pr-{number}" / "report.json",
        report_argv=(
            python_binary, "-m", "multi_swe_bench.harness.gen_report",
            "--mode", "evaluation", "--workdir", str(workdir),
            "--output_dir", str(output_dir), "--specifics", f"{org}/{repo}:pr-{number}",
            "--dataset_files", str(dataset), "--max_workers", "1",
            "--log_dir", str(log_dir), "--log_level", "DEBUG",
            "--log_to_console", "true", "--regen", "true",
        ),
        materialized_patch_path=(
            workdir / org / repo / "evals" / f"pr-{number}" / "fix.patch"
        ),
        container_exit_status_path=container_exit_status_path,
    )


def parse_official_report(target: FrozenOfficialTarget, report: Mapping[str, Any]) -> bool:
    if target.benchmark_id == "swebench_verified":
        id_fields = (
            "submitted_ids", "completed_ids", "incomplete_ids", "resolved_ids",
            "unresolved_ids", "empty_patch_ids", "error_ids", "infra_failure_ids",
            "ambiguous_failure_ids",
        )
        rows = {
            name: _strict_string_list(report.get(name), f"summary.{name}")
            for name in id_fields
        }
        resolved = set(rows["resolved_ids"])
        unresolved = set(rows["unresolved_ids"])
        count_pairs = {
            "submitted_instances": "submitted_ids",
            "completed_instances": "completed_ids",
            "resolved_instances": "resolved_ids",
            "unresolved_instances": "unresolved_ids",
            "infra_failure_instances": "infra_failure_ids",
            "ambiguous_failure_instances": "ambiguous_failure_ids",
            "empty_patch_instances": "empty_patch_ids",
            "error_instances": "error_ids",
        }
        if (
            report.get("schema_version") != 2
            or not _exact_int(report.get("total_instances"), 1)
            or not _exact_int(report.get("submitted_instances"), 1)
            or not _exact_int(report.get("completed_instances"), 1)
            or not _exact_int(report.get("empty_patch_instances"), 0)
            or not _exact_int(report.get("error_instances"), 0)
            or rows["submitted_ids"] != [target.instance_id]
            or rows["completed_ids"] != [target.instance_id]
            or rows["incomplete_ids"]
            or rows["empty_patch_ids"]
            or rows["error_ids"]
            or rows["infra_failure_ids"]
            or rows["ambiguous_failure_ids"]
            or any(
                not _exact_int(report.get(count_name), len(rows[ids_name]))
                for count_name, ids_name in count_pairs.items()
            )
        ):
            raise OfficialGraderError("SWE-bench report does not prove one completed non-empty-patch evaluation")
        if target.instance_id not in resolved | unresolved or target.instance_id in resolved & unresolved:
            raise OfficialGraderError("SWE-bench report does not classify the exact target")
        if resolved | unresolved != {target.instance_id}:
            raise OfficialGraderError("SWE-bench report resolution target set mismatch")
        return target.instance_id in resolved
    try:
        return validate_multi_swe_final_report_outcome(
            instance_id=target.instance_id,
            final_report=report,
        )
    except MultiSWEReportSemanticsError as exc:
        raise OfficialGraderError(
            f"Multi-SWE FinalReport validation failed [{exc.code}]: {exc}"
        ) from None


class OfficialHarnessGraderGateway:
    """Exact SWE-bench/Multi-SWE-bench adapter; no generic command surface."""

    def __init__(
        self,
        target: FrozenOfficialTarget,
        *,
        source_row: Mapping[str, Any],
        harness_root: Path,
        output_root: Path,
        model_name: str,
        support_images: Sequence[tuple[str, str]] = (),
        runner: Runner = subprocess.run,
        docker_binary: str = "docker",
        python_binary: str = sys.executable,
        timeout_seconds: int = 2400,
    ):
        if target.benchmark_id != "swebench_verified":
            _validated_multi_swe_prebuilt_evaluation()
        if not harness_root.is_dir():
            raise ValueError("pinned official harness checkout is missing")
        completed = subprocess.run(
            ["git", "-C", str(harness_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        )
        if completed.returncode != 0 or completed.stdout.strip() != target.harness_revision:
            raise ValueError("official harness checkout revision mismatch")
        if canonical_row_hash(source_row) != target.source_row_sha256:
            raise ValueError("source row hash mismatch")
        if not model_name or "/" in model_name or "\\" in model_name:
            raise ValueError("model name must be a safe report identifier")
        for image, tag in support_images:
            if not DIGEST_IMAGE.fullmatch(image) or not TAGGED_IMAGE.fullmatch(tag):
                raise ValueError("support image binding is not frozen")
        self.target = target
        self.source_row = dict(source_row)
        self.harness_root = harness_root.resolve()
        self.output_root = output_root.resolve()
        self.model_name = model_name
        self.support_images = tuple(support_images)
        self.runner = runner
        self.docker_binary = docker_binary
        self.python_binary = python_binary
        self.timeout_seconds = timeout_seconds
        self.execution_env = minimal_subprocess_env(os.environ)
        self._secret_values = tuple(
            value for key, value in os.environ.items()
            if SECRET_ENV_NAME.search(key) and isinstance(value, str) and len(value) >= 4
        )
        self._restricted_root = self.output_root / "restricted-evidence"

    def _run(
        self, argv: Sequence[str], *, cwd: Path | None = None, timeout: int = 60
    ) -> subprocess.CompletedProcess[str]:
        completed = self.runner(
            list(argv),
            cwd=cwd,
            env=dict(self.execution_env),
            capture_output=True,
            text=False,
            timeout=timeout,
            check=False,
        )
        # Never decode before the original byte streams have been retained.
        # ``_RawBackedText`` lets existing public/redaction logic consume text
        # while ``_restricted_streams`` writes the exact production bytes.
        return subprocess.CompletedProcess(
            completed.args,
            completed.returncode,
            stdout=_stream_text(completed.stdout),
            stderr=_stream_text(completed.stderr),
        )

    def _execution_contract(self, patch: str) -> dict[str, Any]:
        raw = patch.encode("utf-8")
        common: dict[str, Any] = {
            "schema": "trimem/official-grader-execution-contract/1.0",
            "api_calls": 0,
            "source_image_build_calls": 0,
            "host_prepare_script_reads": 0,
            "submitted_patch_bytes": len(raw),
            "submitted_patch_sha256": hashlib.sha256(raw).hexdigest(),
        }
        if self.target.benchmark_id != "swebench_verified":
            flags = _validated_multi_swe_prebuilt_evaluation()
            return {
                **common,
                "profile": "MULTI_SWE_PREBUILT_EVALUATION",
                "execution_mode": flags["mode"],
                "human_mode": flags["human_mode"],
                "force_build": flags["force_build"],
                "need_clone": flags["need_clone"],
                "fix_patch_run_cmd": flags["fix_patch_run_cmd"],
                "container_image_execution": "IMMUTABLE_DIGEST",
                "tag_digest_same_image_id_required": True,
                "docker_pull_fallback_allowed": False,
                "container_exit_status": "CAPTURED_AND_FULL_DOMAIN_VALIDATED",
                "report_module": "multi_swe_bench.harness.gen_report",
                "report_mode": "evaluation",
                "patch_transport": {
                    "host_source": "evaluation_instance_fix.patch",
                    "container_destination": "/home/fix.patch",
                    "mode": "rw",
                },
            }
        return {
            **common,
            "profile": "SWE_BENCH_OFFICIAL_PREDICTION",
            "execution_mode": "evaluation",
            "human_mode": None,
            "force_build": None,
            "need_clone": None,
            "report_module": "swebench.harness.run_evaluation",
            "report_mode": "inline",
            "patch_transport": {
                "host_source": "prediction.jsonl.model_patch",
                "container_destination": None,
                "mode": None,
            },
        }

    def _execution_control_evidence(self) -> dict[str, Any]:
        common = {
            "schema": "trimem/official-grader-execution-control/1.0",
            "harness_revision": self.target.harness_revision,
            "source_image_build_calls": 0,
            "host_prepare_script_reads": 0,
        }
        if self.target.benchmark_id != "swebench_verified":
            return {
                **common,
                "profile": "MULTI_SWE_PREBUILT_EVALUATION",
                "proof_basis": "PINNED_CONTROL_FLOW_AND_ADAPTER_CONSTRUCTION_INVARIANT",
                "dispatch": (
                    "trimem_multi_swe_entrypoint.execute_pinned_instance_only"
                    "->CliArgs.run(instance_only)->run_mode_instance_only"
                ),
                "support_container_bootstrap_calls": 0,
                "upstream_module_main_executed": False,
                "structurally_excluded_calls": [
                    "run_evaluation.__main__.nix_swe_bootstrap",
                    "run_mode_image",
                    "check_commit_hashes",
                    "build_image",
                    "run_and_save_logs",
                ],
            }
        return {
            **common,
            "profile": "SWE_BENCH_OFFICIAL_PREDICTION",
            "proof_basis": "PINNED_CONTROL_FLOW_AND_FIXED_ARGV",
            "dispatch": "main(task_repo=None,rewrite_reports=False)->run_instances",
            "source_build_guard": {
                "expression": "task_repo and not rewrite_reports",
                "task_repo_argv_present": False,
                "rewrite_reports_argv_present": False,
                "evaluates": False,
            },
            "structurally_excluded_calls": ["_build_before_eval"],
        }

    def _capture_materialized_patch(self, path: Path, patch: str) -> dict[str, Any]:
        """Bind the exact upstream-created host patch, retain it restricted, then purge it."""

        expected = patch.encode("utf-8")
        lexical = path.absolute()
        if self.output_root not in lexical.parents:
            raise OfficialGraderError("materialized submitted patch escaped output root")
        if path.is_symlink():
            path.unlink()
            raise OfficialGraderError("materialized submitted patch is a symlink")
        resolved = path.resolve()
        if self.output_root not in resolved.parents:
            raise OfficialGraderError("materialized submitted patch escaped output root")
        try:
            if not resolved.is_file():
                raise OfficialGraderError("materialized submitted patch is missing")
            observed = resolved.read_bytes()
            restricted = self._restricted_blob("submitted-patch", "materialized", observed)
        finally:
            if resolved.is_file():
                resolved.unlink()
        if resolved.exists() or resolved.is_symlink():
            raise OfficialGraderError("materialized submitted patch purge failed")
        evidence = {
            "schema": "trimem/materialized-submitted-patch-evidence/1.0",
            "host_path": resolved.relative_to(self.output_root).as_posix(),
            "container_destination": "/home/fix.patch",
            "mode": "rw",
            "bytes": len(observed),
            "sha256": hashlib.sha256(observed).hexdigest(),
            "request_identity_match": observed == expected,
            "restricted_materialized_patch": restricted,
            "purged_after_capture": True,
        }
        if observed != expected:
            raise _MaterializedPatchEvidenceError(
                "materialized submitted patch bytes mismatch", evidence
            )
        return evidence

    def _restricted_blob(self, stage: str, kind: str, raw: bytes) -> dict[str, Any]:
        digest = hashlib.sha256(raw).hexdigest()
        safe_stage = re.sub(r"[^A-Za-z0-9_.-]", "_", stage)
        target = self._restricted_root / f"{safe_stage}-{kind}-{digest}.bin"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise OfficialGraderError("restricted evidence target must not be a symlink")
        if target.exists() and (
            not target.is_file() or target.read_bytes() != raw
        ):
            raise OfficialGraderError("restricted evidence digest collision")
        if not target.exists():
            try:
                atomic_write_bytes(target, raw)
            except FileExistsError:
                # Another same-process/thread publisher may have won after the
                # existence check.  Content-addressing makes an exact match
                # idempotent and rejects every other outcome.
                if not target.is_file() or target.read_bytes() != raw:
                    raise OfficialGraderError(
                        "restricted evidence concurrent publication differs"
                    ) from None
        return {
            "path": target.relative_to(self.output_root).as_posix(),
            "sha256": digest,
            "bytes": len(raw),
            "access": "RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS",
        }

    def _restricted_streams(
        self, stage: str, stdout: object, stderr: object
    ) -> dict[str, Any]:
        return {
            "stdout": self._restricted_blob(stage, "stdout", _stream_bytes(stdout)),
            "stderr": self._restricted_blob(stage, "stderr", _stream_bytes(stderr)),
        }

    def _redact(self, value: str) -> str:
        return redact_text(value, self._secret_values)

    def _compose_evidence_envelope(
        self,
        request: GradeRequest,
        *,
        execution_contract: Mapping[str, Any] | None,
        execution_control_evidence: Mapping[str, Any] | None,
        adapter_status: str,
        adapter_failure_stage: str | None,
        adapter_primary_error: Mapping[str, Any] | None,
        adapter_secondary_evidence_failures: Sequence[str] = (),
        image_evidence: Sequence[Mapping[str, Any]] = (),
        extra: Mapping[str, Any] | None = None,
        adapter_normalized: bool = False,
        official_final_report_resolved: bool | None = None,
        scientific_resolved: bool | None = None,
    ) -> dict[str, Any]:
        """Build the sole canonical adapter evidence root on every path."""

        values = dict(extra or {})
        envelope: dict[str, Any] = {
            "schema": OFFICIAL_EVIDENCE_SCHEMA,
            "benchmark_id": self.target.benchmark_id,
            "dataset_revision": self.target.dataset_revision,
            "harness_revision": self.target.harness_revision,
            "source_row_sha256": self.target.source_row_sha256,
            "execution_contract": (
                dict(execution_contract) if execution_contract is not None else None
            ),
            "execution_control_evidence": (
                dict(execution_control_evidence)
                if execution_control_evidence is not None
                else None
            ),
            "image_evidence": [dict(row) for row in image_evidence],
            "invocation_argv": [],
            "harness_invocation_status": "NOT_REACHED",
            "report_invocation_argv": [],
            "report_invocation_status": "NOT_REACHED",
            "harness_restricted_raw_streams": None,
            "report_restricted_raw_streams": None,
            "materialized_private_inputs": [],
            "materialized_patch_evidence": None,
            "restricted_raw_report": None,
            "test_output": None,
            "official_test_status": None,
            "container_exit_status": None,
            "container_exit_summary": None,
            "semantic_normalization": None,
            "adapter_status": adapter_status,
            "adapter_failure_stage": adapter_failure_stage,
            "adapter_primary_error": (
                dict(adapter_primary_error) if adapter_primary_error is not None else None
            ),
            "adapter_secondary_evidence_failures": list(
                adapter_secondary_evidence_failures
            ),
            "official_final_report_resolved": official_final_report_resolved,
            "adapter_normalized": adapter_normalized,
            "scientific_resolved": scientific_resolved,
        }
        for name in (
            "invocation_argv",
            "harness_invocation_status",
            "report_invocation_argv",
            "report_invocation_status",
            "harness_restricted_raw_streams",
            "report_restricted_raw_streams",
            "materialized_private_inputs",
            "materialized_patch_evidence",
            "restricted_raw_report",
            "test_output",
            "official_test_status",
            "container_exit_status",
            "container_exit_summary",
            "semantic_normalization",
        ):
            if name in values:
                envelope[name] = values[name]
        if "image_evidence" in values:
            envelope["image_evidence"] = values["image_evidence"]
        if set(envelope) != OFFICIAL_EVIDENCE_FIELDS:
            raise AssertionError("official adapter evidence envelope field drift")
        return envelope

    def _evidence_envelope(
        self,
        request: GradeRequest,
        *,
        adapter_status: str,
        adapter_failure_stage: str | None,
        adapter_primary_error: Mapping[str, Any] | None,
        adapter_secondary_evidence_failures: Sequence[str] = (),
        image_evidence: Sequence[Mapping[str, Any]] = (),
        extra: Mapping[str, Any] | None = None,
        adapter_normalized: bool = False,
        official_final_report_resolved: bool | None = None,
        scientific_resolved: bool | None = None,
    ) -> dict[str, Any]:
        """Build the sole canonical adapter evidence root on every path."""

        return self._compose_evidence_envelope(
            request,
            execution_contract=self._execution_contract(request.patch),
            execution_control_evidence=self._execution_control_evidence(),
            adapter_status=adapter_status,
            adapter_failure_stage=adapter_failure_stage,
            adapter_primary_error=adapter_primary_error,
            adapter_secondary_evidence_failures=adapter_secondary_evidence_failures,
            image_evidence=image_evidence,
            extra=extra,
            adapter_normalized=adapter_normalized,
            official_final_report_resolved=official_final_report_resolved,
            scientific_resolved=scientific_resolved,
        )

    def _purge_private_inputs(self, paths: Sequence[Path]) -> list[dict[str, Any]]:
        """Hash then delete gold/test-bearing grader inputs before handoff.

        The hashes prove which one-row materialization was used without
        redistributing the row, gold patch, test patch, or submitted patch in a
        public artifact. The official harness may still have private internal
        logs; workflows treat the entire grader work directory as restricted.
        """

        evidence: list[dict[str, Any]] = []
        failures: list[str] = []
        for path in paths:
            try:
                resolved = path.resolve()
                if self.output_root not in resolved.parents:
                    failures.append(f"{path.name}: escaped output root")
                    continue
                if not resolved.is_file():
                    continue
                raw = resolved.read_bytes()
                evidence.append({
                    "name": resolved.name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                    "retention": "PURGED_AFTER_HASH_BOUND_GRADING",
                })
                resolved.unlink()
            except OSError as exc:
                failures.append(f"{path.name}: {type(exc).__name__}: {exc}")
        for path in paths:
            try:
                if path.exists():
                    failures.append(f"{path.name}: remains after purge")
            except OSError as exc:
                failures.append(f"{path.name}: existence check failed: {type(exc).__name__}: {exc}")
        if failures:
            raise _PrivateInputPurgeError("; ".join(failures), evidence)
        return evidence

    def _actual_test_evidence(
        self,
        invocation: HarnessInvocation,
        *,
        resolved: bool,
        final_report: Mapping[str, Any],
        expected_patch: str,
    ) -> dict[str, Any]:
        captured: dict[str, Any] = {}
        raw_values: dict[str, bytes] = {}
        try:
            candidates: list[tuple[str, Path]] = [
                ("test_output", invocation.test_output_path),
                ("official_test_status", invocation.test_status_path),
            ]
            if self.target.benchmark_id != "swebench_verified":
                if invocation.container_exit_status_path is None:
                    raise OfficialGraderError(
                        "Multi-SWE container exit-status path is missing"
                    )
                candidates.append(
                    ("container_exit_status", invocation.container_exit_status_path)
                )
            elif invocation.container_exit_status_path is not None:
                candidates.append(
                    ("container_exit_status", invocation.container_exit_status_path)
                )
            for name, path in candidates:
                resolved_path = path.resolve()
                allowed_roots = (
                    (self.output_root,)
                    if name == "container_exit_status"
                    else (self.harness_root, self.output_root)
                )
                if path.is_symlink() or not any(
                    root in resolved_path.parents
                    for root in allowed_roots
                ):
                    raise OfficialGraderError(
                        f"official {name} path escaped the frozen harness roots"
                    )
                if not resolved_path.is_file():
                    raise OfficialGraderError(f"official {name} file is missing")
                raw = resolved_path.read_bytes()
                if not raw or not raw.strip():
                    raise OfficialGraderError(f"official {name} file is empty")
                raw_values[name] = raw
                captured[name] = self._restricted_blob("official-tests", name, raw)
            summary = validate_official_test_evidence(
                self.target,
                source_row=self.source_row,
                test_output_raw=raw_values["test_output"],
                test_status_raw=raw_values["official_test_status"],
                resolved=resolved,
                final_report=final_report,
            )
            captured["semantic_normalization"] = summary
            if self.target.benchmark_id != "swebench_verified":
                captured["container_exit_summary"] = validate_multi_swe_container_exit_status(
                    self.target,
                    raw=raw_values["container_exit_status"],
                    resolved=resolved,
                    test_summary=summary,
                    expected_patch=expected_patch,
                )
            elif invocation.container_exit_status_path is not None:
                raise OfficialGraderError(
                    "SWE-bench unexpectedly has Multi-SWE exit evidence"
                )
        except _ActualTestEvidenceError:
            raise
        except (OSError, UnicodeDecodeError, ValueError, OfficialGraderError) as exc:
            raise _ActualTestEvidenceError(str(exc), captured) from None
        return captured

    def _capture_available_test_references(
        self,
        invocation: HarnessInvocation,
        *,
        secondary_evidence_failures: list[str] | None = None,
    ) -> dict[str, Any]:
        """Best-effort retain raw outputs without replacing an earlier failure."""

        captured: dict[str, Any] = {}
        candidates: list[tuple[str, Path]] = [
            ("test_output", invocation.test_output_path),
            ("official_test_status", invocation.test_status_path),
        ]
        if invocation.container_exit_status_path is not None:
            candidates.append(("container_exit_status", invocation.container_exit_status_path))
        for name, path in candidates:
            try:
                resolved = path.resolve()
                allowed = (
                    self.output_root in resolved.parents
                    or self.harness_root in resolved.parents
                )
                if path.is_symlink() or not allowed or not resolved.is_file():
                    continue
                raw = resolved.read_bytes()
                if raw:
                    captured[name] = self._restricted_blob("official-tests", name, raw)
            except Exception as exc:
                if secondary_evidence_failures is not None:
                    secondary_evidence_failures.append(
                        f"available_{name}_capture: {type(exc).__name__}: "
                        + self._redact(str(exc))
                    )
        return captured

    def _capture_available_report(
        self,
        invocation: HarnessInvocation,
        *,
        secondary_evidence_failures: list[str],
    ) -> dict[str, Any]:
        """Retain and, when possible, classify a report left by a failed command."""

        path = invocation.report_path
        captured: dict[str, Any] = {}
        try:
            resolved_path = path.resolve()
            if (
                path.is_symlink()
                or self.output_root not in resolved_path.parents
                or not resolved_path.is_file()
            ):
                return captured
            raw = resolved_path.read_bytes()
            if not raw:
                return captured
            captured["restricted_raw_report"] = self._restricted_blob(
                "official-report", "report", raw
            )
            try:
                value = strict_json_loads(raw)
                if isinstance(value, Mapping):
                    captured["official_final_report_resolved"] = (
                        parse_official_report(self.target, value)
                    )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OfficialGraderError) as exc:
                secondary_evidence_failures.append(
                    "available_report_classification: "
                    + type(exc).__name__
                    + ": "
                    + self._redact(str(exc))
                )
        except Exception as exc:
            secondary_evidence_failures.append(
                "available_report_capture: "
                + type(exc).__name__
                + ": "
                + self._redact(str(exc))
            )
        return captured

    def _capture_available_outputs(
        self,
        invocation: HarnessInvocation,
        *,
        secondary_evidence_failures: list[str],
    ) -> dict[str, Any]:
        """Best-effort capture every output already materialized by the harness."""

        captured = self._capture_available_test_references(
            invocation,
            secondary_evidence_failures=secondary_evidence_failures,
        )
        report = self._capture_available_report(
            invocation,
            secondary_evidence_failures=secondary_evidence_failures,
        )
        overlap = set(captured) & set(report)
        if overlap:
            secondary_evidence_failures.append(
                "available_output_capture: duplicate evidence fields "
                + repr(sorted(overlap))
            )
        captured.update(report)
        return captured

    @staticmethod
    def _container_start_proven(available: Mapping[str, Any]) -> bool:
        """Conservatively count a container only from post-start artifacts."""

        return any(
            available.get(name) is not None
            for name in ("container_exit_status", "test_output", "official_test_status")
        )

    def _failure(
        self,
        request: GradeRequest,
        started: int,
        *,
        stage: str,
        status: str,
        reason: str,
        stdout: object = "",
        stderr: object = "",
        exit_code: int = -1,
        container_started: bool = False,
        evidence: Sequence[Mapping[str, Any]] = (),
        extra: Mapping[str, Any] | None = None,
        secondary_evidence_failures: Sequence[str] = (),
    ) -> GraderInvocationFailure:
        # Freeze the primary descriptor before attempting any evidence I/O.
        # A full disk, permission error, or even a contract-construction bug is
        # secondary once the official failure has already occurred.
        primary = {"stage": stage, "status": status, "reason": reason}
        secondary = list(secondary_evidence_failures)
        extra_values = dict(extra or {})
        if "harness_invocation_status" not in extra_values:
            extra_values["harness_invocation_status"] = {
                "harness_timeout": "TIMEOUT",
                "harness_launch_failed": "LAUNCH_FAILED",
                "harness_exit_nonzero": "EXIT_NONZERO",
            }.get(status, "NOT_REACHED")
        official_outcome = extra_values.pop("official_final_report_resolved", None)
        if (
            stage == "official_harness"
            and extra_values.get("harness_invocation_status")
            in {"TIMEOUT", "LAUNCH_FAILED", "EXIT_NONZERO"}
            and extra_values.get("harness_restricted_raw_streams") is None
        ):
            try:
                extra_values["harness_restricted_raw_streams"] = (
                    self._restricted_streams("official-harness", stdout, stderr)
                )
            except Exception as exc:  # evidence I/O must never mask the primary
                secondary.append(
                    "restricted_stream_capture: "
                    + type(exc).__name__
                    + ": "
                    + self._redact(str(exc))
                )
        try:
            envelope = self._evidence_envelope(
                request,
                adapter_status="FAILURE",
                adapter_failure_stage=stage,
                adapter_primary_error=primary,
                adapter_secondary_evidence_failures=secondary,
                image_evidence=evidence,
                extra=extra_values,
                adapter_normalized=False,
                official_final_report_resolved=(
                    official_outcome if isinstance(official_outcome, bool) else None
                ),
                scientific_resolved=None,
            )
        except Exception as exc:  # contract evidence is secondary to the primary
            secondary.append(
                "adapter_evidence_construction: "
                + type(exc).__name__
                + ": "
                + self._redact(str(exc))
            )
            # The emergency envelope deliberately performs no filesystem or
            # execution-contract lookup.  It still has the exact v2 field set
            # and retains every already-captured field from ``extra_values``.
            envelope = self._compose_evidence_envelope(
                request,
                execution_contract=None,
                execution_control_evidence=None,
                adapter_status="FAILURE",
                adapter_failure_stage=stage,
                adapter_primary_error=primary,
                adapter_secondary_evidence_failures=secondary,
                image_evidence=evidence,
                extra=extra_values,
                adapter_normalized=False,
                official_final_report_resolved=(
                    official_outcome if isinstance(official_outcome, bool) else None
                ),
                scientific_resolved=None,
            )
        report = {
            "task_id": request.task_id,
            "status": status,
            "failure_stage": stage,
            "reason": reason,
            "_trimem": envelope,
        }
        failure = GraderInvocationFailure(GradeResult(
            task_id=request.task_id, resolved=False, exit_code=exit_code,
            stdout=self._redact(_stream_text(stdout)),
            stderr=self._redact(_stream_text(stderr)), report=report,
            grader_id=f"official-{self.target.benchmark_id}@{self.target.harness_revision}",
            container_digest=self.target.image, official=True,
            wall_time_ms=max(0, (time.perf_counter_ns() - started) // 1_000_000),
            container_started=container_started, status=status,
        ))
        failure.args = (
            f"{reason}; secondary_evidence_failures={secondary}",
        )
        return failure

    def _verify_and_tag(
        self,
        request: GradeRequest,
        started: int,
        image: str,
        tag: str,
        evidence: list[dict[str, Any]],
        *,
        role: str,
    ) -> dict[str, Any]:
        if role not in {"TARGET", "SUPPORT"}:
            raise ValueError("official image evidence role is invalid")
        expected = image.rsplit("@", 1)[1]
        inspect_argv = [
            self.docker_binary,
            "image",
            "inspect",
            "--format",
            "{{json .RepoDigests}}",
            image,
        ]
        current: dict[str, Any] = {
            "schema": OFFICIAL_IMAGE_EVIDENCE_SCHEMA,
            "role": role,
            "image": image,
            "tag": tag,
            "expected": expected,
            "observed": [],
            "inspect_argv": inspect_argv,
            "inspect_invocation_status": "NOT_REACHED",
            "inspect_exit_code": None,
            "inspect_restricted_raw_streams": None,
            "tag_argv": [self.docker_binary, "image", "tag", image, tag],
            "tag_invocation_status": "NOT_REACHED",
            "tag_exit_code": None,
            "tag_restricted_raw_streams": None,
        }

        def capture_stage(
            name: str,
            status: str,
            stdout: object,
            stderr: object,
        ) -> list[str]:
            current[f"{name}_invocation_status"] = status
            try:
                current[f"{name}_restricted_raw_streams"] = (
                    self._restricted_streams(
                        (
                            f"image-{role.lower()}-{name}-"
                            + hashlib.sha256(image.encode("utf-8")).hexdigest()[:16]
                        ),
                        stdout,
                        stderr,
                    )
                )
                return []
            except Exception as exc:
                return [
                    f"image_{name}_stream_capture: "
                    + type(exc).__name__
                    + ": "
                    + self._redact(str(exc))
                ]

        try:
            inspected = self._run(inspect_argv)
        except subprocess.TimeoutExpired as exc:
            secondary = capture_stage(
                "inspect", "TIMEOUT", exc.stdout, exc.stderr
            )
            raise self._failure(
                request, started, stage="image_inspect", status="image_inspect_timeout", reason="timeout",
                stdout=exc.stdout, stderr=exc.stderr,
                evidence=[*evidence, current],
                secondary_evidence_failures=secondary,
            ) from None
        except OSError as exc:
            secondary = capture_stage(
                "inspect", "LAUNCH_FAILED", b"", f"{type(exc).__name__}: {exc}"
            )
            raise self._failure(
                request, started, stage="image_inspect", status="image_inspect_launch_failed",
                reason="launch_failed", stderr=str(exc),
                evidence=[*evidence, current],
                secondary_evidence_failures=secondary,
            ) from None
        secondary = capture_stage(
            "inspect",
            "SUCCESS" if inspected.returncode == 0 else "EXIT_NONZERO",
            inspected.stdout,
            inspected.stderr,
        )
        current["inspect_exit_code"] = inspected.returncode
        if inspected.returncode != 0:
            raise self._failure(
                request, started, stage="image_inspect", status="image_inspect_failed",
                reason="image_unavailable", stdout=inspected.stdout, stderr=inspected.stderr,
                exit_code=inspected.returncode, evidence=[*evidence, current],
                secondary_evidence_failures=secondary,
            )
        try:
            repo_digests = strict_json_loads(_stream_bytes(inspected.stdout))
            if (
                not isinstance(repo_digests, list)
                or not repo_digests
                or any(
                    type(value) is not str
                    or not value
                    or "@sha256:" not in value
                    for value in repo_digests
                )
                or len(repo_digests) != len(set(repo_digests))
            ):
                raise ValueError("RepoDigests is not an exact nonempty string list")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            raise self._failure(
                request, started, stage="image_inspect", status="image_inspect_invalid",
                reason="invalid_repo_digests", stdout=inspected.stdout, stderr=inspected.stderr,
                exit_code=inspected.returncode, evidence=[*evidence, current],
                secondary_evidence_failures=secondary,
            ) from None
        observed = sorted({value.rsplit("@", 1)[-1] for value in repo_digests})
        current["observed"] = observed
        if observed != [expected]:
            raise self._failure(
                request, started, stage="image_inspect", status="image_digest_mismatch",
                reason="digest_mismatch", stdout=inspected.stdout, stderr=inspected.stderr,
                exit_code=inspected.returncode, evidence=[*evidence, current],
                secondary_evidence_failures=secondary,
            )
        if secondary:
            raise self._failure(
                request,
                started,
                stage="image_inspect_evidence",
                status="image_stream_capture_failed",
                reason="restricted_stream_capture_failed",
                stdout=inspected.stdout,
                stderr=inspected.stderr,
                exit_code=inspected.returncode,
                evidence=[*evidence, current],
                secondary_evidence_failures=secondary,
            )
        try:
            tagged = self._run(current["tag_argv"])
        except subprocess.TimeoutExpired as exc:
            secondary = capture_stage("tag", "TIMEOUT", exc.stdout, exc.stderr)
            raise self._failure(
                request, started, stage="image_tag", status="image_tag_timeout", reason="timeout",
                stdout=exc.stdout, stderr=exc.stderr,
                evidence=[*evidence, current],
                secondary_evidence_failures=secondary,
            ) from None
        except OSError as exc:
            secondary = capture_stage(
                "tag", "LAUNCH_FAILED", b"", f"{type(exc).__name__}: {exc}"
            )
            raise self._failure(
                request, started, stage="image_tag", status="image_tag_launch_failed", reason="launch_failed",
                stderr=str(exc), evidence=[*evidence, current],
                secondary_evidence_failures=secondary,
            ) from None
        secondary = capture_stage(
            "tag",
            "SUCCESS" if tagged.returncode == 0 else "EXIT_NONZERO",
            tagged.stdout,
            tagged.stderr,
        )
        current["tag_exit_code"] = tagged.returncode
        if tagged.returncode != 0:
            raise self._failure(
                request, started, stage="image_tag", status="image_tag_failed", reason="tag_failed",
                stdout=tagged.stdout, stderr=tagged.stderr, exit_code=tagged.returncode,
                evidence=[*evidence, current],
                secondary_evidence_failures=secondary,
            )
        if secondary:
            raise self._failure(
                request,
                started,
                stage="image_tag_evidence",
                status="image_stream_capture_failed",
                reason="restricted_stream_capture_failed",
                stdout=tagged.stdout,
                stderr=tagged.stderr,
                exit_code=tagged.returncode,
                evidence=[*evidence, current],
                secondary_evidence_failures=secondary,
            )
        return current

    def grade(self, request: GradeRequest) -> GradeResult:
        if (request.task_id, request.repository, request.base_commit) != (
            self.target.target_id, self.target.repository, self.target.base_commit
        ):
            raise ValueError("grade request does not match frozen benchmark target")
        if not isinstance(request.patch, str) or not request.patch.strip():
            raise ValueError("official grader refuses an empty patch before evaluator execution")
        started = time.perf_counter_ns()
        image_evidence: list[dict[str, Any]] = []
        def purge(
            paths: Sequence[Path],
            *,
            container_started: bool,
            preserve_primary: bool = False,
            available_evidence: Mapping[str, Any] | None = None,
            available_secondary: Sequence[str] = (),
        ) -> tuple[list[dict[str, Any]], list[str]]:
            try:
                return self._purge_private_inputs(paths), []
            except (OSError, OfficialGraderError) as exc:
                retained = (
                    list(exc.evidence)
                    if isinstance(exc, _PrivateInputPurgeError)
                    else []
                )
                secondary = [
                    *available_secondary,
                    "private_input_purge: " + type(exc).__name__ + ": " + str(exc)
                ]
                if preserve_primary:
                    return retained, secondary
                raise self._failure(
                    request, started, stage="private_input_purge",
                    status="private_input_purge_failed", reason=type(exc).__name__,
                    stderr=str(exc), container_started=container_started, evidence=image_evidence,
                    extra={
                        **dict(available_evidence or {}),
                        "materialized_private_inputs": retained,
                    },
                    secondary_evidence_failures=secondary,
                ) from None
        image_evidence.append(self._verify_and_tag(
            request,
            started,
            self.target.image,
            self.target.harness_image_tag,
            image_evidence,
            role="TARGET",
        ))
        for image, tag in self.support_images:
            image_evidence.append(
                self._verify_and_tag(
                    request,
                    started,
                    image,
                    tag,
                    image_evidence,
                    role="SUPPORT",
                )
            )
        task_root = self.output_root / self.target.target_id.replace("/", "_")
        try:
            invocation = build_harness_invocation(
                self.target, row=self.source_row, patch=request.patch, harness_root=self.harness_root,
                run_root=task_root, model_name=self.model_name, python_binary=self.python_binary,
            )
        except (OSError, ValueError, OfficialGraderError) as exc:
            partial_paths = tuple(
                task_root / name for name in (
                    "dataset.json", "dataset.jsonl", "prediction.jsonl", "config.json"
                )
            )
            materialized, purge_secondary = purge(
                partial_paths, container_started=False, preserve_primary=True
            )
            raise self._failure(
                request, started, stage="input_materialization", status="input_materialization_failed",
                reason=type(exc).__name__, stderr=str(exc), evidence=image_evidence,
                extra={"materialized_private_inputs": materialized},
                secondary_evidence_failures=purge_secondary,
            ) from None
        private_paths = invocation.private_input_paths + (
            (invocation.materialized_patch_path,)
            if invocation.materialized_patch_path is not None else ()
        )
        stale_candidates = [
            invocation.test_output_path,
            invocation.test_status_path,
            invocation.report_path,
        ]
        if invocation.container_exit_status_path is not None:
            stale_candidates.append(invocation.container_exit_status_path)
        stale = [path for path in stale_candidates if path.exists()]
        if stale:
            materialized, purge_secondary = purge(
                private_paths, container_started=False, preserve_primary=True
            )
            raise self._failure(
                request, started, stage="official_harness", status="stale_test_evidence",
                reason="preexisting_test_evidence", evidence=image_evidence,
                extra={"invocation_argv": list(invocation.argv),
                       "materialized_private_inputs": materialized,
                       "stale_test_evidence_names": [path.name for path in stale]},
                secondary_evidence_failures=purge_secondary,
            )
        materialized_patch_evidence: dict[str, Any] | None = None

        def capture_patch_after_primary() -> list[str]:
            """Best-effort patch capture that cannot replace an earlier error."""

            nonlocal materialized_patch_evidence
            path = invocation.materialized_patch_path
            if path is None:
                return []
            try:
                if not path.exists() and not path.is_symlink():
                    return []
                materialized_patch_evidence = self._capture_materialized_patch(
                    path, request.patch
                )
                return []
            except _MaterializedPatchEvidenceError as exc:
                materialized_patch_evidence = dict(exc.evidence)
                return [
                    "materialized_patch_capture: "
                    + type(exc).__name__
                    + ": "
                    + str(exc)
                ]
            except (OSError, ValueError, OfficialGraderError) as exc:
                return [
                    "materialized_patch_capture: "
                    + type(exc).__name__
                    + ": "
                    + str(exc)
                ]

        try:
            completed = self._run(invocation.argv, cwd=invocation.cwd, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            capture_secondary: list[str] = []
            available_after_timeout = self._capture_available_outputs(
                invocation, secondary_evidence_failures=capture_secondary
            )
            patch_secondary = capture_patch_after_primary()
            container_started = self._container_start_proven(available_after_timeout)
            materialized, purge_secondary = purge(
                private_paths,
                container_started=container_started,
                preserve_primary=True,
            )
            timeout_extra: dict[str, Any] = {
                "invocation_argv": list(invocation.argv),
                "harness_invocation_status": "TIMEOUT",
                "materialized_private_inputs": materialized,
                **available_after_timeout,
            }
            if materialized_patch_evidence is not None:
                timeout_extra["materialized_patch_evidence"] = (
                    materialized_patch_evidence
                )
            raise self._failure(
                request, started, stage="official_harness", status="harness_timeout", reason="timeout",
                stdout=exc.stdout, stderr=exc.stderr,
                container_started=container_started,
                evidence=image_evidence, extra=timeout_extra,
                secondary_evidence_failures=[
                    *capture_secondary, *patch_secondary, *purge_secondary,
                ],
            ) from None
        except OSError as exc:
            materialized, purge_secondary = purge(
                private_paths, container_started=False, preserve_primary=True
            )
            raise self._failure(
                request, started, stage="official_harness", status="harness_launch_failed", reason="launch_failed",
                stderr=str(exc), container_started=False, evidence=image_evidence,
                extra={"invocation_argv": list(invocation.argv),
                       "harness_invocation_status": "LAUNCH_FAILED",
                       "materialized_private_inputs": materialized},
                secondary_evidence_failures=purge_secondary,
            ) from None

        def command_evidence(
            materialized: Sequence[Mapping[str, Any]],
            report_completed: subprocess.CompletedProcess[str] | None = None,
            *,
            harness_status: str = "SUCCESS",
            report_status: str = "NOT_RUN",
            report_stdout: object = "",
            report_stderr: object = "",
            secondary_evidence_failures: list[str] | None = None,
        ) -> dict[str, Any]:
            evidence: dict[str, Any] = {
                "image_evidence": image_evidence,
                "invocation_argv": list(invocation.argv),
                "harness_invocation_status": harness_status,
                "report_path": str(invocation.report_path.relative_to(task_root)),
                "public_stream_policy": "REDACTED; canonical raw bytes are restricted evidence",
                "materialized_private_inputs": list(materialized),
            }
            try:
                evidence["harness_restricted_raw_streams"] = self._restricted_streams(
                    "official-harness", completed.stdout, completed.stderr
                )
            except Exception as exc:
                if secondary_evidence_failures is None:
                    raise
                secondary_evidence_failures.append(
                    "harness_stream_capture: "
                    + type(exc).__name__
                    + ": "
                    + self._redact(str(exc))
                )
            if materialized_patch_evidence is not None:
                evidence["materialized_patch_evidence"] = materialized_patch_evidence
            if invocation.report_argv:
                evidence["report_invocation_argv"] = list(invocation.report_argv)
                evidence["report_invocation_status"] = report_status
                if report_completed is not None:
                    report_stdout = report_completed.stdout
                    report_stderr = report_completed.stderr
                if report_completed is not None or report_status in {"TIMEOUT", "LAUNCH_FAILED"}:
                    try:
                        evidence["report_restricted_raw_streams"] = self._restricted_streams(
                            "official-report", report_stdout, report_stderr
                        )
                    except Exception as exc:
                        if secondary_evidence_failures is None:
                            raise
                        secondary_evidence_failures.append(
                            "report_stream_capture: "
                            + type(exc).__name__
                            + ": "
                            + self._redact(str(exc))
                        )
            else:
                evidence["report_invocation_argv"] = []
                evidence["report_invocation_status"] = "NOT_APPLICABLE"
                evidence["report_restricted_raw_streams"] = None
            return evidence

        capture_secondary = []
        available_after_harness = self._capture_available_outputs(
            invocation, secondary_evidence_failures=capture_secondary
        )
        container_started = self._container_start_proven(available_after_harness)
        if completed.returncode != 0:
            patch_secondary = capture_patch_after_primary()
            materialized, purge_secondary = purge(
                private_paths,
                container_started=container_started,
                preserve_primary=True,
            )
            command_secondary: list[str] = []
            common = command_evidence(
                materialized,
                harness_status="EXIT_NONZERO",
                secondary_evidence_failures=command_secondary,
            )
            raise self._failure(
                request, started, stage="official_harness", status="harness_exit_nonzero",
                reason="nonzero_exit", stdout=completed.stdout, stderr=completed.stderr,
                exit_code=completed.returncode,
                container_started=container_started, evidence=image_evidence,
                extra={**common, **available_after_harness},
                secondary_evidence_failures=[
                    *capture_secondary,
                    *patch_secondary,
                    *purge_secondary,
                    *command_secondary,
                ],
            )
        if invocation.materialized_patch_path is not None:
            try:
                materialized_patch_evidence = self._capture_materialized_patch(
                    invocation.materialized_patch_path, request.patch
                )
            except _MaterializedPatchEvidenceError as exc:
                materialized_patch_evidence = dict(exc.evidence)
                materialized, purge_secondary = purge(
                    private_paths,
                    container_started=container_started,
                    preserve_primary=True,
                )
                command_secondary = []
                common = command_evidence(
                    materialized, secondary_evidence_failures=command_secondary
                )
                raise self._failure(
                    request, started, stage="submitted_patch_evidence",
                    status="materialized_patch_invalid", reason=str(exc),
                    stdout=completed.stdout, stderr=completed.stderr,
                    exit_code=completed.returncode,
                    container_started=container_started,
                    evidence=image_evidence, extra={**common, **available_after_harness},
                    secondary_evidence_failures=[
                        *capture_secondary,
                        *purge_secondary,
                        *command_secondary,
                    ],
                ) from None
            except (OSError, ValueError, OfficialGraderError) as exc:
                materialized, purge_secondary = purge(
                    private_paths,
                    container_started=container_started,
                    preserve_primary=True,
                )
                command_secondary = []
                common = command_evidence(
                    materialized, secondary_evidence_failures=command_secondary
                )
                raise self._failure(
                    request, started, stage="submitted_patch_evidence",
                    status="materialized_patch_invalid", reason=str(exc),
                    stdout=completed.stdout, stderr=completed.stderr,
                    exit_code=completed.returncode,
                    container_started=container_started,
                    evidence=image_evidence, extra={**common, **available_after_harness},
                    secondary_evidence_failures=[
                        *capture_secondary,
                        *purge_secondary,
                        *command_secondary,
                    ],
                ) from None
        report_completed: subprocess.CompletedProcess[str] | None = None
        if invocation.report_argv:
            try:
                report_completed = self._run(
                    invocation.report_argv, cwd=invocation.cwd, timeout=self.timeout_seconds
                )
            except subprocess.TimeoutExpired as exc:
                report_secondary: list[str] = []
                available_report = self._capture_available_report(
                    invocation,
                    secondary_evidence_failures=report_secondary,
                )
                materialized, purge_secondary = purge(
                    private_paths,
                    container_started=container_started,
                    preserve_primary=True,
                )
                command_secondary = []
                common = command_evidence(
                    materialized,
                    report_status="TIMEOUT",
                    report_stdout=exc.stdout,
                    report_stderr=exc.stderr,
                    secondary_evidence_failures=command_secondary,
                )
                raise self._failure(
                    request, started, stage="official_report", status="report_timeout", reason="timeout",
                    stdout=completed.stdout + _stream_text(exc.stdout),
                    stderr=completed.stderr + _stream_text(exc.stderr),
                    container_started=container_started,
                    evidence=image_evidence,
                    extra={**common, **available_after_harness, **available_report},
                    secondary_evidence_failures=[
                        *capture_secondary,
                        *report_secondary,
                        *purge_secondary,
                        *command_secondary,
                    ],
                ) from None
            except OSError as exc:
                report_secondary = []
                available_report = self._capture_available_report(
                    invocation,
                    secondary_evidence_failures=report_secondary,
                )
                materialized, purge_secondary = purge(
                    private_paths,
                    container_started=container_started,
                    preserve_primary=True,
                )
                command_secondary = []
                common = command_evidence(
                    materialized,
                    report_status="LAUNCH_FAILED",
                    report_stderr=str(exc),
                    secondary_evidence_failures=command_secondary,
                )
                raise self._failure(
                    request, started, stage="official_report", status="report_launch_failed",
                    reason="launch_failed", stdout=completed.stdout,
                    stderr=completed.stderr + str(exc),
                    container_started=container_started,
                    evidence=image_evidence,
                    extra={**common, **available_after_harness, **available_report},
                    secondary_evidence_failures=[
                        *capture_secondary,
                        *report_secondary,
                        *purge_secondary,
                        *command_secondary,
                    ],
                ) from None
            if report_completed.returncode != 0:
                report_secondary = []
                available_report = self._capture_available_report(
                    invocation,
                    secondary_evidence_failures=report_secondary,
                )
                materialized, purge_secondary = purge(
                    private_paths,
                    container_started=container_started,
                    preserve_primary=True,
                )
                command_secondary = []
                common = command_evidence(
                    materialized,
                    report_completed,
                    report_status="EXIT_NONZERO",
                    secondary_evidence_failures=command_secondary,
                )
                raise self._failure(
                    request, started, stage="official_report", status="report_exit_nonzero",
                    reason="nonzero_exit", stdout=completed.stdout + report_completed.stdout,
                    stderr=completed.stderr + report_completed.stderr,
                    exit_code=report_completed.returncode,
                    container_started=container_started,
                    evidence=image_evidence,
                    extra={**common, **available_after_harness, **available_report},
                    secondary_evidence_failures=[
                        *capture_secondary,
                        *report_secondary,
                        *purge_secondary,
                        *command_secondary,
                    ],
                )
        available_capture_failures: list[str] = []
        available_test_references = self._capture_available_test_references(
            invocation,
            secondary_evidence_failures=available_capture_failures,
        )
        container_started = container_started or self._container_start_proven(
            available_test_references
        )
        if available_capture_failures:
            available_report_failures: list[str] = []
            available_report = self._capture_available_report(
                invocation,
                secondary_evidence_failures=available_report_failures,
            )
            materialized, purge_secondary = purge(
                private_paths,
                container_started=container_started,
                preserve_primary=True,
            )
            command_secondary: list[str] = []
            common = command_evidence(
                materialized,
                report_completed,
                report_status=(
                    "SUCCESS" if report_completed is not None else "NOT_APPLICABLE"
                ),
                secondary_evidence_failures=command_secondary,
            )
            raise self._failure(
                request,
                started,
                stage="adapter_evidence_capture",
                status="adapter_evidence_capture_failed",
                reason="available_test_evidence_capture_failed",
                stdout=completed.stdout
                + (report_completed.stdout if report_completed else ""),
                stderr=completed.stderr
                + (report_completed.stderr if report_completed else ""),
                exit_code=completed.returncode,
                container_started=container_started,
                evidence=image_evidence,
                extra={
                    **common,
                    **available_test_references,
                    **available_report,
                },
                secondary_evidence_failures=[
                    *capture_secondary,
                    *available_capture_failures,
                    *available_report_failures,
                    *purge_secondary,
                    *command_secondary,
                ],
            )
        try:
            available_command_evidence = command_evidence(
                (),
                report_completed,
                report_status=(
                    "SUCCESS" if report_completed is not None else "NOT_APPLICABLE"
                ),
            )
        except Exception as exc:
            available_report_failures = []
            available_report = self._capture_available_report(
                invocation,
                secondary_evidence_failures=available_report_failures,
            )
            materialized, purge_secondary = purge(
                private_paths,
                container_started=container_started,
                preserve_primary=True,
            )
            command_secondary = [
                "initial_command_evidence_capture: "
                + type(exc).__name__
                + ": "
                + self._redact(str(exc))
            ]
            common = command_evidence(
                materialized,
                report_completed,
                report_status=(
                    "SUCCESS" if report_completed is not None else "NOT_APPLICABLE"
                ),
                secondary_evidence_failures=command_secondary,
            )
            raise self._failure(
                request,
                started,
                stage="adapter_evidence_capture",
                status="adapter_evidence_capture_failed",
                reason=type(exc).__name__,
                stdout=completed.stdout + (report_completed.stdout if report_completed else ""),
                stderr=completed.stderr + (report_completed.stderr if report_completed else "") + str(exc),
                exit_code=completed.returncode,
                container_started=container_started,
                evidence=image_evidence,
                extra={
                    **common,
                    **available_test_references,
                    **available_report,
                },
                secondary_evidence_failures=[
                    *capture_secondary,
                    *available_report_failures,
                    *purge_secondary,
                    *command_secondary,
                ],
            ) from None
        pre_purge_report_failures: list[str] = []
        pre_purge_report = self._capture_available_report(
            invocation,
            secondary_evidence_failures=pre_purge_report_failures,
        )
        materialized, _purge_secondary = purge(
            private_paths,
            container_started=container_started,
            available_evidence={
                **available_command_evidence,
                **available_test_references,
                **pre_purge_report,
            },
            available_secondary=pre_purge_report_failures,
        )
        common = {
            **available_command_evidence,
            "materialized_private_inputs": materialized,
        }
        combined_stdout = completed.stdout + (report_completed.stdout if report_completed else "")
        combined_stderr = completed.stderr + (report_completed.stderr if report_completed else "")
        if not invocation.report_path.is_file():
            raise self._failure(
                request, started, stage="official_report", status="missing_report", reason="missing_report",
                stdout=combined_stdout, stderr=combined_stderr, exit_code=completed.returncode,
                container_started=container_started, evidence=image_evidence,
                extra={**common, **available_test_references},
            )
        try:
            report_raw = invocation.report_path.read_bytes()
            restricted_report = self._restricted_blob(
                "official-report", "report", report_raw
            )
        except (OSError, OfficialGraderError) as exc:
            raise self._failure(
                request,
                started,
                stage="adapter_evidence_capture",
                status="adapter_evidence_capture_failed",
                reason=type(exc).__name__,
                stdout=combined_stdout,
                stderr=combined_stderr,
                exit_code=completed.returncode,
                container_started=container_started,
                evidence=image_evidence,
                extra={**common, **available_test_references},
            ) from None
        try:
            report = strict_json_loads(report_raw)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise self._failure(
                request, started, stage="official_report", status="invalid_report", reason="invalid_report",
                stdout=combined_stdout, stderr=combined_stderr, exit_code=completed.returncode,
                container_started=container_started, evidence=image_evidence,
                extra={
                    **common,
                    **available_test_references,
                    "restricted_raw_report": restricted_report,
                },
            ) from None
        if not isinstance(report, dict):
            raise self._failure(
                request, started, stage="official_report", status="report_schema_mismatch",
                reason="report_root_not_object", stdout=combined_stdout, stderr=combined_stderr,
                exit_code=completed.returncode,
                container_started=container_started, evidence=image_evidence,
                extra={
                    **common,
                    **available_test_references,
                    "restricted_raw_report": restricted_report,
                },
            )
        try:
            resolved = parse_official_report(self.target, report)
        except OfficialGraderError as exc:
            raise self._failure(
                request, started, stage="official_report", status="report_schema_mismatch",
                reason=str(exc), stdout=combined_stdout, stderr=combined_stderr,
                exit_code=completed.returncode,
                container_started=container_started, evidence=image_evidence,
                extra={
                    **common,
                    **available_test_references,
                    "restricted_raw_report": restricted_report,
                },
            ) from None
        try:
            test_evidence = self._actual_test_evidence(
                invocation,
                resolved=resolved,
                final_report=report,
                expected_patch=request.patch,
            )
        except _ActualTestEvidenceError as exc:
            raise self._failure(
                request, started, stage="adapter_semantic_normalization",
                status="adapter_contract_failed", reason=str(exc), stdout=combined_stdout,
                stderr=combined_stderr, exit_code=completed.returncode,
                container_started=container_started, evidence=image_evidence,
                extra={
                    **common,
                    **exc.evidence,
                    "restricted_raw_report": restricted_report,
                    "official_final_report_resolved": resolved,
                },
            ) from None
        except (OSError, UnicodeDecodeError, ValueError, OfficialGraderError) as exc:
            raise self._failure(
                request, started, stage="official_test_evidence",
                status="test_evidence_invalid", reason=str(exc), stdout=combined_stdout,
                stderr=combined_stderr, exit_code=completed.returncode,
                container_started=container_started, evidence=image_evidence,
                extra={
                    **common,
                    **available_test_references,
                    "restricted_raw_report": restricted_report,
                    "official_final_report_resolved": resolved,
                },
            ) from None
        try:
            public_report = {
                "task_id": request.task_id,
                "status": "success",
                "failure_stage": None,
                "reason": None,
                "_trimem": self._evidence_envelope(
                    request,
                    adapter_status="SUCCESS",
                    adapter_failure_stage=None,
                    adapter_primary_error=None,
                    image_evidence=image_evidence,
                    extra={
                        **common,
                        **test_evidence,
                        "restricted_raw_report": restricted_report,
                    },
                    adapter_normalized=True,
                    official_final_report_resolved=resolved,
                    scientific_resolved=resolved,
                ),
            }
            elapsed = max(0, (time.perf_counter_ns() - started) // 1_000_000)
            return GradeResult(
                task_id=request.task_id,
                resolved=resolved,
                exit_code=completed.returncode,
                stdout=self._redact(combined_stdout),
                stderr=self._redact(combined_stderr),
                report=public_report,
                grader_id=(
                    f"official-{self.target.benchmark_id}"
                    f"@{self.target.harness_revision}"
                ),
                container_digest=self.target.image,
                official=True,
                wall_time_ms=elapsed,
                container_started=container_started,
                status="success",
            )
        except Exception as exc:
            raise self._failure(
                request,
                started,
                stage="adapter_evidence_finalization",
                status="adapter_evidence_finalization_failed",
                reason=type(exc).__name__,
                stdout=combined_stdout,
                stderr=combined_stderr,
                exit_code=completed.returncode,
                container_started=container_started,
                evidence=image_evidence,
                extra={
                    **common,
                    **test_evidence,
                    "restricted_raw_report": restricted_report,
                    "official_final_report_resolved": resolved,
                },
                secondary_evidence_failures=[
                    "success_envelope_finalization: "
                    + type(exc).__name__
                    + ": "
                    + self._redact(str(exc))
                ],
            ) from None


def _stream_bytes(value: object) -> bytes:
    if value is None:
        return b""
    raw = getattr(value, "raw_bytes", None)
    if isinstance(raw, bytes):
        return raw
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return str(value).encode("utf-8")


def _stream_text(value: object) -> str:
    return _RawBackedText(value)


__all__ = [
    "FrozenOfficialTarget", "HarnessInvocation", "MULTI_FIX_PATCH_RUN_COMMAND",
    "MULTI_SWE_PREBUILT_EVALUATION", "OFFICIAL_EVIDENCE_FIELDS",
    "OFFICIAL_EVIDENCE_SCHEMA", "OFFICIAL_IMAGE_EVIDENCE_FIELDS",
    "OFFICIAL_IMAGE_EVIDENCE_SCHEMA", "OfficialGraderError",
    "OfficialHarnessGraderGateway", "build_harness_invocation", "canonical_row_hash",
    "adapter_evidence_envelope_contract", "minimal_subprocess_env",
    "parse_official_report", "redact_text",
    "validate_multi_swe_container_exit_status", "validate_official_test_evidence",
]
