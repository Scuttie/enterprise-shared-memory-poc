from __future__ import annotations

import base64
from dataclasses import asdict
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import trimem_benchmark_matrix as benchmark_matrix
import trimem_benchmark_run as benchmark
import trimem_official_harness_loader_preflight as loader_preflight
import trimem_multi_swe_entrypoint as multi_entrypoint
import trimem_public_artifact as public_artifact
import trimem_run_with_resume as resume_driver
from enterprise_memory.trimem.agent_runtime import (
    AgentRunResult,
    CodingTask,
    ExperienceExtraction,
)
from enterprise_memory.trimem.grader import (
    GradeRequest,
    GradeResult,
    GraderInvocationFailure,
)
from enterprise_memory.trimem.policy import (
    DoubleDQNConfig,
    DoubleDQNMemoryPolicy,
    FeatureSchema,
    MemoryAction,
    MemoryState,
)
from enterprise_memory.trimem.workspace import WorkspaceGraderContext


def _preflight(
    tmp_path: Path, *, multi_root_path: Path | None = None
) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    if multi_root_path is not None:
        multi_root_path.mkdir(parents=True, exist_ok=True)
    prefix = tmp_path / "python-prefix"
    python = prefix / "bin" / "exact-python-fixture"
    if not python.exists():
        python.parent.mkdir(parents=True)
        python.write_bytes(b"credential-free exact Python identity fixture\n")
        python.chmod(0o755)
    python = python.resolve(strict=True)
    raw = python.read_bytes()
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": str(python.parent),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    libdir: Path | None = None
    libpython: Path | None = None
    if os.name == "posix":
        libdir = prefix / "lib"
        libdir.mkdir(exist_ok=True)
        libpython = libdir / benchmark.EXPECTED_LIBPYTHON
        libpython.write_bytes(b"credential-free libpython identity fixture\n")
        libdir.chmod(0o755)
        libpython.chmod(0o644)
        environment["LD_LIBRARY_PATH"] = str(libdir.resolve())
    loader_evidence = {
        "schema": benchmark.OFFICIAL_HARNESS_PYTHON_LOADER_SCHEMA,
        "status": "PASS",
        "python_binary": str(python),
        "python_binary_realpath": str(python),
        "python_binary_sha256": hashlib.sha256(raw).hexdigest(),
        "python_binary_bytes": len(raw),
        "python_binary_mode": f"{python.stat().st_mode & 0o7777:04o}",
        "python_version": sys.version,
        "python_prefix": str(prefix.resolve()),
        "libdir": str(libdir.resolve()) if libdir is not None else None,
        "libdir_mode": (
            f"{libdir.stat().st_mode & 0o7777:04o}"
            if libdir is not None
            else None
        ),
        "libpython_path": (
            str(libpython.resolve()) if libpython is not None else None
        ),
        "libpython_realpath": (
            str(libpython.resolve()) if libpython is not None else None
        ),
        "libpython_sha256": (
            hashlib.sha256(libpython.read_bytes()).hexdigest()
            if libpython is not None
            else None
        ),
        "libpython_bytes": (
            len(libpython.read_bytes()) if libpython is not None else None
        ),
        "libpython_mode": (
            f"{libpython.stat().st_mode & 0o7777:04o}"
            if libpython is not None
            else None
        ),
        "loader_probe_exit_code": 0,
        "loader_probe_argv": [str(python), "-c", benchmark.LOADER_PROBE_CODE],
        "loader_probe_stdout_sha256": hashlib.sha256(b"probe\n").hexdigest(),
        "loader_probe_stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "inherited_ld_library_path_used": False,
        "ld_preload_present": False,
        "generated_environment_keys": sorted(environment),
    }
    environment_identity = benchmark.sha256_bytes(
        benchmark.canonical_bytes(environment)
    )
    zero = dict(benchmark.OFFICIAL_HARNESS_PREFLIGHT_ZERO_COUNTERS)
    swe_modules = {
        name: {
            "bytes": 1,
            "path": (
                "swebench/harness/run_evaluation.py"
                if name == "swebench.harness.run_evaluation"
                else None
            ),
            "sha256": hashlib.sha256(name.encode("utf-8")).hexdigest(),
        }
        for name in (
            "swebench.harness.run_evaluation",
            "docker",
            "datasets",
            "unidiff",
        )
    }
    multi_modules = {
        name: {
            "bytes": 1,
            "path": name.replace(".", "/") + ".py",
            "sha256": hashlib.sha256(name.encode("utf-8")).hexdigest(),
        }
        for name in (
            "multi_swe_bench.harness.run_evaluation",
            "multi_swe_bench.harness.gen_report",
            "multi_swe_bench.harness.dataset",
            "multi_swe_bench.harness.report",
            "multi_swe_bench.harness.test_result",
        )
    }
    swe_root = tmp_path.resolve(strict=True)
    multi_root = (
        multi_root_path.resolve(strict=True)
        if multi_root_path is not None
        else swe_root
    )
    swe_payload = {
        "modules": swe_modules,
        "schema": "trimem/swe-bench-loader-import-probe/1.0",
        "status": "PASS",
    }
    multi_payload = {
        "schema": "trimem/multi-swe-loader-self-check/1.0",
        "status": "PASS",
        "harness_revision": benchmark.MULTI_HARNESS_REVISION,
        "modules": multi_modules,
        "cli_argument_destinations": sorted(
            multi_entrypoint.EXPECTED_CLI_ARGUMENT_DESTINATIONS
        ),
        **zero,
    }
    return {
        "schema": benchmark.OFFICIAL_HARNESS_LOADER_PREFLIGHT_SCHEMA,
        "status": "PASS",
        "marker": benchmark.OFFICIAL_HARNESS_LOADER_PREFLIGHT_PASS,
        "environment_constructor": (
            "trimem_official_grader.minimal_subprocess_env"
        ),
        "environment_identity_sha256": environment_identity,
        "environment_keys": sorted(environment),
        "python_loader": loader_evidence,
        "invocation_construction": {
            **loader_preflight.build_invocation_construction_evidence(
                python_binary=str(python),
                swe_root=swe_root,
                multi_root=multi_root,
                environment_identity_sha256=environment_identity,
            )
        },
        "swe_revision": {
            "status": "PASS",
            "revision": benchmark.SWE_HARNESS_REVISION,
            "cwd": str(swe_root),
            "stdout_sha256": hashlib.sha256(
                (benchmark.SWE_HARNESS_REVISION + "\n").encode("ascii")
            ).hexdigest(),
            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        },
        "multi_revision": {
            "status": "PASS",
            "revision": benchmark.MULTI_HARNESS_REVISION,
            "cwd": str(multi_root),
            "stdout_sha256": hashlib.sha256(
                (benchmark.MULTI_HARNESS_REVISION + "\n").encode("ascii")
            ).hexdigest(),
            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        },
        "swe_import_check": {
            "status": "PASS",
            "argv": [str(python), "-c", benchmark.SWE_IMPORT_PROBE_CODE],
            "cwd": str(swe_root),
            "exit_code": 0,
            "stdout_sha256": hashlib.sha256(
                json.dumps(
                    swe_payload, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                + b"\n"
            ).hexdigest(),
            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
            "modules": swe_modules,
        },
        "multi_self_check": {
            "status": "PASS",
            "argv": [
                str(python),
                str((ROOT / "scripts/trimem_multi_swe_entrypoint.py").resolve()),
                "--loader-self-check",
                "--harness-root",
                str(multi_root),
            ],
            "cwd": str(multi_root),
            "exit_code": 0,
            "stdout_sha256": hashlib.sha256(
                json.dumps(
                    multi_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
                + b"\n"
            ).hexdigest(),
            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
            "payload": multi_payload,
        },
        "counters": zero,
    }


def _preflight_environment(evidence: dict[str, object]) -> dict[str, str]:
    loader = evidence["python_loader"]
    python = Path(loader["python_binary_realpath"])
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": str(python.parent),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    if loader["libdir"] is not None:
        environment["LD_LIBRARY_PATH"] = str(loader["libdir"])
    assert sorted(environment) == evidence["environment_keys"]
    return environment


def _request(
    tmp_path: Path,
    task_id: str = "target-001",
    *,
    patch: str = "diff --git a/a b/a\n",
) -> GradeRequest:
    return GradeRequest(
        task_id=task_id,
        repository="example/repository",
        base_commit="a" * 40,
        patch=patch,
        workspace=WorkspaceGraderContext(
            kind="git_checkout",
            repository_files={},
            checkout_root=str(tmp_path),
            base_commit="a" * 40,
        ),
    )


def _grade(
    task_id: str,
    *,
    container_started: bool = True,
    resolved: bool = False,
) -> GradeResult:
    container_digest = "fixture@sha256:" + "b" * 64
    expected_digest = container_digest.rsplit("@", 1)[-1]
    return GradeResult(
        task_id=task_id,
        resolved=resolved,
        exit_code=0 if container_started else 127,
        stdout="",
        stderr="" if container_started else "libpython3.11.so.1.0 not found",
        report={
            "task_id": task_id,
            "resolved": resolved,
            "_trimem": {
                "image_evidence": [
                    {
                        "image": container_digest,
                        "expected": expected_digest,
                        "observed": [expected_digest],
                    }
                ]
            },
        },
        grader_id="official-fixture",
        container_digest=container_digest,
        official=True,
        wall_time_ms=1,
        container_started=container_started,
        status="success" if container_started else "harness_launch_failed",
    )


class _FakeGrader:
    def __init__(self, result: GradeResult, *, fail: bool = False):
        self.result = result
        self.fail = fail
        self.calls = 0

    def grade(self, _request: GradeRequest) -> GradeResult:
        self.calls += 1
        if self.fail:
            raise GraderInvocationFailure(self.result)
        return self.result

    def validate_captured_result(
        self, request: GradeRequest, result: GradeResult
    ) -> None:
        if request.task_id != result.task_id or result != self.result:
            raise ValueError("fake retained grader evidence differs")


class _CrashingGrader(_FakeGrader):
    def grade(self, _request: GradeRequest) -> GradeResult:
        self.calls += 1
        raise RuntimeError("grader process disappeared without a result")


class _RoutingFakeGrader:
    def __init__(self) -> None:
        self.task_ids: list[str] = []
        self.real_external_calls = 0

    @property
    def calls(self) -> int:
        return len(self.task_ids)

    def grade(self, request: GradeRequest) -> GradeResult:
        self.task_ids.append(request.task_id)
        return _grade(request.task_id)

    def validate_captured_result(
        self, request: GradeRequest, result: GradeResult
    ) -> None:
        if result != _grade(request.task_id):
            raise ValueError("routing fake retained grader evidence differs")


def _gateway(
    tmp_path: Path, delegate: _FakeGrader
) -> benchmark.JournaledGraderGateway:
    preflight = _preflight(tmp_path)
    delegate.python_loader_evidence = dict(preflight["python_loader"])
    delegate.execution_env = _preflight_environment(preflight)
    return benchmark.JournaledGraderGateway(
        delegate,
        benchmark.TerminalInvocationJournal(tmp_path / "terminal-journal"),
        preflight_evidence=preflight,
        python_binary=preflight["python_loader"]["python_binary_realpath"],
    )


def _seed_grader_process_state(
    gateway: benchmark.JournaledGraderGateway,
    request: GradeRequest,
    *,
    container_started: bool,
) -> Path:
    request_hash = gateway._request_hash(request)
    key = f"{request.task_id}:{request_hash}"
    path = gateway.journal.begin_grader_request(key, request_hash)
    gateway.journal.transition_grader(
        path,
        expected=("GRADER_NOT_PREPARED",),
        status="GRADER_PREFLIGHT_PASSED",
        values={"loader_preflight_evidence_sha256": gateway._preflight_sha256()},
    )
    gateway.journal.transition_grader(
        path,
        expected=("GRADER_PREFLIGHT_PASSED",),
        status="GRADER_REQUEST_RECORDED",
    )
    gateway.journal.transition_grader(
        path,
        expected=("GRADER_REQUEST_RECORDED",),
        status="GRADER_PROCESS_STARTED",
    )
    if container_started:
        gateway.journal.transition_grader(
            path,
            expected=("GRADER_PROCESS_STARTED",),
            status="GRADER_CONTAINER_STARTED",
            values={
                "official_grader_runs": 1,
                "grader_containers": 1,
                "grader_capacity_disposition": "CONSERVATIVELY_CONSUMED",
            },
        )
    return path


def test_loader_preflight_binds_exact_python_and_zero_execution_counters(
    tmp_path: Path,
) -> None:
    evidence = _preflight(tmp_path)
    python_binary = evidence["python_loader"]["python_binary_realpath"]
    assert benchmark.validate_official_harness_loader_preflight_evidence(
        evidence,
        python_binary=python_binary,
        _runtime_loader_evidence=evidence["python_loader"],
        _runtime_environment=_preflight_environment(evidence),
    )
    evidence["multi_self_check"]["payload"][
        "cli_argument_destinations"
    ].remove("config")
    with pytest.raises(
        benchmark.BenchmarkProcessFailure,
        match="Multi-SWE self-check identity differs",
    ):
        benchmark.validate_official_harness_loader_preflight_evidence(
            evidence,
            python_binary=python_binary,
            _runtime_loader_evidence=evidence["python_loader"],
            _runtime_environment=_preflight_environment(evidence),
        )
    evidence["multi_self_check"]["payload"][
        "cli_argument_destinations"
    ].append("config")
    evidence["multi_self_check"]["payload"][
        "cli_argument_destinations"
    ].sort()
    evidence["counters"] = {**evidence["counters"], "grader_containers": 1}
    with pytest.raises(
        benchmark.BenchmarkProcessFailure, match="zero-execution counters"
    ) as failure:
        benchmark.validate_official_harness_loader_preflight_evidence(
            evidence,
            python_binary=python_binary,
            _runtime_loader_evidence=evidence["python_loader"],
            _runtime_environment=_preflight_environment(evidence),
        )
    assert failure.value.disposition == "GLOBAL_ENVIRONMENT_FAILURE"


def test_preflight_harness_roots_bind_exact_swe_and_shared_multi_checkout(
    tmp_path: Path,
) -> None:
    swe_root = tmp_path / "swe"
    multi_root = tmp_path / "multi"
    evidence = _preflight(swe_root, multi_root_path=multi_root)
    harnesses = {
        "swebench_verified": swe_root,
        "multi_swe_bench_mini": multi_root,
        "multi_swe_bench_flash": multi_root,
    }
    benchmark.validate_preflight_harness_root_binding(evidence, harnesses)

    alternate = tmp_path / "alternate-swe"
    (alternate / "swebench/harness").mkdir(parents=True)
    with pytest.raises(
        benchmark.BenchmarkProcessFailure,
        match="runtime cwd differs from exact preflight",
    ) as failure:
        benchmark.validate_preflight_harness_root_binding(
            evidence,
            {**harnesses, "swebench_verified": alternate},
        )
    assert failure.value.disposition == "GLOBAL_ENVIRONMENT_FAILURE"


def test_grader_runtime_loader_must_match_the_exact_preflight(tmp_path: Path) -> None:
    evidence = _preflight(tmp_path)
    delegate = _FakeGrader(_grade("target-001"))
    delegate.python_loader_evidence = dict(evidence["python_loader"])
    delegate.execution_env = {
        "LANG": "tampered-after-preflight",
    }
    gateway = benchmark.JournaledGraderGateway(
        delegate,
        benchmark.TerminalInvocationJournal(tmp_path / "terminal-journal"),
        preflight_evidence=evidence,
        python_binary=evidence["python_loader"]["python_binary_realpath"],
    )

    with pytest.raises(
        benchmark.BenchmarkProcessFailure,
        match="loader/environment identity differs",
    ) as failure:
        gateway.grade(_request(tmp_path))
    assert failure.value.disposition == "GLOBAL_ENVIRONMENT_FAILURE"
    assert delegate.calls == 0


def test_grader_lifecycle_success_is_validated_and_replayed_once(tmp_path: Path) -> None:
    request = _request(tmp_path)
    delegate = _FakeGrader(_grade(request.task_id))
    gateway = _gateway(tmp_path, delegate)
    assert gateway.grade(request) == gateway.grade(request)
    assert delegate.calls == 1
    path = next((tmp_path / "terminal-journal/grader").glob("*.json"))
    row = benchmark.TerminalInvocationJournal._validated_grader_row(path)
    assert row["status"] == "GRADER_RESULT_VALIDATED"
    assert row["transitions"] == [
        "GRADER_NOT_PREPARED",
        "GRADER_PREFLIGHT_PASSED",
        "GRADER_REQUEST_RECORDED",
        "GRADER_PROCESS_STARTED",
        "GRADER_CONTAINER_STARTED",
        "GRADER_TERMINAL_RESULT_CAPTURED",
        "GRADER_RESULT_VALIDATED",
    ]
    assert (row["official_grader_runs"], row["grader_containers"]) == (1, 1)


@pytest.mark.parametrize(
    ("container_started", "state", "counters", "capacity"),
    (
        (False, "GRADER_INFRA_FAILURE_BEFORE_CONTAINER", (0, 0), "NOT_CONSUMED"),
        (
            True,
            "GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START",
            (1, 1),
            "CONSERVATIVELY_CONSUMED",
        ),
    ),
)
def test_grader_failures_are_nonterminal_and_never_retried(
    tmp_path: Path,
    container_started: bool,
    state: str,
    counters: tuple[int, int],
    capacity: str,
) -> None:
    request = _request(tmp_path)
    delegate = _FakeGrader(
        _grade(request.task_id, container_started=container_started), fail=True
    )
    gateway = _gateway(tmp_path, delegate)
    for _ in range(2):
        with pytest.raises(GraderInvocationFailure):
            gateway.grade(request)
    assert delegate.calls == 1
    path = next((tmp_path / "terminal-journal/grader").glob("*.json"))
    row = benchmark.TerminalInvocationJournal._validated_grader_row(path)
    assert row["status"] == state
    assert (row["official_grader_runs"], row["grader_containers"]) == counters
    assert row["grader_capacity_disposition"] == capacity


@pytest.mark.parametrize(
    ("container_started", "expected_state"),
    (
        (False, "GRADER_INFRA_FAILURE_BEFORE_CONTAINER"),
        (True, "GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START"),
    ),
)
@pytest.mark.parametrize(
    ("field", "mutated_value"),
    (
        ("task_id", "different-target"),
        ("official", False),
        ("container_started", None),
    ),
)
def test_resealed_terminal_grader_result_must_retain_exact_journal_binding(
    tmp_path: Path,
    container_started: bool,
    expected_state: str,
    field: str,
    mutated_value: object,
) -> None:
    request = _request(tmp_path)
    delegate = _FakeGrader(
        _grade(request.task_id, container_started=container_started), fail=True
    )
    gateway = _gateway(tmp_path, delegate)
    with pytest.raises(GraderInvocationFailure):
        gateway.grade(request)

    path = next((tmp_path / "terminal-journal/grader").glob("*.json"))
    row = benchmark.TerminalInvocationJournal._validated_grader_row(path)
    assert row["status"] == expected_state
    if field == "container_started":
        mutated_value = not container_started
    row["result"][field] = mutated_value
    benchmark.write_json(
        path, benchmark.TerminalInvocationJournal._sealed_row(row)
    )

    with pytest.raises(
        benchmark.BenchmarkExecutionError,
        match="grader lifecycle terminal result binding differs",
    ):
        benchmark.TerminalInvocationJournal._validated_grader_row(path)


@pytest.mark.parametrize("container_started", (False, True))
def test_started_grader_without_result_is_closed_unknown_without_reinvocation(
    tmp_path: Path, container_started: bool
) -> None:
    request = _request(tmp_path)
    delegate = _FakeGrader(_grade(request.task_id))
    gateway = _gateway(tmp_path, delegate)
    path = _seed_grader_process_state(
        gateway, request, container_started=container_started
    )

    failures: list[GradeResult] = []
    for _ in range(2):
        with pytest.raises(GraderInvocationFailure) as failure:
            gateway.grade(request)
        failures.append(failure.value.result)

    assert delegate.calls == 0
    assert asdict(failures[0]) == asdict(failures[1])
    row = benchmark.TerminalInvocationJournal._validated_grader_row(path)
    assert row["status"] == "GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START"
    assert row["transitions"] == [
        "GRADER_NOT_PREPARED",
        "GRADER_PREFLIGHT_PASSED",
        "GRADER_REQUEST_RECORDED",
        "GRADER_PROCESS_STARTED",
        "GRADER_CONTAINER_STARTED",
        "GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START",
    ]
    assert (row["official_grader_runs"], row["grader_containers"]) == (1, 1)
    assert row["grader_capacity_disposition"] == "CONSERVATIVELY_CONSUMED"
    assert row["container_start_observed"] is None
    assert row["result"]["status"] == "grader_outcome_unknown_after_process_start"
    assert row["result"]["report"] == {
        "schema": "trimem/grader-outcome-unknown/1.0",
        "task_id": request.task_id,
        "resolved": False,
        "failure_stage": "grader_process_started_without_terminal_result",
        "container_start_observed": None,
        "grader_capacity_consumed_conservatively": True,
        "terminal_streams_available": False,
    }


def test_delegate_crash_is_closed_unknown_once_and_never_retried(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    delegate = _CrashingGrader(_grade(request.task_id))
    gateway = _gateway(tmp_path, delegate)

    for _ in range(2):
        with pytest.raises(GraderInvocationFailure):
            gateway.grade(request)

    assert delegate.calls == 1
    path = next((tmp_path / "terminal-journal/grader").glob("*.json"))
    row = benchmark.TerminalInvocationJournal._validated_grader_row(path)
    assert row["status"] == "GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START"
    assert (row["official_grader_runs"], row["grader_containers"]) == (1, 1)
    assert row["grader_capacity_disposition"] == "CONSERVATIVELY_CONSUMED"


def test_started_grader_unknown_consumes_capacity_but_not_scientific_cell(
    tmp_path: Path,
) -> None:
    task = _task(1)
    task_key = f"M0:M0:{task.task_id}"
    ledger = _ledger(tmp_path, 1)
    ledger.reserve_task_arm(task_key)
    request = _request(tmp_path, task.task_id)
    delegate = _FakeGrader(_grade(request.task_id))
    gateway = _gateway(tmp_path, delegate)
    _seed_grader_process_state(gateway, request, container_started=False)

    with pytest.raises(GraderInvocationFailure) as failure:
        gateway.grade(request)

    ledger_row = ledger._read()
    session = _Session()
    assert delegate.calls == 0
    assert ledger.task_arm_status(task_key) == "RESERVED"
    assert ledger_row["actual"]["task_arm_runs"] == 0
    assert ledger_row["actual"]["grader_containers"] == 0
    assert ledger_row["outstanding"]["task_arm_runs"] == 1
    assert ledger_row["outstanding"]["grader_containers"] == 1
    assert session.task_cursor == 0
    assert not list(tmp_path.rglob("*.result.json"))
    assert not list(tmp_path.rglob("cell-commit-journal.json"))
    disposition = benchmark.process_disposition_for_exception(failure.value)
    assert disposition == "GLOBAL_GRADER_INFRA_FAILURE"
    assert disposition not in benchmark.RESUME_SAFE_PROCESS_DISPOSITIONS


def test_pre_container_failure_cannot_terminalize_ledger_or_advance_cursor(
    tmp_path: Path,
) -> None:
    task = _task(1)
    ledger = _ledger(tmp_path, 1)
    task_key = f"M0:M0:{task.task_id}"
    ledger.reserve_task_arm(task_key)
    delegate = _FakeGrader(_grade(task.task_id, container_started=False), fail=True)
    gateway = _gateway(tmp_path, delegate)
    with pytest.raises(GraderInvocationFailure) as failure:
        gateway.grade(_request(tmp_path, task.task_id))
    session = _Session()
    assert ledger.task_arm_status(task_key) == "RESERVED"
    assert ledger._read()["actual"]["task_arm_runs"] == 0
    assert ledger._read()["actual"]["grader_containers"] == 0
    assert session.task_cursor == 0
    assert not list(tmp_path.rglob("*.result.json"))
    assert not list(tmp_path.rglob("cell-commit-journal.json"))
    disposition = benchmark.process_disposition_for_exception(failure.value)
    assert disposition == "GLOBAL_GRADER_INFRA_FAILURE"
    assert disposition not in benchmark.RESUME_SAFE_PROCESS_DISPOSITIONS


def _ledger(tmp_path: Path, count: int = 2) -> benchmark.AtomicBudgetLedger:
    pricing = benchmark.read_json(
        ROOT / "configs/trimem_v1/cost_plan.json"
    )["model_pricing"]
    cost_ceiling = float(
        (
            Decimal(100)
            * Decimal(str(pricing["input_per_million_tokens_usd"]))
            + Decimal(100)
            * Decimal(str(pricing["output_per_million_tokens_usd"]))
        )
        / Decimal(1_000_000)
    )
    caps = {
        "model_calls": 6,
        "paid_model_calls": 6,
        "solve_calls": 2,
        "decomposition_calls": 2,
        "extraction_calls": 2,
        "input_tokens": 100,
        "output_tokens": 100,
        "total_usd": cost_ceiling,
        "uncached_token_cost_ceiling_usd": cost_ceiling,
        "task_arm_runs": count,
        "benchmark_grader_containers": count,
        "max_input_tokens_per_task_arm": 100,
        "max_model_calls_per_task_arm": 3,
    }
    return benchmark.AtomicBudgetLedger(
        tmp_path / "budget-ledger.json",
        approval_digest="c" * 64,
        caps=caps,
        pricing=pricing,
    )


def _model_call_ledger(
    tmp_path: Path,
    *,
    task_count: int,
    decomposition_cap: int,
    solve_cap: int,
    extraction_cap: int,
    max_calls_per_task: int,
) -> benchmark.AtomicBudgetLedger:
    model_calls = decomposition_cap + solve_cap + extraction_cap
    input_cap = max(model_calls, 1)
    output_cap = 65_536 * task_count
    pricing = benchmark.read_json(
        ROOT / "configs/trimem_v1/cost_plan.json"
    )["model_pricing"]
    cost_ceiling = float(
        (
            Decimal(input_cap)
            * Decimal(str(pricing["input_per_million_tokens_usd"]))
            + Decimal(output_cap)
            * Decimal(str(pricing["output_per_million_tokens_usd"]))
        )
        / Decimal(1_000_000)
    )
    return benchmark.AtomicBudgetLedger(
        tmp_path / "budget-ledger.json",
        approval_digest="c" * 64,
        caps={
            "model_calls": model_calls,
            "paid_model_calls": model_calls,
            "solve_calls": solve_cap,
            "decomposition_calls": decomposition_cap,
            "extraction_calls": extraction_cap,
            "input_tokens": input_cap,
            "output_tokens": output_cap,
            "total_usd": cost_ceiling,
            "uncached_token_cost_ceiling_usd": cost_ceiling,
            "task_arm_runs": task_count,
            "benchmark_grader_containers": task_count,
            "max_input_tokens_per_task_arm": max_calls_per_task,
            "max_model_calls_per_task_arm": max_calls_per_task,
        },
        pricing=pricing,
    )


def _task(index: int) -> CodingTask:
    return CodingTask(
        task_id=f"target-{index:03d}",
        org_id="org",
        user_id="user",
        repository="example/repository",
        commit="a" * 40,
        instruction="fix it",
        files={},
        editable_paths=("a.py",),
    )


_FIXED_EVIDENCE_TIME = "2026-09-06T00:00:00+00:00"
_FIXTURE_RUN_NONCE = "00000000-0000-0000-0000-000000000001"
_FIXTURE_TASK_ORDER_HASH = "sha256:" + "1" * 64
_FIXTURE_CONFIG_HASH = "sha256:" + "2" * 64
_FIXTURE_EXECUTION_LOCK_HASH = "sha256:" + "3" * 64
_FIXTURE_IDENTITY_SEED_DIGEST = "sha256:" + "4" * 64
_FIXTURE_RUNTIME_LOCK_SHA256 = "sha256:" + "5" * 64
_FIXTURE_M2_POLICY_SHA256 = "sha256:" + "6" * 64
_FIXTURE_WORKSPACE_FACTORY_HASH = "7" * 64
_FIXTURE_PRIMARY_MODEL = {"model_id": "credential-free-fixture"}


def _fixture_experiment_id(stream_id: str) -> str:
    safe = "".join(
        character if character.isalnum() or character == "-" else "-"
        for character in stream_id.lower()
    )
    return "trimemv1-aaaaaaaaaaaa-" + safe


def _fixture_namespace(stream_id: str) -> str:
    return "trimem-d110-test-" + stream_id.lower()


def _fixture_canonical_evidence(stream_id: str) -> dict[str, object]:
    from enterprise_memory.trimem.production_runtime import _sha256

    namespace = _fixture_namespace(stream_id)
    row_counts: list[list[object]] = []
    return {
        "namespace": namespace,
        "row_counts": row_counts,
        "digest": _sha256(
            {"namespace": namespace, "row_counts": row_counts}
        ),
    }


def _fixture_qdrant_evidence() -> dict[str, object]:
    from enterprise_memory.trimem.production_runtime import _sha256

    return {"collections": {}, "digest": _sha256({})}


def _fixture_receipt_evidence(stream_id: str) -> dict[str, object]:
    from enterprise_memory.trimem.production_runtime import _sha256

    body = {
        "schema": "trimem/lifecycle-receipt-evidence/1.0",
        "namespace": _fixture_namespace(stream_id),
        "owner_user_id": "user",
        "rows": [],
    }
    return {**body, "digest": _sha256(body)}


def _fixture_manifest_target(
    task: CodingTask, index: int
) -> dict[str, object]:
    return {
        "order_index": index,
        "target_id": task.task_id,
        "benchmark_id": "fixture-benchmark",
        "instance_id": task.task_id,
        "base_commit": task.commit,
        "source_row_sha256": "8" * 64,
    }


def _fixture_image(grade: GradeResult) -> dict[str, object]:
    return {
        "image": grade.container_digest,
        "expected_digest": grade.container_digest.rsplit("@", 1)[-1],
    }


def _fixture_lifecycle_hash(runtime_arm: str) -> str:
    if runtime_arm == "M2":
        return _FIXTURE_M2_POLICY_SHA256.removeprefix("sha256:")
    if runtime_arm == "M1":
        value = benchmark.production_v03_lifecycle_factory.configuration_hash
        return str(value).removeprefix("sha256:")
    return benchmark.sha256_bytes(
        (
            "enterprise_memory.trimem.agent_runtime."
            "NullExperienceLifecycle"
        ).encode("utf-8")
    )


def _fixture_memory_controller_hash(runtime_arm: str) -> str:
    if runtime_arm not in {"M0", "M1", "M2"}:
        return "f" * 64
    policy = (
        benchmark.load_candidate_policy(benchmark.CANDIDATE_IDS[0])
        if runtime_arm == "M2"
        else {}
    )
    return resume_driver._expected_memory_controller_hash(
        runtime_arm=runtime_arm,
        policy=policy,
    )


def _fixture_mutable_m2_policy(*, seed: int = 17) -> DoubleDQNMemoryPolicy:
    return DoubleDQNMemoryPolicy(
        DoubleDQNConfig(
            feature_schema=FeatureSchema(2, 2, 2, 2),
            hidden_dim=5,
            replay_capacity=8,
            batch_size=2,
            min_replay_size=2,
            target_sync_interval=1,
            epsilon_start=0.0,
            epsilon_end=0.0,
            epsilon_decay_steps=2,
            seed=seed,
        )
    )


def _fixture_m2_lifecycle_checkpoint(
    stream_id: str,
    *,
    policy: DoubleDQNMemoryPolicy | None = None,
    pending_by_memory_id: dict[str, object] | None = None,
    context_cost_coefficient: float = -0.1,
) -> dict[str, object]:
    selected_policy = policy or _fixture_mutable_m2_policy()
    payload = {
        "schema": "trimem/postgres-dqn-lifecycle/1.0",
        "namespace": _fixture_namespace(stream_id),
        "split": "development",
        "evaluation": False,
        "pending_by_memory_id": dict(pending_by_memory_id or {}),
        "policy": selected_policy.runtime_state(),
        "reward_config": {
            "context_cost_coefficient": context_cost_coefficient
        },
    }
    return {
        "payload": payload,
        "digest": "sha256:"
        + benchmark.sha256_bytes(benchmark.canonical_bytes(payload)),
    }


def _fixture_agent_config_hashes(
    task: CodingTask,
    *,
    stream_id: str,
    runtime_arm: str,
    sequence_index: int,
) -> dict[str, str]:
    target = _fixture_manifest_target(task, sequence_index)
    image = _fixture_image(_grade(task.task_id))
    model_hash = benchmark.sha256_bytes(
        benchmark.canonical_bytes(
            {
                "execution_lock_hash": _FIXTURE_EXECUTION_LOCK_HASH,
                "primary_model": _FIXTURE_PRIMARY_MODEL,
            }
        )
    )
    grader_hash = benchmark.sha256_bytes(
        benchmark.canonical_bytes(
            {
                "execution_lock_hash": _FIXTURE_EXECUTION_LOCK_HASH,
                "target": target,
                "source_row_sha256": target["source_row_sha256"],
                "grader_image": image,
            }
        )
    )
    return {
        "runtime": _FIXTURE_RUNTIME_LOCK_SHA256.removeprefix("sha256:"),
        "task": benchmark.task_configuration_sha256(task),
        "model": model_hash,
        "memory_controller": _fixture_memory_controller_hash(runtime_arm),
        "grader": grader_hash,
        "workspace": _FIXTURE_WORKSPACE_FACTORY_HASH,
        "lifecycle": _fixture_lifecycle_hash(runtime_arm),
    }


def _target(task: CodingTask, workspace_checkout_root: Path) -> dict[str, object]:
    return {
        "target_id": task.task_id,
        "base_commit": task.commit,
        "repository": task.repository,
        "workspace_checkout_root": str(workspace_checkout_root),
        "task_config_sha256": benchmark.task_configuration_sha256(task),
    }


def _expected_targets(
    output_root: Path,
    stream_id: str,
    tasks: list[CodingTask],
) -> list[dict[str, object]]:
    return [
        _target(
            task,
            benchmark._task_recovery_paths(
                output_root, stream_id, index, task
            )[0],
        )
        for index, task in enumerate(tasks)
    ]


def _fixture_blob_reference(
    value: bytes | str | dict[str, object],
) -> dict[str, object]:
    if isinstance(value, str):
        raw = value.encode("utf-8")
        media_type = "text/plain; charset=utf-8"
    elif isinstance(value, bytes):
        raw = value
        media_type = "application/octet-stream"
    else:
        raw = benchmark.canonical_bytes(value)
        media_type = "application/json"
    return {
        "sha256": benchmark.sha256_bytes(raw),
        "bytes": len(raw),
        "media_type": media_type,
    }


def _grader_evidence_payloads(
    task: CodingTask,
    *,
    arm: str,
    patch: str,
    grade: GradeResult,
) -> tuple[dict[str, object], dict[str, object]]:
    return (
        {
            "task_id": task.task_id,
            "arm": arm,
            "repository": task.repository,
            "base_commit": task.commit,
            "workspace_kind": "git_checkout",
            "patch": _fixture_blob_reference(patch),
        },
        {
            "task_id": task.task_id,
            "arm": arm,
            "official": grade.official,
            "grader_id": grade.grader_id,
            "container_digest": grade.container_digest,
            "exit_code": grade.exit_code,
            "resolved": grade.resolved,
            "container_started": grade.container_started,
            "status": grade.status,
            "wall_time_ms": grade.wall_time_ms,
            "stdout": _fixture_blob_reference(grade.stdout),
            "stderr": _fixture_blob_reference(grade.stderr),
            "report": _fixture_blob_reference(dict(grade.report)),
        },
    )


def _grader_evidence_tail_hash(
    task: CodingTask,
    *,
    arm: str,
    patch: str,
    grade: GradeResult,
) -> str:
    previous = "0" * 64
    for sequence, (event_type, payload) in enumerate(
        zip(
            ("grader_request", "grader_result"),
            _grader_evidence_payloads(
                task, arm=arm, patch=patch, grade=grade
            ),
        ),
        start=1,
    ):
        body = {
            "sequence": sequence,
            "recorded_at": _FIXED_EVIDENCE_TIME,
            "event_type": event_type,
            "payload": payload,
            "previous_event_hash": previous,
        }
        previous = benchmark.sha256_bytes(benchmark.canonical_bytes(body))
    return previous


def _agent_result(
    task: CodingTask,
    *,
    arm: str = "M0",
    stream_id: str | None = None,
) -> AgentRunResult:
    digest = "d" * 64
    patch = ""
    grade = _grade(task.task_id)
    return AgentRunResult(
        run_id=task.task_id + "-" + (stream_id or arm),
        task_id=task.task_id,
        arm=arm,
        resolved=False,
        patch=patch,
        graph_snapshot={},
        grade=grade,
        extraction=ExperienceExtraction(
            episode={},
            semantic_candidate=None,
            response_hash=digest,
            patch_hash=hashlib.sha256(patch.encode("utf-8")).hexdigest(),
            public_evidence_hash=digest,
        ),
        injections=(),
        accounting={
            "summary": {
                "by_call_kind": {},
                "grader_calls": 1,
                "grader_containers": 1,
                "official_grader_runs": 1,
            },
            "calls": [],
            "tools": [],
        },
        evidence_tail_hash=_grader_evidence_tail_hash(
            task, arm=arm, patch=patch, grade=grade
        ),
        lifecycle_result={
            "storage": {
                "retained_records": 0,
                "archived_records": 0,
                "net_memory_growth": 0,
            },
            "credit": {},
        },
        cell_status="CELL_SCIENTIFIC_FAILURE",
        model_failure_class="TASK_INPUT_CONTEXT_BUDGET_EXCEEDED",
        grader_patch_source="CANONICAL_FAILED_CELL_NOOP",
        agent_completed=False,
        extraction_status="SUCCESS",
        failure_metadata={
            "stage": "PRE_PROMPT_PROJECTION",
            "call_kind": "decompose",
            "provider_request_started": False,
            "ledger_reservation_created": False,
        },
    )


def _production_result(
    task: CodingTask,
    *,
    grade: GradeResult,
    accounting: dict[str, object],
    patch: str,
    cell_status: str,
    model_failure_class: str | None,
    grader_patch_source: str,
    agent_completed: bool,
) -> AgentRunResult:
    accounting = dict(accounting)
    accounting["summary"] = {
        **dict(accounting.get("summary", {})),
        "grader_calls": 1,
        "grader_containers": 1,
        "official_grader_runs": 1,
    }
    patch_hash = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    evidence_hash = hashlib.sha256(
        f"evidence:{task.task_id}".encode("utf-8")
    ).hexdigest()
    return AgentRunResult(
        run_id=task.task_id + "-M0",
        task_id=task.task_id,
        arm="M0",
        resolved=grade.resolved,
        patch=patch,
        graph_snapshot={},
        grade=grade,
        extraction=ExperienceExtraction(
            episode={},
            semantic_candidate=None,
            response_hash=evidence_hash,
            patch_hash=patch_hash,
            public_evidence_hash=evidence_hash,
        ),
        injections=(),
        accounting=accounting,
        evidence_tail_hash=_grader_evidence_tail_hash(
            task, arm="M0", patch=patch, grade=grade
        ),
        lifecycle_result={
            "storage": {
                "retained_records": 0,
                "archived_records": 0,
                "net_memory_growth": 0,
            },
            "credit": {},
        },
        cell_status=cell_status,
        model_failure_class=model_failure_class,
        grader_patch_source=grader_patch_source,
        agent_completed=agent_completed,
        extraction_status="SUCCESS",
        failure_metadata=None,
    )


def _record_successful_model_calls(
    ledger: benchmark.AtomicBudgetLedger,
    task_arm_key: str,
    roles: list[str],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    calls: list[dict[str, object]] = []
    request_rows: list[dict[str, object]] = []
    role_counts = {name: roles.count(name) for name in ("decompose", "solve", "extract")}
    for index, role in enumerate(roles):
        logical_id = f"{task_arm_key}:{role}:{index:02d}"
        output_cap = (
            1
            if role == "solve"
            else benchmark.MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[role]
        )
        reservation = ledger.reserve(
            logical_id,
            task_arm_key=task_arm_key,
            call_kind=role,
            input_upper_bound=1,
            output_cap=output_cap,
        )
        ledger.reconcile(
            logical_id,
            reservation,
            input_tokens=1,
            cached_input_tokens=0,
            output_tokens=1,
            status="SUCCESS",
        )
        calls.append(
            {
                "call_kind": role,
                "status": "SUCCESS",
                "provider_reported_usage_available": True,
                "input_tokens": 1,
                "cached_input_tokens": 0,
                "output_tokens": 1,
                "reasoning_tokens": 0,
                "ledger_reservation": {
                    "input_upper_bound": 1,
                    "output_cap": output_cap,
                    "charged_conservatively": False,
                },
            }
        )
        row = ledger.request_row(logical_id)
        assert row is not None
        request_rows.append(row)
    return (
        {
            "summary": {
                "by_call_kind": {
                    role: {"calls": role_counts[role]}
                    for role in ("decompose", "solve", "extract")
                },
                "model_gateway_calls": len(roles),
                "paid_model_calls": len(roles),
            },
            "calls": calls,
            "tools": [],
        },
        request_rows,
    )


def _record(
    result: AgentRunResult,
    *,
    arm: str = "M0",
    runtime_arm: str | None = None,
    task_dir: Path | None = None,
    sequence_index: int | None = None,
    sequence_sha256: str | None = None,
) -> dict[str, object]:
    accounting = benchmark.actual_accounting(result.accounting)
    accounting.update(
        {"grader_calls": 1, "grader_containers": 1, "official_grader_runs": 1}
    )
    memory = {field: 0 for field in benchmark_matrix.MEMORY_FIELDS}
    static_fields: dict[str, object] = {
        "arm": arm,
        "runtime_arm": runtime_arm if runtime_arm is not None else arm,
        "target_id": result.task_id,
        "evidence_tail_hash": result.evidence_tail_hash,
    }
    evidence: dict[str, object] = {}
    if sequence_index is not None or sequence_sha256 is not None:
        assert type(sequence_index) is int and isinstance(sequence_sha256, str)
        static_fields.update(
            {
                "sequence_index": sequence_index,
                "sequence_sha256": sequence_sha256,
            }
        )
    if task_dir is not None:
        stream_id = task_dir.parent.name
        task_index = int(task_dir.name.split("-", 1)[0])
        fixture_task = _task(int(result.task_id.rsplit("-", 1)[-1]))
        fixture_image = _fixture_image(result.grade)
        stdout_path = task_dir / "stdout.txt"
        stderr_path = task_dir / "stderr.txt"
        report_path = task_dir / "report.json"
        checkout_path = task_dir / "checkout-evidence.json"
        events_path = task_dir / "evidence" / "events.jsonl"
        stdout_path.write_bytes(result.grade.stdout.encode("utf-8"))
        stderr_path.write_bytes(result.grade.stderr.encode("utf-8"))
        benchmark.write_json(report_path, result.grade.report)
        checkout = {
            "argv": [],
            "checkout_origin": "EXISTING_CHECKOUT",
            "stdout": "",
            "stderr": "",
            "head": "a" * 40,
            "initial_status": "",
            "materialization": None,
        }
        benchmark.write_json(checkout_path, checkout)
        if not events_path.exists():
            events_path.write_bytes(b"")
        memory = benchmark.actual_memory_metrics(result, events_path)
        checkpoint = benchmark.FileCheckpointStore(
            task_dir / "agent-checkpoints"
        ).load(
            result.run_id,
            required_config_hashes=None,
            required_evidence_hash=result.evidence_tail_hash,
        )
        checkpoint_path = task_dir / "agent-checkpoints" / f"{result.run_id}.json"
        static_fields.update(
            {
                "terminal_checkpoint_sha256": checkpoint.content_hash,
                "terminal_state": "DONE",
                "agent_config_hashes": dict(checkpoint.config_hashes),
                "benchmark_id": "fixture-benchmark",
                "execution_lock_hash": _FIXTURE_EXECUTION_LOCK_HASH,
                "namespace": _fixture_namespace(stream_id),
                "identity_seed_digest": _FIXTURE_IDENTITY_SEED_DIGEST,
                "runtime_lock_sha256": _FIXTURE_RUNTIME_LOCK_SHA256,
                "m2_policy_manifest_sha256": (
                    _FIXTURE_M2_POLICY_SHA256
                    if result.arm == "M2"
                    else None
                ),
                "selected_prompt_candidate_id": benchmark.CANDIDATE_IDS[0],
                "workspace_factory_hash": _FIXTURE_WORKSPACE_FACTORY_HASH,
                "expected_image_digest": fixture_image["expected_digest"],
                "observed_image_digest": fixture_image["expected_digest"],
                "checkout_evidence_sha256": benchmark.sha256_bytes(
                    benchmark.canonical_bytes(checkout)
                ),
            }
        )
        assert checkpoint.config_hashes == _fixture_agent_config_hashes(
            fixture_task,
            stream_id=stream_id,
            runtime_arm=result.arm,
            sequence_index=task_index,
        )
        evidence = {
            "stdout": benchmark.evidence_reference(task_dir, stdout_path),
            "stderr": benchmark.evidence_reference(task_dir, stderr_path),
            "report": benchmark.evidence_reference(task_dir, report_path),
            "raw_events": benchmark.evidence_reference(task_dir, events_path),
            "checkout": benchmark.evidence_reference(task_dir, checkout_path),
            "terminal_checkpoint": benchmark.evidence_reference(
                task_dir, checkpoint_path
            ),
            "restricted_grader_raw": [],
        }
    return benchmark.build_terminal_result_record(
        result=result,
        actual_accounting=accounting,
        actual_memory_metrics=memory,
        provider_outcomes=benchmark.provider_outcome_accounting(result.accounting),
        actual_usd=benchmark.actual_usd_for_accounting(
            accounting,
            benchmark.read_json(
                ROOT / "configs/trimem_v1/cost_plan.json"
            )["model_pricing"],
        ),
        static_fields=static_fields,
        evidence=evidence,
    )


def _materialize_validated_grader(
    task_dir: Path, task: CodingTask, result: AgentRunResult
) -> _FakeGrader:
    delegate = _FakeGrader(result.grade)
    preflight = _preflight(task_dir)
    gateway = _gateway_with_preflight(task_dir, delegate, preflight)
    gateway.grade(_request(task_dir, result.task_id, patch=result.patch))
    assert delegate.calls == 1
    _materialize_done_agent_checkpoint(task_dir, task, result)
    return delegate


def _materialize_done_agent_checkpoint(
    task_dir: Path, task: CodingTask, result: AgentRunResult
) -> None:
    stream_id = task_dir.parent.name
    sequence_index = int(task_dir.name.split("-", 1)[0])
    prepared_payload = {
        "schema": "trimem/benchmark-prepared-task-checkpoint/1.0",
        "namespace": _fixture_namespace(stream_id),
        "experiment_id": _fixture_experiment_id(stream_id),
        "split": "development",
        "arm_id": result.arm,
        "task_order_hash": _FIXTURE_TASK_ORDER_HASH,
        "config_hash": _FIXTURE_CONFIG_HASH,
        "run_nonce": _FIXTURE_RUN_NONCE,
        "sequence_index": sequence_index,
        "task_id": task.task_id,
        "canonical_evidence": _fixture_canonical_evidence(stream_id),
        "qdrant_evidence": _fixture_qdrant_evidence(),
        "lifecycle_receipt_evidence": _fixture_receipt_evidence(stream_id),
        "lifecycle_state": (
            _fixture_m2_lifecycle_checkpoint(stream_id)
            if result.arm == "M2"
            else {}
        ),
    }
    benchmark.write_json(
        task_dir / "prepared-task-checkpoint.json",
        {
            "payload": prepared_payload,
            "digest": "sha256:"
            + benchmark.sha256_bytes(
                benchmark.canonical_bytes(prepared_payload)
            ),
        },
    )
    evidence = benchmark.RawEvidenceLedger(
        task_dir / "evidence",
        clock=lambda: _FIXED_EVIDENCE_TIME,
    )
    assert evidence.last_event_hash == "0" * 64
    request_payload, result_payload = _grader_evidence_payloads(
        task,
        arm=result.arm,
        patch=result.patch,
        grade=result.grade,
    )
    patch_ref = evidence.put_blob(result.patch)
    assert patch_ref == request_payload["patch"]
    evidence.append("grader_request", request_payload)
    evidence.put_blob(result.grade.stdout)
    evidence.put_blob(result.grade.stderr)
    evidence.put_blob(result.grade.report)
    evidence.append("grader_result", result_payload)
    assert evidence.last_event_hash == result.evidence_tail_hash
    grade = asdict(result.grade)
    extraction = asdict(result.extraction)
    storage = dict(result.lifecycle_result["storage"])
    credit = dict(result.lifecycle_result["credit"])
    terminal_payload = {
        (
            "patch"
            if result.cell_status == "AGENT_COMPLETED"
            else "graded_patch"
        ): patch_ref,
        "patch_sha256": hashlib.sha256(result.patch.encode("utf-8")).hexdigest(),
        "grade": grade,
        "grade_sha256": benchmark.sha256_bytes(benchmark.canonical_bytes(grade)),
        "extraction": extraction,
        "extraction_sha256": benchmark.sha256_bytes(
            benchmark.canonical_bytes(extraction)
        ),
        "storage_result": storage,
        "storage_result_sha256": benchmark.sha256_bytes(
            benchmark.canonical_bytes(storage)
        ),
        "credit_result": credit,
        "credit_result_sha256": benchmark.sha256_bytes(
            benchmark.canonical_bytes(credit)
        ),
        "lifecycle_result": dict(result.lifecycle_result),
        "cell_status": result.cell_status,
        "model_failure_class": result.model_failure_class,
        "grader_patch_source": result.grader_patch_source,
        "agent_completed": result.agent_completed,
        "extraction_status": result.extraction_status,
        "failure_metadata": result.failure_metadata,
    }
    checkpoint = benchmark.RuntimeCheckpoint(
        run_id=result.run_id,
        task_id=result.task_id,
        arm=result.arm,
        generation=1,
        next_step_no=1,
        state="DONE",
        active_node_id=None,
        graph_snapshot=result.graph_snapshot,
        workspace_state={},
        injected_memory_ids=(),
        injected_bytes=0,
        injection_ledger=result.injections,
        tool_history=(),
        completed_call_ids=(),
        accounting=result.accounting,
        config_hashes=_fixture_agent_config_hashes(
            task,
            stream_id=stream_id,
            runtime_arm=result.arm,
            sequence_index=sequence_index,
        ),
        evidence_event_hash=result.evidence_tail_hash,
        lifecycle_state=(
            _fixture_m2_lifecycle_checkpoint(stream_id)
            if result.arm == "M2"
            else {}
        ),
        terminal_payload=terminal_payload,
    )
    benchmark.FileCheckpointStore(task_dir / "agent-checkpoints").save(
        checkpoint
    )


class _Session:
    def __init__(self, *, stream_id: str = "M0", arm: str = "M0") -> None:
        self.task_cursor = 0
        self.stream_id = stream_id
        self.arm = arm
        self._active: str | None = None
        self.started: list[str] = []
        self.completed: list[str] = []
        self.completed_digests: list[str] = []

    def before_task(self, task: CodingTask, index: int) -> None:
        assert index == self.task_cursor
        self._active = task.task_id
        self.started.append(task.task_id)

    def controller_for(self, task: CodingTask) -> object:
        assert self._active == task.task_id
        return object()

    def after_task_and_checkpoint(self, task: CodingTask, result: object) -> dict:
        from enterprise_memory.trimem.production_runtime import _sha256

        task_id = result["task_id"] if isinstance(result, dict) else result.task_id
        assert self._active == task.task_id == task_id
        sequence_index = self.task_cursor
        result_payload = dict(result) if isinstance(result, dict) else asdict(result)
        self.completed_digests.append(
            _sha256(
                {
                    "task_id": task_id,
                    "arm": self.arm,
                    "sequence_index": sequence_index,
                    "result": result_payload,
                    "controller_state": {},
                }
            )
        )
        self.task_cursor += 1
        self._active = None
        self.completed.append(task.task_id)
        payload = {
            "schema": "trimem/benchmark-arm-checkpoint/1.0",
            "namespace": _fixture_namespace(self.stream_id),
            "experiment_id": _fixture_experiment_id(self.stream_id),
            "split": "development",
            "arm_id": self.arm,
            "task_order_hash": _FIXTURE_TASK_ORDER_HASH,
            "config_hash": _FIXTURE_CONFIG_HASH,
            "run_nonce": _FIXTURE_RUN_NONCE,
            "next_sequence_index": self.task_cursor,
            "task_cursor": self.task_cursor,
            "stream_state": "TASK_STREAM",
            "canonical_evidence": _fixture_canonical_evidence(self.stream_id),
            "qdrant_evidence": _fixture_qdrant_evidence(),
            "lifecycle_receipt_evidence": _fixture_receipt_evidence(
                self.stream_id
            ),
            "completed_task_digests": list(self.completed_digests),
            "lifecycle_state": (
                {
                    "persistence": {},
                    "lifecycle": _fixture_m2_lifecycle_checkpoint(
                        self.stream_id
                    ),
                }
                if self.arm == "M2"
                else {"persistence": {}, "lifecycle": {}}
                if self.arm == "M1"
                else {}
            ),
        }
        return {
            "payload": payload,
            "digest": "sha256:" + benchmark.sha256_bytes(benchmark.canonical_bytes(payload)),
        }


def _gateway_with_preflight(
    task_dir: Path,
    delegate: object,
    preflight: dict[str, object],
) -> benchmark.JournaledGraderGateway:
    delegate.python_loader_evidence = dict(preflight["python_loader"])
    delegate.execution_env = _preflight_environment(preflight)
    return benchmark.JournaledGraderGateway(
        delegate,
        benchmark.TerminalInvocationJournal(task_dir / "terminal-journal"),
        preflight_evidence=preflight,
        python_binary=preflight["python_loader"]["python_binary_realpath"],
    )


def _finalize_fixture_ledger(
    ledger: benchmark.AtomicBudgetLedger,
    records: list[dict[str, object]],
) -> dict[str, object]:
    expected_actual: dict[str, object] = {
        "paid_model_calls": sum(
            int(row["actual_accounting"]["paid_model_calls"]) for row in records
        ),
        "solve_calls": sum(
            int(row["actual_accounting"]["solve_calls"]) for row in records
        ),
        "decomposition_calls": sum(
            int(row["actual_accounting"]["decomposition_calls"])
            for row in records
        ),
        "extraction_calls": sum(
            int(row["actual_accounting"]["extraction_calls"])
            for row in records
        ),
        "input_tokens": sum(
            int(row["actual_accounting"]["input_tokens"]) for row in records
        ),
        "cached_input_tokens": sum(
            int(row["actual_accounting"]["cached_input_tokens"])
            for row in records
        ),
        "output_tokens": sum(
            int(row["actual_accounting"]["output_tokens"]) for row in records
        ),
        "total_usd": format(
            sum((Decimal(str(row["actual_usd"])) for row in records), Decimal(0)),
            ".12f",
        ),
        "task_arm_runs": len(records),
        "grader_containers": sum(int(row["container_started"]) for row in records),
    }
    expected_task_arms = {
        benchmark.scientific_task_arm_key(row): {
            **{
                field: int(row["actual_accounting"][field])
                for field in benchmark.TASK_LEDGER_PROJECTION_FIELDS
                if field != "total_usd"
            },
            "total_usd": row["actual_usd"],
        }
        for row in records
    }
    return ledger.finalize(
        expected_actual=expected_actual,
        expected_task_arms=expected_task_arms,
        expected_result_records=records,
    )


def _materialize_committed_prefix(
    execution_root: Path,
    *,
    approved_cells: int,
    committed_cells: int,
    stream_id: str = "M0",
    arm: str = "M0",
) -> tuple[list[CodingTask], benchmark.AtomicBudgetLedger, _Session]:
    assert 0 < committed_cells <= approved_cells
    tasks = [_task(index) for index in range(approved_cells)]
    ledger = _ledger(execution_root, approved_cells)
    session = _Session(stream_id=stream_id, arm=arm)
    preflight = _preflight(execution_root / "loader-fixture")
    delegate = _RoutingFakeGrader()
    for index, task in enumerate(tasks[:committed_cells]):
        task_key = f"{stream_id}:{arm}:{task.task_id}"
        reservation = ledger.reserve_task_arm(task_key)
        task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
            execution_root, stream_id, index, task
        )
        task_dir.mkdir(parents=True)
        result = _agent_result(task, arm=arm)
        _materialize_done_agent_checkpoint(task_dir, task, result)
        observed_grade = _gateway_with_preflight(
            task_dir, delegate, preflight
        ).grade(_request(task_dir, task.task_id, patch=""))
        assert observed_grade == result.grade
        record = _record(
            result,
            arm=stream_id,
            runtime_arm=arm,
            task_dir=task_dir,
            sequence_index=index,
            sequence_sha256="fixture-sequence",
        )
        session.before_task(task, index)
        session.controller_for(task)
        benchmark.commit_scientific_cell(
            task_dir=task_dir,
            task=task,
            target_id=task.task_id,
            stream_id=stream_id,
            arm=arm,
            sequence_index=index,
            task_arm_key=task_key,
            task_reservation=reservation,
            record=record,
            result=result,
            ledger=ledger,
            session=session,
            output_root=execution_root,
        )
    assert delegate.calls == committed_cells
    return tasks, ledger, session


def _install_frozen_resume_authority(
    monkeypatch: pytest.MonkeyPatch,
    execution_root: Path,
    *,
    tasks: list[CodingTask],
    stream_plan: list[tuple[str, str]],
    target_ids: list[str] | None = None,
    target_sequence_sha256: str = "fixture-sequence",
) -> dict[str, object]:
    """Install a complete immutable plan at the wrapper's authority boundary."""

    ledger_raw = benchmark.read_json(execution_root / "budget-ledger.json")
    planned_target_ids = (
        list(target_ids)
        if target_ids is not None
        else [task.task_id for task in tasks]
    )
    authority_targets: list[dict[str, object]] = []
    for index, target_id in enumerate(planned_target_ids):
        task = tasks[index]
        authority_targets.append(
            {
                **_fixture_manifest_target(task, index),
                "target_id": target_id,
            }
        )
    images = {
        task.task_id: _fixture_image(_grade(task.task_id))
        for task in tasks
    }
    authority = {
        "approval": {},
        "approval_digest": ledger_raw["approval_digest"],
        "git_head": "a" * 40,
        "hard_cap": ledger_raw["approved_hard_cap"],
        "pricing": {
            "input_per_million_tokens_usd": ledger_raw["pricing"]["input"],
            "cached_input_per_million_tokens_usd": ledger_raw["pricing"]["cached"],
            "output_per_million_tokens_usd": ledger_raw["pricing"]["output"],
        },
        "stream_plan": list(stream_plan),
        "targets": authority_targets,
        "target_ids": planned_target_ids,
        "target_sequence_sha256": target_sequence_sha256,
        "tasks": list(tasks),
        "rows": {},
        "task_order_hash": _FIXTURE_TASK_ORDER_HASH,
        "images": images,
        "model_lock": {"primary_model": _FIXTURE_PRIMARY_MODEL},
        "official_preflight": {},
        "harnesses": {},
    }
    monkeypatch.setattr(
        resume_driver,
        "_validated_resume_authority",
        lambda *_args, **_kwargs: dict(authority),
    )
    monkeypatch.setattr(
        resume_driver,
        "_selected_candidate_for_stream",
        lambda *_args, **_kwargs: benchmark.CANDIDATE_IDS[0],
    )
    monkeypatch.setattr(
        resume_driver,
        "_validate_resume_checkout_suffix",
        lambda *_args, **_kwargs: None,
    )

    def fixture_stream_authority(
        _benchmark: object,
        _authority: object,
        root: Path,
        *,
        split: str,
        stream_id: str,
        runtime_arm: str,
        selected_candidate_id: str,
    ) -> dict[str, object]:
        assert split == "development"
        assert selected_candidate_id == benchmark.CANDIDATE_IDS[0]
        checkout_roots = {
            task.task_id: benchmark._task_recovery_paths(
                root, stream_id, index, task
            )[0]
            for index, task in enumerate(tasks)
        }
        return {
            "experiment_id": _fixture_experiment_id(stream_id),
            "namespace": _fixture_namespace(stream_id),
            "task_order_hash": _FIXTURE_TASK_ORDER_HASH,
            "config_hash": _FIXTURE_CONFIG_HASH,
            "run_nonce": _FIXTURE_RUN_NONCE,
            "execution_lock_hash": _FIXTURE_EXECUTION_LOCK_HASH,
            "identity_seed_digest": _FIXTURE_IDENTITY_SEED_DIGEST,
            "runtime_lock_sha256": _FIXTURE_RUNTIME_LOCK_SHA256,
            "m2_policy_manifest_sha256": (
                _FIXTURE_M2_POLICY_SHA256 if runtime_arm == "M2" else None
            ),
            "selected_prompt_candidate_id": selected_candidate_id,
            "workspace_factory_hash": _FIXTURE_WORKSPACE_FACTORY_HASH,
            "memory_controller_hash": _fixture_memory_controller_hash(
                runtime_arm
            ),
            "workspace_factory": SimpleNamespace(
                checkout_roots=checkout_roots
            ),
            "images": images,
        }

    monkeypatch.setattr(
        resume_driver,
        "_stream_static_authority",
        fixture_stream_authority,
    )
    return {
        "split": "development",
        "approval_file": execution_root / "external-approval-fixture.json",
    }


def _assert_unknown_and_no_process_two(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sandbox: Path,
    execution_root: Path,
    resume_kwargs: dict[str, object],
) -> None:
    assert resume_driver._durable_resume_disposition(
        execution_root, **resume_kwargs
    ) == "UNKNOWN_FAILURE"

    monkeypatch.setattr(resume_driver, "ROOT", sandbox)
    process_calls: list[list[str]] = []

    def reported_safe(argv, **_kwargs):
        process_calls.append(list(argv))
        return subprocess.CompletedProcess(
            argv,
            9,
            stdout=(
                json.dumps(
                    {
                        "process_disposition": "RESUME_SAFE_DURABLE_SUFFIX",
                        "status": "FAIL",
                    }
                )
                + "\n"
            ).encode("utf-8"),
            stderr=b"",
        )

    monkeypatch.setattr(resume_driver.subprocess, "run", reported_safe)
    assert resume_driver.run_with_one_resume(
        "development", sandbox / "approval.json"
    ) == 9
    assert len(process_calls) == 1
    attempts = benchmark.read_json(
        execution_root / "driver-evidence/attempts.json"
    )
    assert attempts["first_disposition"] == "GLOBAL_EVIDENCE_FAILURE"
    assert attempts["resume_eligible"] is False
    assert attempts["resume_started"] is False


def _materialize_cursor_advanced_crash(
    output_root: Path,
) -> tuple[list[CodingTask], benchmark.AtomicBudgetLedger, _Session, Path]:
    task = _task(1)
    tasks = [task]
    ledger = _ledger(output_root, 1)
    task_key = f"M0:M0:{task.task_id}"
    reservation = ledger.reserve_task_arm(task_key)
    task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        output_root, "M0", 0, task
    )
    task_dir.mkdir(parents=True)
    result = _agent_result(task)
    _materialize_validated_grader(task_dir, task, result)
    session = _Session()
    session.before_task(task, 0)
    session.controller_for(task)

    def crash(state: str) -> None:
        if state == "CURSOR_ADVANCED":
            raise RuntimeError("simulated process crash after cursor checkpoint")

    with pytest.raises(benchmark.BenchmarkProcessFailure) as stopped:
        benchmark.commit_scientific_cell(
            task_dir=task_dir,
            task=task,
            target_id=task.task_id,
            stream_id="M0",
            arm="M0",
            sequence_index=0,
            task_arm_key=task_key,
            task_reservation=reservation,
            record=_record(
                result,
                task_dir=task_dir,
                sequence_index=0,
                sequence_sha256="fixture-sequence",
            ),
            result=result,
            ledger=ledger,
            session=session,
            output_root=output_root,
            transition_hook=crash,
        )
    assert stopped.value.disposition == "RESUME_SAFE_CELL_COMMIT_JOURNAL"
    journal_path = task_dir / "cell-commit-journal.json"
    assert benchmark.CellCommitJournal.read_verified(journal_path)["status"] == (
        "CURSOR_ADVANCED"
    )
    assert session.task_cursor == 1
    return tasks, ledger, session, journal_path


@pytest.mark.parametrize(
    "crash_state",
    ["PREPARED", "RESULT_WRITTEN", "LEDGER_TERMINAL", "CURSOR_ADVANCED"],
)
def test_cell_commit_recovers_without_reexecuting_the_grader(
    tmp_path: Path, crash_state: str
) -> None:
    task = _task(1)
    tasks = [task]
    ledger = _ledger(tmp_path, 1)
    task_key = f"M0:M0:{task.task_id}"
    reservation = ledger.reserve_task_arm(task_key)
    task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        tmp_path, "M0", 0, task
    )
    task_dir.mkdir(parents=True)
    result = _agent_result(task)
    delegate = _materialize_validated_grader(task_dir, task, result)
    session = _Session()
    session.before_task(task, 0)
    session.controller_for(task)

    def crash(state: str) -> None:
        if state == crash_state:
            raise RuntimeError("simulated process crash")

    with pytest.raises(benchmark.BenchmarkProcessFailure) as stopped:
        benchmark.commit_scientific_cell(
            task_dir=task_dir,
            task=task,
            target_id=task.task_id,
            stream_id="M0",
            arm="M0",
            sequence_index=0,
            task_arm_key=task_key,
            task_reservation=reservation,
            record=_record(result, task_dir=task_dir),
            result=result,
            ledger=ledger,
            session=session,
            output_root=tmp_path,
            transition_hook=crash,
        )
    assert stopped.value.disposition == "RESUME_SAFE_CELL_COMMIT_JOURNAL"
    journal_path = task_dir / "cell-commit-journal.json"
    journal_row = benchmark.CellCommitJournal.read_verified(journal_path)
    if crash_state == "PREPARED":
        # Result rename completed, process died before the journal transition.
        benchmark.atomic_write(
            benchmark._cell_result_path(task_dir, task),
            benchmark.json_file_bytes(journal_row["result_record"]),
        )
    elif crash_state == "RESULT_WRITTEN":
        # Ledger CAS completed, process died before LEDGER_TERMINAL was sealed.
        ledger.complete_task_arm(
            task_key,
            reservation,
            status="CELL_TERMINAL",
            container_started=True,
        )
    elif crash_state == "LEDGER_TERMINAL":
        # Canonical cursor CAS completed, process died before its journal edge.
        checkpoint = session.after_task_and_checkpoint(task, asdict(result))
        benchmark.save_arm_checkpoint(tmp_path, "M0", checkpoint)
    if crash_state in {"LEDGER_TERMINAL", "CURSOR_ADVANCED"}:
        assert session.task_cursor == 1
        assert benchmark.verify_cell_commit_frontier(
            output_root=tmp_path,
            stream_id="M0",
            arm="M0",
            tasks=tasks,
            expected_targets=_expected_targets(tmp_path, "M0", tasks),
            ledger=ledger,
            canonical_cursor=1,
        ) == 1
    else:
        recovered = _Session()
        assert benchmark.recover_cell_commit_frontier(
            output_root=tmp_path,
            stream_id="M0",
            arm="M0",
            tasks=tasks,
            expected_targets=_expected_targets(tmp_path, "M0", tasks),
            ledger=ledger,
            session=recovered,
            canonical_cursor=0,
        ) == 1
    row = benchmark.CellCommitJournal.read_verified(
        journal_path
    )
    assert row["status"] == "COMMITTED"
    assert ledger.task_arm_status(task_key) == "CELL_TERMINAL"
    ledger_state = ledger._read()
    assert ledger_state["actual"]["task_arm_runs"] == 1
    assert ledger_state["actual"]["grader_containers"] == 1
    assert ledger_state["actual"]["paid_model_calls"] == 0
    assert delegate.calls == 1
    assert len(list(task_dir.glob("*.result.json"))) == 1


def test_fresh_result_accounting_mismatch_cannot_terminalize_ledger(
    tmp_path: Path,
) -> None:
    task = _task(1)
    ledger = _ledger(tmp_path, 1)
    task_key = f"M0:M0:{task.task_id}"
    reservation = ledger.reserve_task_arm(task_key)
    task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        tmp_path, "M0", 0, task
    )
    task_dir.mkdir(parents=True)
    result = _agent_result(task)
    _materialize_validated_grader(task_dir, task, result)
    session = _Session()
    session.before_task(task, 0)
    session.controller_for(task)
    record = _record(result, task_dir=task_dir)
    record["actual_accounting"]["input_tokens"] = 1

    with pytest.raises(
        benchmark.BenchmarkExecutionError,
        match="reserved task-arm/result accounting differs",
    ):
        benchmark.commit_scientific_cell(
            task_dir=task_dir,
            task=task,
            target_id=task.task_id,
            stream_id="M0",
            arm="M0",
            sequence_index=0,
            task_arm_key=task_key,
            task_reservation=reservation,
            record=record,
            result=result,
            ledger=ledger,
            session=session,
            output_root=tmp_path,
        )

    assert ledger.task_arm_status(task_key) == "RESERVED"
    assert ledger._read()["actual"]["task_arm_runs"] == 0
    assert session.task_cursor == 0
    assert benchmark.CellCommitJournal.read_verified(
        task_dir / "cell-commit-journal.json"
    )["status"] == "RESULT_WRITTEN"


