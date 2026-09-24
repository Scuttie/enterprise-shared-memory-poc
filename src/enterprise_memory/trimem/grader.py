"""Fail-closed grader boundary for replay and separately approved official execution."""
from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Callable, Mapping, Optional, Protocol, Sequence

from .accounting import GraderRecord, RawEvidenceLedger, RunAccounting
from .workspace import WorkspaceGraderContext


_DIGEST_REF = re.compile(r"^[a-z0-9./_-]+@sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class GradeResult:
    task_id: str
    resolved: bool
    exit_code: int
    stdout: str
    stderr: str
    report: Mapping[str, object]
    grader_id: str
    container_digest: str
    official: bool
    wall_time_ms: int
    container_started: bool = False
    status: str = "success"


@dataclass(frozen=True)
class GradeRequest:
    task_id: str
    repository: str
    base_commit: str
    patch: str
    workspace: WorkspaceGraderContext

    def __post_init__(self) -> None:
        if not self.task_id or not self.repository or not self.base_commit:
            raise ValueError("grade request task/repository/base commit are required")
        if self.workspace.base_commit not in {None, self.base_commit}:
            raise ValueError("grader workspace base commit mismatch")


class GraderInvocationFailure(RuntimeError):
    """Official container failure whose complete streams/report remain recordable."""

    def __init__(self, result: GradeResult):
        super().__init__("official grader execution failed")
        self.result = result


class GraderGateway(Protocol):
    def grade(self, request: GradeRequest) -> GradeResult: ...


class ReplayGraderGateway:
    """Credential-free grader using a private fixture callback behind the official-shaped interface."""

    def __init__(
        self,
        evaluator: Callable[[Mapping[str, str]], tuple[bool, str, str]],
        *,
        fixture_digest: str,
    ):
        if len(fixture_digest) != 64:
            raise ValueError("fixture_digest must be sha256")
        self._evaluator = evaluator
        self.fixture_digest = fixture_digest

    def grade(self, request: GradeRequest) -> GradeResult:
        start = time.perf_counter_ns()
        resolved, stdout, stderr = self._evaluator(dict(request.workspace.repository_files))
        elapsed = max(0, (time.perf_counter_ns() - start) // 1_000_000)
        report = {
            "task_id": request.task_id,
            "resolved": bool(resolved),
            "fixture_digest": self.fixture_digest,
            "patch_present": bool(request.patch),
            "mode": "credential-free-replay",
        }
        return GradeResult(
            task_id=request.task_id,
            resolved=bool(resolved),
            exit_code=0 if resolved else 1,
            stdout=stdout,
            stderr=stderr,
            report=report,
            grader_id="trimem-official-interface-replay-v1",
            container_digest=f"replay@sha256:{self.fixture_digest}",
            official=False,
            wall_time_ms=elapsed,
        )


@dataclass(frozen=True)
class FrozenDockerGraderTarget:
    task_id: str
    image: str
    command: tuple[str, ...]
    expected_report_name: str = "report.json"

    def __post_init__(self) -> None:
        if not _DIGEST_REF.fullmatch(self.image):
            raise ValueError("grader image must be pinned by sha256 digest")
        if not self.command or any(not isinstance(x, str) or not x for x in self.command):
            raise ValueError("grader command must be an argv tuple")
        if Path(self.expected_report_name).name != self.expected_report_name:
            raise ValueError("report name must be a basename")


class DockerOfficialGraderGateway:
    """Official-container adapter. Constructing it is safe; ``grade`` is an EXEC action.

    Callers must place this behind the separately approved benchmark executor.  There
    is deliberately no shell, tag fallback, swallowed exit, or synthesized report.
    """

    def __init__(self, target: FrozenDockerGraderTarget, *, docker_binary="docker", timeout_seconds=1800):
        self.target = target
        self.docker_binary = docker_binary
        self.timeout_seconds = timeout_seconds

    def grade(self, request: GradeRequest) -> GradeResult:
        if request.task_id != self.target.task_id:
            raise ValueError("grader target mismatch")
        start = time.perf_counter_ns()
        try:
            inspect = subprocess.run(
                [self.docker_binary, "image", "inspect", "--format", "{{json .RepoDigests}}", self.target.image],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GraderInvocationFailure(GradeResult(
                task_id=request.task_id, resolved=False, exit_code=-1,
                stdout=_stream_text(exc.stdout), stderr=_stream_text(exc.stderr),
                report={"task_id": request.task_id, "resolved": False,
                        "failure_stage": "image_inspect", "reason": "timeout"},
                grader_id="official-container-v1", container_digest=self.target.image,
                official=True, wall_time_ms=max(0, (time.perf_counter_ns() - start) // 1_000_000),
                container_started=False, status="image_inspect_timeout",
            )) from None
        except OSError as exc:
            raise GraderInvocationFailure(GradeResult(
                task_id=request.task_id, resolved=False, exit_code=-1,
                stdout="", stderr=str(exc),
                report={"task_id": request.task_id, "resolved": False,
                        "failure_stage": "image_inspect", "reason": "launch_failed"},
                grader_id="official-container-v1", container_digest=self.target.image,
                official=True, wall_time_ms=max(0, (time.perf_counter_ns() - start) // 1_000_000),
                container_started=False, status="image_inspect_launch_failed",
            )) from None
        if inspect.returncode != 0:
            raise GraderInvocationFailure(GradeResult(
                task_id=request.task_id, resolved=False, exit_code=inspect.returncode,
                stdout=inspect.stdout, stderr=inspect.stderr,
                report={"task_id": request.task_id, "resolved": False,
                        "failure_stage": "image_inspect", "reason": "image_unavailable"},
                grader_id="official-container-v1", container_digest=self.target.image,
                official=True, wall_time_ms=max(0, (time.perf_counter_ns() - start) // 1_000_000),
                container_started=False, status="image_inspect_failed",
            ))
        try:
            repo_digests = json.loads(inspect.stdout.strip())
        except json.JSONDecodeError as exc:
            raise GraderInvocationFailure(GradeResult(
                task_id=request.task_id, resolved=False, exit_code=inspect.returncode,
                stdout=inspect.stdout, stderr=inspect.stderr,
                report={"task_id": request.task_id, "resolved": False,
                        "failure_stage": "image_inspect", "reason": "invalid_repo_digests"},
                grader_id="official-container-v1", container_digest=self.target.image,
                official=True, wall_time_ms=max(0, (time.perf_counter_ns() - start) // 1_000_000),
                container_started=False, status="image_inspect_invalid",
            )) from None
        expected_digest = self.target.image.rsplit("@", 1)[1]
        observed = sorted({str(value).rsplit("@", 1)[-1] for value in repo_digests or []})
        if expected_digest not in observed:
            raise GraderInvocationFailure(GradeResult(
                task_id=request.task_id, resolved=False, exit_code=inspect.returncode,
                stdout=inspect.stdout, stderr=inspect.stderr,
                report={"task_id": request.task_id, "resolved": False,
                        "failure_stage": "image_inspect", "reason": "digest_mismatch",
                        "expected_digest": expected_digest, "observed_digests": observed},
                grader_id="official-container-v1", container_digest=self.target.image,
                official=True, wall_time_ms=max(0, (time.perf_counter_ns() - start) // 1_000_000),
                container_started=False, status="image_digest_mismatch",
            ))
        with tempfile.TemporaryDirectory(prefix="trimem-grader-") as temp:
            root = Path(temp)
            output = root / "output"
            output.mkdir()
            if request.workspace.checkout_root is not None:
                repo = Path(request.workspace.checkout_root).resolve()
                if not repo.is_dir():
                    raise ValueError("grader checkout root is missing")
            else:
                repo = root / "repo"
                repo.mkdir()
                for relative, content in request.workspace.repository_files.items():
                    target = (repo / relative).resolve()
                    if repo.resolve() not in target.parents:
                        raise ValueError("repository path traversal")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8", newline="\n")
            (root / "patch.diff").write_text(request.patch, encoding="utf-8", newline="\n")
            argv = [
                self.docker_binary,
                "run",
                "--rm",
                "--network=none",
                "-v",
                f"{repo.resolve()}:/workspace:ro",
                "-v",
                f"{output.resolve()}:/output",
                "-v",
                f"{(root / 'patch.diff').resolve()}:/input/patch.diff:ro",
                self.target.image,
                *self.target.command,
            ]
            try:
                completed = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise GraderInvocationFailure(GradeResult(
                    task_id=request.task_id, resolved=False, exit_code=-1,
                    stdout=_stream_text(exc.stdout), stderr=_stream_text(exc.stderr),
                    report={"task_id": request.task_id, "resolved": False,
                            "failure_stage": "container", "reason": "timeout",
                            "timeout_seconds": self.timeout_seconds,
                            "_trimem_observed_image_digest": expected_digest,
                            "_trimem_image_inspect_stdout": inspect.stdout,
                            "_trimem_image_inspect_stderr": inspect.stderr},
                    grader_id="official-container-v1", container_digest=self.target.image,
                    official=True, wall_time_ms=max(0, (time.perf_counter_ns() - start) // 1_000_000),
                    container_started=True, status="container_timeout",
                )) from None
            except OSError as exc:
                raise GraderInvocationFailure(GradeResult(
                    task_id=request.task_id, resolved=False, exit_code=-1,
                    stdout="", stderr=str(exc),
                    report={"task_id": request.task_id, "resolved": False,
                            "failure_stage": "container", "reason": "launch_failed",
                            "_trimem_observed_image_digest": expected_digest,
                            "_trimem_image_inspect_stdout": inspect.stdout,
                            "_trimem_image_inspect_stderr": inspect.stderr},
                    grader_id="official-container-v1", container_digest=self.target.image,
                    official=True, wall_time_ms=max(0, (time.perf_counter_ns() - start) // 1_000_000),
                    container_started=False, status="container_launch_failed",
                )) from None
            report_path = output / self.target.expected_report_name
            if not report_path.is_file():
                raise GraderInvocationFailure(GradeResult(
                    task_id=request.task_id, resolved=False, exit_code=completed.returncode,
                    stdout=completed.stdout, stderr=completed.stderr,
                    report={"task_id": request.task_id, "resolved": False,
                            "failure_stage": "container", "reason": "missing_report",
                            "expected_report_name": self.target.expected_report_name,
                            "_trimem_observed_image_digest": expected_digest,
                            "_trimem_image_inspect_stdout": inspect.stdout,
                            "_trimem_image_inspect_stderr": inspect.stderr},
                    grader_id="official-container-v1", container_digest=self.target.image,
                    official=True, wall_time_ms=max(0, (time.perf_counter_ns() - start) // 1_000_000),
                    container_started=True, status="missing_report",
                ))
            report_raw = report_path.read_bytes()
            try:
                report = json.loads(report_raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise GraderInvocationFailure(GradeResult(
                    task_id=request.task_id, resolved=False, exit_code=completed.returncode,
                    stdout=completed.stdout, stderr=completed.stderr,
                    report={"task_id": request.task_id, "resolved": False,
                            "failure_stage": "container", "reason": "invalid_report",
                            "raw_report_base64": base64.b64encode(report_raw).decode("ascii"),
                            "_trimem_observed_image_digest": expected_digest,
                            "_trimem_image_inspect_stdout": inspect.stdout,
                            "_trimem_image_inspect_stderr": inspect.stderr},
                    grader_id="official-container-v1", container_digest=self.target.image,
                    official=True, wall_time_ms=max(0, (time.perf_counter_ns() - start) // 1_000_000),
                    container_started=True, status="invalid_report",
                )) from None
            if report.get("task_id") != request.task_id or not isinstance(report.get("resolved"), bool):
                raise GraderInvocationFailure(GradeResult(
                    task_id=request.task_id, resolved=False, exit_code=completed.returncode,
                    stdout=completed.stdout, stderr=completed.stderr,
                    report={"task_id": request.task_id, "resolved": False,
                            "failure_stage": "container", "reason": "report_schema_mismatch",
                            "raw_report_base64": base64.b64encode(report_raw).decode("ascii"),
                            "_trimem_observed_image_digest": expected_digest,
                            "_trimem_image_inspect_stdout": inspect.stdout,
                            "_trimem_image_inspect_stderr": inspect.stderr},
                    grader_id="official-container-v1", container_digest=self.target.image,
                    official=True, wall_time_ms=max(0, (time.perf_counter_ns() - start) // 1_000_000),
                    container_started=True, status="report_schema_mismatch",
                ))
            report = dict(report)
            report["_trimem_observed_image_digest"] = expected_digest
            report["_trimem_image_inspect_stdout"] = inspect.stdout
            report["_trimem_image_inspect_stderr"] = inspect.stderr
            elapsed = max(0, (time.perf_counter_ns() - start) // 1_000_000)
            result = GradeResult(
                task_id=request.task_id,
                resolved=report["resolved"],
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                report=report,
                grader_id="official-container-v1",
                container_digest=self.target.image,
                official=True,
                wall_time_ms=elapsed,
                container_started=True,
                status="success" if completed.returncode == 0 else "container_exit_nonzero",
            )
            if completed.returncode != 0:
                raise GraderInvocationFailure(result)
            return result


class RecordingGraderGateway:
    def __init__(self, delegate: GraderGateway, accounting: RunAccounting, evidence: RawEvidenceLedger, arm: str):
        self.delegate = delegate
        self.accounting = accounting
        self.evidence = evidence
        self.arm = arm

    def grade(self, request: GradeRequest) -> GradeResult:
        patch_ref = self.evidence.put_blob(request.patch)
        self.evidence.append(
            "grader_request",
            {
                "task_id": request.task_id,
                "arm": self.arm,
                "repository": request.repository,
                "base_commit": request.base_commit,
                "workspace_kind": request.workspace.kind,
                "patch": patch_ref,
            },
        )
        try:
            result = self.delegate.grade(request)
        except GraderInvocationFailure as failure:
            self._record_result(request, failure.result)
            raise
        self._record_result(request, result)
        return result

    def _record_result(self, request: GradeRequest, result: GradeResult) -> None:
        stdout_ref = self.evidence.put_blob(result.stdout)
        stderr_ref = self.evidence.put_blob(result.stderr)
        report_ref = self.evidence.put_blob(result.report)
        record = GraderRecord(
            task_id=request.task_id,
            arm=self.arm,
            grader_id=result.grader_id,
            container_digest=result.container_digest,
            exit_code=result.exit_code,
            resolved=result.resolved,
            wall_time_ms=result.wall_time_ms,
            stdout_hash=stdout_ref["sha256"],
            stderr_hash=stderr_ref["sha256"],
            report_hash=report_ref["sha256"],
            official=result.official,
            container_started=result.container_started,
            status=result.status,
        )
        self.accounting.add_grader(record)
        self.evidence.append(
            "grader_result",
            {
                "task_id": request.task_id,
                "arm": self.arm,
                "official": result.official,
                "grader_id": result.grader_id,
                "container_digest": result.container_digest,
                "exit_code": result.exit_code,
                "resolved": result.resolved,
                "container_started": result.container_started,
                "status": result.status,
                "wall_time_ms": result.wall_time_ms,
                "stdout": stdout_ref,
                "stderr": stderr_ref,
                "report": report_ref,
            },
        )


def _stream_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
