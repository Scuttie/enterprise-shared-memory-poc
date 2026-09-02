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


SWE_HARNESS_REVISION = "7a21e05772954cc81471ae19d56f436cecf43c54"
MULTI_HARNESS_REVISION = "24f493f8a103e72312ded4f6b9c89f081d69cb09"
MULTI_ENTRYPOINT = ROOT / "scripts/trimem_multi_swe_entrypoint.py"
MULTI_SWE_PREBUILT_EVALUATION: Mapping[str, object] = MappingProxyType({
    "mode": "instance_only",
    "force_build": False,
    "human_mode": True,
    "need_clone": False,
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


Runner = Callable[..., subprocess.CompletedProcess[str]]


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


def _test_result_summary(value: Any, name: str) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise OfficialGraderError(f"Multi-SWE test result {name} is missing")
    required = {
        "passed_count", "failed_count", "skipped_count",
        "passed_tests", "failed_tests", "skipped_tests",
    }
    if set(value) != required:
        raise OfficialGraderError(f"Multi-SWE test result {name} field set drift")
    rows = {
        kind: _strict_string_list(value[f"{kind}_tests"], f"{name}.{kind}_tests")
        for kind in ("passed", "failed", "skipped")
    }
    for kind, items in rows.items():
        count = value.get(f"{kind}_count")
        if type(count) is not int or count < 0 or count != len(items):
            raise OfficialGraderError(f"Multi-SWE test result {name}.{kind}_count mismatch")
    if any(set(rows[left]) & set(rows[right]) for left, right in (
        ("passed", "failed"), ("passed", "skipped"), ("failed", "skipped")
    )):
        raise OfficialGraderError(f"Multi-SWE test result {name} classifications overlap")
    return {f"{kind}_count": len(rows[kind]) for kind in ("passed", "failed", "skipped")}


def validate_official_test_evidence(
    target: FrozenOfficialTarget,
    *,
    source_row: Mapping[str, Any],
    test_output_raw: bytes,
    test_status_raw: bytes,
    resolved: bool,
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

    org, repo, number = _parse_instance_number(target.instance_id)
    if (
        status.get("org") != org
        or status.get("repo") != repo
        or str(status.get("number")) != number
        or not isinstance(status.get("valid"), bool)
        or status.get("valid") is not resolved
    ):
        raise OfficialGraderError("Multi-SWE official per-instance status identity/result mismatch")
    summaries = {
        name: _test_result_summary(status.get(name), name)
        for name in ("run_result", "test_patch_result", "fix_patch_result")
    }
    fix = summaries["fix_patch_result"]
    fix_total = sum(fix.values())
    if fix_total <= 0:
        raise OfficialGraderError("Multi-SWE official fix test output has no classified tests")
    for name in ("fixed_tests", "p2p_tests", "f2p_tests", "s2p_tests", "n2p_tests"):
        if not isinstance(status.get(name), Mapping):
            raise OfficialGraderError(f"Multi-SWE official test status {name} is missing")
    return {
        "schema": "trimem/official-test-status-summary/1.0",
        "benchmark_id": target.benchmark_id,
        "source": "MULTI_SWE_PER_INSTANCE_REPORT",
        "fix_tests_classified": fix_total,
        "fix_tests_passed": fix["passed_count"],
        "fix_tests_failed": fix["failed_count"],
        "fix_tests_skipped": fix["skipped_count"],
        "resolved": resolved,
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
    path.parent.mkdir(parents=True, exist_ok=True)
    if lines:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    else:
        raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(raw, encoding="utf-8", newline="\n")


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
    _write_json(config_path, config)
    return HarnessInvocation(
        argv=(
            python_binary,
            str(MULTI_ENTRYPOINT),
            "--harness-root",
            str(harness_root),
            "--config",
            str(config_path),
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
    org, repo, number = _parse_instance_number(target.instance_id)
    canonical_id = f"{org}/{repo}:pr-{number}"
    list_fields = (
        "submitted_ids", "completed_ids", "incomplete_ids", "resolved_ids",
        "unresolved_ids", "empty_patch_ids", "error_ids",
    )
    rows: dict[str, list[str]] = {}
    for name in list_fields:
        rows[name] = _strict_string_list(report.get(name), f"summary.{name}")
    count_pairs = {
        "submitted_instances": "submitted_ids", "completed_instances": "completed_ids",
        "incomplete_instances": "incomplete_ids", "resolved_instances": "resolved_ids",
        "unresolved_instances": "unresolved_ids", "empty_patch_instances": "empty_patch_ids",
        "error_instances": "error_ids",
    }
    if (
        not _exact_int(report.get("total_instances"), 1)
        or not _exact_int(report.get("submitted_instances"), 1)
    ):
        raise OfficialGraderError("Multi-SWE-bench report target count mismatch")
    if rows["submitted_ids"] != [canonical_id]:
        raise OfficialGraderError("Multi-SWE-bench report submitted ID mismatch")
    for count_name, ids_name in count_pairs.items():
        if not _exact_int(report.get(count_name), len(rows[ids_name])):
            raise OfficialGraderError(f"Multi-SWE-bench report count mismatch: {count_name}")
        if any(item != canonical_id for item in rows[ids_name]):
            raise OfficialGraderError(f"Multi-SWE-bench report contains an unknown ID: {ids_name}")
    if (
        rows["completed_ids"] != [canonical_id]
        or rows["incomplete_ids"]
        or rows["empty_patch_ids"]
        or rows["error_ids"]
        or not _exact_int(report.get("completed_instances"), 1)
        or not _exact_int(report.get("incomplete_instances"), 0)
        or not _exact_int(report.get("empty_patch_instances"), 0)
        or not _exact_int(report.get("error_instances"), 0)
    ):
        raise OfficialGraderError("Multi-SWE-bench report does not prove one completed non-empty-patch evaluation")
    in_resolved = canonical_id in rows["resolved_ids"]
    in_unresolved = canonical_id in rows["unresolved_ids"]
    if in_resolved == in_unresolved:
        raise OfficialGraderError("Multi-SWE-bench report does not uniquely classify the exact target")
    if set(rows["resolved_ids"]) | set(rows["unresolved_ids"]) != {canonical_id}:
        raise OfficialGraderError("Multi-SWE-bench report resolution target set mismatch")
    return in_resolved


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

    def _run(self, argv: Sequence[str], *, cwd: Path | None = None, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        return self.runner(list(argv), cwd=cwd, env=dict(self.execution_env), capture_output=True,
                           text=True, timeout=timeout, check=False)

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
        if target.exists() and target.read_bytes() != raw:
            raise OfficialGraderError("restricted evidence digest collision")
        if not target.exists():
            target.write_bytes(raw)
            try:
                target.chmod(0o600)
            except OSError:
                pass
        return {
            "path": target.relative_to(self.output_root).as_posix(),
            "sha256": digest,
            "bytes": len(raw),
            "access": "RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS",
        }

    def _restricted_streams(self, stage: str, stdout: str, stderr: str) -> dict[str, Any]:
        return {
            "stdout": self._restricted_blob(stage, "stdout", stdout.encode("utf-8", errors="replace")),
            "stderr": self._restricted_blob(stage, "stderr", stderr.encode("utf-8", errors="replace")),
        }

    def _redact(self, value: str) -> str:
        return redact_text(value, self._secret_values)

    def _purge_private_inputs(self, paths: Sequence[Path]) -> list[dict[str, Any]]:
        """Hash then delete gold/test-bearing grader inputs before handoff.

        The hashes prove which one-row materialization was used without
        redistributing the row, gold patch, test patch, or submitted patch in a
        public artifact. The official harness may still have private internal
        logs; workflows treat the entire grader work directory as restricted.
        """

        evidence = []
        for path in paths:
            resolved = path.resolve()
            if self.output_root not in resolved.parents:
                raise OfficialGraderError("private grader input escaped output root")
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
        if any(path.exists() for path in paths):
            raise OfficialGraderError("private grader input purge failed")
        return evidence

    def _actual_test_evidence(
        self,
        invocation: HarnessInvocation,
        *,
        resolved: bool,
    ) -> dict[str, Any]:
        captured: dict[str, dict[str, Any]] = {}
        raw_values: dict[str, bytes] = {}
        for name, path in (
            ("test_output", invocation.test_output_path),
            ("official_test_status", invocation.test_status_path),
        ):
            resolved_path = path.resolve()
            if path.is_symlink() or not any(
                root in resolved_path.parents for root in (self.harness_root, self.output_root)
            ):
                raise OfficialGraderError(f"official {name} path escaped the frozen harness roots")
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
        )
        return {**captured, "summary": summary}

    def _failure(
        self,
        request: GradeRequest,
        started: int,
        *,
        stage: str,
        status: str,
        reason: str,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = -1,
        container_started: bool = False,
        evidence: Sequence[Mapping[str, Any]] = (),
        extra: Mapping[str, Any] | None = None,
    ) -> GraderInvocationFailure:
        restricted = self._restricted_streams(stage, stdout, stderr)
        report = {
            "task_id": request.task_id,
            "resolved": False,
            "failure_stage": stage,
            "reason": reason,
            "image_evidence": list(evidence),
            "restricted_raw_streams": restricted,
            "public_stream_policy": "REDACTED; canonical raw bytes are restricted evidence",
        }
        extra_values = dict(extra or {})
        report.update(extra_values)
        trimem: dict[str, Any] = {
            "execution_contract": self._execution_contract(request.patch),
            "execution_control_evidence": self._execution_control_evidence(),
        }
        if isinstance(extra_values.get("materialized_patch_evidence"), Mapping):
            trimem["materialized_patch_evidence"] = extra_values["materialized_patch_evidence"]
        report["_trimem"] = trimem
        return GraderInvocationFailure(GradeResult(
            task_id=request.task_id, resolved=False, exit_code=exit_code,
            stdout=self._redact(stdout), stderr=self._redact(stderr), report=report,
            grader_id=f"official-{self.target.benchmark_id}@{self.target.harness_revision}",
            container_digest=self.target.image, official=True,
            wall_time_ms=max(0, (time.perf_counter_ns() - started) // 1_000_000),
            container_started=container_started, status=status,
        ))

    def _verify_and_tag(
        self,
        request: GradeRequest,
        started: int,
        image: str,
        tag: str,
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            inspected = self._run(
                [self.docker_binary, "image", "inspect", "--format", "{{json .RepoDigests}}", image]
            )
        except subprocess.TimeoutExpired as exc:
            raise self._failure(
                request, started, stage="image_inspect", status="image_inspect_timeout", reason="timeout",
                stdout=_stream_text(exc.stdout), stderr=_stream_text(exc.stderr), evidence=evidence,
            ) from None
        except OSError as exc:
            raise self._failure(
                request, started, stage="image_inspect", status="image_inspect_launch_failed",
                reason="launch_failed", stderr=str(exc), evidence=evidence,
            ) from None
        if inspected.returncode != 0:
            raise self._failure(
                request, started, stage="image_inspect", status="image_inspect_failed",
                reason="image_unavailable", stdout=inspected.stdout, stderr=inspected.stderr,
                exit_code=inspected.returncode, evidence=evidence,
            )
        try:
            repo_digests = strict_json_loads(inspected.stdout.strip())
        except json.JSONDecodeError:
            raise self._failure(
                request, started, stage="image_inspect", status="image_inspect_invalid",
                reason="invalid_repo_digests", stdout=inspected.stdout, stderr=inspected.stderr,
                exit_code=inspected.returncode, evidence=evidence,
            ) from None
        expected = image.rsplit("@", 1)[1]
        observed = sorted({str(value).rsplit("@", 1)[-1] for value in repo_digests or []})
        current = {"image": image, "tag": tag, "expected": expected, "observed": observed,
                   "inspect_stdout": self._redact(inspected.stdout),
                   "inspect_stderr": self._redact(inspected.stderr),
                   "inspect_restricted_raw_streams": self._restricted_streams(
                       "image-inspect-" + expected, inspected.stdout, inspected.stderr
                   )}
        if expected not in observed:
            raise self._failure(
                request, started, stage="image_inspect", status="image_digest_mismatch",
                reason="digest_mismatch", stdout=inspected.stdout, stderr=inspected.stderr,
                exit_code=inspected.returncode, evidence=[*evidence, current],
            )
        try:
            tagged = self._run([self.docker_binary, "image", "tag", image, tag])
        except subprocess.TimeoutExpired as exc:
            raise self._failure(
                request, started, stage="image_tag", status="image_tag_timeout", reason="timeout",
                stdout=_stream_text(exc.stdout), stderr=_stream_text(exc.stderr), evidence=[*evidence, current],
            ) from None
        except OSError as exc:
            raise self._failure(
                request, started, stage="image_tag", status="image_tag_launch_failed", reason="launch_failed",
                stderr=str(exc), evidence=[*evidence, current],
            ) from None
        current.update({
            "tag_stdout": self._redact(tagged.stdout), "tag_stderr": self._redact(tagged.stderr),
            "tag_restricted_raw_streams": self._restricted_streams(
                "image-tag-" + expected, tagged.stdout, tagged.stderr
            ),
        })
        if tagged.returncode != 0:
            raise self._failure(
                request, started, stage="image_tag", status="image_tag_failed", reason="tag_failed",
                stdout=tagged.stdout, stderr=tagged.stderr, exit_code=tagged.returncode,
                evidence=[*evidence, current],
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
        def purge(paths: Sequence[Path], *, container_started: bool) -> list[dict[str, Any]]:
            try:
                return self._purge_private_inputs(paths)
            except (OSError, OfficialGraderError) as exc:
                raise self._failure(
                    request, started, stage="private_input_purge",
                    status="private_input_purge_failed", reason=type(exc).__name__,
                    stderr=str(exc), container_started=container_started, evidence=image_evidence,
                ) from None
        image_evidence.append(self._verify_and_tag(
            request, started, self.target.image, self.target.harness_image_tag, image_evidence
        ))
        for image, tag in self.support_images:
            image_evidence.append(self._verify_and_tag(request, started, image, tag, image_evidence))
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
            materialized = purge(partial_paths, container_started=False)
            raise self._failure(
                request, started, stage="input_materialization", status="input_materialization_failed",
                reason=type(exc).__name__, stderr=str(exc), evidence=image_evidence,
                extra={"materialized_private_inputs": materialized},
            ) from None
        private_paths = invocation.private_input_paths + (
            (invocation.materialized_patch_path,)
            if invocation.materialized_patch_path is not None else ()
        )
        stale = [
            path for path in (invocation.test_output_path, invocation.test_status_path)
            if path.exists()
        ]
        if stale:
            materialized = purge(private_paths, container_started=False)
            raise self._failure(
                request, started, stage="official_harness", status="stale_test_evidence",
                reason="preexisting_test_evidence", evidence=image_evidence,
                extra={"materialized_private_inputs": materialized,
                       "stale_test_evidence_names": [path.name for path in stale]},
            )
        try:
            completed = self._run(invocation.argv, cwd=invocation.cwd, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            materialized = purge(private_paths, container_started=True)
            raise self._failure(
                request, started, stage="official_harness", status="harness_timeout", reason="timeout",
                stdout=_stream_text(exc.stdout), stderr=_stream_text(exc.stderr), container_started=True,
                evidence=image_evidence, extra={"invocation_argv": list(invocation.argv),
                                                "materialized_private_inputs": materialized},
            ) from None
        except OSError as exc:
            materialized = purge(private_paths, container_started=False)
            raise self._failure(
                request, started, stage="official_harness", status="harness_launch_failed", reason="launch_failed",
                stderr=str(exc), container_started=False, evidence=image_evidence,
                extra={"invocation_argv": list(invocation.argv),
                       "materialized_private_inputs": materialized},
            ) from None

        materialized_patch_evidence: dict[str, Any] | None = None

        def command_evidence(
            materialized: Sequence[Mapping[str, Any]],
            report_completed: subprocess.CompletedProcess[str] | None = None,
            *,
            report_status: str = "NOT_RUN",
        ) -> dict[str, Any]:
            evidence: dict[str, Any] = {
                "image_evidence": image_evidence,
                "invocation_argv": list(invocation.argv),
                "report_path": str(invocation.report_path.relative_to(task_root)),
                "harness_restricted_raw_streams": self._restricted_streams(
                    "official-harness", completed.stdout, completed.stderr
                ),
                "public_stream_policy": "REDACTED; canonical raw bytes are restricted evidence",
                "materialized_private_inputs": list(materialized),
            }
            if materialized_patch_evidence is not None:
                evidence["materialized_patch_evidence"] = materialized_patch_evidence
            if invocation.report_argv:
                evidence["report_invocation_argv"] = list(invocation.report_argv)
                evidence["report_invocation_status"] = report_status
                if report_completed is not None:
                    evidence["report_restricted_raw_streams"] = self._restricted_streams(
                        "official-report", report_completed.stdout, report_completed.stderr
                    )
            return evidence

        if completed.returncode != 0:
            materialized = purge(private_paths, container_started=True)
            common = command_evidence(materialized)
            raise self._failure(
                request, started, stage="official_harness", status="harness_exit_nonzero",
                reason="nonzero_exit", stdout=completed.stdout, stderr=completed.stderr,
                exit_code=completed.returncode, container_started=True, evidence=image_evidence, extra=common,
            )
        if invocation.materialized_patch_path is not None:
            try:
                materialized_patch_evidence = self._capture_materialized_patch(
                    invocation.materialized_patch_path, request.patch
                )
            except _MaterializedPatchEvidenceError as exc:
                materialized_patch_evidence = dict(exc.evidence)
                materialized = purge(private_paths, container_started=True)
                common = command_evidence(materialized)
                raise self._failure(
                    request, started, stage="submitted_patch_evidence",
                    status="materialized_patch_invalid", reason=str(exc),
                    stdout=completed.stdout, stderr=completed.stderr,
                    exit_code=completed.returncode, container_started=True,
                    evidence=image_evidence, extra=common,
                ) from None
            except (OSError, ValueError, OfficialGraderError) as exc:
                materialized = purge(private_paths, container_started=True)
                common = command_evidence(materialized)
                raise self._failure(
                    request, started, stage="submitted_patch_evidence",
                    status="materialized_patch_invalid", reason=str(exc),
                    stdout=completed.stdout, stderr=completed.stderr,
                    exit_code=completed.returncode, container_started=True,
                    evidence=image_evidence, extra=common,
                ) from None
        report_completed: subprocess.CompletedProcess[str] | None = None
        if invocation.report_argv:
            try:
                report_completed = self._run(
                    invocation.report_argv, cwd=invocation.cwd, timeout=self.timeout_seconds
                )
            except subprocess.TimeoutExpired as exc:
                materialized = purge(private_paths, container_started=True)
                common = command_evidence(materialized, report_status="TIMEOUT")
                raise self._failure(
                    request, started, stage="official_report", status="report_timeout", reason="timeout",
                    stdout=completed.stdout + _stream_text(exc.stdout),
                    stderr=completed.stderr + _stream_text(exc.stderr), container_started=True,
                    evidence=image_evidence, extra=common,
                ) from None
            except OSError as exc:
                materialized = purge(private_paths, container_started=True)
                common = command_evidence(materialized, report_status="LAUNCH_FAILED")
                raise self._failure(
                    request, started, stage="official_report", status="report_launch_failed",
                    reason="launch_failed", stdout=completed.stdout,
                    stderr=completed.stderr + str(exc), container_started=True,
                    evidence=image_evidence, extra=common,
                ) from None
            if report_completed.returncode != 0:
                materialized = purge(private_paths, container_started=True)
                common = command_evidence(
                    materialized, report_completed, report_status="EXIT_NONZERO"
                )
                raise self._failure(
                    request, started, stage="official_report", status="report_exit_nonzero",
                    reason="nonzero_exit", stdout=completed.stdout + report_completed.stdout,
                    stderr=completed.stderr + report_completed.stderr,
                    exit_code=report_completed.returncode, container_started=True,
                    evidence=image_evidence, extra=common,
                )
        materialized = purge(private_paths, container_started=True)
        common = command_evidence(
            materialized,
            report_completed,
            report_status="SUCCESS" if report_completed is not None else "NOT_APPLICABLE",
        )
        combined_stdout = completed.stdout + (report_completed.stdout if report_completed else "")
        combined_stderr = completed.stderr + (report_completed.stderr if report_completed else "")
        if not invocation.report_path.is_file():
            raise self._failure(
                request, started, stage="official_harness", status="missing_report", reason="missing_report",
                stdout=combined_stdout, stderr=combined_stderr, exit_code=completed.returncode,
                container_started=True, evidence=image_evidence, extra=common,
            )
        report_raw = invocation.report_path.read_bytes()
        try:
            report = strict_json_loads(report_raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            restricted_report = self._restricted_blob("official-harness", "report", report_raw)
            raise self._failure(
                request, started, stage="official_harness", status="invalid_report", reason="invalid_report",
                stdout=combined_stdout, stderr=combined_stderr, exit_code=completed.returncode,
                container_started=True, evidence=image_evidence,
                extra={**common, "restricted_raw_report": restricted_report},
            ) from None
        if not isinstance(report, dict):
            raise self._failure(
                request, started, stage="official_harness", status="report_schema_mismatch",
                reason="report_root_not_object", stdout=combined_stdout, stderr=combined_stderr,
                exit_code=completed.returncode, container_started=True, evidence=image_evidence, extra=common,
            )
        try:
            resolved = parse_official_report(self.target, report)
        except OfficialGraderError as exc:
            raise self._failure(
                request, started, stage="official_harness", status="report_schema_mismatch",
                reason=str(exc), stdout=combined_stdout, stderr=combined_stderr,
                exit_code=completed.returncode, container_started=True, evidence=image_evidence,
                extra={**common, "raw_report": report},
            ) from None
        try:
            test_evidence = self._actual_test_evidence(invocation, resolved=resolved)
        except (OSError, UnicodeDecodeError, ValueError, OfficialGraderError) as exc:
            raise self._failure(
                request, started, stage="official_test_evidence",
                status="test_evidence_invalid", reason=str(exc), stdout=combined_stdout,
                stderr=combined_stderr, exit_code=completed.returncode,
                container_started=True, evidence=image_evidence,
                extra={**common, "raw_report": report},
            ) from None
        report = dict(report)
        report["_trimem"] = {
            "benchmark_id": self.target.benchmark_id,
            "dataset_revision": self.target.dataset_revision,
            "execution_contract": self._execution_contract(request.patch),
            "execution_control_evidence": self._execution_control_evidence(),
            "harness_revision": self.target.harness_revision,
            **common,
            "source_row_sha256": self.target.source_row_sha256,
            "test_evidence": test_evidence,
        }
        elapsed = max(0, (time.perf_counter_ns() - started) // 1_000_000)
        return GradeResult(
            task_id=request.task_id, resolved=resolved, exit_code=completed.returncode,
            stdout=self._redact(combined_stdout), stderr=self._redact(combined_stderr), report=report,
            grader_id=f"official-{self.target.benchmark_id}@{self.target.harness_revision}",
            container_digest=self.target.image, official=True, wall_time_ms=elapsed,
            container_started=True, status="success",
        )


def _stream_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


__all__ = [
    "FrozenOfficialTarget", "HarnessInvocation", "MULTI_SWE_PREBUILT_EVALUATION", "OfficialGraderError",
    "OfficialHarnessGraderGateway", "build_harness_invocation", "canonical_row_hash",
    "minimal_subprocess_env", "parse_official_report", "redact_text",
    "validate_official_test_evidence",
]