@pytest.mark.parametrize(
    "mutation",
    (
        "PATCH",
        "EXTRACTION",
        "INJECTIONS",
        "ACCOUNTING",
        "LIFECYCLE_RESULT",
        "EVIDENCE_TAIL_HASH",
        "TERMINAL_STATE",
        "TERMINAL_CHECKPOINT_SHA256",
        "TERMINAL_CHECKPOINT_REFERENCE",
        "ACTUAL_MEMORY_METRICS",
        "STDOUT_EVIDENCE",
        "CHECKOUT_EVIDENCE",
        "EVIDENCE_REFERENCE_PATH",
        "RAW_GRADER_RESULT_UNKNOWN_FIELD",
    ),
)
def test_resealed_inline_session_result_cannot_authorize_ledger_terminal_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    task = _task(1)
    ledger = _ledger(tmp_path, 1)
    task_key = f"M0:M0:{task.task_id}"
    reservation = ledger.reserve_task_arm(task_key)
    task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        tmp_path, "M0", 0, task
    )
    task_dir.mkdir(parents=True)
    result = _agent_result(task)
    _materialize_validated_grader(task_dir, task, result)
    session = _Session()
    session.before_task(task, 0)
    session.controller_for(task)

    with pytest.raises(benchmark.BenchmarkProcessFailure):
        benchmark.commit_scientific_cell(
            task_dir=task_dir,
            task=task,
            target_id=task.task_id,
            stream_id="M0",
            arm="M0",
            sequence_index=0,
            task_arm_key=task_key,
            task_reservation=reservation,
            record=_record(
                result,
                task_dir=task_dir,
                sequence_index=0,
                sequence_sha256="fixture-sequence",
            ),
            result=result,
            ledger=ledger,
            session=session,
            output_root=tmp_path,
            transition_hook=lambda state: (_ for _ in ()).throw(RuntimeError())
            if state == "LEDGER_TERMINAL"
            else None,
        )
    journal_path = task_dir / "cell-commit-journal.json"
    row = benchmark.CellCommitJournal.read_verified(journal_path)
    assert row["status"] == "LEDGER_TERMINAL"
    forged = json.loads(
        benchmark.canonical_bytes(row["session_result"]).decode("utf-8")
    )
    forged_record = json.loads(
        benchmark.canonical_bytes(row["result_record"]).decode("utf-8")
    )
    result_was_forged = False
    if mutation == "PATCH":
        forged["patch"] = "forged patch"
    elif mutation == "EXTRACTION":
        forged["extraction"]["response_hash"] = "e" * 64
    elif mutation == "INJECTIONS":
        forged["injections"].append({"memory_id": "forged"})
    elif mutation == "ACCOUNTING":
        forged["accounting"]["summary"]["forged"] = 1
    elif mutation == "LIFECYCLE_RESULT":
        forged["lifecycle_result"]["storage"] = {"forged": True}
    elif mutation == "EVIDENCE_TAIL_HASH":
        forged["evidence_tail_hash"] = "e" * 64
    elif mutation == "TERMINAL_STATE":
        forged_record["terminal_state"] = "FORGED_DONE"
        result_was_forged = True
    elif mutation == "TERMINAL_CHECKPOINT_SHA256":
        forged_record["terminal_checkpoint_sha256"] = "e" * 64
        result_was_forged = True
    elif mutation == "TERMINAL_CHECKPOINT_REFERENCE":
        forged_record["evidence"]["terminal_checkpoint"]["sha256"] = "e" * 64
        result_was_forged = True
    elif mutation == "ACTUAL_MEMORY_METRICS":
        forged_record["actual_memory_metrics"]["recall_attempts"] = 1
        result_was_forged = True
    elif mutation == "STDOUT_EVIDENCE":
        stdout_path = task_dir / "stdout.txt"
        stdout_path.write_bytes(b"forged grader output")
        forged_record["evidence"]["stdout"] = benchmark.evidence_reference(
            task_dir, stdout_path
        )
        result_was_forged = True
    elif mutation == "CHECKOUT_EVIDENCE":
        checkout_path = task_dir / "checkout-evidence.json"
        checkout = benchmark.read_json(checkout_path)
        checkout["head"] = "b" * 40
        benchmark.write_json(checkout_path, checkout)
        forged_record["checkout_evidence_sha256"] = benchmark.sha256_bytes(
            benchmark.canonical_bytes(checkout)
        )
        forged_record["evidence"]["checkout"] = benchmark.evidence_reference(
            task_dir, checkout_path
        )
        result_was_forged = True
    elif mutation == "EVIDENCE_REFERENCE_PATH":
        forged_record["evidence"]["stdout"]["path"] = "../outside.txt"
        result_was_forged = True
    elif mutation == "RAW_GRADER_RESULT_UNKNOWN_FIELD":
        events_path = task_dir / "evidence" / "events.jsonl"
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        assert [event["event_type"] for event in events] == [
            "grader_request",
            "grader_result",
        ]
        events[-1]["payload"]["attacker_controlled_field"] = True
        body = {
            name: value
            for name, value in events[-1].items()
            if name != "event_hash"
        }
        events[-1]["event_hash"] = benchmark.sha256_bytes(
            benchmark.canonical_bytes(body)
        )
        events_path.write_bytes(
            b"".join(
                benchmark.canonical_bytes(event) + b"\n"
                for event in events
            )
        )
        forged["evidence_tail_hash"] = events[-1]["event_hash"]
        forged_record["evidence_tail_hash"] = events[-1]["event_hash"]
        checkpoint_path = (
            task_dir / "agent-checkpoints" / f"{result.run_id}.json"
        )
        checkpoint = benchmark.read_json(checkpoint_path)
        checkpoint["evidence_event_hash"] = events[-1]["event_hash"]
        checkpoint_raw = benchmark.canonical_bytes(checkpoint)
        checkpoint_sha256 = benchmark.sha256_bytes(checkpoint_raw)
        checkpoint_path.write_bytes(checkpoint_raw)
        checkpoint_path.with_suffix(".sha256").write_text(
            checkpoint_sha256 + "\n", encoding="ascii", newline="\n"
        )
        forged_record["terminal_checkpoint_sha256"] = checkpoint_sha256
        forged_record["evidence"]["raw_events"] = (
            benchmark.evidence_reference(task_dir, events_path)
        )
        forged_record["evidence"]["terminal_checkpoint"] = (
            benchmark.evidence_reference(task_dir, checkpoint_path)
        )
        result_was_forged = True
    else:  # pragma: no cover - the parameter set is closed.
        raise AssertionError(mutation)
    row["session_result"] = forged
    row["result_record"] = forged_record
    row["binding"]["session_result_sha256"] = benchmark.sha256_bytes(
        benchmark.canonical_bytes(forged)
    )
    row["binding"]["result_sha256"] = benchmark.sha256_bytes(
        benchmark.json_file_bytes(forged_record)
    )
    row["binding_sha256"] = benchmark.sha256_bytes(
        benchmark.canonical_bytes(row["binding"])
    )
    benchmark.write_json(
        journal_path,
        benchmark.CellCommitJournal._sealed(row),
    )
    if result_was_forged:
        benchmark.atomic_write(
            benchmark._cell_result_path(task_dir, task),
            benchmark.json_file_bytes(forged_record),
        )

    # All attacker-controlled journal seals are internally coherent.  The
    # retained DONE checkpoint and raw evidence are the independent authority.
    resealed = benchmark.CellCommitJournal.read_verified(journal_path)
    assert resealed["session_result"] == forged
    with pytest.raises(
        benchmark.BenchmarkExecutionError,
        match=(
            "DONE checkpoint|checkpoint/evidence|memory metrics|grader evidence|"
            "checkout evidence|canonical evidence|raw grader result"
        ),
    ):
        benchmark.validate_cell_session_result_against_done_checkpoint(
            task_dir,
            resealed,
            resealed["result_record"],
            grader_result=benchmark._validated_task_grader_result(task_dir),
            expected_target=_target(task, task_dir),
        )
    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        tmp_path,
        tasks=[task],
        stream_plan=[("M0", "M0")],
    )
    assert resume_driver._durable_resume_disposition(
        tmp_path,
        **resume_kwargs,
    ) == (
        "UNKNOWN_FAILURE"
    )
    with pytest.raises(benchmark.BenchmarkExecutionError):
        benchmark.verify_cell_commit_frontier(
            output_root=tmp_path,
            stream_id="M0",
            arm="M0",
            tasks=[task],
            expected_targets=_expected_targets(tmp_path, "M0", [task]),
            ledger=ledger,
            canonical_cursor=0,
        )
    with pytest.raises(
        benchmark.BenchmarkExecutionError,
        match=(
            "DONE checkpoint|checkpoint/evidence|memory metrics|grader evidence|"
            "checkout evidence|canonical evidence|raw grader result"
        ),
    ):
        benchmark.recover_cell_commit_frontier(
            output_root=tmp_path,
            stream_id="M0",
            arm="M0",
            tasks=[task],
            expected_targets=_expected_targets(tmp_path, "M0", [task]),
            ledger=ledger,
            session=_Session(),
            canonical_cursor=0,
        )


