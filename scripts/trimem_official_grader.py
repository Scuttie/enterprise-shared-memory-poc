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


Runner = Callable[..., subprocess.CompletedProcess[str]]


def canonical_row_hash(row: Mapping[str, Any]) -> str:
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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
    config = {
        "mode": "evaluation", "workdir": str(workdir), "patch_files": [str(prediction)],
        "dataset_files": [str(dataset)], "force_build": False, "output_dir": str(output_dir),
        "specifics": [f"{org}/{repo}:pr-{number}"], "skips": [], "repo_dir": str(repo_dir),
        "need_clone": False, "global_env": [], "clear_env": True, "stop_on_error": True,
        "max_workers": 1, "max_workers_build_image": 1, "max_workers_run_instance": 1,
        "log_dir": str(log_dir), "log_level": "DEBUG", "log_to_console": True, "human_mode": False,
    }
    config_path = run_root / "config.json"
    _write_json(config_path, config)
    return HarnessInvocation(
        argv=(python_binary, "-m", "multi_swe_bench.harness.run_evaluation", "--config", str(config_path)),
        cwd=harness_root,
        report_path=output_dir / "final_report.json",
        private_input_paths=(dataset, prediction, config_path),
    )


def parse_official_report(target: FrozenOfficialTarget, report: Mapping[str, Any]) -> bool:
    if target.benchmark_id == "swebench_verified":
        resolved = set(report.get("resolved_ids", ()))
        unresolved = set(report.get("unresolved_ids", ()))
        if target.instance_id not in resolved | unresolved or target.instance_id in resolved & unresolved:
            raise OfficialGraderError("SWE-bench report does not classify the exact target")
        if int(report.get("submitted_instances", -1)) != 1:
            raise OfficialGraderError("SWE-bench report submitted target count mismatch")
        return target.instance_id in resolved
    org, repo, number = _parse_instance_number(target.instance_id)
    canonical_id = f"{org}/{repo}:pr-{number}"
    list_fields = (
        "submitted_ids", "completed_ids", "incomplete_ids", "resolved_ids",
        "unresolved_ids", "empty_patch_ids", "error_ids",
    )
    rows: dict[str, list[str]] = {}
    for name in list_fields:
        value = report.get(name)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise OfficialGraderError(f"Multi-SWE-bench report field {name} is invalid")
        rows[name] = value
    count_pairs = {
        "submitted_instances": "submitted_ids", "completed_instances": "completed_ids",
        "incomplete_instances": "incomplete_ids", "resolved_instances": "resolved_ids",
        "unresolved_instances": "unresolved_ids", "empty_patch_instances": "empty_patch_ids",
        "error_instances": "error_ids",
    }
    if report.get("total_instances") != 1 or report.get("submitted_instances") != 1:
        raise OfficialGraderError("Multi-SWE-bench report target count mismatch")
    if rows["submitted_ids"] != [canonical_id]:
        raise OfficialGraderError("Multi-SWE-bench report submitted ID mismatch")
    for count_name, ids_name in count_pairs.items():
        if report.get(count_name) != len(rows[ids_name]):
            raise OfficialGraderError(f"Multi-SWE-bench report count mismatch: {count_name}")
        if any(item != canonical_id for item in rows[ids_name]):
            raise OfficialGraderError(f"Multi-SWE-bench report contains an unknown ID: {ids_name}")
    in_resolved = canonical_id in rows["resolved_ids"]
    non_resolved = any(
        canonical_id in rows[name]
        for name in ("unresolved_ids", "incomplete_ids", "empty_patch_ids", "error_ids")
    )
    if in_resolved == non_resolved:
        raise OfficialGraderError("Multi-SWE-bench report does not uniquely classify the exact target")
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
        report.update(dict(extra or {}))
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
        try:
            completed = self._run(invocation.argv, cwd=invocation.cwd, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            materialized = purge(invocation.private_input_paths, container_started=True)
            raise self._failure(
                request, started, stage="official_harness", status="harness_timeout", reason="timeout",
                stdout=_stream_text(exc.stdout), stderr=_stream_text(exc.stderr), container_started=True,
                evidence=image_evidence, extra={"invocation_argv": list(invocation.argv),
                                                "materialized_private_inputs": materialized},
            ) from None
        except OSError as exc:
            materialized = purge(invocation.private_input_paths, container_started=False)
            raise self._failure(
                request, started, stage="official_harness", status="harness_launch_failed", reason="launch_failed",
                stderr=str(exc), container_started=False, evidence=image_evidence,
                extra={"invocation_argv": list(invocation.argv),
                       "materialized_private_inputs": materialized},
            ) from None
        materialized = purge(invocation.private_input_paths, container_started=True)
        common = {
            "image_evidence": image_evidence,
            "invocation_argv": list(invocation.argv),
            "report_path": str(invocation.report_path.relative_to(task_root)),
            "harness_restricted_raw_streams": self._restricted_streams(
                "official-harness", completed.stdout, completed.stderr
            ),
            "public_stream_policy": "REDACTED; canonical raw bytes are restricted evidence",
            "materialized_private_inputs": materialized,
        }
        if completed.returncode != 0:
            raise self._failure(
                request, started, stage="official_harness", status="harness_exit_nonzero",
                reason="nonzero_exit", stdout=completed.stdout, stderr=completed.stderr,
                exit_code=completed.returncode, container_started=True, evidence=image_evidence, extra=common,
            )
        if not invocation.report_path.is_file():
            raise self._failure(
                request, started, stage="official_harness", status="missing_report", reason="missing_report",
                stdout=completed.stdout, stderr=completed.stderr, exit_code=completed.returncode,
                container_started=True, evidence=image_evidence, extra=common,
            )
        report_raw = invocation.report_path.read_bytes()
        try:
            report = strict_json_loads(report_raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            restricted_report = self._restricted_blob("official-harness", "report", report_raw)
            raise self._failure(
                request, started, stage="official_harness", status="invalid_report", reason="invalid_report",
                stdout=completed.stdout, stderr=completed.stderr, exit_code=completed.returncode,
                container_started=True, evidence=image_evidence,
                extra={**common, "restricted_raw_report": restricted_report},
            ) from None
        if not isinstance(report, dict):
            raise self._failure(
                request, started, stage="official_harness", status="report_schema_mismatch",
                reason="report_root_not_object", stdout=completed.stdout, stderr=completed.stderr,
                exit_code=completed.returncode, container_started=True, evidence=image_evidence, extra=common,
            )
        try:
            resolved = parse_official_report(self.target, report)
        except OfficialGraderError as exc:
            raise self._failure(
                request, started, stage="official_harness", status="report_schema_mismatch",
                reason=str(exc), stdout=completed.stdout, stderr=completed.stderr,
                exit_code=completed.returncode, container_started=True, evidence=image_evidence,
                extra={**common, "raw_report": report},
            ) from None
        report = dict(report)
        report["_trimem"] = {
            "benchmark_id": self.target.benchmark_id,
            "dataset_revision": self.target.dataset_revision,
            "harness_revision": self.target.harness_revision,
            **common,
            "source_row_sha256": self.target.source_row_sha256,
        }
        elapsed = max(0, (time.perf_counter_ns() - started) // 1_000_000)
        return GradeResult(
            task_id=request.task_id, resolved=resolved, exit_code=completed.returncode,
            stdout=self._redact(completed.stdout), stderr=self._redact(completed.stderr), report=report,
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
    "FrozenOfficialTarget", "HarnessInvocation", "OfficialGraderError",
    "OfficialHarnessGraderGateway", "build_harness_invocation", "canonical_row_hash",
    "minimal_subprocess_env", "parse_official_report", "redact_text",
]
