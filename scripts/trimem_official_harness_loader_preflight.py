"""Credential-free exact-loader and pinned-harness import preflight.

This command performs no model/API operation, image operation, Docker
operation, patch application, or official grading.  It is intended to run on
the protected runner before credentials are materialized.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from trimem_atomic_evidence import atomic_write_bytes  # noqa: E402
from trimem_harness_lock import (  # noqa: E402
    HarnessLockError,
    validate_pristine_checkout,
)
from trimem_official_grader import (  # noqa: E402
    MULTI_HARNESS_REVISION,
    SWE_ENTRYPOINT,
    SWE_HARNESS_REVISION,
    FrozenOfficialTarget,
    build_harness_invocation,
    canonical_row_hash,
    minimal_subprocess_env,
)
from trimem_official_harness_loader import (  # noqa: E402
    OfficialHarnessPythonLoader,
    OfficialHarnessPythonLoaderError,
    build_official_harness_python_loader,
)


PREFLIGHT_SCHEMA = "trimem/official-harness-loader-preflight/1.0"
PREFLIGHT_PASS = "TRIMEM_OFFICIAL_HARNESS_LOADER_PREFLIGHT_PASS"
PREFLIGHT_NOT_READY = "TRIMEM_OFFICIAL_HARNESS_LOADER_PREFLIGHT_NOT_READY"
MULTI_SELF_CHECK_SCHEMA = "trimem/multi-swe-loader-self-check/1.0"
SWE_IMPORT_PROBE_SCHEMA = "trimem/swe-bench-loader-import-probe/1.0"
ZERO_COUNTERS: Mapping[str, object] = {
    "model_metadata_requests": 0,
    "model_generation_calls": 0,
    "paid_calls": 0,
    "image_pulls": 0,
    "grader_attempts": 0,
    "grader_containers": 0,
    "usd": 0,
}


class OfficialHarnessLoaderPreflightError(RuntimeError):
    """The exact official-harness launch surface is not ready."""


ProcessRunner = Callable[..., subprocess.CompletedProcess[object]]
LoaderBuilder = Callable[..., OfficialHarnessPythonLoader]
EnvironmentBuilder = Callable[..., dict[str, str]]


def _raw(value: object) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return str(value).encode("utf-8")


def _strict_object(raw: bytes, *, description: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise OfficialHarnessLoaderPreflightError(
                    f"{description} contains duplicate fields"
                )
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfficialHarnessLoaderPreflightError(
            f"{description} is not strict UTF-8 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise OfficialHarnessLoaderPreflightError(f"{description} is not an object")
    return value


def _run(
    runner: ProcessRunner,
    argv: list[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    description: str,
) -> tuple[subprocess.CompletedProcess[object], bytes, bytes]:
    try:
        completed = runner(
            argv,
            cwd=cwd,
            env=dict(environment),
            capture_output=True,
            text=False,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OfficialHarnessLoaderPreflightError(f"{description} did not start") from exc
    stdout, stderr = _raw(completed.stdout), _raw(completed.stderr)
    if completed.returncode != 0:
        raise OfficialHarnessLoaderPreflightError(
            f"{description} exited {completed.returncode}"
        )
    return completed, stdout, stderr


def _verify_revision(
    root: Path,
    revision: str,
    *,
    runner: ProcessRunner,
    environment: Mapping[str, str],
    label: str,
) -> dict[str, object]:
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise OfficialHarnessLoaderPreflightError(f"{label} root is not a directory")
    completed, stdout, stderr = _run(
        runner,
        ["git", "-C", str(resolved), "rev-parse", "HEAD"],
        cwd=resolved,
        environment=environment,
        description=f"{label} revision probe",
    )
    del completed
    try:
        observed = stdout.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise OfficialHarnessLoaderPreflightError(
            f"{label} revision output is not ASCII"
        ) from exc
    if observed != revision:
        raise OfficialHarnessLoaderPreflightError(f"{label} revision differs")
    return {
        "cwd": str(resolved),
        "revision": observed,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "status": "PASS",
    }


def _swe_import_check(
    root: Path,
    *,
    python_binary: str,
    runner: ProcessRunner,
    environment: Mapping[str, str],
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(
        prefix="trimem-swe-task-local-preflight-"
    ) as directory:
        task_local_root = Path(directory).resolve(strict=True)
        argv = [
            python_binary,
            "-P",
            str(SWE_ENTRYPOINT),
            "--harness-root",
            str(root.resolve(strict=True)),
            "--self-check",
        ]
        completed, stdout, stderr = _run(
            runner,
            argv,
            cwd=task_local_root,
            environment=environment,
            description="task-local SWE-bench entrypoint import probe",
        )
    payload = _strict_object(stdout, description="SWE-bench import probe output")
    if (
        payload.get("schema") != SWE_IMPORT_PROBE_SCHEMA
        or payload.get("status") != "PASS"
        or set(payload) != {"schema", "status", "modules"}
        or not isinstance(payload.get("modules"), dict)
        or set(payload["modules"])
        != {"swebench.harness.run_evaluation", "docker", "datasets", "unidiff"}
    ):
        raise OfficialHarnessLoaderPreflightError("SWE-bench import probe contract differs")
    return {
        "argv": argv,
        "cwd": "<TASK_LOCAL_PREFLIGHT_ROOT>",
        "exit_code": completed.returncode,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "modules": payload["modules"],
        "status": "PASS",
    }


def _multi_self_check(
    root: Path,
    *,
    python_binary: str,
    runner: ProcessRunner,
    environment: Mapping[str, str],
) -> dict[str, object]:
    entrypoint = (ROOT / "scripts/trimem_multi_swe_entrypoint.py").resolve(strict=True)
    argv = [
        python_binary,
        str(entrypoint),
        "--loader-self-check",
        "--harness-root",
        str(root),
    ]
    completed, stdout, stderr = _run(
        runner,
        argv,
        cwd=root,
        environment=environment,
        description="Multi-SWE loader self-check",
    )
    payload = _strict_object(stdout, description="Multi-SWE loader self-check output")
    if (
        payload.get("schema") != MULTI_SELF_CHECK_SCHEMA
        or payload.get("status") != "PASS"
        or payload.get("harness_revision") != MULTI_HARNESS_REVISION
    ):
        raise OfficialHarnessLoaderPreflightError("Multi-SWE self-check contract differs")
    for name, expected in ZERO_COUNTERS.items():
        if payload.get(name) != expected:
            raise OfficialHarnessLoaderPreflightError(
                "Multi-SWE self-check non-execution counters differ"
            )
    return {
        "argv": argv,
        "cwd": str(root.resolve(strict=True)),
        "exit_code": completed.returncode,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "payload": payload,
        "status": "PASS",
    }


def _normalized_invocation_argv(
    argv: tuple[str, ...], *, temporary_root: Path
) -> list[str]:
    root = temporary_root.resolve(strict=True)
    normalized: list[str] = []
    for item in argv:
        candidate = Path(item)
        if candidate.is_absolute():
            try:
                relative = candidate.resolve().relative_to(root)
            except (OSError, ValueError):
                pass
            else:
                normalized.append(
                    "<PREFLIGHT_RUN_ROOT>/" + relative.as_posix()
                )
                continue
        normalized.append(item)
    return normalized


def build_invocation_construction_evidence(
    *,
    python_binary: str,
    swe_root: Path,
    multi_root: Path,
    environment_identity_sha256: str,
) -> dict[str, object]:
    swe_row = {
        "instance_id": "trimem__loader-1",
        "repo": "trimem/loader",
        "base_commit": "1" * 40,
    }
    multi_row = {
        "org": "trimem",
        "repo": "loader",
        "number": 1,
        "base": {"sha": "2" * 40},
    }
    image = "trimem/loader@sha256:" + "3" * 64
    tag = "trimem/loader:preflight"
    with tempfile.TemporaryDirectory(prefix="trimem-loader-preflight-") as directory:
        temporary = Path(directory)
        swe_target = FrozenOfficialTarget(
            target_id="swebench_verified--trimem__loader-1",
            benchmark_id="swebench_verified",
            instance_id="trimem__loader-1",
            repository="trimem/loader",
            base_commit="1" * 40,
            dataset_revision="4" * 40,
            source_row_sha256=canonical_row_hash(swe_row),
            image=image,
            harness_image_tag=tag,
            harness_revision=SWE_HARNESS_REVISION,
        )
        multi_target = FrozenOfficialTarget(
            target_id="multi_swe_bench_mini--trimem__loader-1",
            benchmark_id="multi_swe_bench_mini",
            instance_id="trimem__loader-1",
            repository="trimem/loader",
            base_commit="2" * 40,
            dataset_revision="5" * 40,
            source_row_sha256=canonical_row_hash(multi_row),
            image=image,
            harness_image_tag=tag,
            harness_revision=MULTI_HARNESS_REVISION,
        )
        swe = build_harness_invocation(
            swe_target,
            row=swe_row,
            patch="",
            harness_root=swe_root,
            run_root=temporary / "swe",
            model_name="trimem-loader-preflight",
            python_binary=python_binary,
        )
        multi = build_harness_invocation(
            multi_target,
            row=multi_row,
            patch="",
            harness_root=multi_root,
            run_root=temporary / "multi",
            model_name="trimem-loader-preflight",
            python_binary=python_binary,
        )
        if (
            swe.argv[0] != python_binary
            or swe.argv[1:5]
            != (
                "-P",
                str(SWE_ENTRYPOINT),
                "--harness-root",
                str(swe_root),
            )
            or multi.argv[0] != python_binary
            or multi.report_argv[0] != python_binary
            or swe.cwd.resolve() != (temporary / "swe").resolve()
            or multi.cwd.resolve() != multi_root.resolve()
            or any("prepare.sh" in item for item in (*swe.argv, *multi.argv, *multi.report_argv))
        ):
            raise OfficialHarnessLoaderPreflightError(
                "official harness invocation-construction contract differs"
            )
        swe_argv = _normalized_invocation_argv(
            swe.argv, temporary_root=temporary
        )
        multi_argv = _normalized_invocation_argv(
            multi.argv, temporary_root=temporary
        )
        multi_report_argv = _normalized_invocation_argv(
            multi.report_argv, temporary_root=temporary
        )
        return {
            "swe_argv": swe_argv,
            "swe_argv_sha256": hashlib.sha256(
                json.dumps(swe_argv, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "multi_argv": multi_argv,
            "multi_argv_sha256": hashlib.sha256(
                json.dumps(multi_argv, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "multi_report_argv": multi_report_argv,
            "multi_report_argv_sha256": hashlib.sha256(
                json.dumps(multi_report_argv, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "swe_cwd": "<PREFLIGHT_RUN_ROOT>/swe",
            "multi_cwd": str(multi.cwd.resolve(strict=True)),
            "exact_python_binary": python_binary,
            "execution_environment_identity_sha256": environment_identity_sha256,
            "host_prepare_script_reads": 0,
            "source_image_build_calls": 0,
            "docker_executions": 0,
            "status": "PASS",
        }


def run_official_harness_loader_preflight(
    *,
    python_binary: str | Path,
    swe_harness_root: Path,
    multi_harness_root: Path,
    source_environment: Mapping[str, str] | None = None,
    runner: ProcessRunner = subprocess.run,
    loader_builder: LoaderBuilder = build_official_harness_python_loader,
    environment_builder: EnvironmentBuilder = minimal_subprocess_env,
) -> dict[str, object]:
    """Run the exact no-container preflight and return canonical evidence."""

    source = dict(os.environ if source_environment is None else source_environment)
    try:
        swe_lexical = swe_harness_root.absolute()
        multi_lexical = multi_harness_root.absolute()
        validate_pristine_checkout(swe_lexical, SWE_HARNESS_REVISION)
        validate_pristine_checkout(multi_lexical, MULTI_HARNESS_REVISION)
        swe_root = swe_lexical.resolve(strict=True)
        multi_root = multi_lexical.resolve(strict=True)
    except (HarnessLockError, OSError, RuntimeError) as exc:
        raise OfficialHarnessLoaderPreflightError(
            "pinned harness checkout is not pristine"
        ) from exc
    try:
        environment = environment_builder(source, python_binary=python_binary)
        loader = loader_builder(
            source,
            python_binary=python_binary,
            probe_cwd=swe_root,
        )
    except OfficialHarnessPythonLoaderError as exc:
        raise OfficialHarnessLoaderPreflightError("exact Python loader is not ready") from exc
    if environment != dict(loader.environment):
        raise OfficialHarnessLoaderPreflightError(
            "minimal_subprocess_env differs from the canonical loader environment"
        )
    exact_python = str(loader.evidence["python_binary_realpath"])
    environment_identity = hashlib.sha256(
        json.dumps(
            environment,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    result: dict[str, object] = {
        "schema": PREFLIGHT_SCHEMA,
        "status": "PASS",
        "marker": PREFLIGHT_PASS,
        "environment_constructor": (
            "trimem_official_grader.minimal_subprocess_env"
        ),
        "python_loader": dict(loader.evidence),
        "environment_identity_sha256": environment_identity,
        "environment_keys": sorted(environment),
        "swe_revision": _verify_revision(
            swe_root,
            SWE_HARNESS_REVISION,
            runner=runner,
            environment=environment,
            label="SWE-bench",
        ),
        "multi_revision": _verify_revision(
            multi_root,
            MULTI_HARNESS_REVISION,
            runner=runner,
            environment=environment,
            label="Multi-SWE",
        ),
        "swe_import_check": _swe_import_check(
            swe_root,
            python_binary=exact_python,
            runner=runner,
            environment=environment,
        ),
        "multi_self_check": _multi_self_check(
            multi_root,
            python_binary=exact_python,
            runner=runner,
            environment=environment,
        ),
        "invocation_construction": build_invocation_construction_evidence(
            python_binary=exact_python,
            swe_root=swe_root,
            multi_root=multi_root,
            environment_identity_sha256=environment_identity,
        ),
        "counters": dict(ZERO_COUNTERS),
    }
    return result


def failure_result(exc: BaseException) -> dict[str, object]:
    """Return a non-secret fail-closed result with exact zero counters."""

    return {
        "schema": PREFLIGHT_SCHEMA,
        "status": "NOT_READY",
        "marker": PREFLIGHT_NOT_READY,
        "failure_type": type(exc).__name__,
        "failure_reason": "credential-free official-harness loader preflight failed",
        "counters": dict(ZERO_COUNTERS),
    }


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-binary", type=Path, default=Path(sys.executable))
    parser.add_argument("--swe-harness-root", type=Path, required=True)
    parser.add_argument("--multi-harness-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = run_official_harness_loader_preflight(
            python_binary=args.python_binary,
            swe_harness_root=args.swe_harness_root,
            multi_harness_root=args.multi_harness_root,
        )
        raw = _canonical_bytes(result)
        if args.output is not None:
            atomic_write_bytes(args.output, raw)
        print(raw.decode("utf-8").rstrip("\n"))
        print(PREFLIGHT_PASS)
        return 0
    except Exception as exc:  # every unexpected preflight state fails closed
        result = failure_result(exc)
        raw = _canonical_bytes(result)
        if args.output is not None:
            try:
                atomic_write_bytes(args.output, raw)
            except OSError:
                pass
        print(raw.decode("utf-8").rstrip("\n"), file=sys.stderr)
        print(PREFLIGHT_NOT_READY, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PREFLIGHT_NOT_READY",
    "PREFLIGHT_PASS",
    "PREFLIGHT_SCHEMA",
    "ZERO_COUNTERS",
    "OfficialHarnessLoaderPreflightError",
    "build_invocation_construction_evidence",
    "failure_result",
    "run_official_harness_loader_preflight",
]