@pytest.mark.parametrize(
    "retained_file",
    ("STDOUT", "EVENTS", "PATCH_BLOB", "DONE_SIDECAR", "EVIDENCE_DIR"),
)
def test_symlinked_retained_evidence_is_unknown_and_never_starts_process_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    retained_file: str,
) -> None:
    """Identical bytes outside the task custody root are not resume authority."""

    def short_fixture_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    monkeypatch.setattr(benchmark, "atomic_write", short_fixture_write)
    sandbox = tmp_path
    execution_root = (
        sandbox / "artifacts/trimem_v1/benchmark_exec/development"
    )
    tasks, ledger, _session = _materialize_committed_prefix(
        execution_root,
        approved_cells=1,
        committed_cells=1,
    )
    task = tasks[0]
    task_dir, run_id, _prepared = benchmark._task_recovery_paths(
        execution_root, "M0", 0, task
    )
    paths = {
        "STDOUT": task_dir / "stdout.txt",
        "EVENTS": task_dir / "evidence" / "events.jsonl",
        "PATCH_BLOB": (
            task_dir
            / "evidence"
            / "blobs"
            / hashlib.sha256(b"").hexdigest()
        ),
        "DONE_SIDECAR": task_dir / "agent-checkpoints" / f"{run_id}.sha256",
        "EVIDENCE_DIR": task_dir / "evidence",
    }
    retained = paths[retained_file]
    outside = sandbox / f"outside-{retained_file.lower()}"
    is_directory = retained_file == "EVIDENCE_DIR"
    if is_directory:
        retained.rename(outside)
    else:
        outside.write_bytes(retained.read_bytes())
        retained.unlink()
    try:
        retained.symlink_to(outside, target_is_directory=is_directory)
    except OSError as exc:  # pragma: no cover - Windows policy dependent.
        pytest.skip(f"symbolic links unavailable: {exc}")
    assert retained.is_symlink()

    with pytest.raises(
        benchmark.BenchmarkExecutionError,
        match="symlink",
    ):
        benchmark.verify_cell_commit_frontier(
            output_root=execution_root,
            stream_id="M0",
            arm="M0",
            tasks=tasks,
            expected_targets=_expected_targets(
                execution_root, "M0", tasks
            ),
            ledger=ledger,
            canonical_cursor=1,
        )
    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=tasks,
        stream_plan=[("M0", "M0")],
    )
    _assert_unknown_and_no_process_two(
        monkeypatch,
        sandbox=sandbox,
        execution_root=execution_root,
        resume_kwargs=resume_kwargs,
    )


@pytest.mark.parametrize("status", ("CURSOR_ADVANCED", "COMMITTED"))
@pytest.mark.parametrize("mutation", ("MISSING", "MALFORMED"))
def test_cursor_terminal_cell_journal_requires_checkpoint_digest(
    tmp_path: Path,
    status: str,
    mutation: str,
) -> None:
    if status == "CURSOR_ADVANCED":
        _tasks, _ledger_row, _session, journal_path = (
            _materialize_cursor_advanced_crash(tmp_path)
        )
    else:
        tasks, _ledger_row, _session = _materialize_committed_prefix(
            tmp_path,
            approved_cells=1,
            committed_cells=1,
        )
        task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
            tmp_path, "M0", 0, tasks[0]
        )
        journal_path = task_dir / "cell-commit-journal.json"

    row = benchmark.CellCommitJournal.read_verified(journal_path)
    assert row["status"] == status
    if mutation == "MISSING":
        row.pop("stream_checkpoint_sha256")
    else:
        row["stream_checkpoint_sha256"] = "not-a-sha256"
    benchmark.write_json(
        journal_path, benchmark.CellCommitJournal._sealed(row)
    )

    with pytest.raises(
        benchmark.BenchmarkExecutionError,
        match=(
            "cell-commit journal integrity failure"
            if mutation == "MISSING"
            else "cell-commit stream checkpoint hash is malformed"
        ),
    ):
        benchmark.CellCommitJournal.read_verified(journal_path)


def test_resealed_checkpoint_payload_after_cursor_crash_fails_closed(
    tmp_path: Path,
) -> None:
    tasks, ledger, _session, _journal_path = (
        _materialize_cursor_advanced_crash(tmp_path)
    )
    checkpoint = benchmark.load_arm_checkpoint(tmp_path, "M0")
    payload = dict(checkpoint["payload"])
    payload["task_cursor"] = 2
    tampered = {
        "payload": payload,
        "digest": "sha256:"
        + benchmark.sha256_bytes(benchmark.canonical_bytes(payload)),
    }
    # Rewriting through the real saver also reseals the outer sidecar.  The
    # remaining mismatch is exclusively the cell journal's checkpoint bind.
    benchmark.save_arm_checkpoint(tmp_path, "M0", tampered)
    assert benchmark.load_arm_checkpoint(tmp_path, "M0") == tampered

    with pytest.raises(
        benchmark.BenchmarkExecutionError,
        match="stream checkpoint",
    ):
        benchmark.verify_cell_commit_frontier(
            output_root=tmp_path,
            stream_id="M0",
            arm="M0",
            tasks=tasks,
            expected_targets=_expected_targets(tmp_path, "M0", tasks),
            ledger=ledger,
            canonical_cursor=1,
        )
    with pytest.raises(
        benchmark.BenchmarkExecutionError,
        match="stream checkpoint",
    ):
        benchmark.recover_cell_commit_frontier(
            output_root=tmp_path,
            stream_id="M0",
            arm="M0",
            tasks=tasks,
            expected_targets=_expected_targets(tmp_path, "M0", tasks),
            ledger=ledger,
            session=_Session(),
            canonical_cursor=1,
        )


def test_two_cells_form_one_contiguous_committed_cursor_prefix(tmp_path: Path) -> None:
    tasks = [_task(1), _task(2)]
    ledger = _ledger(tmp_path, 2)
    session = _Session()
    for index, task in enumerate(tasks):
        task_key = f"M0:M0:{task.task_id}"
        reservation = ledger.reserve_task_arm(task_key)
        task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
            tmp_path, "M0", index, task
        )
        task_dir.mkdir(parents=True)
        result = _agent_result(task)
        _materialize_validated_grader(task_dir, task, result)
        session.before_task(task, index)
        session.controller_for(task)
        benchmark.commit_scientific_cell(
            task_dir=task_dir,
            task=task,
            target_id=task.task_id,
            stream_id="M0",
            arm="M0",
            sequence_index=index,
            task_arm_key=task_key,
            task_reservation=reservation,
            record=_record(result, task_dir=task_dir),
            result=result,
            ledger=ledger,
            session=session,
            output_root=tmp_path,
        )
        assert benchmark.verify_cell_commit_frontier(
            output_root=tmp_path,
            stream_id="M0",
            arm="M0",
            tasks=tasks,
            expected_targets=_expected_targets(tmp_path, "M0", tasks),
            ledger=ledger,
            canonical_cursor=index + 1,
        ) == index + 1
    assert session.task_cursor == 2


def test_step_cap_partial_patch_commits_before_the_next_cell_executes(
    tmp_path: Path,
) -> None:
    tasks = [_task(1), _task(2)]
    ledger = _model_call_ledger(
        tmp_path,
        task_count=2,
        decomposition_cap=1,
        solve_cap=8,
        extraction_cap=1,
        max_calls_per_task=10,
    )
    preflight = _preflight(tmp_path / "loader-fixture")
    session = _Session()
    records: list[dict[str, object]] = []

    first = tasks[0]
    first_key = f"M0:M0:{first.task_id}"
    first_reservation = ledger.reserve_task_arm(first_key)
    first_accounting, first_requests = _record_successful_model_calls(
        ledger,
        first_key,
        ["decompose", *("solve" for _ in range(8)), "extract"],
    )
    first_accounting["tools"] = [{"tool_name": "replace_text"}]
    first_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        tmp_path, "M0", 0, first
    )
    first_dir.mkdir(parents=True)
    partial_patch = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -0,0 +1 @@\n"
        "+partial = True\n"
    )
    first_delegate = _FakeGrader(_grade(first.task_id, resolved=False))
    first_grade = _gateway_with_preflight(
        first_dir, first_delegate, preflight
    ).grade(_request(first_dir, first.task_id, patch=partial_patch))
    first_result = _production_result(
        first,
        grade=first_grade,
        accounting=first_accounting,
        patch=partial_patch,
        cell_status="CELL_SCIENTIFIC_FAILURE",
        model_failure_class="per-subtask step cap reached",
        grader_patch_source="MODEL_PARTIAL_PATCH",
        agent_completed=False,
    )
    _materialize_done_agent_checkpoint(first_dir, first, first_result)
    first_record = _record(
        first_result,
        task_dir=first_dir,
        sequence_index=0,
        sequence_sha256="fixture-sequence",
    )
    benchmark.validate_scientific_role_call_accounting(first_record)
    benchmark.validate_result_request_statuses(first_record, first_requests)
    session.before_task(first, 0)
    session.controller_for(first)
    benchmark.commit_scientific_cell(
        task_dir=first_dir,
        task=first,
        target_id=first.task_id,
        stream_id="M0",
        arm="M0",
        sequence_index=0,
        task_arm_key=first_key,
        task_reservation=first_reservation,
        record=first_record,
        result=first_result,
        ledger=ledger,
        session=session,
        output_root=tmp_path,
    )
    records.append(first_record)
    assert first_result.patch == partial_patch
    assert first_grade.official is True and first_grade.resolved is False
    assert first_record["grader_patch_source"] == "MODEL_PARTIAL_PATCH"
    assert first_record["actual_accounting"]["solve_calls"] == 8
    assert benchmark.CellCommitJournal.read_verified(
        first_dir / "cell-commit-journal.json"
    )["status"] == "COMMITTED"

    second = tasks[1]
    second_key = f"M0:M0:{second.task_id}"
    second_reservation = ledger.reserve_task_arm(second_key)
    second_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        tmp_path, "M0", 1, second
    )
    second_dir.mkdir(parents=True)
    second_result = _agent_result(second)
    second_delegate = _FakeGrader(second_result.grade)
    observed_second_grade = _gateway_with_preflight(
        second_dir, second_delegate, preflight
    ).grade(_request(second_dir, second.task_id, patch=""))
    assert observed_second_grade == second_result.grade
    _materialize_done_agent_checkpoint(second_dir, second, second_result)
    second_record = _record(
        second_result,
        task_dir=second_dir,
        sequence_index=1,
        sequence_sha256="fixture-sequence",
    )
    benchmark.validate_result_request_statuses(second_record, [])
    session.before_task(second, 1)
    session.controller_for(second)
    benchmark.commit_scientific_cell(
        task_dir=second_dir,
        task=second,
        target_id=second.task_id,
        stream_id="M0",
        arm="M0",
        sequence_index=1,
        task_arm_key=second_key,
        task_reservation=second_reservation,
        record=second_record,
        result=second_result,
        ledger=ledger,
        session=session,
        output_root=tmp_path,
    )
    records.append(second_record)

    assert session.started == [task.task_id for task in tasks]
    assert session.completed == [task.task_id for task in tasks]
    assert session.task_cursor == 2
    assert first_delegate.calls == second_delegate.calls == 1
    assert benchmark.verify_cell_commit_frontier(
        output_root=tmp_path,
        stream_id="M0",
        arm="M0",
        tasks=tasks,
        expected_targets=_expected_targets(tmp_path, "M0", tasks),
        ledger=ledger,
        canonical_cursor=2,
    ) == 2
    finalized = _finalize_fixture_ledger(ledger, records)
    assert finalized["actual"]["task_arm_runs"] == 2
    assert finalized["actual"]["grader_containers"] == 2
    terminal = benchmark_matrix.scientific_terminal_summary(records)
    assert terminal["model_failure_class_counts"] == {
        "PER_SUBTASK_STEP_CAP_REACHED": 1,
        "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED": 1,
    }


def test_resolved_model_patch_and_fake_official_result_commit_atomically(
    tmp_path: Path,
) -> None:
    task = _task(1)
    task_key = f"M0:M0:{task.task_id}"
    ledger = _model_call_ledger(
        tmp_path,
        task_count=1,
        decomposition_cap=1,
        solve_cap=1,
        extraction_cap=1,
        max_calls_per_task=3,
    )
    reservation = ledger.reserve_task_arm(task_key)
    accounting, requests = _record_successful_model_calls(
        ledger, task_key, ["decompose", "solve", "extract"]
    )
    patch = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -0,0 +1 @@\n"
        "+resolved = True\n"
    )
    task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        tmp_path, "M0", 0, task
    )
    task_dir.mkdir(parents=True)
    preflight = _preflight(tmp_path / "loader-fixture")
    delegate = _FakeGrader(_grade(task.task_id, resolved=True))
    grade = _gateway_with_preflight(task_dir, delegate, preflight).grade(
        _request(task_dir, task.task_id, patch=patch)
    )
    result = _production_result(
        task,
        grade=grade,
        accounting=accounting,
        patch=patch,
        cell_status="AGENT_COMPLETED",
        model_failure_class=None,
        grader_patch_source="MODEL_PATCH",
        agent_completed=True,
    )
    _materialize_done_agent_checkpoint(task_dir, task, result)
    record = _record(
        result,
        task_dir=task_dir,
        sequence_index=0,
        sequence_sha256="fixture-sequence",
    )
    benchmark.validate_scientific_role_call_accounting(record)
    benchmark.validate_result_request_statuses(record, requests)
    session = _Session()
    session.before_task(task, 0)
    session.controller_for(task)
    committed = benchmark.commit_scientific_cell(
        task_dir=task_dir,
        task=task,
        target_id=task.task_id,
        stream_id="M0",
        arm="M0",
        sequence_index=0,
        task_arm_key=task_key,
        task_reservation=reservation,
        record=record,
        result=result,
        ledger=ledger,
        session=session,
        output_root=tmp_path,
    )

    assert delegate.calls == 1
    assert result.patch == patch
    assert grade.official is True and grade.resolved is True
    assert record["resolved"] is True
    assert record["cell_status"] == "AGENT_COMPLETED"
    assert committed["status"] == "COMMITTED"
    assert session.task_cursor == 1
    finalized = _finalize_fixture_ledger(ledger, [record])
    assert finalized["actual"]["paid_model_calls"] == 3
    assert finalized["actual"]["grader_containers"] == 1


def test_72_fake_cells_cross_real_grader_and_atomic_commit_boundaries(
    tmp_path: Path,
) -> None:
    streams = (
        ("M2-baseline", "M2"),
        ("M2-precision", "M2"),
        ("M2-recall", "M2"),
        ("M2-balanced", "M2"),
        ("M0", "M0"),
        ("M1", "M1"),
    )
    tasks = [_task(index) for index in range(12)]
    task_count = len(streams) * len(tasks)
    assert task_count == 72
    ledger = _ledger(tmp_path, task_count)
    sessions = {
        stream_id: _Session(stream_id=stream_id, arm=runtime_arm)
        for stream_id, runtime_arm in streams
    }
    preflight = _preflight(tmp_path / "loader-fixture")
    delegate = _RoutingFakeGrader()
    records: list[dict[str, object]] = []

    for stream_id, runtime_arm in streams:
        session = sessions[stream_id]
        for index, task in enumerate(tasks):
            task_key = f"{stream_id}:{runtime_arm}:{task.task_id}"
            reservation = ledger.reserve_task_arm(task_key)
            task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
                tmp_path, stream_id, index, task
            )
            task_dir.mkdir(parents=True)
            gateway = _gateway_with_preflight(task_dir, delegate, preflight)
            grade = gateway.grade(_request(task_dir, task.task_id, patch=""))
            result = _agent_result(
                task,
                arm=runtime_arm,
                stream_id=stream_id,
            )
            assert grade == result.grade
            _materialize_done_agent_checkpoint(task_dir, task, result)
            record = _record(
                result,
                arm=stream_id,
                runtime_arm=runtime_arm,
                task_dir=task_dir,
                sequence_index=index,
                sequence_sha256="fixture-sequence",
            )
            benchmark.validate_result_request_statuses(record, [])
            session.before_task(task, index)
            session.controller_for(task)
            benchmark.commit_scientific_cell(
                task_dir=task_dir,
                task=task,
                target_id=task.task_id,
                stream_id=stream_id,
                arm=runtime_arm,
                sequence_index=index,
                task_arm_key=task_key,
                task_reservation=reservation,
                record=record,
                result=result,
                ledger=ledger,
                session=session,
                output_root=tmp_path,
            )
            records.append(record)

        assert benchmark.verify_cell_commit_frontier(
            output_root=tmp_path,
            stream_id=stream_id,
            arm=runtime_arm,
            tasks=tasks,
            expected_targets=_expected_targets(tmp_path, stream_id, tasks),
            ledger=ledger,
            canonical_cursor=len(tasks),
        ) == len(tasks)
    grader_paths = sorted(
        tmp_path.glob("*/*/terminal-journal/grader/*.json")
    )
    cell_paths = sorted(tmp_path.glob("*/*/cell-commit-journal.json"))
    result_paths = sorted(tmp_path.glob("*/*/*.result.json"))
    assert len(grader_paths) == len(cell_paths) == len(result_paths) == task_count
    grader_rows = [
        benchmark.TerminalInvocationJournal._validated_grader_row(path)
        for path in grader_paths
    ]
    assert {row["status"] for row in grader_rows} == {"GRADER_RESULT_VALIDATED"}
    assert sum(int(row["official_grader_runs"]) for row in grader_rows) == task_count
    assert sum(int(row["grader_containers"]) for row in grader_rows) == task_count
    assert len({row["key"] for row in grader_rows}) == task_count
    cell_rows = [benchmark.CellCommitJournal.read_verified(path) for path in cell_paths]
    assert {row["status"] for row in cell_rows} == {"COMMITTED"}
    assert len({row["binding"]["task_arm_key"] for row in cell_rows}) == task_count
    for record in records:
        task_key = benchmark.scientific_task_arm_key(record)
        ledger_row = ledger.task_arm_row(task_key)
        assert ledger_row is not None
        benchmark._validate_cell_result_ledger_pair(
            record, ledger_row, task_arm_key=task_key
        )
    ledger_state = _finalize_fixture_ledger(ledger, records)
    assert ledger_state["actual"]["task_arm_runs"] == task_count
    assert ledger_state["actual"]["grader_containers"] == task_count
    assert all(value == 0 for value in ledger_state["outstanding"].values())
    assert {session.task_cursor for session in sessions.values()} == {len(tasks)}
    assert delegate.calls == task_count
    assert set(delegate.task_ids) == {task.task_id for task in tasks}
    assert all(delegate.task_ids.count(task.task_id) == len(streams) for task in tasks)
    assert delegate.real_external_calls == 0

    terminal = benchmark_matrix.scientific_terminal_summary(records)
    assert terminal == {
        "terminal_result_count": task_count,
        "resolved_count": 0,
        "unresolved_count": task_count,
        "contained_failure_count": task_count,
        "cell_status_counts": {"CELL_SCIENTIFIC_FAILURE": task_count},
        "model_failure_class_counts": {
            "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED": task_count
        },
        "model_partial_patch_count": 0,
        "canonical_failed_cell_noop_count": task_count,
        "extraction_failure_count": 0,
    }
    accounting = {
        field: sum(int(row["actual_accounting"][field]) for row in records)
        for field in public_artifact.SCIENTIFIC_ACCOUNTING_FIELDS
    }
    memory = {
        field: sum(int(row["actual_memory_metrics"][field]) for row in records)
        for field in public_artifact.SCIENTIFIC_MEMORY_FIELDS
    }
    provider = benchmark.combine_provider_outcomes(
        [row["provider_outcomes"] for row in records]
    )
    outcomes = [
        {
            "arm": row["arm"],
            "benchmark_id": "swebench_verified",
            "benchmark_role": "PRIMARY",
            "resolved": row["resolved"],
            "target_id": row["target_id"],
            "actual_accounting": row["actual_accounting"],
            "actual_memory_metrics": row["actual_memory_metrics"],
            "provider_outcomes": row["provider_outcomes"],
            "actual_usd": row["actual_usd"],
        }
        for row in records
    ]
    validated_terminal = public_artifact.validate_public_scientific_terminal_summary(
        terminal, outcomes=outcomes
    )
    total_usd = benchmark.actual_usd_for_accounting(
        accounting,
        {
            "input_per_million_tokens_usd": 1,
            "cached_input_per_million_tokens_usd": 1,
            "output_per_million_tokens_usd": 1,
        },
    )
    phase_budget = {
        "schema": "trimem/verified-phase-budget/1.0",
        "actual_accounting": accounting,
        "model_calls": 0,
        "task_arm_runs": task_count,
        "total_usd": total_usd,
        "uncached_token_cost_usd": total_usd,
        "hard_cap": {},
        "status": "PASS",
    }
    stream_total_inputs: list[dict[str, object]] = []
    for stream_id, _runtime_arm in streams:
        stream_records = [row for row in records if row["arm"] == stream_id]
        stream_terminal = benchmark_matrix.scientific_terminal_summary(
            stream_records
        )
        stream_accounting = {
            field: sum(
                int(row["actual_accounting"][field]) for row in stream_records
            )
            for field in public_artifact.SCIENTIFIC_ACCOUNTING_FIELDS
        }
        stream_memory = {
            field: sum(
                int(row["actual_memory_metrics"][field]) for row in stream_records
            )
            for field in public_artifact.SCIENTIFIC_MEMORY_FIELDS
        }
        stream_provider = benchmark.combine_provider_outcomes(
            [row["provider_outcomes"] for row in stream_records]
        )
        stream_total_inputs.append(
            {
                "arm": stream_id,
                "actual_accounting": stream_accounting,
                "actual_memory_metrics": stream_memory,
                "provider_outcomes": stream_provider,
                "actual_usd": benchmark.actual_usd_for_accounting(
                    stream_accounting,
                    {
                        "input_per_million_tokens_usd": 1,
                        "cached_input_per_million_tokens_usd": 1,
                        "output_per_million_tokens_usd": 1,
                    },
                ),
                "identity_seed_digest": "sha256:"
                + hashlib.sha256(stream_id.encode("utf-8")).hexdigest(),
                "reporting_scope": "DESCRIPTIVE_POOLED_ALL_BENCHMARKS",
                "resolved_count": stream_terminal["resolved_count"],
                "terminal_result_count": stream_terminal[
                    "terminal_result_count"
                ],
                "cell_status_counts": stream_terminal["cell_status_counts"],
                "contained_failure_count": stream_terminal[
                    "contained_failure_count"
                ],
                "model_failure_class_counts": stream_terminal[
                    "model_failure_class_counts"
                ],
                "model_partial_patch_count": stream_terminal[
                    "model_partial_patch_count"
                ],
                "canonical_failed_cell_noop_count": stream_terminal[
                    "canonical_failed_cell_noop_count"
                ],
                "extraction_failure_count": stream_terminal[
                    "extraction_failure_count"
                ],
            }
        )
    stream_totals = public_artifact.validate_public_scientific_stream_totals(
        stream_total_inputs,
        outcomes=outcomes,
        arms=[stream_id for stream_id, _runtime_arm in streams],
        terminal_summary=validated_terminal,
        pricing={
            "input_per_million_tokens_usd": 1,
            "cached_input_per_million_tokens_usd": 1,
            "output_per_million_tokens_usd": 1,
        },
        phase_budget=phase_budget,
        global_provider_outcomes=provider,
    )
    fake_counters = {
        "fake_grader_delegate_calls": delegate.calls,
        "fake_grader_results": task_count,
        "expected_official_grader_runs": task_count,
        "expected_grader_containers": task_count,
        "real_model_api_calls": 0,
        "real_grader_process_calls": delegate.real_external_calls,
        "real_docker_calls": 0,
    }
    aggregate_path = tmp_path / "aggregate.TEST_FAKE.json"
    public_path = tmp_path / "public.TEST_FAKE.json"
    benchmark.write_json(
        aggregate_path,
        {
            "schema": "trimem/d110-test-fake-aggregate/1.0",
            "status": "TEST_FAKE_ONLY",
            "scientific_terminal_summary": validated_terminal,
            "outcomes": outcomes,
            "stream_totals": stream_totals,
            "execution_counters": fake_counters,
        },
    )
    public_outcomes = [
        {
            key: row[key]
            for key in public_artifact.BENCHMARK_OUTCOME_FIELDS
        }
        for row in outcomes
    ]
    benchmark.write_json(
        public_path,
        {
            "schema": "trimem/d110-test-fake-public-artifact/1.0",
            "status": "TEST_FAKE_ONLY",
            "scientific_terminal_summary": validated_terminal,
            "outcomes": public_outcomes,
            "stream_totals": stream_totals,
            "execution_counters": fake_counters,
        },
    )
    assert aggregate_path.is_file() and public_path.is_file()
    assert fake_counters == {
        "fake_grader_delegate_calls": 72,
        "fake_grader_results": 72,
        "expected_official_grader_runs": 72,
        "expected_grader_containers": 72,
        "real_model_api_calls": 0,
        "real_grader_process_calls": 0,
        "real_docker_calls": 0,
    }
    forbidden_public_outcome_fields = {
        "cell_status",
        "execution_status",
        "failure_metadata",
        "grader_exit_code",
        "grader_status",
        "model_failure_class",
    }
    assert all(
        not (forbidden_public_outcome_fields & set(row)) for row in public_outcomes
    )


@pytest.mark.parametrize(
    ("approved_cells", "committed_cells", "boundary"),
    (
        (2, 1, "BETWEEN_CELLS"),
        (2, 2, "FINAL_BEFORE_AGGREGATE"),
    ),
)
def test_all_committed_frontier_is_a_verified_durable_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    approved_cells: int,
    committed_cells: int,
    boundary: str,
) -> None:
    def short_fixture_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    monkeypatch.setattr(benchmark, "atomic_write", short_fixture_write)
    execution_root = tmp_path / boundary
    tasks, ledger, session = _materialize_committed_prefix(
        execution_root,
        approved_cells=approved_cells,
        committed_cells=committed_cells,
    )
    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=tasks,
        stream_plan=[("M0", "M0")],
    )

    assert session.task_cursor == committed_cells
    assert len(ledger._read()["task_arms"]) == committed_cells
    assert resume_driver._durable_resume_disposition(
        execution_root, **resume_kwargs
    ) == (
        "RESUME_SAFE_DURABLE_SUFFIX"
    )


@pytest.mark.parametrize(
    "mutation",
    ("ARBITRARY_STREAM", "SWAPPED_TARGET_INDEX", "WRONG_SEQUENCE_DIGEST"),
)
def test_frozen_plan_mismatch_is_unknown_and_never_starts_process_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    """Self-consistent local seals cannot replace the approved campaign plan."""

    def short_fixture_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    monkeypatch.setattr(benchmark, "atomic_write", short_fixture_write)
    sandbox = tmp_path
    execution_root = (
        sandbox / "artifacts/trimem_v1/benchmark_exec/development"
    )
    approved_cells = 2 if mutation == "SWAPPED_TARGET_INDEX" else 1
    stream_id = "ARBITRARY" if mutation == "ARBITRARY_STREAM" else "M0"
    arm = "ARBITRARY" if mutation == "ARBITRARY_STREAM" else "M0"
    tasks, _ledger_row, _session = _materialize_committed_prefix(
        execution_root,
        approved_cells=approved_cells,
        committed_cells=approved_cells,
        stream_id=stream_id,
        arm=arm,
    )
    target_ids = [task.task_id for task in tasks]
    if mutation == "SWAPPED_TARGET_INDEX":
        target_ids.reverse()
    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=tasks,
        stream_plan=[("M0", "M0")],
        target_ids=target_ids,
        target_sequence_sha256=(
            "wrong-sequence"
            if mutation == "WRONG_SEQUENCE_DIGEST"
            else "fixture-sequence"
        ),
    )
    _assert_unknown_and_no_process_two(
        monkeypatch,
        sandbox=sandbox,
        execution_root=execution_root,
        resume_kwargs=resume_kwargs,
    )


@pytest.mark.parametrize(
    "authority_path",
    (
        "EXECUTION_ROOT",
        "BUDGET_LEDGER",
        "BUDGET_LEDGER_LOCK",
        "STREAM_CHECKPOINT",
        "STREAM_CHECKPOINT_SIDECAR",
        "TASK_DIRECTORY",
        "CELL_COMMIT_JOURNAL",
        "CANONICAL_RESULT",
        "PREPARED_TASK_CHECKPOINT",
        "TERMINAL_JOURNAL_DIRECTORY",
        "GRADER_JOURNAL_DIRECTORY",
        "GRADER_JOURNAL_FILE",
    ),
)
def test_outside_root_symlink_authority_is_unknown_and_never_starts_process_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authority_path: str,
) -> None:
    """Locally identical bytes outside custody never authorize process two."""

    def short_fixture_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    monkeypatch.setattr(benchmark, "atomic_write", short_fixture_write)
    sandbox = tmp_path
    execution_root = (
        sandbox / "artifacts/trimem_v1/benchmark_exec/development"
    )
    tasks, ledger, _session = _materialize_committed_prefix(
        execution_root,
        approved_cells=1,
        committed_cells=1,
    )
    task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        execution_root, "M0", 0, tasks[0]
    )
    grader_files = sorted((task_dir / "terminal-journal/grader").glob("*.json"))
    assert len(grader_files) == 1
    paths = {
        "EXECUTION_ROOT": execution_root,
        "BUDGET_LEDGER": execution_root / "budget-ledger.json",
        "BUDGET_LEDGER_LOCK": execution_root / "budget-ledger.json.lock",
        "STREAM_CHECKPOINT": execution_root / "M0.stream-checkpoint.json",
        "STREAM_CHECKPOINT_SIDECAR": execution_root
        / "M0.stream-checkpoint.sha256",
        "TASK_DIRECTORY": task_dir,
        "CELL_COMMIT_JOURNAL": task_dir / "cell-commit-journal.json",
        "CANONICAL_RESULT": task_dir / f"{tasks[0].task_id}.result.json",
        "PREPARED_TASK_CHECKPOINT": task_dir / "prepared-task-checkpoint.json",
        "TERMINAL_JOURNAL_DIRECTORY": task_dir / "terminal-journal",
        "GRADER_JOURNAL_DIRECTORY": task_dir / "terminal-journal/grader",
        "GRADER_JOURNAL_FILE": grader_files[0],
    }
    retained = paths[authority_path]
    assert retained.exists() and not retained.is_symlink()
    is_directory = retained.is_dir()
    outside = sandbox / f"outside-authority-{authority_path.lower()}"
    retained.rename(outside)
    try:
        retained.symlink_to(outside, target_is_directory=is_directory)
    except OSError as exc:
        outside.rename(retained)
        pytest.skip(f"symlink privilege unavailable: {exc}")
    assert retained.is_symlink()

    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=tasks,
        stream_plan=[("M0", "M0")],
    )
    _assert_unknown_and_no_process_two(
        monkeypatch,
        sandbox=sandbox,
        execution_root=execution_root,
        resume_kwargs=resume_kwargs,
    )
    if authority_path == "CANONICAL_RESULT":
        with pytest.raises(benchmark.BenchmarkExecutionError):
            benchmark.verify_cell_commit_frontier(
                output_root=execution_root,
                stream_id="M0",
                arm="M0",
                tasks=tasks,
                expected_targets=_expected_targets(
                    execution_root, "M0", tasks
                ),
                ledger=ledger,
                canonical_cursor=1,
            )


def test_journal_less_current_task_artifact_is_unknown_and_never_starts_process_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later task footprint cannot be ignored behind a committed prefix."""

    def short_fixture_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    monkeypatch.setattr(benchmark, "atomic_write", short_fixture_write)
    sandbox = tmp_path
    execution_root = (
        sandbox / "artifacts/trimem_v1/benchmark_exec/development"
    )
    tasks, _ledger_row, _session = _materialize_committed_prefix(
        execution_root,
        approved_cells=2,
        committed_cells=1,
    )
    current_task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        execution_root, "M0", 1, tasks[1]
    )
    current_task_dir.mkdir(parents=True)
    benchmark.write_json(
        current_task_dir / "prepared-task-checkpoint.json",
        {"untrusted_journal_less_current_task": True},
    )
    assert not (current_task_dir / "cell-commit-journal.json").exists()

    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=tasks,
        stream_plan=[("M0", "M0")],
    )
    _assert_unknown_and_no_process_two(
        monkeypatch,
        sandbox=sandbox,
        execution_root=execution_root,
        resume_kwargs=resume_kwargs,
    )


def test_unapproved_stream_task_artifact_is_unknown_and_never_starts_process_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid committed prefix cannot hide a footprint in an unknown stream."""

    def short_fixture_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    monkeypatch.setattr(benchmark, "atomic_write", short_fixture_write)
    sandbox = tmp_path
    execution_root = (
        sandbox / "artifacts/trimem_v1/benchmark_exec/development"
    )
    tasks, _ledger_row, _session = _materialize_committed_prefix(
        execution_root,
        approved_cells=1,
        committed_cells=1,
    )
    unapproved_task_dir = execution_root / "UNAPPROVED" / "000-task-0"
    unapproved_task_dir.mkdir(parents=True)
    benchmark.write_json(
        unapproved_task_dir / "prepared-task-checkpoint.json",
        {"untrusted_unapproved_stream_task": True},
    )

    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=tasks,
        stream_plan=[("M0", "M0")],
    )
    _assert_unknown_and_no_process_two(
        monkeypatch,
        sandbox=sandbox,
        execution_root=execution_root,
        resume_kwargs=resume_kwargs,
    )


def test_ambiguous_extra_model_journal_is_unknown_and_never_starts_process_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unbound provider-send marker cannot hide behind a committed cell."""

    def short_fixture_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    monkeypatch.setattr(benchmark, "atomic_write", short_fixture_write)
    sandbox = tmp_path
    execution_root = (
        sandbox / "artifacts/trimem_v1/benchmark_exec/development"
    )
    tasks, _ledger_row, _session = _materialize_committed_prefix(
        execution_root,
        approved_cells=1,
        committed_cells=1,
    )
    task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        execution_root, "M0", 0, tasks[0]
    )
    model_key = "unbound-extra-model-call"
    model_journal = (
        task_dir
        / "terminal-journal/model"
        / (benchmark.sha256_bytes(model_key.encode("utf-8")) + ".json")
    )
    benchmark.write_json(
        model_journal,
        {
            "schema": "trimem/terminal-invocation-journal/2.0",
            "kind": "model",
            "key": model_key,
            "request_sha256": "e" * 64,
            "status": "PROVIDER_SEND_STARTED",
            "provider_send_started": True,
            "preflight": None,
        },
    )

    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=tasks,
        stream_plan=[("M0", "M0")],
    )
    _assert_unknown_and_no_process_two(
        monkeypatch,
        sandbox=sandbox,
        execution_root=execution_root,
        resume_kwargs=resume_kwargs,
    )


def _materialize_terminal_success_model_journal(
    execution_root: Path,
) -> tuple[
    Path,
    str,
    dict[str, object],
    Path,
]:
    """Create one exact ledger/journal/raw-evidence success triple."""

    stream_id = "M0"
    task = _task(1)
    task_arm_key = f"{stream_id}:M0:{task.task_id}"
    logical_call_id = f"{task.task_id}:M0:solve:0001"
    ledger_logical_call_id = f"{stream_id}:{logical_call_id}"
    task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        execution_root, stream_id, 0, task
    )
    task_dir.mkdir(parents=True)
    ledger = _ledger(execution_root, 1)
    ledger.reserve_task_arm(task_arm_key)
    preflight = ledger.preview_reservation(
        ledger_logical_call_id,
        request_sha256="a" * 64,
        task_arm_key=task_arm_key,
        call_kind="solve",
        input_upper_bound=1,
        output_cap=1,
    )
    ledger.reserve_preflighted(preflight)
    ledger.reconcile(
        ledger_logical_call_id,
        preflight.reservation_id,
        input_tokens=1,
        cached_input_tokens=0,
        output_tokens=1,
        status="SUCCESS",
    )
    reservation = {
        "reservation_id": preflight.reservation_id,
        "input_upper_bound": preflight.input_upper_bound,
        "output_cap": preflight.output_cap,
        "charged_conservatively": False,
    }
    terminal = {
        "text": "credential-free-response",
        "provider": "openai-responses",
        "model": _FIXTURE_PRIMARY_MODEL["model_id"],
        "input_tokens": 1,
        "output_tokens": 1,
        "wall_time_ms": 1,
        "paid": True,
        "cached_input_tokens": 0,
        "reasoning_tokens": 0,
        "attempt": 1,
        "status": "success",
        "provider_reported_usage_available": True,
        "provider_response_envelope": None,
        "ledger_reservation": reservation,
        "terminal_outcome_replayed": False,
        "response_mode": "structured_text",
        "output_items": [],
        "function_call_id": None,
        "function_name": None,
        "function_arguments": None,
        "function_arguments_sha256": None,
    }
    journal_path = (
        task_dir
        / "terminal-journal/model"
        / (
            benchmark.sha256_bytes(logical_call_id.encode("utf-8"))
            + ".json"
        )
    )
    benchmark.write_json(
        journal_path,
        {
            "schema": "trimem/terminal-invocation-journal/2.0",
            "kind": "model",
            "key": logical_call_id,
            "request_sha256": preflight.request_sha256,
            "status": "PROVIDER_TERMINAL_SUCCESS",
            "provider_send_started": True,
            "preflight": asdict(preflight),
            "ledger_reservation": reservation,
            "response": terminal,
        },
    )
    evidence = benchmark.RawEvidenceLedger(
        task_dir / "evidence",
        clock=lambda: _FIXED_EVIDENCE_TIME,
    )
    response_ref = evidence.put_blob(terminal["text"])
    evidence.append(
        "model_response",
        {
            "logical_call_id": logical_call_id,
            "request_sha256": preflight.request_sha256,
            "response": response_ref,
            "provider": terminal["provider"],
            "model": terminal["model"],
            "paid": terminal["paid"],
            "attempt": terminal["attempt"],
            "input_tokens": terminal["input_tokens"],
            "output_tokens": terminal["output_tokens"],
            "cached_input_tokens": terminal["cached_input_tokens"],
            "reasoning_tokens": terminal["reasoning_tokens"],
            "wall_time_ms": terminal["wall_time_ms"],
            "status": terminal["status"],
            "provider_reported_usage_available": terminal[
                "provider_reported_usage_available"
            ],
            "provider_response_envelope": terminal[
                "provider_response_envelope"
            ],
            "ledger_reservation": terminal["ledger_reservation"],
            "response_mode": terminal["response_mode"],
            "output_items": terminal["output_items"],
            "function_call_id": None,
            "function_name": None,
            "function_arguments": None,
            "function_arguments_sha256": None,
        },
    )
    ledger_requests = benchmark.read_json(ledger.path)["requests"]
    return task_dir, task_arm_key, ledger_requests, journal_path


def _validate_terminal_success_model_journal(
    execution_root: Path,
    task_dir: Path,
    task_arm_key: str,
    ledger_requests: dict[str, object],
) -> list[object]:
    return resume_driver._validate_task_model_journals(
        benchmark,
        execution_root=execution_root,
        task_dir=task_dir,
        stream_id="M0",
        task_arm_key=task_arm_key,
        ledger_requests=ledger_requests,
        expected_model=str(_FIXTURE_PRIMARY_MODEL["model_id"]),
    )


def test_terminal_success_model_journal_is_exactly_ledger_and_evidence_bound(
    tmp_path: Path,
) -> None:
    execution_root = tmp_path / "development"
    task_dir, task_arm_key, ledger_requests, _journal_path = (
        _materialize_terminal_success_model_journal(execution_root)
    )

    rows = _validate_terminal_success_model_journal(
        execution_root, task_dir, task_arm_key, ledger_requests
    )

    assert len(rows) == 1
    assert rows[0]["status"] == "SUCCESS"


@pytest.mark.parametrize(
    "corruption",
    ["response_text", "usage", "status", "ledger_reservation"],
)
def test_terminal_success_model_journal_tamper_is_rejected(
    tmp_path: Path,
    corruption: str,
) -> None:
    execution_root = tmp_path / "development"
    task_dir, task_arm_key, ledger_requests, journal_path = (
        _materialize_terminal_success_model_journal(execution_root)
    )
    row = benchmark.read_json(journal_path)
    response = row["response"]
    if corruption == "response_text":
        response["text"] = "tampered-response"
    elif corruption == "usage":
        response["input_tokens"] = 2
    elif corruption == "status":
        response["status"] = "tampered-status"
    elif corruption == "ledger_reservation":
        response["ledger_reservation"]["reservation_id"] = "f" * 64
    else:  # pragma: no cover - exhaustive parameter guard
        raise AssertionError(corruption)
    benchmark.write_json(journal_path, row)

    with pytest.raises(ValueError):
        _validate_terminal_success_model_journal(
            execution_root, task_dir, task_arm_key, ledger_requests
        )


def _frozen_m2_policy_checkpoint(*, seed: int = 17) -> dict[str, object]:
    return asdict(_fixture_mutable_m2_policy(seed=seed).freeze_checkpoint())


def test_m2_final_policy_is_deterministically_replayed_from_pending_credit() -> None:
    state = MemoryState(
        candidate_embedding=(0.1, 0.2),
        task_embedding=(0.3, 0.4),
        subtask_embedding=(0.5, 0.6),
        verification_outcome=1.0,
        novelty=0.8,
        redundancy=0.1,
        recency=1.0,
        reuse_frequency=0.0,
        past_gain_loss=0.0,
        version_validity=1.0,
        memory_occupancy=0.2,
        graph_statistics=(0.0, 1.0),
        context_cost=0.4,
    )
    credit_id = "credit:pending-fixture"
    policy = _fixture_mutable_m2_policy()
    policy.queue_delayed_credit(
        credit_id,
        state,
        MemoryAction.MOVE_TO_EPISODIC,
        split="development",
    )
    runtime_state = policy.runtime_state()
    lifecycle = _fixture_m2_lifecycle_checkpoint(
        "M2",
        policy=policy,
        pending_by_memory_id={
            "memory-fixture": {
                "credit_id": credit_id,
                "state": asdict(state),
                "context_cost": state.context_cost,
            }
        },
        context_cost_coefficient=-0.25,
    )
    prior_payload = {
        "arm_id": "M2",
        "split": "development",
        "lifecycle_state": {"persistence": {}, "lifecycle": lifecycle},
    }

    expected_policy = _fixture_mutable_m2_policy()
    expected_policy.restore_runtime_state(runtime_state)
    expected_policy.credit_delayed_reward(
        credit_id,
        -0.25 * state.context_cost,
        state,
        done=True,
        split="development",
        train_updates=1,
    )
    expected = asdict(expected_policy.freeze_checkpoint())

    assert benchmark._expected_finalized_m2_policy_checkpoint(
        prior_payload
    ) == expected


def _m2_finalization_fixture(
    execution_root: Path,
) -> tuple[
    list[CodingTask],
    benchmark.AtomicBudgetLedger,
    _Session,
    Path,
    dict[str, object],
    dict[str, object],
]:
    tasks, ledger, session = _materialize_committed_prefix(
        execution_root,
        approved_cells=2,
        committed_cells=2,
        stream_id="M2",
        arm="M2",
    )
    last_task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        execution_root, "M2", 1, tasks[-1]
    )
    last_journal_path = last_task_dir / "cell-commit-journal.json"
    last_journal = benchmark.CellCommitJournal.read_verified(last_journal_path)
    prior_checkpoint = benchmark.load_arm_checkpoint(execution_root, "M2")
    prior_payload = dict(prior_checkpoint["payload"])
    assert prior_payload["completed_task_digests"] == session.completed_digests
    assert last_journal["stream_checkpoint_sha256"] == benchmark.sha256_bytes(
        benchmark.canonical_bytes(prior_checkpoint)
    )
    payload = {
        **prior_payload,
        "task_cursor": 2,
        "stream_state": "DEVELOPMENT_FINALIZED",
        "next_sequence_index": 3,
        "final_policy_checkpoint": _frozen_m2_policy_checkpoint(),
    }
    checkpoint = {
        "payload": payload,
        "digest": "sha256:"
        + benchmark.sha256_bytes(benchmark.canonical_bytes(payload)),
    }
    return (
        tasks,
        ledger,
        session,
        last_journal_path,
        prior_checkpoint,
        checkpoint,
    )


def test_m2_development_finalized_checkpoint_is_a_durable_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution_root = tmp_path / "development"
    tasks, ledger, session, last_journal_path, _prior, checkpoint = (
        _m2_finalization_fixture(execution_root)
    )
    benchmark.save_development_finalized_arm_checkpoint(
        execution_root,
        "M2",
        checkpoint,
        last_cell_journal_path=last_journal_path,
    )
    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=tasks,
        stream_plan=[("M2", "M2")],
    )

    assert session.task_cursor == 2
    assert len(ledger._read()["task_arms"]) == 2
    assert resume_driver._durable_resume_disposition(
        execution_root, **resume_kwargs
    ) == (
        "RESUME_SAFE_DURABLE_SUFFIX"
    )


def test_partial_m2_finalization_is_unknown_and_never_starts_process_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DEVELOPMENT_FINALIZED envelope covers the complete frozen target set."""

    def short_fixture_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    monkeypatch.setattr(benchmark, "atomic_write", short_fixture_write)
    sandbox = tmp_path
    execution_root = (
        sandbox / "artifacts/trimem_v1/benchmark_exec/development"
    )
    tasks, _ledger_row, _session = _materialize_committed_prefix(
        execution_root,
        approved_cells=2,
        committed_cells=1,
        stream_id="M2",
        arm="M2",
    )
    task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        execution_root, "M2", 0, tasks[0]
    )
    journal_path = task_dir / "cell-commit-journal.json"
    prior = benchmark.load_arm_checkpoint(execution_root, "M2")
    payload = {
        **prior["payload"],
        "stream_state": "DEVELOPMENT_FINALIZED",
        "next_sequence_index": 2,
        "final_policy_checkpoint": _frozen_m2_policy_checkpoint(),
    }
    final = {
        "payload": payload,
        "digest": "sha256:"
        + benchmark.sha256_bytes(benchmark.canonical_bytes(payload)),
    }
    benchmark.save_development_finalized_arm_checkpoint(
        execution_root,
        "M2",
        final,
        last_cell_journal_path=journal_path,
    )
    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=tasks,
        stream_plan=[("M2", "M2")],
    )
    _assert_unknown_and_no_process_two(
        monkeypatch,
        sandbox=sandbox,
        execution_root=execution_root,
        resume_kwargs=resume_kwargs,
    )


def test_later_m2_stream_cannot_follow_unfinalized_prior_m2_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every earlier M2 candidate must cross its finalization bridge first."""

    def short_fixture_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    monkeypatch.setattr(benchmark, "atomic_write", short_fixture_write)
    sandbox = tmp_path
    execution_root = (
        sandbox / "artifacts/trimem_v1/benchmark_exec/development"
    )
    # Keep these short because the fixture's content-addressed blob names can
    # otherwise exceed the Windows test worker's path budget.
    first_stream = "A"
    second_stream = "B"
    tasks, ledger, _first_session = _materialize_committed_prefix(
        execution_root,
        approved_cells=2,
        committed_cells=1,
        stream_id=first_stream,
        arm="M2",
    )
    task = tasks[0]
    task_key = f"{second_stream}:M2:{task.task_id}"
    reservation = ledger.reserve_task_arm(task_key)
    task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        execution_root, second_stream, 0, task
    )
    task_dir.mkdir(parents=True)
    result = _agent_result(task, arm="M2")
    _materialize_validated_grader(task_dir, task, result)
    second_session = _Session(stream_id=second_stream, arm="M2")
    second_session.before_task(task, 0)
    second_session.controller_for(task)
    benchmark.commit_scientific_cell(
        task_dir=task_dir,
        task=task,
        target_id=task.task_id,
        stream_id=second_stream,
        arm="M2",
        sequence_index=0,
        task_arm_key=task_key,
        task_reservation=reservation,
        record=_record(
            result,
            arm=second_stream,
            runtime_arm="M2",
            task_dir=task_dir,
            sequence_index=0,
            sequence_sha256="fixture-sequence",
        ),
        result=result,
        ledger=ledger,
        session=second_session,
        output_root=execution_root,
    )
    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=[task],
        stream_plan=[(first_stream, "M2"), (second_stream, "M2")],
    )
    _assert_unknown_and_no_process_two(
        monkeypatch,
        sandbox=sandbox,
        execution_root=execution_root,
        resume_kwargs=resume_kwargs,
    )


@pytest.mark.parametrize(
    ("crash_edge", "expected_during_crash"),
    (
        ("AFTER_BINDING_BEFORE_FINAL_CHECKPOINT", "UNKNOWN_FAILURE"),
        ("AFTER_FINAL_CHECKPOINT_BEFORE_RETURN", "RESUME_SAFE_DURABLE_SUFFIX"),
    ),
)
def test_m2_finalization_bridge_recovers_only_a_coherent_write_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_edge: str,
    expected_during_crash: str,
) -> None:
    execution_root = tmp_path / crash_edge
    tasks, _ledger_row, _session, last_journal_path, prior, final = (
        _m2_finalization_fixture(execution_root)
    )
    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=tasks,
        stream_plan=[("M2", "M2")],
    )
    original_save = benchmark.save_arm_checkpoint

    def crash_at_final_checkpoint(
        root: Path, stream_id: str, checkpoint: dict[str, object]
    ) -> None:
        assert root == execution_root and stream_id == "M2"
        assert checkpoint == final
        if crash_edge == "AFTER_FINAL_CHECKPOINT_BEFORE_RETURN":
            original_save(root, stream_id, checkpoint)
        raise RuntimeError("simulated finalization process death")

    monkeypatch.setattr(benchmark, "save_arm_checkpoint", crash_at_final_checkpoint)
    with pytest.raises(RuntimeError, match="simulated finalization process death"):
        benchmark.save_development_finalized_arm_checkpoint(
            execution_root,
            "M2",
            final,
            last_cell_journal_path=last_journal_path,
        )
    binding_path = benchmark._development_finalization_binding_path(
        execution_root, "M2"
    )
    assert binding_path.is_file()
    assert resume_driver._durable_resume_disposition(
        execution_root, **resume_kwargs
    ) == (
        expected_during_crash
    )
    if crash_edge == "AFTER_BINDING_BEFORE_FINAL_CHECKPOINT":
        assert benchmark.load_arm_checkpoint(execution_root, "M2") == prior
    else:
        assert benchmark.load_arm_checkpoint(execution_root, "M2") == final

    # The same process inputs recover idempotently without changing the bridge.
    binding_before = binding_path.read_bytes()
    monkeypatch.setattr(benchmark, "save_arm_checkpoint", original_save)
    recovered = benchmark.save_development_finalized_arm_checkpoint(
        execution_root,
        "M2",
        final,
        last_cell_journal_path=last_journal_path,
    )
    assert binding_path.read_bytes() == binding_before
    assert recovered == benchmark.load_development_finalization_binding(
        execution_root,
        "M2",
        last_cell_journal_path=last_journal_path,
    )
    assert resume_driver._durable_resume_disposition(
        execution_root, **resume_kwargs
    ) == (
        "RESUME_SAFE_DURABLE_SUFFIX"
    )


def test_m2_retained_prior_before_bridge_is_a_safe_finalization_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution_root = tmp_path / "retained-before-bridge"
    tasks, _ledger_row, _session, last_journal_path, prior, final = (
        _m2_finalization_fixture(execution_root)
    )
    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=tasks,
        stream_plan=[("M2", "M2")],
    )
    binding_path = benchmark._development_finalization_binding_path(
        execution_root, "M2"
    )
    original_write_json = benchmark.write_json

    def die_before_bridge(path: Path, value: object) -> None:
        if path == binding_path:
            raise RuntimeError("simulated death before finalization bridge")
        original_write_json(path, value)

    monkeypatch.setattr(benchmark, "write_json", die_before_bridge)
    with pytest.raises(
        RuntimeError, match="simulated death before finalization bridge"
    ):
        benchmark.save_development_finalized_arm_checkpoint(
            execution_root,
            "M2",
            final,
            last_cell_journal_path=last_journal_path,
        )
    assert benchmark.load_arm_checkpoint(execution_root, "M2") == prior
    assert not binding_path.exists()
    assert benchmark._development_pre_finalization_checkpoint_path(
        execution_root, "M2"
    ).is_file()
    assert resume_driver._durable_resume_disposition(
        execution_root, **resume_kwargs
    ) == "RESUME_SAFE_DURABLE_SUFFIX"

    monkeypatch.setattr(benchmark, "write_json", original_write_json)
    benchmark.save_development_finalized_arm_checkpoint(
        execution_root,
        "M2",
        final,
        last_cell_journal_path=last_journal_path,
    )
    assert resume_driver._durable_resume_disposition(
        execution_root, **resume_kwargs
    ) == "RESUME_SAFE_DURABLE_SUFFIX"


def test_m2_rehashed_final_checkpoint_mutation_is_not_bound_by_predecessor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution_root = tmp_path / "rehashed-final-mutation"
    tasks, _ledger_row, _session, last_journal_path, _prior, final = (
        _m2_finalization_fixture(execution_root)
    )
    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=tasks,
        stream_plan=[("M2", "M2")],
    )
    benchmark.save_development_finalized_arm_checkpoint(
        execution_root,
        "M2",
        final,
        last_cell_journal_path=last_journal_path,
    )
    assert resume_driver._durable_resume_disposition(
        execution_root, **resume_kwargs
    ) == (
        "RESUME_SAFE_DURABLE_SUFFIX"
    )

    tampered = json.loads(
        benchmark.canonical_bytes(final).decode("utf-8")
    )
    tampered["payload"]["canonical_evidence"] = {
        "forged_after_finalization": True
    }
    tampered["digest"] = "sha256:" + benchmark.sha256_bytes(
        benchmark.canonical_bytes(tampered["payload"])
    )
    # This reseals both the envelope and its local sidecar, but cannot alter
    # the already sealed predecessor bridge.
    benchmark.save_arm_checkpoint(execution_root, "M2", tampered)
    assert benchmark.load_arm_checkpoint(execution_root, "M2") == tampered

    with pytest.raises(
        benchmark.BenchmarkExecutionError,
        match="development finalization predecessor binding differs",
    ):
        benchmark.load_development_finalization_binding(
            execution_root,
            "M2",
            last_cell_journal_path=last_journal_path,
        )
    assert resume_driver._durable_resume_disposition(
        execution_root, **resume_kwargs
    ) == (
        "UNKNOWN_FAILURE"
    )


def test_m2_coherently_resealed_policy_and_local_bridge_is_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A local bridge seal cannot authorize an unrelated frozen M2 policy."""

    execution_root = tmp_path / "coherently-resealed-final-policy"
    tasks, _ledger_row, _session, last_journal_path, _prior, final = (
        _m2_finalization_fixture(execution_root)
    )
    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=tasks,
        stream_plan=[("M2", "M2")],
    )
    benchmark.save_development_finalized_arm_checkpoint(
        execution_root,
        "M2",
        final,
        last_cell_journal_path=last_journal_path,
    )
    assert resume_driver._durable_resume_disposition(
        execution_root, **resume_kwargs
    ) == "RESUME_SAFE_DURABLE_SUFFIX"

    resealed = json.loads(benchmark.canonical_bytes(final).decode("utf-8"))
    resealed["payload"]["final_policy_checkpoint"] = (
        _frozen_m2_policy_checkpoint(seed=18)
    )
    resealed["digest"] = "sha256:" + benchmark.sha256_bytes(
        benchmark.canonical_bytes(resealed["payload"])
    )
    benchmark.save_arm_checkpoint(execution_root, "M2", resealed)

    binding_path = benchmark._development_finalization_binding_path(
        execution_root, "M2"
    )
    binding = benchmark.read_json(binding_path)
    binding["finalized_stream_checkpoint_sha256"] = benchmark.sha256_bytes(
        benchmark.canonical_bytes(resealed)
    )
    benchmark.write_json(
        binding_path,
        benchmark._sealed_development_finalization_binding(binding),
    )
    # Recomputing every local digest is insufficient: the retained predecessor
    # independently determines the only acceptable frozen policy.
    with pytest.raises(
        benchmark.BenchmarkExecutionError,
        match="final policy differs from deterministic task frontier",
    ):
        benchmark.load_development_finalization_binding(
            execution_root,
            "M2",
            last_cell_journal_path=last_journal_path,
        )

    assert resume_driver._durable_resume_disposition(
        execution_root, **resume_kwargs
    ) == "UNKNOWN_FAILURE"


@pytest.mark.parametrize(
    "mutation",
    ("CONTENT", "OUTSIDE_RETAINED_SYMLINK", "OUTSIDE_BINDING_SYMLINK"),
)
def test_m2_retained_pre_finalization_checkpoint_is_resume_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    execution_root = tmp_path / "retained-pre-finalization-authority"
    tasks, _ledger_row, _session, last_journal_path, _prior, final = (
        _m2_finalization_fixture(execution_root)
    )
    benchmark.save_development_finalized_arm_checkpoint(
        execution_root,
        "M2",
        final,
        last_cell_journal_path=last_journal_path,
    )
    retained = benchmark._development_pre_finalization_checkpoint_path(
        execution_root, "M2"
    )
    assert retained.is_file() and not retained.is_symlink()
    if mutation == "CONTENT":
        retained.write_bytes(retained.read_bytes() + b" ")
    else:
        attacked = (
            retained
            if mutation == "OUTSIDE_RETAINED_SYMLINK"
            else benchmark._development_finalization_binding_path(
                execution_root, "M2"
            )
        )
        outside = tmp_path / f"outside-{attacked.name}"
        attacked.replace(outside)
        try:
            attacked.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"symlink privilege unavailable: {exc}")
        assert attacked.is_symlink()

    with pytest.raises(benchmark.BenchmarkExecutionError):
        benchmark.load_development_finalization_binding(
            execution_root,
            "M2",
            last_cell_journal_path=last_journal_path,
        )
    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=tasks,
        stream_plan=[("M2", "M2")],
    )
    assert resume_driver._durable_resume_disposition(
        execution_root, **resume_kwargs
    ) == "UNKNOWN_FAILURE"


def test_post_cursor_cas_ledger_terminal_window_is_resume_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task(1)
    ledger = _ledger(tmp_path, 1)
    task_key = f"M0:M0:{task.task_id}"
    reservation = ledger.reserve_task_arm(task_key)
    task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        tmp_path, "M0", 0, task
    )
    task_dir.mkdir(parents=True)
    result = _agent_result(task)
    _materialize_validated_grader(task_dir, task, result)
    session = _Session()
    session.before_task(task, 0)
    session.controller_for(task)

    with pytest.raises(benchmark.BenchmarkProcessFailure):
        benchmark.commit_scientific_cell(
            task_dir=task_dir,
            task=task,
            target_id=task.task_id,
            stream_id="M0",
            arm="M0",
            sequence_index=0,
            task_arm_key=task_key,
            task_reservation=reservation,
            record=_record(
                result,
                task_dir=task_dir,
                sequence_index=0,
                sequence_sha256="fixture-sequence",
            ),
            result=result,
            ledger=ledger,
            session=session,
            output_root=tmp_path,
            transition_hook=lambda state: (_ for _ in ()).throw(RuntimeError())
            if state == "LEDGER_TERMINAL"
            else None,
        )
    journal = benchmark.CellCommitJournal.read_verified(
        task_dir / "cell-commit-journal.json"
    )
    assert journal["status"] == "LEDGER_TERMINAL"

    # Reproduce a hard death after the canonical cursor CAS and local
    # checkpoint write but before the journal's CURSOR_ADVANCED edge.
    checkpoint = session.after_task_and_checkpoint(task, asdict(result))
    benchmark.save_arm_checkpoint(tmp_path, "M0", checkpoint)
    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        tmp_path,
        tasks=[task],
        stream_plan=[("M0", "M0")],
    )
    assert resume_driver._durable_resume_disposition(
        tmp_path, **resume_kwargs
    ) == (
        "RESUME_SAFE_CELL_COMMIT_JOURNAL"
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "RESULT_BYTES",
        "RESULT_PATH",
        "LEDGER_STATUS",
        "LEDGER_ACCOUNTING",
        "CHECKPOINT_CURSOR",
        "CHECKPOINT_UNBOUND_PAYLOAD",
        "CHECKPOINT_PATH",
    ),
)
def test_df_tamper_is_unknown_and_never_resumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    # This production-layout fixture is deep enough to exceed the legacy
    # Windows path limit only for atomic-write temporary suffixes.  Atomic
    # rename itself is covered by the shorter commit/crash tests above.
    def short_fixture_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    monkeypatch.setattr(benchmark, "atomic_write", short_fixture_write)
    sandbox = tmp_path
    execution_root = (
        sandbox / "artifacts/trimem_v1/benchmark_exec/development"
    )
    tasks, ledger, _session = _materialize_committed_prefix(
        execution_root,
        approved_cells=1,
        committed_cells=1,
    )
    task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        execution_root, "M0", 0, tasks[0]
    )
    result_path = benchmark._cell_result_path(task_dir, tasks[0])
    checkpoint_path, checkpoint_sidecar = benchmark._arm_checkpoint_paths(
        execution_root, "M0"
    )
    if mutation == "RESULT_BYTES":
        result_path.write_bytes(result_path.read_bytes() + b"\n")
    elif mutation == "RESULT_PATH":
        result_path.rename(task_dir / "moved-result.json")
    elif mutation in {"LEDGER_STATUS", "LEDGER_ACCOUNTING"}:
        ledger_payload = benchmark.read_json(ledger.path)
        if mutation == "LEDGER_STATUS":
            task_key = f"M0:M0:{tasks[0].task_id}"
            ledger_payload["task_arms"][task_key]["status"] = "RESERVED"
        else:
            ledger_payload["actual"]["grader_containers"] = 0
        benchmark.write_json(ledger.path, ledger_payload)
    elif mutation == "CHECKPOINT_CURSOR":
        payload = {"task_cursor": 0}
        benchmark.save_arm_checkpoint(
            execution_root,
            "M0",
            {
                "payload": payload,
                "digest": "sha256:"
                + benchmark.sha256_bytes(benchmark.canonical_bytes(payload)),
            },
        )
    elif mutation == "CHECKPOINT_UNBOUND_PAYLOAD":
        checkpoint = benchmark.load_arm_checkpoint(execution_root, "M0")
        payload = dict(checkpoint["payload"])
        payload["unbound_mutation"] = "must-not-authorize-process-two"
        benchmark.save_arm_checkpoint(
            execution_root,
            "M0",
            {
                "payload": payload,
                "digest": "sha256:"
                + benchmark.sha256_bytes(benchmark.canonical_bytes(payload)),
            },
        )
    elif mutation == "CHECKPOINT_PATH":
        checkpoint_path.rename(execution_root / "wrong.stream-checkpoint.json")
        checkpoint_sidecar.rename(execution_root / "wrong.stream-checkpoint.sha256")
    else:  # pragma: no cover - the parameter set above is closed.
        raise AssertionError(mutation)

    resume_kwargs = _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=tasks,
        stream_plan=[("M0", "M0")],
    )
    assert resume_driver._durable_resume_disposition(
        execution_root, **resume_kwargs
    ) == (
        "UNKNOWN_FAILURE"
    )
    monkeypatch.setattr(resume_driver, "ROOT", sandbox)
    process_calls: list[list[str]] = []

    def hard_failure(argv, **_kwargs):
        process_calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 7, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume_driver.subprocess, "run", hard_failure)
    assert resume_driver.run_with_one_resume(
        "development", sandbox / "approval.json"
    ) == 7
    assert len(process_calls) == 1
    assert "--resume" not in process_calls[0]
    attempts = benchmark.read_json(
        execution_root / "driver-evidence/attempts.json"
    )
    assert attempts["first_disposition"] == "UNKNOWN_FAILURE"
    assert attempts["resume_eligible"] is False
    assert attempts["resume_started"] is False


@pytest.mark.parametrize(
    ("disposition", "second_process"),
    (
        ("GLOBAL_GRADER_INFRA_FAILURE", False),
        # A runner label alone cannot authorize a second process; the separate
        # abrupt-exit test below supplies the required durable journal.
        ("RESUME_SAFE_CELL_COMMIT_JOURNAL", False),
    ),
)
def test_process_driver_resumes_only_machine_readable_safe_classes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    disposition: str,
    second_process: bool,
) -> None:
    monkeypatch.setattr(resume_driver, "ROOT", tmp_path)
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        current = disposition if len(calls) == 1 else "SUCCESS"
        code = 7 if len(calls) == 1 else 0
        raw = (
            json.dumps(
                {
                    "process_disposition": current,
                    "status": "FAIL" if code else "PASS",
                }
            )
            + "\n"
        ).encode()
        return subprocess.CompletedProcess(argv, code, stdout=raw, stderr=b"")

    monkeypatch.setattr(resume_driver.subprocess, "run", fake_run)
    code = resume_driver.run_with_one_resume("development", tmp_path / "approval")
    assert (len(calls) == 2) is second_process
    assert ("--resume" in calls[-1]) is second_process
    assert code == 7


def test_process_driver_never_upgrades_abrupt_unknown_exit_to_resume_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Keep this deep fixed production-layout fixture below Windows' temporary
    # filename limit; atomic-write behavior is covered by the shorter tests.
    def short_fixture_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    monkeypatch.setattr(benchmark, "atomic_write", short_fixture_write)
    execution_root = (
        tmp_path / "artifacts/trimem_v1/benchmark_exec/development"
    )
    task = _task(1)
    ledger = _ledger(execution_root, 1)
    task_key = f"M0:M0:{task.task_id}"
    reservation = ledger.reserve_task_arm(task_key)
    task_dir, _run_id, _prepared = benchmark._task_recovery_paths(
        execution_root, "M0", 0, task
    )
    task_dir.mkdir(parents=True)
    result = _agent_result(task)
    _materialize_validated_grader(task_dir, task, result)
    session = _Session()
    session.before_task(task, 0)
    session.controller_for(task)
    with pytest.raises(benchmark.BenchmarkProcessFailure):
        benchmark.commit_scientific_cell(
            task_dir=task_dir,
            task=task,
            target_id=task.task_id,
            stream_id="M0",
            arm="M0",
            sequence_index=0,
            task_arm_key=task_key,
            task_reservation=reservation,
            record=_record(
                result,
                task_dir=task_dir,
                sequence_index=0,
                sequence_sha256="fixture-sequence",
            ),
            result=result,
            ledger=ledger,
            session=session,
            output_root=execution_root,
            transition_hook=lambda state: (_ for _ in ()).throw(RuntimeError())
            if state == "PREPARED"
            else None,
        )
    _install_frozen_resume_authority(
        monkeypatch,
        execution_root,
        tasks=[task],
        stream_plan=[("M0", "M0")],
    )
    monkeypatch.setattr(resume_driver, "ROOT", tmp_path)
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, -9, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume_driver.subprocess, "run", fake_run)
    assert resume_driver.run_with_one_resume(
        "development", tmp_path / "approval.json"
    ) == 1
    assert len(calls) == 1
    assert "--resume" not in calls[0]
    manifest = json.loads(
        (execution_root / "driver-evidence/attempts.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["first_disposition"] == "UNKNOWN_FAILURE"
    assert manifest["resume_eligible"] is False
    assert manifest["resume_started"] is False
    assert "reported_process_disposition" not in manifest["attempts"][0]
    assert manifest["attempts"][0]["disposition_source"] == "RUNNER_STDOUT"


def test_exec_010_is_immutable_pre_container_nonterminal_history() -> None:
    request = ROOT / (
        "artifacts/trimem_v1/exec_requests/"
        "DEVELOPMENT_TUNING_EXEC_REQUEST_010.json"
    )
    assert hashlib.sha256(request.read_bytes()).hexdigest() == (
        "f42389df5a12c8f0d06bcd3eb2c97c69b0fde39667f8c880832e1c01bf998d9f"
    )
    readiness = json.loads(
        (ROOT / "artifacts/trimem_v1/readiness_requirements.json").read_text(
            encoding="utf-8"
        )
    )
    authority = readiness["development_authorization_boundary"]
    assert authority["request_010_attempt_one_consumed"] is True
    assert authority["request_010_rerun_allowed"] is False
    assert authority["request_010_attempt_two_allowed"] is False
    failure = readiness["current_development_execution_failure"]
    boundary = failure["failure_boundary"]
    assert boundary["context_projections_bounded"] == 8
    assert boundary["context_projections_total"] == 8
    assert boundary["decomposition_calls"] == 1
    assert boundary["solve_calls"] == 8
    assert boundary["partial_patch_nonempty"] is True
    assert boundary["per_subtask_step_cap_reached"] is True
    assert boundary["grader_adapter_invoked"] is True
    assert boundary["exact_child_python_exit_code"] == 127
    assert boundary["stderr_class"] == "LIBPYTHON3_11_SO_1_0_UNAVAILABLE"
    assert boundary["container_started"] is False
    assert boundary["official_grader_runs"] == 0
    assert boundary["task_arm_cursor"] == 0
    assert boundary["cell_terminal_records"] == 0
    assert boundary["public_aggregate_present"] is False
    assert failure["observed_usage"]["official_grader_runs"] == 0
    assert failure["observed_usage"]["grader_containers"] == 0
    assert failure["observed_usage"]["terminal_task_arm_runs"] == 0
    assert failure["grader_state"] == "GRADER_INFRA_FAILURE_BEFORE_CONTAINER"
    assert failure["process_disposition"] == {
        "first_disposition": "GLOBAL_GRADER_INFRA_FAILURE",
        "resume_eligible": False,
        "resume_started": False,
    }
    assert "task-arm cap ledger state does not match the stream cursor" not in (
        json.dumps(failure, sort_keys=True)
    )
    custody = failure["evidence_custody"]
    assert custody["status"] == "TRIMEM_FAILURE_EVIDENCE_CUSTODY_PASS"
    assert custody["public_artifact_present"] is False
    amendment = json.loads(
        (
            ROOT
            / "artifacts/trimem_v1/development_grader_launch_stream_commit_amendment.json"
        ).read_text(encoding="utf-8")
    )
    for relative, expected in amendment[
        "historical_execution_evidence_sha256"
    ].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_exec_010_sanitized_fixture_exercises_pre_container_failure_and_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The historical target identity plus sealed journal filename exceeds the
    # legacy Windows temporary-path limit. Atomic rename semantics are covered
    # by the dedicated crash matrix; keep this provenance regression portable.
    def short_fixture_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    monkeypatch.setattr(benchmark, "atomic_write", short_fixture_write)
    fixture_path = (
        ROOT / "tests/fixtures/trimem_d110/exec_010_sanitized.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    provenance = fixture["provenance"]
    boundary = fixture["historical_failure_boundary"]
    expected = fixture["expected_regression"]
    patch_record = fixture["safe_partial_patch"]

    request_path = ROOT / provenance["request_path"]
    assert hashlib.sha256(request_path.read_bytes()).hexdigest() == (
        provenance["request_raw_sha256"]
    )
    readiness = json.loads(
        (ROOT / "artifacts/trimem_v1/readiness_requirements.json").read_text(
            encoding="utf-8"
        )
    )
    historical = readiness["current_development_execution_failure"]
    assert boundary == {
        **historical["failure_boundary"],
        "grader_containers": historical["observed_usage"]["grader_containers"],
    }
    assert fixture["historical_usage"] == historical["observed_usage"]
    assert fixture["evidence_custody"] == {
        key: historical["evidence_custody"][key]
        for key in (
            "status",
            "restricted_encrypted",
            "evidence_inventories",
            "plaintext_inventory",
        )
    }
    assert fixture["sanitization"]["historical_patch_content_included"] is False
    assert fixture["sanitization"]["raw_historical_evidence_included"] is False

    raw_patch = base64.b64decode(
        patch_record["content_base64"].encode("ascii"), validate=True
    )
    assert raw_patch == patch_record["utf8_text"].encode("utf-8")
    assert len(raw_patch) == patch_record["bytes"]
    assert hashlib.sha256(raw_patch).hexdigest() == patch_record["sha256"]
    assert raw_patch
    original_patch_sha256 = patch_record["sha256"]

    # Keep the fixture inside pytest's session directory but omit pytest's long
    # human-readable per-test component so the sealed 64-hex journal name fits.
    sandbox = tmp_path.parent / (
        "d" + hashlib.sha256(str(tmp_path).encode("utf-8")).hexdigest()[:8]
    )
    sandbox.mkdir()
    execution_root = (
        sandbox / "artifacts/trimem_v1/benchmark_exec/development"
    )
    task = CodingTask(
        task_id=boundary["target"],
        org_id="sanitized-fixture-org",
        user_id="sanitized-fixture-user",
        repository="django/django",
        commit="a" * 40,
        instruction="sanitized credential-free _010 regression",
        files={},
        editable_paths=("trimem_d110_fixture.py",),
    )
    # Keep the production root/stream/sequence shape while avoiding embedding
    # the long historical target twice in Windows' legacy-length path.
    task_dir = execution_root / boundary["stream"] / "000-exec-010-sanitized"
    patch_path = task_dir / patch_record["path"]
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_bytes(raw_patch)

    ledger = _ledger(execution_root, 1)
    task_arm_key = f"{boundary['stream']}:M2:{task.task_id}"
    ledger.reserve_task_arm(task_arm_key)
    session = _Session(stream_id=boundary["stream"], arm="M2")
    delegates: list[_FakeGrader] = []
    process_calls: list[list[str]] = []

    def pre_container_failure(argv, **_kwargs):
        process_calls.append(list(argv))
        assert len(process_calls) == 1
        assert "--resume" not in argv
        session.before_task(task, expected["task_arm_cursor"])
        session.controller_for(task)
        result = GradeResult(
            task_id=task.task_id,
            resolved=False,
            exit_code=boundary["exact_child_python_exit_code"],
            stdout="",
            stderr=expected["process_stderr_utf8"].removesuffix("\n"),
            report={
                "task_id": task.task_id,
                "resolved": False,
                "failure_stage": "python_launch",
                "stderr_class": boundary["stderr_class"],
                "_trimem": {
                    "image_evidence": [
                        {
                            "image": fixture["grader_target"]["image"],
                            "expected": fixture["grader_target"][
                                "expected_digest"
                            ],
                            "observed": [],
                        }
                    ]
                },
            },
            grader_id="official-swebench-sanitized-fixture",
            container_digest=fixture["grader_target"]["image"],
            official=True,
            wall_time_ms=1,
            container_started=False,
            status="harness_launch_failed",
        )
        delegate = _FakeGrader(result, fail=True)
        delegates.append(delegate)
        gateway = _gateway(task_dir, delegate)
        request = GradeRequest(
            task_id=task.task_id,
            repository=task.repository,
            base_commit=task.commit,
            patch=raw_patch.decode("utf-8", errors="strict"),
            workspace=WorkspaceGraderContext(
                kind="git_checkout",
                repository_files={},
                checkout_root=str(task_dir),
                base_commit=task.commit,
            ),
        )
        with pytest.raises(GraderInvocationFailure) as failure:
            gateway.grade(request)
        disposition = benchmark.process_disposition_for_exception(failure.value)
        stdout = (
            json.dumps(
                {
                    "error": str(failure.value),
                    "process_disposition": disposition,
                    "status": "FAIL",
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        stderr = (failure.value.result.stderr + "\n").encode("utf-8")
        assert stdout == expected["process_stdout_utf8"].encode("utf-8")
        assert stderr == expected["process_stderr_utf8"].encode("utf-8")
        return subprocess.CompletedProcess(
            argv,
            boundary["exact_child_python_exit_code"],
            stdout=stdout,
            stderr=stderr,
        )

    monkeypatch.setattr(resume_driver, "ROOT", sandbox)
    monkeypatch.setattr(resume_driver.subprocess, "run", pre_container_failure)
    assert resume_driver.run_with_one_resume(
        "development", sandbox / "external-protected-approval.json"
    ) == boundary["exact_child_python_exit_code"]

    driver_evidence = execution_root / "driver-evidence"
    captured_stdout = (driver_evidence / "attempt-1.stdout.bin").read_bytes()
    captured_stderr = (driver_evidence / "attempt-1.stderr.bin").read_bytes()
    banned = expected["banned_legacy_diagnostic"].encode("utf-8")
    assert captured_stdout == expected["process_stdout_utf8"].encode("utf-8")
    assert captured_stderr == expected["process_stderr_utf8"].encode("utf-8")
    assert banned not in captured_stdout
    assert banned not in captured_stderr

    attempts = benchmark.read_json(driver_evidence / "attempts.json")
    assert attempts["first_disposition"] == expected["first_disposition"]
    assert attempts["resume_eligible"] is expected["resume_eligible"]
    assert attempts["resume_started"] is expected["resume_started"]
    assert attempts["second_process_exit_code"] is None
    assert len(attempts["attempts"]) == expected["process_count"]
    assert len(process_calls) == expected["process_count"]
    assert len(delegates) == 1
    assert delegates[0].calls == expected["grader_delegate_calls"]

    journal_path = next(
        (task_dir / "terminal-journal/grader").glob("*.json")
    )
    journal = benchmark.TerminalInvocationJournal._validated_grader_row(
        journal_path
    )
    assert journal["status"] == "GRADER_INFRA_FAILURE_BEFORE_CONTAINER"
    assert journal["official_grader_runs"] == boundary["official_grader_runs"]
    assert journal["grader_containers"] == boundary["grader_containers"]
    assert journal["grader_capacity_disposition"] == "NOT_CONSUMED"

    ledger_row = ledger._read()
    assert ledger.task_arm_status(task_arm_key) == expected["ledger_status"]
    assert ledger_row["actual"]["task_arm_runs"] == (
        expected["terminal_task_arm_runs"]
    )
    assert ledger_row["actual"]["grader_containers"] == 0
    assert ledger_row["outstanding"]["task_arm_runs"] == 1
    assert ledger_row["outstanding"]["grader_containers"] == 1
    assert session.task_cursor == expected["task_arm_cursor"]
    assert session.completed == []
    assert not list(execution_root.glob("*.stream-checkpoint.json"))
    assert len(list(execution_root.rglob("*.result.json"))) == (
        expected["cell_result_count"]
    )
    assert not list(execution_root.rglob("cell-commit-journal.json"))
    assert patch_path.read_bytes() == raw_patch
    assert hashlib.sha256(patch_path.read_bytes()).hexdigest() == (
        original_patch_sha256
    )
