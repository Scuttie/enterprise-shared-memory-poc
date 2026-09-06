"""Approved TriMem V1 benchmark orchestrator.

The command has no free-form instance selection.  It reads one committed split,
executes one complete arm stream serially, and refuses to start before the
approval binding, freeze, target rows, production services, model bridge,
workspace factory, grader images, and hard caps all verify.

Importing this module is credential-free.  The CLI is an EXEC path and must only
be invoked by the manual workflows after their fail-closed gate passes.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
import urllib.request
import uuid

from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from enterprise_memory.providers.openai_responses import (  # noqa: E402
    OpenAIResponsesProvider,
    RestrictedProviderResponseStore,
)
from enterprise_memory.trimem.accounting import RawEvidenceLedger, strict_json_loads  # noqa: E402
from enterprise_memory.trimem.agent_runtime import (  # noqa: E402
    AgentRunResult,
    CodingTask,
    ExperienceExtraction,
    TriMemAgentRuntime,
)
from enterprise_memory.trimem.benchmark_seed import seed_benchmark_identities  # noqa: E402
from enterprise_memory.trimem.checkpoint import (  # noqa: E402
    FileCheckpointStore,
    RuntimeCheckpoint,
)
from enterprise_memory.trimem.gateway import (  # noqa: E402
    AsyncProviderModelGateway,
    GatewayInvocationFailure,
    GatewayRequest,
    GatewayResponse,
    ModelPreflightFailure,
    PREFLIGHT_PASSED,
    ReservationPreflight,
    gateway_request_sha256,
)
from enterprise_memory.trimem.git_workspace import (  # noqa: E402
    DockerSandboxCommandRunner,
    GitCheckoutWorkspaceFactory,
    validate_safe_local_git_configuration,
)
from enterprise_memory.trimem.grader import (  # noqa: E402
    GradeRequest,
    GradeResult,
    GraderInvocationFailure,
)
from enterprise_memory.trimem.production_lifecycle import production_dqn_lifecycle_factory  # noqa: E402
from enterprise_memory.trimem.production_runtime import open_benchmark_arm  # noqa: E402
from enterprise_memory.trimem.production_v03_lifecycle import (  # noqa: E402
    production_v03_lifecycle_factory,
)
from enterprise_memory.trimem.runtime_lock import RuntimeLock  # noqa: E402
from enterprise_memory.trimem.schema import canonical_hash  # noqa: E402
from enterprise_memory.trimem.scientific_terminal import (  # noqa: E402
    SCIENTIFIC_CELL_STATUSES,
    SCIENTIFIC_EXECUTION_STATUS,
    SCIENTIFIC_LEDGER_TERMINAL_STATUS,
    SCIENTIFIC_MODEL_RESERVATION_TERMINAL_STATUSES,
    ScientificTerminalContractError,
    canonical_scientific_failure_class,
    scientific_task_arm_key,
    validate_result_ledger_pair,
    validate_result_request_statuses,
    validate_scientific_role_call_accounting,
    validate_scientific_terminal_result,
)
from trimem_benchmark_matrix import sequence_sha256  # noqa: E402
from trimem_harness_lock import (  # noqa: E402
    HarnessLockError,
    prepare_harnesses,
    validate_lexical_directory_chain,
    validate_pristine_checkout,
)
from trimem_m2_candidates import (  # noqa: E402
    CANDIDATE_IDS,
    candidate_row,
    load_bundle as load_m2_candidate_bundle,
    load_candidate_policy,
    runtime_lock_for,
    select_development_candidate,
    validate_selected_m2,
)
from trimem_official_grader import (  # noqa: E402
    MULTI_HARNESS_REVISION,
    SWE_HARNESS_REVISION,
    FrozenOfficialTarget,
    OfficialHarnessGraderGateway,
    minimal_subprocess_env,
)
from trimem_official_harness_loader import (  # noqa: E402
    EXPECTED_LIBPYTHON,
    LOADER_PROBE_CODE,
    build_official_harness_python_loader,
)
from trimem_official_harness_loader_preflight import (  # noqa: E402
    SWE_IMPORT_PROBE_CODE,
    build_invocation_construction_evidence,
)
from trimem_multi_swe_entrypoint import (  # noqa: E402
    EXPECTED_CONFIG_FIELDS as MULTI_EXPECTED_CONFIG_FIELDS,
    LOADER_SELF_CHECK_MODULES as MULTI_LOADER_SELF_CHECK_MODULES,
)
from trimem_grader_smoke_trigger_preflight import (  # noqa: E402
    REQUEST_SCHEMA as GRADER_SMOKE_REQUEST_SCHEMA,
    SENTINEL_PATH as GRADER_SMOKE_SENTINEL_PATH,
    TriggerPreflightError,
    validate_request_document as validate_grader_smoke_request_document,
)
from trimem_development_trigger_d19 import (  # noqa: E402
    EXPECTED_WORKFLOW_REF as DEVELOPMENT_WORKFLOW_REF,
    SENTINEL_PATH as DEVELOPMENT_SENTINEL_PATH,
    DevelopmentTriggerError,
    validate_sentinel_commit as validate_development_sentinel_commit,
)
from trimem_exec_approval import (  # noqa: E402
    ApprovalValidationError,
    validate_external_approval_document,
)
from trimem_development_phase_cap import (  # noqa: E402
    DevelopmentPhaseCapError,
    PROTOCOL_CANARY_INPUT_RESERVATION,
    PROTOCOL_CANARY_OUTPUT_RESERVATION,
    scientific_cap_after_protocol_canary,
    validate_development_phase_hard_cap,
)


SHA256 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
ARMS = ("M0", "M1", "M2")
SPLITS = ("development", "heldout")
MANIFESTS = {
    "development": Path("configs/trimem_v1/development_manifest.json"),
    "heldout": Path("configs/trimem_v1/heldout_manifest.json"),
    "grader-smoke": Path("configs/trimem_v1/grader_smoke_manifest.json"),
}
PHASES = {
    "development": "DEVELOPMENT_TUNING",
    "heldout": "HELDOUT_BENCHMARK",
    "grader-smoke": "GRADER_SMOKE",
}
LEDGER_ACTUAL_FIELDS = (
    "paid_model_calls",
    "solve_calls",
    "decomposition_calls",
    "extraction_calls",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "total_usd",
    "task_arm_runs",
    "grader_containers",
)
LEDGER_OUTSTANDING_FIELDS = tuple(
    field for field in LEDGER_ACTUAL_FIELDS if field != "cached_input_tokens"
)
CALL_CAP_BY_KIND = {
    "solve": "solve_calls",
    "decompose": "decomposition_calls",
    "extract": "extraction_calls",
}
TASK_LEDGER_PROJECTION_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "solve_calls",
    "decomposition_calls",
    "extraction_calls",
    "model_gateway_calls",
    "paid_model_calls",
    "total_usd",
)
TERMINAL_LEDGER_REQUEST_FIELDS = {
    "reservation_id",
    "status",
    "input_upper_bound",
    "output_cap",
    "reserved_usd",
    "task_arm_key",
    "call_kind",
    "call_cap_name",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "actual_usd",
}
RESERVED_LEDGER_REQUEST_FIELDS = TERMINAL_LEDGER_REQUEST_FIELDS - {
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "actual_usd",
}
TERMINAL_LEDGER_TASK_ARM_FIELDS = {
    "reservation_id",
    "status",
    "actual_input_tokens",
    "outstanding_input_tokens",
    "actual_model_calls",
    "outstanding_model_calls",
    "actual_output_tokens",
    "outstanding_output_tokens",
    "actual_decomposition_output_tokens",
    "actual_solve_output_tokens",
    "actual_extraction_output_tokens",
    "remaining_decomposition_output_tokens",
    "remaining_solve_output_tokens",
    "remaining_extraction_output_tokens",
    "container_started",
}
RESERVED_LEDGER_TASK_ARM_FIELDS = TERMINAL_LEDGER_TASK_ARM_FIELDS - {
    "container_started",
}
LEDGER_TASK_ARM_TERMINAL_STATUSES = frozenset(
    {SCIENTIFIC_LEDGER_TERMINAL_STATUS}
)
MAX_LEDGER_INPUT_BOUND_PER_CALL = 262_000
MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND = {
    "solve": 16_384,
    "decompose": 8_192,
    "extract": 8_192,
}
TASK_OUTPUT_POOL_BY_CALL_KIND = {
    "decompose": 8_192,
    "solve": 49_152,
    "extract": 8_192,
}
TASK_TOTAL_OUTPUT_POOL = 65_536
PROTOCOL_CANARY_RELATIVE_PATH = Path("control/protocol-action-canary.json")
TASK_ACTUAL_OUTPUT_FIELD_BY_CALL_KIND = {
    "decompose": "actual_decomposition_output_tokens",
    "solve": "actual_solve_output_tokens",
    "extract": "actual_extraction_output_tokens",
}
TASK_REMAINING_OUTPUT_FIELD_BY_CALL_KIND = {
    "decompose": "remaining_decomposition_output_tokens",
    "solve": "remaining_solve_output_tokens",
    "extract": "remaining_extraction_output_tokens",
}
BENCHMARK_EXEC_REQUEST = Path("configs/trimem_v1/benchmark_exec_request.json")
GRADER_SMOKE_EXEC_REQUEST = Path(
    GRADER_SMOKE_SENTINEL_PATH
)
DEVELOPMENT_EXEC_REQUEST = Path(DEVELOPMENT_SENTINEL_PATH)
OFFICIAL_HARNESS_LOADER_PREFLIGHT = Path(
    "artifacts/trimem_v1/benchmark_exec/control/official-harness-loader-preflight.json"
)
OFFICIAL_HARNESS_LOADER_PREFLIGHT_SCHEMA = (
    "trimem/official-harness-loader-preflight/1.0"
)
OFFICIAL_HARNESS_LOADER_PREFLIGHT_PASS = (
    "TRIMEM_OFFICIAL_HARNESS_LOADER_PREFLIGHT_PASS"
)
OFFICIAL_HARNESS_PYTHON_LOADER_SCHEMA = (
    "trimem/official-harness-python-loader/1.0"
)
OFFICIAL_HARNESS_PREFLIGHT_ZERO_COUNTERS = {
    "model_metadata_requests": 0,
    "model_generation_calls": 0,
    "paid_calls": 0,
    "image_pulls": 0,
    "grader_attempts": 0,
    "grader_containers": 0,
    "usd": 0,
}
OFFICIAL_DATASET_URLS = {
    "swebench_verified": "https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified/resolve/{revision}/{path}",
    "multi_swe_bench_mini": "https://huggingface.co/datasets/ByteDance-Seed/Multi-SWE-bench_mini/resolve/{revision}/{path}",
    "multi_swe_bench_flash": "https://huggingface.co/datasets/ByteDance-Seed/Multi-SWE-bench-flash/resolve/{revision}/{path}",
}


class BenchmarkExecutionError(RuntimeError):
    pass


PROCESS_DISPOSITIONS = frozenset(
    {
        "SUCCESS",
        "RESUME_SAFE_DURABLE_SUFFIX",
        "RESUME_SAFE_CELL_COMMIT_JOURNAL",
        "GLOBAL_ENVIRONMENT_FAILURE",
        "GLOBAL_CREDENTIAL_FAILURE",
        "GLOBAL_MODEL_IDENTITY_FAILURE",
        "GLOBAL_LEDGER_INTEGRITY_FAILURE",
        "GLOBAL_GRADER_INFRA_FAILURE",
        "GLOBAL_EVIDENCE_FAILURE",
        "UNKNOWN_FAILURE",
    }
)
RESUME_SAFE_PROCESS_DISPOSITIONS = frozenset(
    {"RESUME_SAFE_DURABLE_SUFFIX", "RESUME_SAFE_CELL_COMMIT_JOURNAL"}
)
GRADER_LIFECYCLE_STATES = (
    "GRADER_NOT_PREPARED",
    "GRADER_PREFLIGHT_PASSED",
    "GRADER_REQUEST_RECORDED",
    "GRADER_PROCESS_STARTED",
    "GRADER_CONTAINER_STARTED",
    "GRADER_TERMINAL_RESULT_CAPTURED",
    "GRADER_INFRA_FAILURE_BEFORE_CONTAINER",
    "GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START",
    "GRADER_RESULT_VALIDATED",
)
CELL_COMMIT_STATES = (
    "PREPARED",
    "RESULT_WRITTEN",
    "LEDGER_TERMINAL",
    "CURSOR_ADVANCED",
    "COMMITTED",
)


class BenchmarkProcessFailure(BenchmarkExecutionError):
    """Failure carrying the only disposition the same-attempt driver may trust."""

    def __init__(self, disposition: str, message: str):
        if disposition not in PROCESS_DISPOSITIONS - {"SUCCESS"}:
            raise ValueError("invalid benchmark process disposition")
        super().__init__(message)
        self.disposition = disposition


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=strict_object)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise BenchmarkExecutionError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BenchmarkExecutionError(f"JSON root is not an object: {path}")
    return value


def validate_official_harness_loader_preflight_evidence(
    value: Mapping[str, Any],
    *,
    python_binary: str | Path = sys.executable,
    _runtime_loader_evidence: Optional[Mapping[str, Any]] = None,
    _runtime_environment: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """Validate the workflow's no-container preflight against this process.

    The report is not a generic PASS flag.  It is accepted only when its
    producer contract, zero-execution counters, pinned harness revisions, and
    exact interpreter bytes all agree with the benchmark process that will
    construct the official grader.
    """

    def fail(message: str) -> None:
        raise BenchmarkProcessFailure(
            "GLOBAL_ENVIRONMENT_FAILURE",
            "official harness loader preflight " + message,
        )

    if not isinstance(value, Mapping):
        fail("is not an object")
    evidence = dict(value)
    required_top_level = {
        "schema",
        "status",
        "marker",
        "environment_constructor",
        "python_loader",
        "environment_identity_sha256",
        "environment_keys",
        "swe_revision",
        "multi_revision",
        "swe_import_check",
        "multi_self_check",
        "invocation_construction",
        "counters",
    }
    if (
        set(evidence) != required_top_level
        or evidence.get("schema") != OFFICIAL_HARNESS_LOADER_PREFLIGHT_SCHEMA
        or evidence.get("status") != "PASS"
        or evidence.get("marker") != OFFICIAL_HARNESS_LOADER_PREFLIGHT_PASS
        or evidence.get("environment_constructor")
        != "trimem_official_grader.minimal_subprocess_env"
        or not isinstance(evidence.get("environment_identity_sha256"), str)
        or SHA256.fullmatch(evidence["environment_identity_sha256"]) is None
        or not isinstance(evidence.get("environment_keys"), list)
        or evidence["environment_keys"] != sorted(set(evidence["environment_keys"]))
        or any(
            not isinstance(name, str) or not name
            for name in evidence["environment_keys"]
        )
    ):
        fail("schema/status marker differs")
    environment_identity = evidence.get("environment_identity_sha256")
    environment_keys = evidence.get("environment_keys")
    forbidden_environment_keys = {
        "LD_PRELOAD",
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
    }
    if (
        not isinstance(environment_identity, str)
        or SHA256.fullmatch(environment_identity) is None
        or not isinstance(environment_keys, list)
        or environment_keys != sorted(set(environment_keys))
        or not all(isinstance(name, str) and name for name in environment_keys)
        or forbidden_environment_keys.intersection(environment_keys)
    ):
        fail("generated environment identity differs")
    counters = evidence.get("counters")
    if (
        not isinstance(counters, Mapping)
        or set(counters) != set(OFFICIAL_HARNESS_PREFLIGHT_ZERO_COUNTERS)
        or any(
            type(counters.get(name)) is not int
            or counters.get(name) != expected
            for name, expected in OFFICIAL_HARNESS_PREFLIGHT_ZERO_COUNTERS.items()
        )
    ):
        fail("zero-execution counters differ")

    try:
        expected_python = Path(python_binary).resolve(strict=True)
    except OSError:
        fail("exact Python binary does not resolve")
        raise AssertionError("unreachable")
    if not expected_python.is_file():
        fail("exact Python binary is not a file")
    expected_python_raw = expected_python.read_bytes()
    loader = evidence.get("python_loader")
    if not isinstance(loader, Mapping):
        fail("Python-loader evidence is absent")
    required_loader_fields = {
        "schema",
        "python_binary",
        "python_binary_realpath",
        "python_binary_sha256",
        "python_binary_bytes",
        "python_binary_mode",
        "python_version",
        "python_prefix",
        "libdir",
        "libdir_mode",
        "libpython_path",
        "libpython_realpath",
        "libpython_sha256",
        "libpython_bytes",
        "libpython_mode",
        "inherited_ld_library_path_used",
        "ld_preload_present",
        "generated_environment_keys",
        "loader_probe_argv",
        "loader_probe_exit_code",
        "loader_probe_stdout_sha256",
        "loader_probe_stderr_sha256",
        "status",
    }
    if set(loader) != required_loader_fields:
        fail("Python-loader evidence field set differs")
    try:
        observed_python = Path(str(loader.get("python_binary_realpath"))).resolve(
            strict=True
        )
        supplied_python = Path(str(loader.get("python_binary"))).resolve(strict=True)
    except OSError:
        fail("Python-loader identity does not resolve")
        raise AssertionError("unreachable")
    probe_argv = loader.get("loader_probe_argv")
    if (
        loader.get("schema") != OFFICIAL_HARNESS_PYTHON_LOADER_SCHEMA
        or loader.get("status") != "PASS"
        or observed_python != expected_python
        or supplied_python != expected_python
        or loader.get("python_binary_realpath") != str(expected_python)
        or loader.get("python_binary_sha256")
        != sha256_bytes(expected_python_raw)
        or loader.get("python_binary_bytes") != len(expected_python_raw)
        or loader.get("python_version") != sys.version
        or loader.get("loader_probe_exit_code") != 0
        or probe_argv != [str(expected_python), "-c", LOADER_PROBE_CODE]
        or not isinstance(loader.get("python_binary_mode"), str)
        or re.fullmatch(r"[0-7]{4}", loader["python_binary_mode"]) is None
        or not isinstance(loader.get("loader_probe_stdout_sha256"), str)
        or SHA256.fullmatch(loader["loader_probe_stdout_sha256"]) is None
        or not isinstance(loader.get("loader_probe_stderr_sha256"), str)
        or SHA256.fullmatch(loader["loader_probe_stderr_sha256"]) is None
        or loader.get("inherited_ld_library_path_used") is not False
        or loader.get("ld_preload_present") is not False
        or loader.get("generated_environment_keys") != environment_keys
    ):
        fail("exact Python-loader identity differs")

    try:
        python_prefix = Path(str(loader.get("python_prefix"))).resolve(strict=True)
    except OSError:
        fail("Python installation prefix does not resolve")
        raise AssertionError("unreachable")
    if not python_prefix.is_dir():
        fail("Python installation prefix is not a directory")
    if os.name == "posix":
        try:
            libdir = Path(str(loader.get("libdir"))).resolve(strict=True)
            libpython_path = Path(str(loader.get("libpython_path")))
            libpython_realpath = Path(
                str(loader.get("libpython_realpath"))
            ).resolve(strict=True)
        except OSError:
            fail("Python loader library identity does not resolve")
            raise AssertionError("unreachable")
        try:
            libdir.relative_to(python_prefix)
            libpython_realpath.relative_to(python_prefix)
        except ValueError:
            fail("Python loader library escaped its installation prefix")
        try:
            resolved_declared_library = libpython_path.resolve(strict=True)
        except OSError:
            fail("declared libpython path does not resolve")
            raise AssertionError("unreachable")
        libpython_raw = libpython_realpath.read_bytes()
        current_libdir_mode = stat.S_IMODE(libdir.stat().st_mode)
        current_libpython_mode = stat.S_IMODE(libpython_realpath.stat().st_mode)
        if (
            not libdir.is_dir()
            or not libpython_realpath.is_file()
            or libpython_path.name != EXPECTED_LIBPYTHON
            or libpython_path.parent.resolve(strict=True) != libdir
            or resolved_declared_library != libpython_realpath
            or loader.get("libdir") != str(libdir)
            or loader.get("libpython_realpath") != str(libpython_realpath)
            or loader.get("libpython_sha256") != sha256_bytes(libpython_raw)
            or loader.get("libpython_bytes") != len(libpython_raw)
            or loader.get("libdir_mode") != f"{current_libdir_mode:04o}"
            or loader.get("libpython_mode") != f"{current_libpython_mode:04o}"
            or current_libdir_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or current_libpython_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or "LD_LIBRARY_PATH" not in environment_keys
        ):
            fail("exact libpython loader identity differs")
    elif any(
        loader.get(name) is not None
        for name in (
            "libdir",
            "libdir_mode",
            "libpython_path",
            "libpython_realpath",
            "libpython_sha256",
            "libpython_bytes",
            "libpython_mode",
        )
    ) or "LD_LIBRARY_PATH" in environment_keys:
        fail("non-ELF developer loader unexpectedly supplied a library path")

    if (_runtime_loader_evidence is None) != (_runtime_environment is None):
        fail("runtime loader/environment test binding is incomplete")
    if _runtime_loader_evidence is None:
        try:
            runtime_loader = build_official_harness_python_loader(
                os.environ,
                python_binary=str(loader["python_binary"]),
                probe_cwd=python_prefix,
            )
            current_loader = dict(runtime_loader.evidence)
            current_environment = minimal_subprocess_env(
                os.environ, python_binary=str(loader["python_binary"])
            )
        except Exception as exc:
            fail(f"cannot reconstruct the current exact loader: {type(exc).__name__}")
            raise AssertionError("unreachable")
        if current_environment != dict(runtime_loader.environment):
            fail("current minimal environment differs from canonical loader")
    else:
        current_loader = dict(_runtime_loader_evidence)
        current_environment = {
            str(name): str(child)
            for name, child in dict(_runtime_environment).items()
        }
    if (
        canonical_bytes(current_loader) != canonical_bytes(dict(loader))
        or sorted(current_environment) != environment_keys
        or sha256_bytes(canonical_bytes(current_environment))
        != environment_identity
    ):
        fail("current exact loader/environment identity differs")

    injected_runtime = _runtime_loader_evidence is not None
    harness_roots: dict[str, Path] = {}
    revision_contracts = (
        ("swe_revision", SWE_HARNESS_REVISION),
        ("multi_revision", MULTI_HARNESS_REVISION),
    )
    for name, revision in revision_contracts:
        row = evidence.get(name)
        if (
            not isinstance(row, Mapping)
            or set(row)
            != {"cwd", "revision", "status", "stdout_sha256", "stderr_sha256"}
            or row.get("status") != "PASS"
            or row.get("revision") != revision
            or not isinstance(row.get("cwd"), str)
            or not isinstance(row.get("stdout_sha256"), str)
            or SHA256.fullmatch(row["stdout_sha256"]) is None
            or not isinstance(row.get("stderr_sha256"), str)
            or SHA256.fullmatch(row["stderr_sha256"]) is None
        ):
            fail(f"{name.replace('_', ' ')} differs")
        try:
            root = Path(row["cwd"]).resolve(strict=True)
        except OSError:
            fail(f"{name.replace('_', ' ')} cwd does not resolve")
            raise AssertionError("unreachable")
        if not root.is_dir():
            fail(f"{name.replace('_', ' ')} cwd is not a directory")
        harness_roots[name] = root
        if not injected_runtime:
            try:
                validate_pristine_checkout(root, revision)
            except HarnessLockError:
                fail(f"{name.replace('_', ' ')} cannot be reverified")
                raise AssertionError("unreachable")
            expected_revision_stdout = (revision + "\n").encode("ascii")
            if (
                sha256_bytes(expected_revision_stdout) != row["stdout_sha256"]
                or sha256_bytes(b"") != row["stderr_sha256"]
            ):
                fail(f"{name.replace('_', ' ')} checkout identity differs")

    swe_root = harness_roots["swe_revision"]
    multi_root = harness_roots["multi_revision"]
    invocation = evidence.get("invocation_construction")
    try:
        expected_invocation = build_invocation_construction_evidence(
            python_binary=str(expected_python),
            swe_root=swe_root,
            multi_root=multi_root,
            environment_identity_sha256=environment_identity,
        )
    except Exception as exc:
        fail(f"invocation construction cannot be reproduced: {type(exc).__name__}")
        raise AssertionError("unreachable")
    if (
        not isinstance(invocation, Mapping)
        or dict(invocation) != expected_invocation
    ):
        fail("invocation-construction identity differs")
    for name in ("swe_import_check", "multi_self_check"):
        row = evidence.get(name)
        if not isinstance(row, Mapping) or row.get("status") != "PASS":
            fail(f"{name.replace('_', ' ')} did not pass")
    swe_import = evidence["swe_import_check"]
    swe_modules = swe_import.get("modules")
    expected_swe_modules = {
        "swebench.harness.run_evaluation",
        "docker",
        "datasets",
        "unidiff",
    }
    if (
        set(swe_import)
        != {"argv", "cwd", "exit_code", "modules", "status", "stderr_sha256", "stdout_sha256"}
        or swe_import.get("exit_code") != 0
        or swe_import.get("cwd") != str(swe_root)
        or swe_import.get("argv")
        != [str(expected_python), "-c", SWE_IMPORT_PROBE_CODE]
        or not isinstance(swe_modules, Mapping)
        or set(swe_modules) != expected_swe_modules
        or not isinstance(swe_import.get("stdout_sha256"), str)
        or SHA256.fullmatch(swe_import["stdout_sha256"]) is None
        or not isinstance(swe_import.get("stderr_sha256"), str)
        or SHA256.fullmatch(swe_import["stderr_sha256"]) is None
    ):
        fail("SWE-bench import probe identity differs")
    for name, module in swe_modules.items():
        if (
            not isinstance(module, Mapping)
            or set(module) != {"bytes", "path", "sha256"}
            or type(module.get("bytes")) is not int
            or module["bytes"] <= 0
            or not isinstance(module.get("sha256"), str)
            or SHA256.fullmatch(module["sha256"]) is None
            or (
                name == "swebench.harness.run_evaluation"
                and module.get("path")
                != "swebench/harness/run_evaluation.py"
            )
        ):
            fail(f"SWE-bench import module evidence differs: {name}")
        if not injected_runtime:
            if name == "swebench.harness.run_evaluation":
                module_path = swe_root / "swebench/harness/run_evaluation.py"
            else:
                spec = importlib.util.find_spec(name)
                origin = None if spec is None else spec.origin
                if not isinstance(origin, str):
                    fail(f"SWE-bench dependency module cannot be resolved: {name}")
                module_path = Path(origin).resolve(strict=True)
                if module.get("path") is not None:
                    fail(f"SWE-bench external module path leaked into evidence: {name}")
            raw_module = module_path.read_bytes()
            if (
                module.get("bytes") != len(raw_module)
                or module.get("sha256") != sha256_bytes(raw_module)
            ):
                fail(f"SWE-bench import module bytes differ: {name}")
    expected_swe_stdout = (
        json.dumps(
            {
                "modules": dict(swe_modules),
                "schema": "trimem/swe-bench-loader-import-probe/1.0",
                "status": "PASS",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    if (
        swe_import["stdout_sha256"] != sha256_bytes(expected_swe_stdout)
        or swe_import["stderr_sha256"] != sha256_bytes(b"")
    ):
        fail("SWE-bench import probe stream hashes differ")

    multi_check = evidence["multi_self_check"]
    multi_payload = multi_check.get("payload")
    expected_multi_modules = {
        "multi_swe_bench.harness.run_evaluation",
        "multi_swe_bench.harness.gen_report",
        "multi_swe_bench.harness.dataset",
        "multi_swe_bench.harness.report",
        "multi_swe_bench.harness.test_result",
    }
    if (
        set(multi_check)
        != {"argv", "cwd", "exit_code", "payload", "status", "stderr_sha256", "stdout_sha256"}
        or multi_check.get("exit_code") != 0
        or multi_check.get("cwd") != str(multi_root)
        or not isinstance(multi_check.get("argv"), list)
        or len(multi_check["argv"]) != 5
        or multi_check["argv"][0] != str(expected_python)
        or multi_check["argv"][1]
        != str((ROOT / "scripts/trimem_multi_swe_entrypoint.py").resolve(strict=True))
        or multi_check["argv"][2] != "--loader-self-check"
        or multi_check["argv"][3] != "--harness-root"
        or multi_check["argv"][4] != str(multi_root)
        or not isinstance(multi_check.get("stdout_sha256"), str)
        or SHA256.fullmatch(multi_check["stdout_sha256"]) is None
        or not isinstance(multi_check.get("stderr_sha256"), str)
        or SHA256.fullmatch(multi_check["stderr_sha256"]) is None
        or not isinstance(multi_payload, Mapping)
        or multi_payload.get("schema")
        != "trimem/multi-swe-loader-self-check/1.0"
        or multi_payload.get("status") != "PASS"
        or multi_payload.get("harness_revision") != MULTI_HARNESS_REVISION
        or not isinstance(multi_payload.get("modules"), Mapping)
        or set(multi_payload["modules"]) != expected_multi_modules
        or multi_payload.get("cli_argument_destinations")
        != sorted(MULTI_EXPECTED_CONFIG_FIELDS)
        or any(
            multi_payload.get(name) != expected
            for name, expected in OFFICIAL_HARNESS_PREFLIGHT_ZERO_COUNTERS.items()
        )
    ):
        fail("Multi-SWE self-check identity differs")
    for name, module in multi_payload["modules"].items():
        if (
            not isinstance(module, Mapping)
            or set(module) != {"bytes", "path", "sha256"}
            or type(module.get("bytes")) is not int
            or module["bytes"] <= 0
            or not isinstance(module.get("path"), str)
            or not module["path"]
            or not isinstance(module.get("sha256"), str)
            or SHA256.fullmatch(module["sha256"]) is None
        ):
            fail(f"Multi-SWE import module evidence differs: {name}")
        if not injected_runtime:
            expected_relative = name.replace(".", "/") + ".py"
            module_path = multi_root / expected_relative
            raw_module = module_path.read_bytes()
            if (
                module.get("path") != expected_relative
                or module.get("bytes") != len(raw_module)
                or module.get("sha256") != sha256_bytes(raw_module)
            ):
                fail(f"Multi-SWE import module bytes differ: {name}")
    if set(expected_multi_modules) != set(MULTI_LOADER_SELF_CHECK_MODULES):
        fail("Multi-SWE local loader module contract differs")
    expected_multi_stdout = (
        json.dumps(
            dict(multi_payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
    if (
        multi_check["stdout_sha256"] != sha256_bytes(expected_multi_stdout)
        or multi_check["stderr_sha256"] != sha256_bytes(b"")
    ):
        fail("Multi-SWE self-check stream hashes differ")
    return evidence


def load_official_harness_loader_preflight(
    path: Path = ROOT / OFFICIAL_HARNESS_LOADER_PREFLIGHT,
) -> dict[str, Any]:
    """Load the fixed workflow-produced report before any task reservation."""

    try:
        evidence = read_json(path)
    except BenchmarkExecutionError as exc:
        raise BenchmarkProcessFailure(
            "GLOBAL_ENVIRONMENT_FAILURE",
            "official harness loader preflight evidence is missing or malformed",
        ) from exc
    return validate_official_harness_loader_preflight_evidence(evidence)


def validate_preflight_harness_root_binding(
    evidence: Mapping[str, Any],
    harnesses: Mapping[str, Path],
) -> None:
    """Bind preflight cwd evidence to the exact production checkout objects."""

    try:
        swe_evidence_root = Path(
            str(evidence["swe_revision"]["cwd"])
        ).resolve(strict=True)
        multi_evidence_root = Path(
            str(evidence["multi_revision"]["cwd"])
        ).resolve(strict=True)
        swe_runtime_root = harnesses["swebench_verified"].resolve(strict=True)
        multi_mini_root = harnesses["multi_swe_bench_mini"].resolve(strict=True)
        multi_flash_root = harnesses["multi_swe_bench_flash"].resolve(strict=True)
    except (KeyError, TypeError, OSError) as exc:
        raise BenchmarkProcessFailure(
            "GLOBAL_ENVIRONMENT_FAILURE",
            "official harness preflight/runtime cwd binding is incomplete",
        ) from exc
    if (
        swe_evidence_root != swe_runtime_root
        or multi_evidence_root != multi_mini_root
        or multi_evidence_root != multi_flash_root
    ):
        raise BenchmarkProcessFailure(
            "GLOBAL_ENVIRONMENT_FAILURE",
            "official harness runtime cwd differs from exact preflight",
        )


def atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, json_file_bytes(value))


def json_file_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0 or not HEX40.fullmatch(completed.stdout.strip()):
        raise BenchmarkExecutionError("cannot resolve exact Git HEAD")
    return completed.stdout.strip()


def validate_grader_smoke_sentinel(request_path: Path) -> dict[str, Any]:
    """Revalidate the full committed sentinel contract at the EXEC boundary."""

    request = read_json(request_path)
    expected_source_head = request.get("source_head")
    if not isinstance(expected_source_head, str) or HEX40.fullmatch(expected_source_head) is None:
        raise BenchmarkExecutionError("grader-smoke sentinel source_head is invalid")
    execution_head = git_head()
    if os.environ.get("GITHUB_EVENT_NAME") == "push":
        parents = subprocess.run(
            ["git", "rev-list", "--parents", "-n", "1", execution_head],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        parent_fields = parents.stdout.strip().split()
        if (
            parents.returncode != 0
            or parent_fields != [execution_head, expected_source_head]
        ):
            raise BenchmarkExecutionError(
                "grader-smoke push HEAD is not the exact one-parent sentinel commit"
            )
    try:
        return validate_grader_smoke_request_document(
            ROOT,
            request_path.read_bytes(),
            expected_source_head=expected_source_head,
            material_commit=execution_head,
        )
    except (ImportError, OSError, TriggerPreflightError) as exc:
        raise BenchmarkExecutionError(
            f"grader-smoke sentinel exact-content validation failed: {exc}"
        ) from None


def git_tracked(path: Path) -> None:
    relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    completed = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise BenchmarkExecutionError(f"required execution artifact is not git-tracked: {relative}")


def validate_benchmark_environment() -> dict[str, Any]:
    import importlib.metadata

    lock_path = ROOT / "configs/trimem_v1/benchmark_environment_lock.json"
    requirements_path = ROOT / "configs/trimem_v1/benchmark_environment.lock"
    input_path = ROOT / "configs/trimem_v1/benchmark_environment.in"
    for path in (lock_path, requirements_path, input_path):
        git_tracked(path)
    lock = read_json(lock_path)
    runner, dependency = lock.get("runner", {}), lock.get("dependency_lock", {})
    if runner != {
        "automatic_ci_runner_label": "ubuntu-24.04",
        "benchmark_exec_runner_labels": [
            "self-hosted", "linux", "x64", "ubuntu-24.04", "trimem-benchmark"
        ],
        "benchmark_exec_max_job_minutes": 7200,
        "benchmark_exec_runner_boundary": (
            "protected ephemeral self-hosted runner; one serial phase job owns PostgreSQL, "
            "Qdrant and the atomic global ledger"
        ),
        "operating_system": "linux", "architecture": "x86_64",
        "python_implementation": "CPython", "python_version": "3.11.10",
    }:
        raise BenchmarkExecutionError("benchmark runner lock is not exact")
    if platform.system().lower() != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise BenchmarkExecutionError("benchmark runner OS/architecture mismatch")
    if platform.python_implementation() != "CPython" or platform.python_version() != "3.11.10":
        raise BenchmarkExecutionError("benchmark CPython version mismatch")
    for path, field in ((requirements_path, "lock_sha256"), (input_path, "input_sha256")):
        if sha256_bytes(path.read_bytes()) != dependency.get(field):
            raise BenchmarkExecutionError(f"benchmark dependency {field} mismatch")
    expected_env = lock.get("embedding_execution", {}).get("environment", {})
    if not isinstance(expected_env, Mapping) or any(os.environ.get(key) != value for key, value in expected_env.items()):
        raise BenchmarkExecutionError("CPU/deterministic benchmark environment variables are not exact")
    for distribution, expected_version in lock.get("critical_versions", {}).items():
        try:
            observed = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as exc:
            raise BenchmarkExecutionError(f"benchmark dependency is missing: {distribution}") from exc
        if observed != expected_version:
            raise BenchmarkExecutionError(f"benchmark dependency version mismatch: {distribution}")
    import torch
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    if not torch.are_deterministic_algorithms_enabled() or torch.cuda.is_available():
        raise BenchmarkExecutionError("benchmark embedder is not CPU-only deterministic")
    return lock


def validate_database_role_boundary(admin_database_url: str, runtime_database_url: str) -> None:
    try:
        admin = make_url(admin_database_url)
        runtime = make_url(runtime_database_url)
    except Exception as exc:
        raise BenchmarkExecutionError("benchmark database URLs are invalid") from exc
    if admin.drivername != "postgresql+asyncpg" or runtime.drivername != "postgresql+asyncpg":
        raise BenchmarkExecutionError("benchmark admin/runtime databases require postgresql+asyncpg")
    if runtime.username != "api_service" or admin.username in {
        None, "api_service", "worker_service", "index_worker_service"
    }:
        raise BenchmarkExecutionError("benchmark database roles are not admin/runtime separated")
    admin_endpoint = (admin.host, admin.port or 5432, admin.database)
    runtime_endpoint = (runtime.host, runtime.port or 5432, runtime.database)
    if admin_endpoint != runtime_endpoint:
        raise BenchmarkExecutionError("benchmark admin/runtime database endpoints differ")


def _iso_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def validate_exec_approval(split: str, approval_path: Path) -> dict[str, Any]:
    """Bind an external immutable approval to an already-frozen commit.

    The committed request deliberately remains PENDING.  Making that file
    APPROVED would change both HEAD and the freeze it was meant to approve, so
    an approval embedded in the freeze has no finite fixed point.  The manual
    workflow instead supplies a protected, immutable artifact outside the
    repository and this function binds every byte of it to the committed
    request, HEAD, freeze, phase, and caps.
    """
    if split == "heldout" and os.environ.get("GITHUB_EVENT_NAME") == "push":
        raise BenchmarkExecutionError(
            "benchmark branch push cannot route to HELDOUT_BENCHMARK"
        )
    policy_request_path = ROOT / BENCHMARK_EXEC_REQUEST
    request_path = {
        "grader-smoke": ROOT / GRADER_SMOKE_EXEC_REQUEST,
        "development": ROOT / DEVELOPMENT_EXEC_REQUEST,
        "heldout": policy_request_path,
    }[split]
    freeze_path = ROOT / "artifacts/trimem_v1/freeze.json"
    cost_path = ROOT / "configs/trimem_v1/cost_plan.json"
    for path in (
        policy_request_path,
        request_path,
        freeze_path,
        cost_path,
        ROOT / MANIFESTS[split],
    ):
        git_tracked(path)
    request = read_json(request_path)
    policy_request = read_json(policy_request_path)
    cost = read_json(cost_path)
    phase = PHASES[split]
    if policy_request.get("approval_state") != "PENDING_EXEC_APPROVAL":
        raise BenchmarkExecutionError("committed request must remain pending and immutable")
    phases = {
        row.get("phase"): row
        for row in policy_request.get("phases", ())
        if isinstance(row, dict)
    }
    if phases.get(phase, {}).get("status") != "PENDING_EXEC_APPROVAL":
        raise BenchmarkExecutionError(f"committed {phase} request is not pending")
    if split == "grader-smoke":
        if request.get("schema") != GRADER_SMOKE_REQUEST_SCHEMA:
            raise BenchmarkExecutionError("grader-smoke sentinel schema mismatch")
        if request.get("phase") != phase:
            raise BenchmarkExecutionError("grader-smoke sentinel phase mismatch")
        policy_hash = sha256_bytes(policy_request_path.read_bytes())
        if request.get("frozen_request_sha256") not in {
            policy_hash,
            "sha256:" + policy_hash,
        }:
            raise BenchmarkExecutionError(
                "grader-smoke sentinel does not bind the frozen execution policy"
            )
        validate_grader_smoke_sentinel(request_path)
    elif split == "development":
        if os.environ.get("GITHUB_EVENT_NAME") != "push":
            raise BenchmarkExecutionError(
                "one-time DEVELOPMENT_TUNING execution requires the exact sentinel push"
            )
        if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
            raise BenchmarkExecutionError(
                "one-time DEVELOPMENT_TUNING execution requires workflow attempt 1"
            )
        if os.environ.get("GITHUB_WORKFLOW_REF") != DEVELOPMENT_WORKFLOW_REF:
            raise BenchmarkExecutionError(
                "DEVELOPMENT_TUNING approval is outside the exact branch workflow"
            )
        if os.environ.get("GITHUB_WORKFLOW_SHA") != git_head():
            raise BenchmarkExecutionError(
                "DEVELOPMENT_TUNING workflow source differs from execution HEAD"
            )
        try:
            validated_request = validate_development_sentinel_commit(
                ROOT,
                git_head(),
            )
        except DevelopmentTriggerError as exc:
            raise BenchmarkExecutionError(str(exc)) from None
        if request != validated_request:
            raise BenchmarkExecutionError("DEV sentinel validation result differs")
    try:
        approval_resolved = approval_path.resolve(strict=True)
    except OSError as exc:
        raise BenchmarkExecutionError("external EXEC approval artifact is missing") from exc
    root_resolved = ROOT.resolve()
    if approval_resolved == root_resolved or root_resolved in approval_resolved.parents:
        raise BenchmarkExecutionError("EXEC approval must be external to the frozen repository")
    approval_raw = approval_resolved.read_bytes()
    approval_document = read_json(approval_resolved)
    expected_approval_schema = (
        "trimem/external-exec-approval/1.2"
        if split == "development"
        and "approved_openai_key_commitment"
        in request.get("required_external_approval_fields", ())
        else "trimem/external-exec-approval/1.1"
        if split == "development"
        else "trimem/external-exec-approval/1.0"
    )
    if approval_document.get("schema") != expected_approval_schema:
        raise BenchmarkExecutionError("external EXEC approval schema mismatch")
    if approval_document.get("request_id") != request.get("request_id"):
        raise BenchmarkExecutionError("external approval request identity mismatch")
    request_hash = sha256_bytes(request_path.read_bytes())
    if approval_document.get("approved_request_sha256") not in {request_hash, "sha256:" + request_hash}:
        raise BenchmarkExecutionError("external approval does not bind the committed request bytes")
    approval = approval_document.get("approval")
    if not isinstance(approval, dict):
        raise BenchmarkExecutionError("external approval binding is missing")
    required_approval_fields = (
        request.get("required_external_approval_fields", ())
        if split == "development"
        else policy_request.get("required_approval_fields", ())
    )
    missing = sorted(set(required_approval_fields) - set(approval))
    if missing:
        raise BenchmarkExecutionError(f"approval binding fields are missing: {missing}")
    head = git_head()
    if approval.get("approved_git_commit") != head:
        raise BenchmarkExecutionError("approval Git commit differs from execution HEAD")
    source_head = request.get("source_head") if split == "development" else None
    if split == "development" and approval.get("approved_source_git_commit") != source_head:
        raise BenchmarkExecutionError(
            "approval source Git commit differs from the DEV sentinel parent"
        )
    freeze_hash = sha256_bytes(freeze_path.read_bytes())
    if approval.get("approved_freeze_sha256") not in {freeze_hash, "sha256:" + freeze_hash}:
        raise BenchmarkExecutionError("approval freeze digest differs from committed freeze")
    if approval.get("approved_phase") != phase:
        raise BenchmarkExecutionError("approval phase mismatch")
    workflow_run_id = os.environ.get("GITHUB_RUN_ID")
    workflow_run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
    if not workflow_run_id or re.fullmatch(r"[1-9][0-9]*", workflow_run_id) is None:
        raise BenchmarkExecutionError("exact GITHUB_RUN_ID is required for single-dispatch approval binding")
    if not workflow_run_attempt or re.fullmatch(r"[1-9][0-9]*", workflow_run_attempt) is None:
        raise BenchmarkExecutionError("exact GITHUB_RUN_ATTEMPT is required for single-attempt approval binding")
    if split in {"grader-smoke", "development"} and workflow_run_attempt != "1":
        raise BenchmarkExecutionError(
            "one-time phase execution requires workflow run attempt 1"
        )
    if str(approval.get("approved_workflow_run_id")) != workflow_run_id:
        raise BenchmarkExecutionError("approval workflow run ID differs from this dispatch")
    if str(approval.get("approved_workflow_run_attempt")) != workflow_run_attempt:
        raise BenchmarkExecutionError("approval workflow run attempt differs from this attempt")
    if not isinstance(approval.get("approval_actor"), str) or not approval["approval_actor"].strip():
        raise BenchmarkExecutionError("approval actor is missing")
    if not _iso_timestamp(approval.get("approval_timestamp")):
        raise BenchmarkExecutionError("approval timestamp is not an exact UTC timestamp")
    approved_at = datetime.fromisoformat(approval["approval_timestamp"][:-1] + "+00:00")
    if approved_at > datetime.now(timezone.utc):
        raise BenchmarkExecutionError("approval timestamp is in the future")
    if approval.get("approved_legal_terms_acceptance") is not True:
        raise BenchmarkExecutionError("approval actor did not accept applicable benchmark/source-project terms")
    hard = cost.get("phase_hard_caps", {}).get(phase, {})
    if not isinstance(hard, dict) or not hard:
        raise BenchmarkExecutionError("frozen phase hard cap is missing")
    if phase == "DEVELOPMENT_TUNING":
        try:
            hard = validate_development_phase_hard_cap(hard)
        except DevelopmentPhaseCapError as exc:
            raise BenchmarkExecutionError(str(exc)) from None
    exact = {
        "approved_task_arm_runs": hard.get("task_arm_runs"),
        "approved_paid_model_call_cap": hard.get("paid_model_calls"),
        "approved_input_token_cap": hard.get("input_tokens"),
        "approved_output_token_cap": hard.get("output_tokens"),
        "approved_currency_hard_cap": hard.get("total_usd"),
        "approved_grader_containers": hard.get("benchmark_grader_containers"),
    }
    for name, expected in exact.items():
        if approval.get(name) != expected:
            raise BenchmarkExecutionError(f"approval cap does not equal frozen proposed cap: {name}")
    try:
        approval = validate_external_approval_document(
            approval_document,
            request=request,
            policy_request=policy_request,
            phase=phase,
            hard_cap=hard,
            request_sha256=request_hash,
            freeze_sha256=freeze_hash,
            git_head=head,
            source_head=source_head,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
        )
    except ApprovalValidationError as exc:
        raise BenchmarkExecutionError(str(exc)) from None
    return {
        "request": request,
        "approval": approval,
        "approval_artifact_sha256": sha256_bytes(approval_raw),
        "approval_document": approval_document,
        "approved_request_sha256": request_hash,
        "approved_workflow_run_id": workflow_run_id,
        "approved_workflow_run_attempt": workflow_run_attempt,
        "git_head": head,
        "source_head": source_head,
        "freeze_sha256": freeze_hash,
        "phase": phase,
        "hard_cap": hard,
    }


def write_external_approval_evidence(
    output: Path,
    *,
    split: str,
    approval_path: Path,
    validated: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist the exact restricted approval and its public hash-only binding."""

    approval_raw = approval_path.resolve(strict=True).read_bytes()
    if sha256_bytes(approval_raw) != validated["approval_artifact_sha256"]:
        raise BenchmarkExecutionError("exact external approval bytes/hash mismatch")
    restricted_approval = output / "restricted-external-approval.json"
    if restricted_approval.exists():
        if restricted_approval.read_bytes() != approval_raw:
            raise BenchmarkExecutionError(
                "resume external approval differs from the first process attempt"
            )
    else:
        restricted_approval.write_bytes(approval_raw)
        try:
            restricted_approval.chmod(0o600)
        except OSError:
            pass
    public = {
        "approval_artifact_sha256": validated["approval_artifact_sha256"],
        "approved_request_sha256": validated["approved_request_sha256"],
        "approved_workflow_run_id": validated["approved_workflow_run_id"],
        "approved_workflow_run_attempt": validated["approved_workflow_run_attempt"],
        "freeze_sha256": validated["freeze_sha256"],
        "git_head": validated["git_head"],
        "phase": validated["phase"],
    }
    if split == "development":
        public["source_head"] = validated["source_head"]
    write_json(output / "external-approval-evidence.json", public)
    return public


@contextmanager
def _exclusive_file_lock(path: Path):
    if path.is_symlink():
        raise BenchmarkExecutionError("budget ledger lock path is a symbolic link")
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


class AtomicBudgetLedger:
    """Cross-process durable caps for one serial benchmark execution.

    All three arms use this same file in one workflow job.  Model calls reserve
    the conservative uncached input byte bound, provider maximum output, one
    paid call, their exact solve/decomposition/extraction class, and worst-case
    USD before delegation. Task-arm and grader capacity is also reserved before
    the runtime starts a task.
    """

    def __init__(self, path: Path, *, approval_digest: str, caps: Mapping[str, Any], pricing: Mapping[str, Any]):
        if path.is_symlink():
            raise BenchmarkExecutionError("budget ledger path is a symbolic link")
        self.path = path.resolve()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        if self.lock_path.is_symlink():
            raise BenchmarkExecutionError("budget ledger lock path is a symbolic link")
        self.approval_digest = approval_digest
        self.approved_hard_cap = dict(caps)
        self.caps = {
            "paid_model_calls": int(caps["paid_model_calls"]),
            "solve_calls": int(caps["solve_calls"]),
            "decomposition_calls": int(caps["decomposition_calls"]),
            "extraction_calls": int(caps["extraction_calls"]),
            "input_tokens": int(caps["input_tokens"]),
            "output_tokens": int(caps["output_tokens"]),
            "total_usd": float(caps["total_usd"]),
            "task_arm_runs": int(caps["task_arm_runs"]),
            "grader_containers": int(caps["benchmark_grader_containers"]),
            "max_input_tokens_per_task_arm": int(caps["max_input_tokens_per_task_arm"]),
            "max_model_calls_per_task_arm": int(caps["max_model_calls_per_task_arm"]),
        }
        self.pricing = {
            "input": float(pricing["input_per_million_tokens_usd"]),
            "cached": float(pricing["cached_input_per_million_tokens_usd"]),
            "output": float(pricing["output_per_million_tokens_usd"]),
        }
        if any(value <= 0 for value in self.caps.values()) or any(value <= 0 for value in self.pricing.values()):
            raise ValueError("budget caps and pricing must be positive")
        if int(caps["model_calls"]) != self.caps["paid_model_calls"] or int(
            caps["model_calls"]
        ) != sum(self.caps[field] for field in CALL_CAP_BY_KIND.values()):
            raise ValueError("approved model/paid/role call caps do not add up")
        uncached_ceiling = (
            Decimal(self.caps["input_tokens"]) * Decimal(str(self.pricing["input"]))
            + Decimal(self.caps["output_tokens"])
            * Decimal(str(self.pricing["output"]))
        ) / Decimal(1_000_000)
        if uncached_ceiling != Decimal(str(caps["uncached_token_cost_ceiling_usd"])):
            raise ValueError("uncached token-cost ceiling differs from caps/pricing")

    def _empty(self) -> dict[str, Any]:
        return {
            "schema": "trimem/atomic-budget-ledger/1.4",
            "approval_digest": self.approval_digest,
            "approved_hard_cap": self.approved_hard_cap,
            "approved_hard_cap_sha256": sha256_bytes(
                canonical_bytes(self.approved_hard_cap)
            ),
            "caps": self.caps,
            "pricing": self.pricing,
            "actual": {"paid_model_calls": 0, "solve_calls": 0,
                       "decomposition_calls": 0, "extraction_calls": 0,
                       "input_tokens": 0, "cached_input_tokens": 0,
                       "output_tokens": 0, "total_usd": 0.0, "task_arm_runs": 0,
                       "grader_containers": 0},
            "outstanding": {"paid_model_calls": 0, "solve_calls": 0,
                            "decomposition_calls": 0, "extraction_calls": 0,
                            "input_tokens": 0, "output_tokens": 0,
                            "total_usd": 0.0, "task_arm_runs": 0, "grader_containers": 0},
            "requests": {},
            "task_arms": {},
        }

    def _read(self) -> dict[str, Any]:
        value = self._empty() if not self.path.exists() else read_json(self.path)
        if (value.get("schema") != "trimem/atomic-budget-ledger/1.4" or
                value.get("approval_digest") != self.approval_digest or
                value.get("approved_hard_cap") != self.approved_hard_cap or
                value.get("approved_hard_cap_sha256") != sha256_bytes(
                    canonical_bytes(self.approved_hard_cap)
                ) or
                value.get("caps") != self.caps or value.get("pricing") != self.pricing):
            raise BenchmarkExecutionError("budget ledger approval/cap identity mismatch")
        return self._validate_dynamic_state(value)

    @staticmethod
    def _money_equal(left: Any, right: Any) -> bool:
        try:
            if isinstance(left, bool) or isinstance(right, bool):
                return False
            return abs(Decimal(str(left)) - Decimal(str(right))) <= Decimal(
                "0.000000000001"
            )
        except (InvalidOperation, ValueError, TypeError):
            return False

    def _validate_dynamic_state(
        self, state: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Reconstruct every mutable counter without modifying the ledger.

        Cap checks are meaningful only after the persisted request/task graph
        proves the counters used by those checks.  This validator therefore
        treats any shape, identity, lifecycle, or arithmetic disagreement as
        ledger corruption before a caller can classify ordinary cell/phase
        exhaustion.
        """

        def fail(reason: str) -> None:
            raise BenchmarkExecutionError(f"budget ledger integrity failure: {reason}")

        expected_top = {
            "schema",
            "approval_digest",
            "approved_hard_cap",
            "approved_hard_cap_sha256",
            "caps",
            "pricing",
            "actual",
            "outstanding",
            "requests",
            "task_arms",
        }
        if not isinstance(state, Mapping) or set(state) != expected_top:
            fail("top-level field set differs")
        actual = state.get("actual")
        outstanding = state.get("outstanding")
        requests = state.get("requests")
        task_arms = state.get("task_arms")
        if not isinstance(actual, Mapping) or set(actual) != set(
            LEDGER_ACTUAL_FIELDS
        ):
            fail("actual counter shape differs")
        if not isinstance(outstanding, Mapping) or set(outstanding) != set(
            LEDGER_OUTSTANDING_FIELDS
        ):
            fail("outstanding counter shape differs")
        if not isinstance(requests, Mapping) or not isinstance(task_arms, Mapping):
            fail("request/task-arm collections are malformed")

        integer_actual = set(LEDGER_ACTUAL_FIELDS) - {"total_usd"}
        integer_outstanding = set(LEDGER_OUTSTANDING_FIELDS) - {"total_usd"}
        if any(
            type(actual.get(name)) is not int or actual[name] < 0
            for name in integer_actual
        ):
            fail("actual counters must be non-negative integers")
        if any(
            type(outstanding.get(name)) is not int or outstanding[name] < 0
            for name in integer_outstanding
        ):
            fail("outstanding counters must be non-negative integers")

        def money(value: Any, label: str) -> Decimal:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                fail(f"{label} is not finite non-negative money")
            try:
                amount = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                fail(f"{label} is not finite non-negative money")
            if not amount.is_finite() or amount < 0:
                fail(f"{label} is not finite non-negative money")
            return amount

        actual_usd = money(actual.get("total_usd"), "actual total_usd")
        outstanding_usd = money(
            outstanding.get("total_usd"), "outstanding total_usd"
        )
        if actual["cached_input_tokens"] > actual["input_tokens"]:
            fail("cached input exceeds actual input")
        if actual["paid_model_calls"] != sum(
            int(actual[name]) for name in CALL_CAP_BY_KIND.values()
        ):
            fail("actual paid/role call counters disagree")
        if outstanding["paid_model_calls"] != sum(
            int(outstanding[name]) for name in CALL_CAP_BY_KIND.values()
        ):
            fail("outstanding paid/role call counters disagree")

        phase_cap_fields = {
            "paid_model_calls",
            "solve_calls",
            "decomposition_calls",
            "extraction_calls",
            "input_tokens",
            "output_tokens",
            "task_arm_runs",
            "grader_containers",
        }
        for name in phase_cap_fields:
            if actual[name] + outstanding[name] > self.caps[name]:
                fail(f"{name} counters exceed the approved cap")
        if actual_usd + outstanding_usd > (
            Decimal(str(self.caps["total_usd"])) + Decimal("0.000000000001")
        ):
            fail("total_usd counters exceed the approved cap")

        task_numeric_fields = RESERVED_LEDGER_TASK_ARM_FIELDS - {
            "reservation_id",
            "status",
        }
        task_projection: dict[str, dict[str, Any]] = {}
        active_task_count = 0
        completed_task_count = 0
        completed_container_count = 0
        for task_key, row in task_arms.items():
            if not isinstance(task_key, str) or not task_key or not isinstance(row, Mapping):
                fail("task-arm identity or row is malformed")
            status = row.get("status")
            if not isinstance(status, str):
                fail(f"task-arm lifecycle status is malformed: {task_key}")
            expected_fields = (
                RESERVED_LEDGER_TASK_ARM_FIELDS
                if status == "RESERVED"
                else TERMINAL_LEDGER_TASK_ARM_FIELDS
                if status in LEDGER_TASK_ARM_TERMINAL_STATUSES
                else set()
            )
            if not expected_fields or set(row) != expected_fields:
                fail(
                    "task-arm/result accounting differs "
                    f"(lifecycle/field shape): {task_key}"
                )
            expected_reservation_id = sha256_bytes(
                canonical_bytes(
                    {"approval": self.approval_digest, "task_arm_key": task_key}
                )
            )
            if row.get("reservation_id") != expected_reservation_id:
                fail(
                    "task-arm/result accounting differs "
                    f"(reservation identity): {task_key}"
                )
            if any(
                type(row.get(name)) is not int or row[name] < 0
                for name in task_numeric_fields
            ):
                fail(f"task-arm counters are malformed: {task_key}")
            if status == "RESERVED":
                active_task_count += 1
            else:
                if type(row.get("container_started")) is not bool:
                    fail(f"terminal task-arm container state is malformed: {task_key}")
                completed_task_count += 1
                completed_container_count += int(bool(row["container_started"]))
            task_projection[task_key] = {
                "actual_input_tokens": 0,
                "outstanding_input_tokens": 0,
                "actual_model_calls": 0,
                "outstanding_model_calls": 0,
                "actual_output_tokens": 0,
                "outstanding_output_tokens": 0,
                "actual_role_output": {
                    kind: 0 for kind in TASK_OUTPUT_POOL_BY_CALL_KIND
                },
                "outstanding_role_output": {
                    kind: 0 for kind in TASK_OUTPUT_POOL_BY_CALL_KIND
                },
            }

        reconstructed_actual = {
            "paid_model_calls": 0,
            "solve_calls": 0,
            "decomposition_calls": 0,
            "extraction_calls": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "total_usd": Decimal(0),
            "task_arm_runs": completed_task_count,
            "grader_containers": completed_container_count,
        }
        reconstructed_outstanding = {
            "paid_model_calls": 0,
            "solve_calls": 0,
            "decomposition_calls": 0,
            "extraction_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_usd": Decimal(0),
            "task_arm_runs": active_task_count,
            "grader_containers": active_task_count,
        }
        conservative_statuses = {
            "SUCCESS_CONSERVATIVE_USAGE",
            "PROVIDER_FAILURE_CONSERVATIVE",
        }
        for logical_id, row in requests.items():
            if (
                not isinstance(logical_id, str)
                or not logical_id
                or not isinstance(row, Mapping)
            ):
                fail("model request identity or row is malformed")
            status = row.get("status")
            if not isinstance(status, str):
                fail(f"request lifecycle status is malformed: {logical_id}")
            terminal = status in SCIENTIFIC_MODEL_RESERVATION_TERMINAL_STATUSES
            expected_fields = (
                RESERVED_LEDGER_REQUEST_FIELDS
                if status == "RESERVED"
                else TERMINAL_LEDGER_REQUEST_FIELDS
                if terminal
                else set()
            )
            if not expected_fields or set(row) != expected_fields:
                label = "terminal" if terminal else "reserved"
                fail(
                    f"{label} request shape differs "
                    f"(lifecycle/field shape): {logical_id}"
                )
            call_kind = row.get("call_kind")
            if not isinstance(call_kind, str):
                fail(f"request role binding differs: {logical_id}")
            cap_name = CALL_CAP_BY_KIND.get(call_kind)
            if cap_name is None or row.get("call_cap_name") != cap_name:
                fail(f"request role binding differs: {logical_id}")
            task_key = row.get("task_arm_key")
            if not isinstance(task_key, str) or task_key not in task_projection:
                fail(f"request has no task-arm reservation: {logical_id}")
            task_row = task_arms[task_key]
            if status == "RESERVED" and task_row.get("status") != "RESERVED":
                fail(f"reserved request belongs to a terminal task-arm: {logical_id}")

            input_upper_bound = row.get("input_upper_bound")
            output_cap = row.get("output_cap")
            if (
                type(input_upper_bound) is not int
                or not 0 < input_upper_bound <= MAX_LEDGER_INPUT_BOUND_PER_CALL
                or type(output_cap) is not int
                or output_cap <= 0
                or output_cap > MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[str(call_kind)]
                or (
                    call_kind != "solve"
                    and output_cap != MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[str(call_kind)]
                )
            ):
                fail(f"request reservation bounds are invalid: {logical_id}")
            expected_reservation_id = sha256_bytes(
                canonical_bytes(
                    {
                        "approval": self.approval_digest,
                        "logical_call_id": logical_id,
                        "task_arm_key": task_key,
                        "call_kind": call_kind,
                        "input_upper_bound": input_upper_bound,
                        "output_cap": output_cap,
                    }
                )
            )
            if row.get("reservation_id") != expected_reservation_id:
                fail(f"request reservation identity differs: {logical_id}")
            expected_reserved_usd = (
                Decimal(input_upper_bound) * Decimal(str(self.pricing["input"]))
                + Decimal(output_cap) * Decimal(str(self.pricing["output"]))
            ) / Decimal(1_000_000)
            reserved_usd = money(
                row.get("reserved_usd"), f"request reserved_usd: {logical_id}"
            )
            if not self._money_equal(reserved_usd, expected_reserved_usd):
                fail(f"request reserved USD differs: {logical_id}")

            projection = task_projection[str(task_key)]
            if status == "RESERVED":
                reconstructed_outstanding["paid_model_calls"] += 1
                reconstructed_outstanding[str(cap_name)] += 1
                reconstructed_outstanding["input_tokens"] += input_upper_bound
                reconstructed_outstanding["output_tokens"] += output_cap
                reconstructed_outstanding["total_usd"] += reserved_usd
                projection["outstanding_input_tokens"] += input_upper_bound
                projection["outstanding_model_calls"] += 1
                projection["outstanding_output_tokens"] += output_cap
                projection["outstanding_role_output"][str(call_kind)] += output_cap
                continue

            usage_names = ("input_tokens", "cached_input_tokens", "output_tokens")
            if any(
                type(row.get(name)) is not int or row[name] < 0
                for name in usage_names
            ):
                fail(f"terminal request usage is malformed: {logical_id}")
            if (
                row["cached_input_tokens"] > row["input_tokens"]
                or row["input_tokens"] > input_upper_bound
                or row["output_tokens"] > output_cap
            ):
                fail(
                    "terminal request actual usage exceeds its reservation: "
                    f"{logical_id}"
                )
            if status in conservative_statuses and (
                row["input_tokens"] != input_upper_bound
                or row["cached_input_tokens"] != 0
                or row["output_tokens"] != output_cap
            ):
                fail(f"conservative terminal request is not cap-charged: {logical_id}")
            expected_actual_usd = (
                Decimal(row["input_tokens"] - row["cached_input_tokens"])
                * Decimal(str(self.pricing["input"]))
                + Decimal(row["cached_input_tokens"])
                * Decimal(str(self.pricing["cached"]))
                + Decimal(row["output_tokens"])
                * Decimal(str(self.pricing["output"]))
            ) / Decimal(1_000_000)
            request_actual_usd = money(
                row.get("actual_usd"), f"request actual_usd: {logical_id}"
            )
            if not self._money_equal(request_actual_usd, expected_actual_usd):
                fail(f"terminal request actual USD differs: {logical_id}")
            if request_actual_usd > reserved_usd + Decimal("0.000000000001"):
                fail(f"terminal request actual USD exceeds reservation: {logical_id}")

            reconstructed_actual["paid_model_calls"] += 1
            reconstructed_actual[str(cap_name)] += 1
            reconstructed_actual["input_tokens"] += row["input_tokens"]
            reconstructed_actual["cached_input_tokens"] += row[
                "cached_input_tokens"
            ]
            reconstructed_actual["output_tokens"] += row["output_tokens"]
            reconstructed_actual["total_usd"] += request_actual_usd
            projection["actual_input_tokens"] += row["input_tokens"]
            projection["actual_model_calls"] += 1
            projection["actual_output_tokens"] += row["output_tokens"]
            projection["actual_role_output"][str(call_kind)] += row["output_tokens"]

        for task_key, projection in task_projection.items():
            row = task_arms[task_key]
            for name in (
                "actual_input_tokens",
                "outstanding_input_tokens",
                "actual_model_calls",
                "outstanding_model_calls",
                "actual_output_tokens",
                "outstanding_output_tokens",
            ):
                if row.get(name) != projection[name]:
                    fail(f"task-arm {name} disagrees with requests: {task_key}")
            for kind, pool in TASK_OUTPUT_POOL_BY_CALL_KIND.items():
                actual_field = TASK_ACTUAL_OUTPUT_FIELD_BY_CALL_KIND[kind]
                remaining_field = TASK_REMAINING_OUTPUT_FIELD_BY_CALL_KIND[kind]
                actual_role = projection["actual_role_output"][kind]
                outstanding_role = projection["outstanding_role_output"][kind]
                if row.get(actual_field) != actual_role:
                    fail(f"task-arm {actual_field} disagrees with requests: {task_key}")
                if row.get(remaining_field) != pool - actual_role - outstanding_role:
                    fail(f"task-arm {remaining_field} disagrees with requests: {task_key}")
                if actual_role + outstanding_role > pool:
                    fail(f"task-arm {kind} output pool exceeds its cap: {task_key}")
            if (
                projection["actual_input_tokens"]
                + projection["outstanding_input_tokens"]
                > self.caps["max_input_tokens_per_task_arm"]
                or projection["actual_model_calls"]
                + projection["outstanding_model_calls"]
                > self.caps["max_model_calls_per_task_arm"]
                or projection["actual_output_tokens"]
                + projection["outstanding_output_tokens"]
                > TASK_TOTAL_OUTPUT_POOL
            ):
                fail(f"task-arm counters exceed a frozen pool: {task_key}")
            if row.get("status") != "RESERVED" and (
                projection["outstanding_input_tokens"]
                or projection["outstanding_model_calls"]
                or projection["outstanding_output_tokens"]
            ):
                fail(f"terminal task-arm retains a live request: {task_key}")

        for name in set(LEDGER_ACTUAL_FIELDS) - {"total_usd"}:
            if actual[name] != reconstructed_actual[name]:
                fail(f"actual {name} differs from request/task reconstruction")
        for name in set(LEDGER_OUTSTANDING_FIELDS) - {"total_usd"}:
            if outstanding[name] != reconstructed_outstanding[name]:
                fail(f"outstanding {name} disagrees with request/task reconstruction")
        if not self._money_equal(actual_usd, reconstructed_actual["total_usd"]):
            fail("actual total_usd disagrees with request reconstruction")
        if not self._money_equal(
            outstanding_usd, reconstructed_outstanding["total_usd"]
        ):
            fail("outstanding total_usd disagrees with request reconstruction")
        return dict(state)

    def finalize(
        self,
        *,
        expected_actual: Mapping[str, Any],
        expected_task_arms: Mapping[str, Mapping[str, Any]],
        expected_result_records: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Validate the terminal ledger against every scientific task result."""

        with _exclusive_file_lock(self.lock_path):
            state = self._read()
        if set(state) != {
            "schema", "approval_digest", "approved_hard_cap",
            "approved_hard_cap_sha256", "caps", "pricing", "actual",
            "outstanding", "requests", "task_arms",
        }:
            raise BenchmarkExecutionError("budget ledger top-level shape differs")
        actual, outstanding = state.get("actual"), state.get("outstanding")
        if not isinstance(actual, dict) or set(actual) != set(LEDGER_ACTUAL_FIELDS):
            raise BenchmarkExecutionError("budget ledger actual counter shape differs")
        if not isinstance(outstanding, dict) or set(outstanding) != set(
            LEDGER_OUTSTANDING_FIELDS
        ):
            raise BenchmarkExecutionError("budget ledger outstanding counter shape differs")
        if set(expected_actual) != set(LEDGER_ACTUAL_FIELDS):
            raise BenchmarkExecutionError("task-result ledger projection shape differs")
        for field, expected in expected_actual.items():
            observed = actual[field]
            valid = self._money_equal(observed, expected) if field == "total_usd" else (
                type(observed) is int and observed >= 0 and observed == expected
            )
            if not valid:
                raise BenchmarkExecutionError(
                    f"budget ledger actual {field} differs from task results"
                )
        for field, value in outstanding.items():
            valid = self._money_equal(value, 0) if field == "total_usd" else (
                type(value) is int and value == 0
            )
            if not valid:
                raise BenchmarkExecutionError(
                    f"phase completed with outstanding {field} reservation"
                )
        if actual["cached_input_tokens"] > actual["input_tokens"]:
            raise BenchmarkExecutionError("budget ledger cached input exceeds total input")
        if actual["paid_model_calls"] != sum(
            actual[field] for field in CALL_CAP_BY_KIND.values()
        ):
            raise BenchmarkExecutionError("budget ledger paid/role call totals differ")

        requests = state["requests"]
        if not isinstance(requests, dict) or len(requests) != actual["paid_model_calls"]:
            raise BenchmarkExecutionError("budget ledger request count differs from actual calls")
        role_counts = {field: 0 for field in CALL_CAP_BY_KIND.values()}
        per_task_requests: dict[str, dict[str, Any]] = {
            task_key: {
                field: ("0.000000000000" if field == "total_usd" else 0)
                for field in TASK_LEDGER_PROJECTION_FIELDS
            }
            for task_key in expected_task_arms
        }
        per_task_role_output = {
            task_key: {kind: 0 for kind in TASK_OUTPUT_POOL_BY_CALL_KIND}
            for task_key in expected_task_arms
        }
        per_task_request_rows: dict[str, list[Mapping[str, Any]]] = {
            task_key: [] for task_key in expected_task_arms
        }
        for logical_id, request in requests.items():
            if (
                not isinstance(logical_id, str)
                or not logical_id
                or not isinstance(request, dict)
                or set(request) != TERMINAL_LEDGER_REQUEST_FIELDS
            ):
                raise BenchmarkExecutionError(
                    "budget ledger terminal request shape differs"
                )
            if (
                request.get("status")
                not in SCIENTIFIC_MODEL_RESERVATION_TERMINAL_STATUSES
            ):
                raise BenchmarkExecutionError("phase has a non-terminal model reservation")
            cap_name = CALL_CAP_BY_KIND.get(request.get("call_kind"))
            if cap_name is None or request.get("call_cap_name") != cap_name:
                raise BenchmarkExecutionError("budget ledger request role binding differs")
            task_key = request.get("task_arm_key")
            if not isinstance(task_key, str) or task_key not in per_task_requests:
                raise BenchmarkExecutionError("budget ledger request task-arm binding differs")
            per_task_request_rows[task_key].append(request)
            input_upper_bound = request.get("input_upper_bound")
            output_cap = request.get("output_cap")
            if (
                type(input_upper_bound) is not int
                or not 0 < input_upper_bound <= MAX_LEDGER_INPUT_BOUND_PER_CALL
                or type(output_cap) is not int
                or output_cap <= 0
                or output_cap > MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[str(request["call_kind"])]
                or (
                    request["call_kind"] != "solve"
                    and output_cap != MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[str(request["call_kind"])]
                )
            ):
                raise BenchmarkExecutionError(
                    "budget ledger request reservation bounds are invalid"
                )
            expected_reservation_id = sha256_bytes(canonical_bytes({
                "approval": self.approval_digest,
                "logical_call_id": logical_id,
                "task_arm_key": task_key,
                "call_kind": request["call_kind"],
                "input_upper_bound": input_upper_bound,
                "output_cap": output_cap,
            }))
            if request.get("reservation_id") != expected_reservation_id:
                raise BenchmarkExecutionError(
                    "budget ledger request reservation identity differs"
                )
            expected_reserved_usd = (
                Decimal(input_upper_bound) * Decimal(str(self.pricing["input"]))
                + Decimal(output_cap) * Decimal(str(self.pricing["output"]))
            ) / Decimal(1_000_000)
            if not self._money_equal(
                request.get("reserved_usd"), expected_reserved_usd
            ):
                raise BenchmarkExecutionError(
                    "budget ledger request reserved USD differs from bounds/pricing"
                )
            token_values = (
                request.get("input_tokens"), request.get("cached_input_tokens"),
                request.get("output_tokens"),
            )
            if (
                any(type(value) is not int or value < 0 for value in token_values)
                or token_values[1] > token_values[0]
            ):
                raise BenchmarkExecutionError("budget ledger request token accounting is invalid")
            if token_values[0] > input_upper_bound or token_values[2] > output_cap:
                raise BenchmarkExecutionError(
                    "budget ledger request actual usage exceeds its reservation"
                )
            request_usd = (
                Decimal(token_values[0] - token_values[1])
                * Decimal(str(self.pricing["input"]))
                + Decimal(token_values[1]) * Decimal(str(self.pricing["cached"]))
                + Decimal(token_values[2]) * Decimal(str(self.pricing["output"]))
            ) / Decimal(1_000_000)
            if not self._money_equal(request.get("actual_usd"), request_usd):
                raise BenchmarkExecutionError("budget ledger request USD differs from pricing")
            try:
                actual_usd = Decimal(str(request["actual_usd"]))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise BenchmarkExecutionError(
                    "budget ledger request actual USD is invalid"
                ) from exc
            if actual_usd < 0 or actual_usd > expected_reserved_usd + Decimal(
                "0.000000000001"
            ):
                raise BenchmarkExecutionError(
                    "budget ledger request actual USD exceeds its reservation"
                )
            role_counts[cap_name] += 1
            projection = per_task_requests[str(task_key)]
            projection["input_tokens"] += token_values[0]
            projection["cached_input_tokens"] += token_values[1]
            projection["output_tokens"] += token_values[2]
            per_task_role_output[str(task_key)][str(request["call_kind"])] += token_values[2]
            projection[cap_name] += 1
            projection["model_gateway_calls"] += 1
            projection["paid_model_calls"] += 1
            projection["total_usd"] = format(
                Decimal(str(projection["total_usd"])) + request_usd,
                ".12f",
            )
        if any(actual[field] != count for field, count in role_counts.items()):
            raise BenchmarkExecutionError("budget ledger request/role totals differ")

        result_by_task_arm: dict[str, Mapping[str, Any]] = {}
        for record in expected_result_records:
            try:
                validate_scientific_terminal_result(record)
                task_arm_key = scientific_task_arm_key(record)
            except ScientificTerminalContractError as exc:
                raise BenchmarkExecutionError(
                    f"scientific terminal result contract failed: {exc}"
                ) from None
            if task_arm_key in result_by_task_arm:
                raise BenchmarkExecutionError(
                    "scientific terminal result task-arm identity is duplicated"
                )
            result_by_task_arm[task_arm_key] = record
        if set(result_by_task_arm) != set(expected_task_arms):
            raise BenchmarkExecutionError(
                "scientific result/task projection identities differ"
            )

        task_arms = state.get("task_arms")
        if not isinstance(task_arms, dict) or set(task_arms) != set(expected_task_arms):
            raise BenchmarkExecutionError("budget ledger task-arm identities differ from results")
        for task_arm_key, expected in expected_task_arms.items():
            row = task_arms[task_arm_key]
            projection = per_task_requests[task_arm_key]
            if set(expected) != set(TASK_LEDGER_PROJECTION_FIELDS):
                raise BenchmarkExecutionError("task-result ledger projection shape differs")
            for field in TASK_LEDGER_PROJECTION_FIELDS:
                matches = (
                    self._money_equal(projection[field], expected[field])
                    if field == "total_usd"
                    else type(expected[field]) is int
                    and projection[field] == expected[field]
                )
                if not matches:
                    raise BenchmarkExecutionError(
                        "budget ledger per-task request/result accounting differs"
                    )
            expected_task_reservation_id = sha256_bytes(canonical_bytes({
                "approval": self.approval_digest,
                "task_arm_key": task_arm_key,
            }))
            if (
                not isinstance(row, dict)
                or set(row) != TERMINAL_LEDGER_TASK_ARM_FIELDS
                or row.get("reservation_id") != expected_task_reservation_id
                or type(row.get("actual_input_tokens")) is not int
                or row["actual_input_tokens"] != expected["input_tokens"]
                or row["actual_input_tokens"]
                > self.caps["max_input_tokens_per_task_arm"]
                or type(row.get("actual_model_calls")) is not int
                or row["actual_model_calls"] != expected["model_gateway_calls"]
                or row["actual_model_calls"]
                > self.caps["max_model_calls_per_task_arm"]
                or row.get("outstanding_output_tokens") != 0
                or row.get("actual_output_tokens") != expected["output_tokens"]
            ):
                raise BenchmarkExecutionError(
                    "budget ledger task-arm/result accounting differs"
                )
            try:
                validate_result_ledger_pair(
                    result_by_task_arm[task_arm_key],
                    row,
                    ledger_task_arm_key=task_arm_key,
                )
                validate_result_request_statuses(
                    result_by_task_arm[task_arm_key],
                    per_task_request_rows[task_arm_key],
                )
            except ScientificTerminalContractError as exc:
                raise BenchmarkExecutionError(
                    f"scientific result/ledger terminal contract failed: {exc}"
                ) from None
            for kind, pool in TASK_OUTPUT_POOL_BY_CALL_KIND.items():
                actual_field = TASK_ACTUAL_OUTPUT_FIELD_BY_CALL_KIND[kind]
                remaining_field = TASK_REMAINING_OUTPUT_FIELD_BY_CALL_KIND[kind]
                role_actual = per_task_role_output[task_arm_key][kind]
                if row.get(actual_field) != role_actual or row.get(remaining_field) != pool - role_actual:
                    raise BenchmarkExecutionError("budget ledger task-arm role output accounting differs")

        hard = self.approved_hard_cap
        bounded = {
            "model_calls": actual["paid_model_calls"],
            "paid_model_calls": actual["paid_model_calls"],
            "solve_calls": actual["solve_calls"],
            "decomposition_calls": actual["decomposition_calls"],
            "extraction_calls": actual["extraction_calls"],
            "input_tokens": actual["input_tokens"],
            "output_tokens": actual["output_tokens"],
            "task_arm_runs": actual["task_arm_runs"],
            "benchmark_grader_containers": actual["grader_containers"],
        }
        for field, value in bounded.items():
            if value > hard[field]:
                raise BenchmarkExecutionError(f"terminal {field} exceeds approved hard cap")
        for field in ("task_arm_runs",):
            if bounded[field] != hard[field]:
                raise BenchmarkExecutionError(f"terminal {field} differs from exact workload")
        if bounded["benchmark_grader_containers"] != hard[
            "benchmark_grader_containers"
        ]:
            raise BenchmarkExecutionError(
                "terminal benchmark_grader_containers differs from exact workload"
            )
        actual_usd = Decimal(str(actual["total_usd"]))
        if actual_usd > Decimal(str(hard["total_usd"])) or actual_usd > Decimal(
            str(hard["uncached_token_cost_ceiling_usd"])
        ):
            raise BenchmarkExecutionError("terminal USD exceeds approved hard cap")
        return state

    def reserve_task_arm(self, task_arm_key: str) -> str:
        if not isinstance(task_arm_key, str) or not task_arm_key:
            raise ValueError("task-arm key is required")
        reservation_id = sha256_bytes(canonical_bytes({
            "approval": self.approval_digest, "task_arm_key": task_arm_key,
        }))
        with _exclusive_file_lock(self.lock_path):
            state = self._read()
            if task_arm_key in state["task_arms"]:
                raise BenchmarkExecutionError("duplicate or indeterminate task-arm reservation")
            for name in ("task_arm_runs", "grader_containers"):
                total = state["actual"][name] + state["outstanding"][name] + 1
                if total > self.caps[name]:
                    raise BenchmarkExecutionError(f"task rejected before execution: {name} hard cap")
                state["outstanding"][name] += 1
            state["task_arms"][task_arm_key] = {
                "reservation_id": reservation_id,
                "status": "RESERVED",
                "actual_input_tokens": 0,
                "outstanding_input_tokens": 0,
                "actual_model_calls": 0,
                "outstanding_model_calls": 0,
                "actual_output_tokens": 0,
                "outstanding_output_tokens": 0,
                "actual_decomposition_output_tokens": 0,
                "actual_solve_output_tokens": 0,
                "actual_extraction_output_tokens": 0,
                "remaining_decomposition_output_tokens": 8_192,
                "remaining_solve_output_tokens": 49_152,
                "remaining_extraction_output_tokens": 8_192,
            }
            self._validate_dynamic_state(state)
            write_json(self.path, state)
        return reservation_id

    def resume_task_arm(self, task_arm_key: str) -> str:
        with _exclusive_file_lock(self.lock_path):
            state = self._read()
            row = state["task_arms"].get(task_arm_key)
            if not isinstance(row, dict) or row.get("status") != "RESERVED":
                raise BenchmarkExecutionError("resume has no outstanding task-arm reservation")
            reservation_id = row.get("reservation_id")
            if not isinstance(reservation_id, str) or not SHA256.fullmatch(reservation_id):
                raise BenchmarkExecutionError("resume task-arm reservation is malformed")
            return reservation_id

    def task_arm_status(self, task_arm_key: str) -> Optional[str]:
        with _exclusive_file_lock(self.lock_path):
            row = self._read()["task_arms"].get(task_arm_key)
            return str(row.get("status")) if isinstance(row, dict) else None

    def task_arm_row(self, task_arm_key: str) -> Optional[dict[str, Any]]:
        with _exclusive_file_lock(self.lock_path):
            row = self._read()["task_arms"].get(task_arm_key)
            return dict(row) if isinstance(row, Mapping) else None

    def complete_task_arm(
        self, task_arm_key: str, reservation_id: str, *, status: str,
        container_started: bool = True,
    ) -> None:
        with _exclusive_file_lock(self.lock_path):
            state = self._read()
            row = state["task_arms"].get(task_arm_key)
            if (not isinstance(row, dict) or row.get("reservation_id") != reservation_id or
                    row.get("status") != "RESERVED"):
                raise BenchmarkExecutionError("unknown or already completed task-arm reservation")
            if row["outstanding_input_tokens"] or row["outstanding_model_calls"] or row["outstanding_output_tokens"]:
                raise BenchmarkExecutionError("task-arm has unreconciled model reservations")
            state["outstanding"]["task_arm_runs"] -= 1
            state["outstanding"]["grader_containers"] -= 1
            state["actual"]["task_arm_runs"] += 1
            # Unknown failure after starting the runtime conservatively consumes
            # the one reserved grader-container slot.  A proven pre-container
            # failure records zero but can never release task-arm capacity.
            state["actual"]["grader_containers"] += int(bool(container_started))
            row.update({"status": status, "container_started": bool(container_started)})
            self._validate_dynamic_state(state)
            write_json(self.path, state)

    @staticmethod
    def _preflight_failure(
        classification: str,
        *,
        reason: str,
        request_sha256: str,
        logical_call_id: str,
        **details: Any,
    ) -> ModelPreflightFailure:
        return ModelPreflightFailure(
            classification,
            request_sha256=request_sha256,
            logical_call_id=logical_call_id,
            details={"reason": reason, **details},
        )

    @staticmethod
    def _preflight_payload(preflight: ReservationPreflight) -> dict[str, Any]:
        value = asdict(preflight)
        value.pop("plan_sha256")
        return value

    @classmethod
    def _validate_preflight_plan(cls, preflight: ReservationPreflight) -> None:
        if sha256_bytes(canonical_bytes(cls._preflight_payload(preflight))) != preflight.plan_sha256:
            raise ModelPreflightFailure(
                "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                request_sha256=preflight.request_sha256,
                logical_call_id=preflight.ledger_logical_call_id,
                details={"reason": "reservation preflight plan hash mismatch"},
            )

    def _preview_reservation_from_state(
        self,
        state: Mapping[str, Any],
        logical_call_id: str,
        *,
        request_sha256: str,
        task_arm_key: str,
        call_kind: str,
        input_upper_bound: int,
        output_cap: int,
    ) -> ReservationPreflight:
        if (
            not isinstance(logical_call_id, str)
            or not logical_call_id
            or not isinstance(request_sha256, str)
            or SHA256.fullmatch(request_sha256) is None
            or not isinstance(task_arm_key, str)
            or not task_arm_key
            or type(input_upper_bound) is not int
            or input_upper_bound <= 0
            or type(output_cap) is not int
            or output_cap <= 0
        ):
            raise ValueError("reservation requires a logical call and positive bounds")
        if input_upper_bound > MAX_LEDGER_INPUT_BOUND_PER_CALL:
            raise self._preflight_failure(
                "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED",
                reason="per-call conservative input bound exceeds the frozen runtime cap",
                request_sha256=request_sha256,
                logical_call_id=logical_call_id,
                input_upper_bound=input_upper_bound,
                maximum=MAX_LEDGER_INPUT_BOUND_PER_CALL,
            )
        call_cap_name = {
            "solve": "solve_calls",
            "decompose": "decomposition_calls",
            "extract": "extraction_calls",
        }.get(call_kind)
        if call_cap_name is None:
            raise self._preflight_failure(
                "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                reason="paid request has an unknown call kind",
                request_sha256=request_sha256,
                logical_call_id=logical_call_id,
                call_kind=call_kind,
            )
        if output_cap > MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[call_kind] or (
            call_kind != "solve" and output_cap != MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[call_kind]
        ):
            raise self._preflight_failure(
                "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                reason="per-call output cap differs from the frozen runtime cap",
                request_sha256=request_sha256,
                logical_call_id=logical_call_id,
                output_cap=output_cap,
                expected_output_cap=MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[call_kind],
            )
        amount = input_upper_bound * self.pricing["input"] / 1_000_000 + output_cap * self.pricing["output"] / 1_000_000
        reservation_id = sha256_bytes(canonical_bytes({
            "approval": self.approval_digest, "logical_call_id": logical_call_id,
            "task_arm_key": task_arm_key,
            "call_kind": call_kind, "input_upper_bound": input_upper_bound,
            "output_cap": output_cap,
        }))
        if logical_call_id in state["requests"]:
            raise self._preflight_failure(
                "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                reason="duplicate paid logical call reservation",
                request_sha256=request_sha256,
                logical_call_id=logical_call_id,
            )
        task_arm = state["task_arms"].get(task_arm_key)
        if not isinstance(task_arm, dict) or task_arm.get("status") != "RESERVED":
            raise self._preflight_failure(
                "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                reason="paid call has no active task-arm reservation",
                request_sha256=request_sha256,
                logical_call_id=logical_call_id,
                task_arm_key=task_arm_key,
            )
        task_input_total = (
            task_arm["actual_input_tokens"]
            + task_arm["outstanding_input_tokens"]
            + input_upper_bound
        )
        if task_input_total > self.caps["max_input_tokens_per_task_arm"]:
            raise self._preflight_failure(
                "TASK_ARM_INPUT_POOL_EXHAUSTED",
                reason="paid request rejected before send: task-arm input hard cap",
                request_sha256=request_sha256,
                logical_call_id=logical_call_id,
                projected_total=task_input_total,
                maximum=self.caps["max_input_tokens_per_task_arm"],
            )
        task_call_total = (
            task_arm["actual_model_calls"]
            + task_arm["outstanding_model_calls"]
            + 1
        )
        if task_call_total > self.caps["max_model_calls_per_task_arm"]:
            raise self._preflight_failure(
                "TASK_ARM_MODEL_CALL_POOL_EXHAUSTED",
                reason="paid request rejected before send: task-arm call hard cap",
                request_sha256=request_sha256,
                logical_call_id=logical_call_id,
                projected_total=task_call_total,
                maximum=self.caps["max_model_calls_per_task_arm"],
            )
        actual_role_field = TASK_ACTUAL_OUTPUT_FIELD_BY_CALL_KIND[call_kind]
        role_outstanding = sum(
            int(row["output_cap"])
            for row in state["requests"].values()
            if row.get("status") == "RESERVED"
            and row.get("task_arm_key") == task_arm_key
            and row.get("call_kind") == call_kind
        )
        role_output_total = task_arm[actual_role_field] + role_outstanding + output_cap
        if role_output_total > TASK_OUTPUT_POOL_BY_CALL_KIND[call_kind]:
            raise self._preflight_failure(
                "TASK_ROLE_OUTPUT_POOL_EXHAUSTED",
                reason="paid request rejected before send: task-arm role output pool",
                request_sha256=request_sha256,
                logical_call_id=logical_call_id,
                projected_total=role_output_total,
                maximum=TASK_OUTPUT_POOL_BY_CALL_KIND[call_kind],
            )
        task_output_total = (
            task_arm["actual_output_tokens"]
            + task_arm["outstanding_output_tokens"]
            + output_cap
        )
        if task_output_total > TASK_TOTAL_OUTPUT_POOL:
            raise self._preflight_failure(
                "TASK_TOTAL_OUTPUT_POOL_EXHAUSTED",
                reason="paid request rejected before send: task-arm total output pool",
                request_sha256=request_sha256,
                logical_call_id=logical_call_id,
                projected_total=task_output_total,
                maximum=TASK_TOTAL_OUTPUT_POOL,
            )
        combined = {
            "paid_model_calls": state["actual"]["paid_model_calls"] + state["outstanding"]["paid_model_calls"] + 1,
            call_cap_name: state["actual"][call_cap_name] + state["outstanding"][call_cap_name] + 1,
            "input_tokens": state["actual"]["input_tokens"] + state["outstanding"]["input_tokens"] + input_upper_bound,
            "output_tokens": state["actual"]["output_tokens"] + state["outstanding"]["output_tokens"] + output_cap,
            "total_usd": state["actual"]["total_usd"] + state["outstanding"]["total_usd"] + amount,
        }
        phase_classification = {
            "paid_model_calls": "PHASE_MODEL_CALL_CAP_EXHAUSTED",
            call_cap_name: "PHASE_MODEL_CALL_CAP_EXHAUSTED",
            "input_tokens": "PHASE_INPUT_CAP_EXHAUSTED",
            "output_tokens": "PHASE_OUTPUT_CAP_EXHAUSTED",
            "total_usd": "PHASE_USD_CAP_EXHAUSTED",
        }
        for name, total in combined.items():
            if total > self.caps[name] + (1e-12 if name == "total_usd" else 0):
                raise self._preflight_failure(
                    phase_classification[name],
                    reason=f"paid request rejected before send: {name} hard cap",
                    request_sha256=request_sha256,
                    logical_call_id=logical_call_id,
                    cap_name=name,
                    projected_total=total,
                    maximum=self.caps[name],
                )
        payload = {
            "status": PREFLIGHT_PASSED,
            "request_sha256": request_sha256,
            "ledger_logical_call_id": logical_call_id,
            "task_arm_key": task_arm_key,
            "call_kind": call_kind,
            "input_upper_bound": input_upper_bound,
            "output_cap": output_cap,
            "reserved_usd": amount,
            "reservation_id": reservation_id,
            "ledger_state_sha256": sha256_bytes(canonical_bytes(state)),
        }
        return ReservationPreflight(
            **payload,
            plan_sha256=sha256_bytes(canonical_bytes(payload)),
        )

    def preview_reservation(
        self,
        logical_call_id: str,
        *,
        request_sha256: str,
        task_arm_key: str,
        call_kind: str,
        input_upper_bound: int,
        output_cap: int,
    ) -> ReservationPreflight:
        """Check every local request cap under lock without writing any bytes."""

        try:
            with _exclusive_file_lock(self.lock_path):
                state = self._read()
                return self._preview_reservation_from_state(
                    state,
                    logical_call_id,
                    request_sha256=request_sha256,
                    task_arm_key=task_arm_key,
                    call_kind=call_kind,
                    input_upper_bound=input_upper_bound,
                    output_cap=output_cap,
                )
        except ModelPreflightFailure:
            raise
        except BenchmarkExecutionError as exc:
            raise self._preflight_failure(
                "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                reason=str(exc),
                request_sha256=request_sha256,
                logical_call_id=logical_call_id,
            ) from None

    def reserve_preflighted(self, preflight: ReservationPreflight) -> str:
        """Atomically repeat an exact preview and reserve its frozen bounds."""

        self._validate_preflight_plan(preflight)
        with _exclusive_file_lock(self.lock_path):
            try:
                state = self._read()
            except BenchmarkExecutionError as exc:
                raise self._preflight_failure(
                    "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                    reason=str(exc),
                    request_sha256=preflight.request_sha256,
                    logical_call_id=preflight.ledger_logical_call_id,
                ) from None
            existing = state["requests"].get(preflight.ledger_logical_call_id)
            if existing is not None:
                if (
                    isinstance(existing, Mapping)
                    and existing.get("status") == "RESERVED"
                    and existing.get("reservation_id") == preflight.reservation_id
                    and existing.get("task_arm_key") == preflight.task_arm_key
                    and existing.get("call_kind") == preflight.call_kind
                    and existing.get("input_upper_bound") == preflight.input_upper_bound
                    and existing.get("output_cap") == preflight.output_cap
                    and self._money_equal(existing.get("reserved_usd"), preflight.reserved_usd)
                ):
                    return preflight.reservation_id
                raise self._preflight_failure(
                    "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                    reason="preflight reservation identity differs from existing ledger request",
                    request_sha256=preflight.request_sha256,
                    logical_call_id=preflight.ledger_logical_call_id,
                )
            if sha256_bytes(canonical_bytes(state)) != preflight.ledger_state_sha256:
                raise self._preflight_failure(
                    "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                    reason="ledger changed between read-only preview and atomic reservation",
                    request_sha256=preflight.request_sha256,
                    logical_call_id=preflight.ledger_logical_call_id,
                )
            try:
                repeated = self._preview_reservation_from_state(
                    state,
                    preflight.ledger_logical_call_id,
                    request_sha256=preflight.request_sha256,
                    task_arm_key=preflight.task_arm_key,
                    call_kind=preflight.call_kind,
                    input_upper_bound=preflight.input_upper_bound,
                    output_cap=preflight.output_cap,
                )
            except ModelPreflightFailure as exc:
                raise self._preflight_failure(
                    "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                    reason="atomic reservation disagreed with successful preview",
                    request_sha256=preflight.request_sha256,
                    logical_call_id=preflight.ledger_logical_call_id,
                    atomic_classification=exc.classification,
                ) from None
            if repeated != preflight:
                raise self._preflight_failure(
                    "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                    reason="atomic reservation plan differs from successful preview",
                    request_sha256=preflight.request_sha256,
                    logical_call_id=preflight.ledger_logical_call_id,
                )
            call_cap_name = CALL_CAP_BY_KIND[preflight.call_kind]
            task_arm = state["task_arms"][preflight.task_arm_key]
            actual_role_field = TASK_ACTUAL_OUTPUT_FIELD_BY_CALL_KIND[preflight.call_kind]
            remaining_role_field = TASK_REMAINING_OUTPUT_FIELD_BY_CALL_KIND[preflight.call_kind]
            role_outstanding = sum(
                int(row["output_cap"])
                for row in state["requests"].values()
                if row.get("status") == "RESERVED"
                and row.get("task_arm_key") == preflight.task_arm_key
                and row.get("call_kind") == preflight.call_kind
            )
            state["outstanding"]["paid_model_calls"] += 1
            state["outstanding"][call_cap_name] += 1
            state["outstanding"]["input_tokens"] += preflight.input_upper_bound
            state["outstanding"]["output_tokens"] += preflight.output_cap
            state["outstanding"]["total_usd"] += preflight.reserved_usd
            task_arm["outstanding_input_tokens"] += preflight.input_upper_bound
            task_arm["outstanding_model_calls"] += 1
            task_arm["outstanding_output_tokens"] += preflight.output_cap
            task_arm[remaining_role_field] = (
                TASK_OUTPUT_POOL_BY_CALL_KIND[preflight.call_kind]
                - task_arm[actual_role_field]
                - role_outstanding
                - preflight.output_cap
            )
            state["requests"][preflight.ledger_logical_call_id] = {
                "reservation_id": preflight.reservation_id, "status": "RESERVED",
                "input_upper_bound": preflight.input_upper_bound,
                "output_cap": preflight.output_cap,
                "reserved_usd": preflight.reserved_usd,
                "task_arm_key": preflight.task_arm_key,
                "call_kind": preflight.call_kind, "call_cap_name": call_cap_name,
            }
            self._validate_dynamic_state(state)
            write_json(self.path, state)
        return preflight.reservation_id

    def reserve(
        self, logical_call_id: str, *, task_arm_key: str,
        call_kind: str, input_upper_bound: int, output_cap: int,
    ) -> str:
        """Compatibility entry point; paid gateways use explicit preview/reserve."""

        request_sha256 = sha256_bytes(canonical_bytes({
            "logical_call_id": logical_call_id,
            "task_arm_key": task_arm_key,
            "call_kind": call_kind,
            "input_upper_bound": input_upper_bound,
            "output_cap": output_cap,
        }))
        try:
            preflight = self.preview_reservation(
                logical_call_id,
                request_sha256=request_sha256,
                task_arm_key=task_arm_key,
                call_kind=call_kind,
                input_upper_bound=input_upper_bound,
                output_cap=output_cap,
            )
            return self.reserve_preflighted(preflight)
        except ModelPreflightFailure as exc:
            reason = str(exc.details.get("reason") or exc.classification)
            raise BenchmarkExecutionError(f"{reason} [{exc.classification}]") from None

    def request_row(self, logical_call_id: str) -> Optional[dict[str, Any]]:
        try:
            with _exclusive_file_lock(self.lock_path):
                row = self._read()["requests"].get(logical_call_id)
        except BenchmarkExecutionError as exc:
            raise ModelPreflightFailure(
                "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                logical_call_id=logical_call_id,
                details={"reason": str(exc)},
            ) from None
        return dict(row) if isinstance(row, Mapping) else None

    def reconcile(
        self,
        logical_call_id: str,
        reservation_id: str,
        *,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        status: str,
        conservative_unknown: bool = False,
    ) -> None:
        self._reconcile(
            logical_call_id,
            reservation_id,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            status=status,
            conservative_unknown=conservative_unknown,
            allow_existing=False,
        )

    def reconcile_or_verify(
        self,
        logical_call_id: str,
        reservation_id: str,
        *,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        status: str,
        conservative_unknown: bool = False,
    ) -> None:
        """Reconcile once, or prove an identical durable reconciliation exists."""

        self._reconcile(
            logical_call_id,
            reservation_id,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            status=status,
            conservative_unknown=conservative_unknown,
            allow_existing=True,
        )

    def _reconcile(
        self,
        logical_call_id: str,
        reservation_id: str,
        *,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        status: str,
        conservative_unknown: bool = False,
        allow_existing: bool = False,
    ) -> None:
        with _exclusive_file_lock(self.lock_path):
            state = self._read()
            request = state["requests"].get(logical_call_id)
            if not isinstance(request, dict) or request.get("reservation_id") != reservation_id:
                raise BenchmarkExecutionError("unknown or already reconciled paid reservation")
            call_kind = request.get("call_kind")
            call_cap_name = {
                "solve": "solve_calls",
                "decompose": "decomposition_calls",
                "extract": "extraction_calls",
            }.get(call_kind)
            if call_cap_name is None or request.get("call_cap_name") != call_cap_name:
                raise BenchmarkExecutionError("paid reservation call-kind identity mismatch")
            if conservative_unknown:
                input_tokens, cached_input_tokens, output_tokens = request["input_upper_bound"], 0, request["output_cap"]
            values = (input_tokens, cached_input_tokens, output_tokens)
            if any(type(value) is not int or value < 0 for value in values) or cached_input_tokens > input_tokens:
                raise BenchmarkExecutionError("provider usage is not exact non-negative accounting")
            if input_tokens > request["input_upper_bound"] or output_tokens > request["output_cap"]:
                raise BenchmarkExecutionError("actual provider usage exceeded its atomic reservation")
            uncached = input_tokens - cached_input_tokens
            actual_usd = (
                uncached * self.pricing["input"] + cached_input_tokens * self.pricing["cached"] +
                output_tokens * self.pricing["output"]
            ) / 1_000_000
            if request.get("status") != "RESERVED":
                if allow_existing and (
                    request.get("status") == status
                    and request.get("input_tokens") == input_tokens
                    and request.get("cached_input_tokens") == cached_input_tokens
                    and request.get("output_tokens") == output_tokens
                    and self._money_equal(request.get("actual_usd"), actual_usd)
                ):
                    return
                raise BenchmarkExecutionError("unknown or already reconciled paid reservation")
            state["outstanding"]["paid_model_calls"] -= 1
            state["outstanding"][call_cap_name] -= 1
            state["outstanding"]["input_tokens"] -= request["input_upper_bound"]
            state["outstanding"]["output_tokens"] -= request["output_cap"]
            state["outstanding"]["total_usd"] -= request["reserved_usd"]
            task_arm = state["task_arms"].get(request["task_arm_key"])
            if not isinstance(task_arm, dict) or task_arm.get("status") != "RESERVED":
                raise BenchmarkExecutionError("paid reservation task-arm identity mismatch")
            task_arm["outstanding_input_tokens"] -= request["input_upper_bound"]
            task_arm["outstanding_model_calls"] -= 1
            task_arm["outstanding_output_tokens"] -= request["output_cap"]
            task_arm["actual_input_tokens"] += input_tokens
            task_arm["actual_model_calls"] += 1
            task_arm["actual_output_tokens"] += output_tokens
            actual_role_field = TASK_ACTUAL_OUTPUT_FIELD_BY_CALL_KIND[str(call_kind)]
            remaining_role_field = TASK_REMAINING_OUTPUT_FIELD_BY_CALL_KIND[str(call_kind)]
            task_arm[actual_role_field] += output_tokens
            role_outstanding = sum(
                int(row["output_cap"])
                for key, row in state["requests"].items()
                if key != logical_call_id
                and row.get("status") == "RESERVED"
                and row.get("task_arm_key") == request["task_arm_key"]
                and row.get("call_kind") == call_kind
            )
            task_arm[remaining_role_field] = (
                TASK_OUTPUT_POOL_BY_CALL_KIND[str(call_kind)]
                - task_arm[actual_role_field]
                - role_outstanding
            )
            state["actual"]["paid_model_calls"] += 1
            state["actual"][call_cap_name] += 1
            state["actual"]["input_tokens"] += input_tokens
            state["actual"]["cached_input_tokens"] += cached_input_tokens
            state["actual"]["output_tokens"] += output_tokens
            state["actual"]["total_usd"] += actual_usd
            request.update({"status": status, "input_tokens": input_tokens,
                            "cached_input_tokens": cached_input_tokens, "output_tokens": output_tokens,
                            "actual_usd": actual_usd})
            for name in (
                "paid_model_calls", call_cap_name, "input_tokens", "output_tokens",
                "total_usd",
            ):
                if state["actual"][name] > self.caps[name] + (1e-12 if name == "total_usd" else 0):
                    raise BenchmarkExecutionError(f"reconciled provider usage exceeded {name} hard cap")
            self._validate_dynamic_state(state)
            write_json(self.path, state)


class BudgetedModelGateway:
    def __init__(
        self, delegate: AsyncProviderModelGateway, ledger: AtomicBudgetLedger, *, stream_id: str
    ):
        if type(delegate) is not AsyncProviderModelGateway:
            raise TypeError("benchmark model gateway must use AsyncProviderModelGateway")
        if not isinstance(stream_id, str) or not stream_id:
            raise ValueError("benchmark stream_id is required")
        self.delegate = delegate
        self.ledger = ledger
        self.stream_id = stream_id

    def _request_values(self, request: GatewayRequest) -> dict[str, Any]:
        # UTF-8 bytes upper-bound prompt tokens for this text-only envelope;
        # 4096 additional tokens conservatively cover role/schema framing.
        input_bound = max(1, len(request.prompt.encode("utf-8"))) + 4_096
        return {
            "request_sha256": gateway_request_sha256(request),
            "task_arm_key": f"{self.stream_id}:{request.arm}:{request.task_id}",
            "ledger_logical_call_id": f"{self.stream_id}:{request.logical_call_id}",
            "call_kind": request.call_kind,
            "input_upper_bound": input_bound,
            "output_cap": request.max_output_tokens,
        }

    @staticmethod
    def _reservation_metadata(
        preflight: ReservationPreflight, *, charged_conservatively: bool
    ) -> dict[str, Any]:
        return {
            "reservation_id": preflight.reservation_id,
            "input_upper_bound": preflight.input_upper_bound,
            "output_cap": preflight.output_cap,
            "charged_conservatively": bool(charged_conservatively),
        }

    def _validate_request_preflight(
        self, request: GatewayRequest, preflight: ReservationPreflight
    ) -> None:
        values = self._request_values(request)
        expected = {
            name: getattr(preflight, name)
            for name in values
        }
        if expected != values:
            raise ModelPreflightFailure(
                "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                request_sha256=values["request_sha256"],
                logical_call_id=values["ledger_logical_call_id"],
                details={"reason": "request differs from its reservation preflight"},
            )
        self.ledger._validate_preflight_plan(preflight)

    def preview_reservation(self, request: GatewayRequest) -> ReservationPreflight:
        values = self._request_values(request)
        return self.ledger.preview_reservation(
            values["ledger_logical_call_id"],
            request_sha256=values["request_sha256"],
            task_arm_key=values["task_arm_key"],
            call_kind=values["call_kind"],
            input_upper_bound=values["input_upper_bound"],
            output_cap=values["output_cap"],
        )

    def request_row(self, request: GatewayRequest) -> Optional[dict[str, Any]]:
        return self.ledger.request_row(self._request_values(request)["ledger_logical_call_id"])

    def reserve_preflighted(
        self, request: GatewayRequest, preflight: ReservationPreflight
    ) -> str:
        self._validate_request_preflight(request, preflight)
        return self.ledger.reserve_preflighted(preflight)

    def send_reserved(
        self, request: GatewayRequest, preflight: ReservationPreflight
    ) -> GatewayResponse:
        """Perform only the provider side effect; the caller owns reconciliation."""

        self._validate_request_preflight(request, preflight)
        try:
            response = self.delegate.invoke(request)
        except GatewayInvocationFailure as exc:
            exc.ledger_reservation = self._reservation_metadata(
                preflight,
                charged_conservatively=not exc.provider_reported_usage_available,
            )
            raise
        if response.paid is not True:
            raise BenchmarkExecutionError("benchmark provider response is not marked paid")
        unknown_usage = not response.provider_reported_usage_available
        return replace(
            response,
            ledger_reservation=self._reservation_metadata(
                preflight, charged_conservatively=unknown_usage
            ),
        )

    def reconcile_success(
        self,
        preflight: ReservationPreflight,
        response: GatewayResponse,
    ) -> None:
        unknown_usage = not response.provider_reported_usage_available
        self.ledger.reconcile_or_verify(
            preflight.ledger_logical_call_id,
            preflight.reservation_id,
            input_tokens=response.input_tokens if not unknown_usage else 0,
            cached_input_tokens=response.cached_input_tokens if not unknown_usage else 0,
            output_tokens=response.output_tokens if not unknown_usage else 0,
            status="SUCCESS_CONSERVATIVE_USAGE" if unknown_usage else "SUCCESS",
            conservative_unknown=unknown_usage,
        )

    def reconcile_failure(
        self,
        preflight: ReservationPreflight,
        failure: GatewayInvocationFailure,
    ) -> None:
        unknown_usage = not failure.provider_reported_usage_available
        self.ledger.reconcile_or_verify(
            preflight.ledger_logical_call_id,
            preflight.reservation_id,
            input_tokens=failure.input_tokens if not unknown_usage else 0,
            cached_input_tokens=failure.cached_input_tokens if not unknown_usage else 0,
            output_tokens=failure.output_tokens if not unknown_usage else 0,
            status="PROVIDER_FAILURE_CONSERVATIVE" if unknown_usage else "PROVIDER_FAILURE",
            conservative_unknown=unknown_usage,
        )

    def settle_unknown(
        self, request: GatewayRequest, preflight: ReservationPreflight
    ) -> Mapping[str, Any]:
        self._validate_request_preflight(request, preflight)
        self.ledger.reconcile_or_verify(
            preflight.ledger_logical_call_id,
            preflight.reservation_id,
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            status="PROVIDER_FAILURE_CONSERVATIVE",
            conservative_unknown=True,
        )
        return self._reservation_metadata(preflight, charged_conservatively=True)

    def settle_existing_unknown(self, request: GatewayRequest) -> Mapping[str, Any]:
        """Conservatively settle a legacy reservation that predates preflight plans."""

        values = self._request_values(request)
        row = self.ledger.request_row(values["ledger_logical_call_id"])
        if not isinstance(row, Mapping):
            raise ModelPreflightFailure(
                "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                request_sha256=values["request_sha256"],
                logical_call_id=values["ledger_logical_call_id"],
                details={"reason": "provider send marker has no matching ledger reservation"},
            )
        if (
            row.get("task_arm_key") != values["task_arm_key"]
            or row.get("call_kind") != values["call_kind"]
            or row.get("input_upper_bound") != values["input_upper_bound"]
            or row.get("output_cap") != values["output_cap"]
            or not isinstance(row.get("reservation_id"), str)
        ):
            raise ModelPreflightFailure(
                "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                request_sha256=values["request_sha256"],
                logical_call_id=values["ledger_logical_call_id"],
                details={"reason": "legacy provider send/reservation identity differs"},
            )
        if row.get("status") == "RESERVED":
            self.ledger.reconcile_or_verify(
                values["ledger_logical_call_id"],
                str(row["reservation_id"]),
                input_tokens=0,
                cached_input_tokens=0,
                output_tokens=0,
                status="PROVIDER_FAILURE_CONSERVATIVE",
                conservative_unknown=True,
            )
        return {
            "reservation_id": row["reservation_id"],
            "input_upper_bound": row["input_upper_bound"],
            "output_cap": row["output_cap"],
            "charged_conservatively": (
                row.get("status") == "RESERVED"
                or "CONSERVATIVE" in str(row.get("status", ""))
            ),
        }

    def invoke_preflighted(
        self,
        request: GatewayRequest,
        preflight: Optional[ReservationPreflight],
    ) -> GatewayResponse:
        if preflight is None:
            preflight = self.preview_reservation(request)
        self.reserve_preflighted(request, preflight)
        try:
            response = self.send_reserved(request, preflight)
        except GatewayInvocationFailure as exc:
            self.reconcile_failure(preflight, exc)
            raise
        except Exception:
            self.settle_unknown(request, preflight)
            raise
        self.reconcile_success(preflight, response)
        return response

    def invoke(self, request: GatewayRequest) -> GatewayResponse:
        return self.invoke_preflighted(request, self.preview_reservation(request))


class TerminalInvocationJournal:
    """Write-ahead, hash-bound cache for paid model and official grader calls.

    Model calls use an explicit v2 request/send/terminal lifecycle.  A recorded
    request with no send marker is safe to continue; a send marker with no
    terminal outcome is never retried and is conservatively settled.  The v1
    IN_FLIGHT format remains readable for historical calls and for the separate
    grader boundary.
    """

    def __init__(self, root: Path):
        if root.is_symlink():
            raise BenchmarkExecutionError("terminal invocation journal is a symbolic link")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, kind: str, key: str) -> Path:
        return self.root / kind / (sha256_bytes(key.encode("utf-8")) + ".json")

    def begin(self, kind: str, key: str, request_hash: str) -> Path:
        path = self._path(kind, key)
        if path.exists():
            row = read_json(path)
            if row.get("key") != key or row.get("request_sha256") != request_hash:
                raise BenchmarkExecutionError("terminal journal request identity mismatch")
            return path
        write_json(path, {
            "schema": "trimem/terminal-invocation-journal/1.0",
            "kind": kind,
            "key": key,
            "request_sha256": request_hash,
            "status": "IN_FLIGHT",
        })
        return path

    def begin_model_request(
        self,
        key: str,
        request_hash: str,
        preflight: Optional[ReservationPreflight],
    ) -> Path:
        """Durably record a model request after its read-only preflight passed."""

        path = self._path("model", key)
        if path.exists():
            row = read_json(path)
            if row.get("key") != key or row.get("request_sha256") != request_hash:
                raise BenchmarkExecutionError("terminal journal request identity mismatch")
            return path
        write_json(path, {
            "schema": "trimem/terminal-invocation-journal/2.0",
            "kind": "model",
            "key": key,
            "request_sha256": request_hash,
            "status": "REQUEST_RECORDED",
            "provider_send_started": False,
            "preflight": asdict(preflight) if preflight is not None else None,
        })
        return path

    @staticmethod
    def _sealed_row(value: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(value)
        row.pop("journal_sha256", None)
        row["journal_sha256"] = sha256_bytes(canonical_bytes(row))
        return row

    @classmethod
    def _validated_grader_row(cls, path: Path) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise BenchmarkExecutionError(
                "grader lifecycle journal is not one regular file"
            )
        row = read_json(path)
        supplied = row.get("journal_sha256")
        expected = cls._sealed_row(row).get("journal_sha256")
        if (
            row.get("schema") != "trimem/grader-lifecycle-journal/1.0"
            or row.get("kind") != "grader"
            or row.get("status") not in GRADER_LIFECYCLE_STATES
            or not isinstance(row.get("key"), str)
            or not isinstance(row.get("request_sha256"), str)
            or SHA256.fullmatch(str(row.get("request_sha256"))) is None
            or not isinstance(row.get("transitions"), list)
            or not row["transitions"]
            or row["transitions"][-1] != row.get("status")
            or supplied != expected
        ):
            raise BenchmarkExecutionError("grader lifecycle journal integrity failure")
        common = [
            "GRADER_NOT_PREPARED",
            "GRADER_PREFLIGHT_PASSED",
            "GRADER_REQUEST_RECORDED",
            "GRADER_PROCESS_STARTED",
        ]
        valid_transitions = {
            tuple(common[:1]),
            tuple(common[:2]),
            tuple(common[:3]),
            tuple(common),
            (*common, "GRADER_INFRA_FAILURE_BEFORE_CONTAINER"),
            (*common, "GRADER_CONTAINER_STARTED"),
            (
                *common,
                "GRADER_CONTAINER_STARTED",
                "GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START",
            ),
            (
                *common,
                "GRADER_CONTAINER_STARTED",
                "GRADER_TERMINAL_RESULT_CAPTURED",
            ),
            (
                *common,
                "GRADER_CONTAINER_STARTED",
                "GRADER_TERMINAL_RESULT_CAPTURED",
                "GRADER_RESULT_VALIDATED",
            ),
        }
        if tuple(row["transitions"]) not in valid_transitions:
            raise BenchmarkExecutionError(
                "grader lifecycle transition history is invalid"
            )
        state = row["status"]
        request_suffix = ":" + row["request_sha256"]
        if not row["key"].endswith(request_suffix) or len(row["key"]) <= len(
            request_suffix
        ):
            raise BenchmarkExecutionError(
                "grader lifecycle task/request binding is invalid"
            )
        task_id = row["key"][: -len(request_suffix)]
        base_fields = {
            "schema",
            "kind",
            "key",
            "request_sha256",
            "status",
            "transitions",
            "official_grader_runs",
            "grader_containers",
            "grader_capacity_disposition",
            "journal_sha256",
        }
        allowed_fields = set(base_fields)
        if state != "GRADER_NOT_PREPARED":
            allowed_fields.add("loader_preflight_evidence_sha256")
        terminal_states = {
            "GRADER_INFRA_FAILURE_BEFORE_CONTAINER",
            "GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START",
            "GRADER_TERMINAL_RESULT_CAPTURED",
            "GRADER_RESULT_VALIDATED",
        }
        if state in terminal_states:
            allowed_fields.add("result")
        if state in {
            "GRADER_CONTAINER_STARTED",
            "GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START",
        }:
            allowed_fields.add("container_start_observed")
        if not base_fields <= set(row) or not set(row) <= allowed_fields:
            raise BenchmarkExecutionError(
                "grader lifecycle journal field set differs"
            )
        counters = (row.get("official_grader_runs"), row.get("grader_containers"))
        capacity = row.get("grader_capacity_disposition")
        expected_accounting = (
            (1, 1, "CONSERVATIVELY_CONSUMED")
            if state
            in {
                "GRADER_CONTAINER_STARTED",
                "GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START",
            }
            else (1, 1, "AUTHORITATIVE_RESULT")
            if state
            in {"GRADER_TERMINAL_RESULT_CAPTURED", "GRADER_RESULT_VALIDATED"}
            else (0, 0, "NOT_CONSUMED")
        )
        if (*counters, capacity) != expected_accounting:
            raise BenchmarkExecutionError(
                "grader lifecycle capacity accounting differs"
            )
        if state != "GRADER_NOT_PREPARED" and (
            not isinstance(row.get("loader_preflight_evidence_sha256"), str)
            or SHA256.fullmatch(row["loader_preflight_evidence_sha256"]) is None
        ):
            raise BenchmarkExecutionError(
                "grader lifecycle preflight evidence binding is absent"
            )
        if state in terminal_states and not isinstance(row.get("result"), Mapping):
            raise BenchmarkExecutionError("grader lifecycle terminal result is absent")
        if state in terminal_states:
            result = row["result"]
            result_fields = {
                "task_id",
                "resolved",
                "exit_code",
                "stdout",
                "stderr",
                "report",
                "grader_id",
                "container_digest",
                "official",
                "wall_time_ms",
                "container_started",
                "status",
            }
            expected_container_started = state != (
                "GRADER_INFRA_FAILURE_BEFORE_CONTAINER"
            )
            if (
                set(result) != result_fields
                or result.get("task_id") != task_id
                or type(result.get("resolved")) is not bool
                or (
                    state
                    in {
                        "GRADER_INFRA_FAILURE_BEFORE_CONTAINER",
                        "GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START",
                    }
                    and result.get("resolved") is not False
                )
                or type(result.get("exit_code")) is not int
                or not isinstance(result.get("stdout"), str)
                or not isinstance(result.get("stderr"), str)
                or not isinstance(result.get("report"), Mapping)
                or not isinstance(result.get("grader_id"), str)
                or not result["grader_id"]
                or not isinstance(result.get("container_digest"), str)
                or not result["container_digest"]
                or result.get("official") is not True
                or type(result.get("wall_time_ms")) is not int
                or result["wall_time_ms"] < 0
                or result.get("container_started") is not expected_container_started
                or not isinstance(result.get("status"), str)
                or not result["status"]
            ):
                raise BenchmarkExecutionError(
                    "grader lifecycle terminal result binding differs"
                )
        return row

    def begin_grader_request(self, key: str, request_hash: str) -> Path:
        """Create the fail-closed official-grader lifecycle before any process."""

        path = self._path("grader", key)
        if path.exists():
            row = self._validated_grader_row(path)
            if row.get("key") != key or row.get("request_sha256") != request_hash:
                raise BenchmarkExecutionError(
                    "grader lifecycle journal request identity mismatch"
                )
            return path
        write_json(
            path,
            self._sealed_row(
                {
                    "schema": "trimem/grader-lifecycle-journal/1.0",
                    "kind": "grader",
                    "key": key,
                    "request_sha256": request_hash,
                    "status": "GRADER_NOT_PREPARED",
                    "transitions": ["GRADER_NOT_PREPARED"],
                    "official_grader_runs": 0,
                    "grader_containers": 0,
                    "grader_capacity_disposition": "NOT_CONSUMED",
                }
            ),
        )
        return path

    @classmethod
    def transition_grader(
        cls,
        path: Path,
        *,
        expected: Sequence[str],
        status: str,
        values: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        if status not in GRADER_LIFECYCLE_STATES:
            raise BenchmarkExecutionError("unknown grader lifecycle transition")
        current = cls._validated_grader_row(path)
        additions = dict(values or {})
        if current.get("status") == status:
            if any(current.get(name) != value for name, value in additions.items()):
                raise BenchmarkExecutionError(
                    "grader lifecycle idempotent evidence differs"
                )
            return current
        if current.get("status") not in set(expected):
            raise BenchmarkExecutionError("grader lifecycle transition is invalid")
        transitions = [*current["transitions"], status]
        updated = cls._sealed_row(
            {**current, **additions, "status": status, "transitions": transitions}
        )
        write_json(path, updated)
        return updated

    @staticmethod
    def transition_model(
        path: Path,
        *,
        expected: Sequence[str],
        status: str,
        values: Optional[Mapping[str, Any]] = None,
    ) -> None:
        current = read_json(path)
        if current.get("schema") != "trimem/terminal-invocation-journal/2.0":
            raise BenchmarkExecutionError("model journal schema is not lifecycle v2")
        if current.get("status") not in set(expected):
            raise BenchmarkExecutionError("model journal lifecycle transition is invalid")
        write_json(path, {**current, **dict(values or {}), "status": status})

    @staticmethod
    def upgrade_legacy_model_request(
        path: Path,
        *,
        preflight: Optional[ReservationPreflight],
    ) -> None:
        current = read_json(path)
        if (
            current.get("schema") != "trimem/terminal-invocation-journal/1.0"
            or current.get("kind") != "model"
            or current.get("status") != "IN_FLIGHT"
        ):
            raise BenchmarkExecutionError("legacy model journal cannot be upgraded")
        write_json(path, {
            "schema": "trimem/terminal-invocation-journal/2.0",
            "kind": "model",
            "key": current["key"],
            "request_sha256": current["request_sha256"],
            "status": "REQUEST_RECORDED",
            "provider_send_started": False,
            "preflight": asdict(preflight) if preflight is not None else None,
            "legacy_schema": current["schema"],
            "legacy_delegate_started": bool(current.get("delegate_started")),
        })

    @staticmethod
    def load(path: Path) -> dict[str, Any]:
        return read_json(path)

    @staticmethod
    def finish(path: Path, value: Mapping[str, Any]) -> None:
        current = read_json(path)
        if current.get("status") != "IN_FLIGHT":
            raise BenchmarkExecutionError("terminal journal entry is already finalized")
        write_json(path, {**current, **dict(value)})


class JournaledModelGateway:
    def __init__(self, delegate: Any, journal: TerminalInvocationJournal):
        self.delegate = delegate
        self.journal = journal

    @staticmethod
    def _failure_dict(exc: GatewayInvocationFailure) -> dict[str, Any]:
        return {
            "provider": exc.provider, "model": exc.model, "status": exc.status,
            "attempt": exc.attempt, "input_tokens": exc.input_tokens,
            "output_tokens": exc.output_tokens,
            "cached_input_tokens": exc.cached_input_tokens,
            "reasoning_tokens": exc.reasoning_tokens,
            "wall_time_ms": exc.wall_time_ms, "response_text": exc.response_text,
            "provider_request_id": exc.provider_request_id,
            "response_id": exc.response_id,
            "response_status": exc.response_status,
            "response_error_code": exc.response_error_code,
            "incomplete_reason": exc.incomplete_reason,
            "output_item_types": list(exc.output_item_types),
            "content_item_types": list(exc.content_item_types),
            "refusal_present": exc.refusal_present,
            "provider_reported_usage_available": exc.provider_reported_usage_available,
            "raw_envelope_reference": exc.raw_envelope_reference,
            "extracted_text_bytes": exc.extracted_text_bytes,
            "structured_output_bytes": exc.structured_output_bytes,
            "original_provider_terminal_classification": (
                exc.original_provider_terminal_classification
            ),
            "provider_response_envelope": exc.provider_response_envelope,
            "ledger_reservation": exc.ledger_reservation,
        }

    def _path_and_row(
        self, request: GatewayRequest
    ) -> tuple[Path, Optional[dict[str, Any]]]:
        request_hash = gateway_request_sha256(request)
        path = self.journal._path("model", request.logical_call_id)
        if not path.exists():
            return path, None
        row = self.journal.load(path)
        if (
            row.get("key") != request.logical_call_id
            or row.get("request_sha256") != request_hash
        ):
            raise BenchmarkExecutionError("terminal journal request identity mismatch")
        return path, row

    @staticmethod
    def _stored_preflight(row: Mapping[str, Any]) -> Optional[ReservationPreflight]:
        value = row.get("preflight")
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise BenchmarkExecutionError("model journal preflight is malformed")
        try:
            return ReservationPreflight(**dict(value))
        except (TypeError, ValueError) as exc:
            raise BenchmarkExecutionError("model journal preflight is malformed") from exc

    def _ledger_row(self, request: GatewayRequest) -> tuple[bool, Optional[dict[str, Any]]]:
        getter = getattr(self.delegate, "request_row", None)
        if not callable(getter):
            return False, None
        return True, getter(request)

    def request_lifecycle(self, request: GatewayRequest) -> Mapping[str, Any]:
        """Return one explicit, hash-bound lifecycle state without mutation."""

        _, row = self._path_and_row(request)
        has_ledger, ledger_row = self._ledger_row(request)
        if row is None:
            state = "NOT_PREPARED"
            send_started = False
        elif row.get("schema") == "trimem/terminal-invocation-journal/2.0":
            state = str(row.get("status"))
            if state not in {
                "REQUEST_RECORDED",
                "PROVIDER_SEND_STARTED",
                "PROVIDER_TERMINAL_SUCCESS",
                "PROVIDER_TERMINAL_FAILURE",
                "PROVIDER_OUTCOME_UNKNOWN",
            }:
                raise BenchmarkExecutionError("unknown model journal lifecycle state")
            send_started = bool(row.get("provider_send_started"))
            if send_started != (state in {
                "PROVIDER_SEND_STARTED",
                "PROVIDER_TERMINAL_SUCCESS",
                "PROVIDER_TERMINAL_FAILURE",
                "PROVIDER_OUTCOME_UNKNOWN",
            }):
                raise BenchmarkExecutionError("model journal send-state marker differs")
        elif row.get("schema") == "trimem/terminal-invocation-journal/1.0":
            legacy = str(row.get("status"))
            if legacy == "SUCCESS":
                state, send_started = "PROVIDER_TERMINAL_SUCCESS", True
            elif legacy == "FAILURE":
                state, send_started = "PROVIDER_TERMINAL_FAILURE", True
            elif legacy == "IN_FLIGHT" and row.get("delegate_started") is not True:
                state, send_started = "REQUEST_RECORDED", False
            elif legacy == "IN_FLIGHT" and has_ledger and ledger_row is None:
                # In v1, delegate_started was persisted before atomic reserve.
                # Absence from that exact ledger therefore proves no send.
                state, send_started = "REQUEST_RECORDED", False
            elif legacy == "IN_FLIGHT":
                state, send_started = "PROVIDER_SEND_STARTED", True
            else:
                raise BenchmarkExecutionError("unknown legacy model journal state")
        else:
            raise BenchmarkExecutionError("unknown model journal schema")
        return {
            "state": state,
            "request_sha256": gateway_request_sha256(request),
            "journal_present": row is not None,
            "ledger_reservation_present": ledger_row is not None,
            "provider_send_started": send_started,
        }

    def preview_reservation(
        self, request: GatewayRequest
    ) -> Optional[ReservationPreflight]:
        lifecycle = self.request_lifecycle(request)
        _, row = self._path_and_row(request)
        if lifecycle["state"] in {
            "PROVIDER_SEND_STARTED",
            "PROVIDER_OUTCOME_UNKNOWN",
        }:
            raise self.settle_unknown(request)
        if lifecycle["state"] in {
            "PROVIDER_TERMINAL_SUCCESS",
            "PROVIDER_TERMINAL_FAILURE",
        }:
            raise BenchmarkExecutionError("terminal model request cannot be preflighted")
        if row is not None:
            stored = self._stored_preflight(row)
            if stored is not None:
                validator = getattr(self.delegate, "_validate_request_preflight", None)
                if callable(validator):
                    validator(request, stored)
                return stored
        preview = getattr(self.delegate, "preview_reservation", None)
        return preview(request) if callable(preview) else None

    def _reconcile_replayed_success(
        self, row: Mapping[str, Any], response: GatewayResponse
    ) -> None:
        preflight = self._stored_preflight(row)
        reconcile = getattr(self.delegate, "reconcile_success", None)
        if preflight is not None and callable(reconcile):
            reconcile(preflight, response)

    def _reconcile_replayed_failure(
        self, row: Mapping[str, Any], failure: GatewayInvocationFailure
    ) -> None:
        preflight = self._stored_preflight(row)
        reconcile = getattr(self.delegate, "reconcile_failure", None)
        if preflight is not None and callable(reconcile):
            reconcile(preflight, failure)

    def replay_terminal(self, request: GatewayRequest) -> Optional[GatewayResponse]:
        _, row = self._path_and_row(request)
        if row is None:
            return None
        lifecycle = self.request_lifecycle(request)
        state = lifecycle["state"]
        if state == "PROVIDER_TERMINAL_SUCCESS":
            response = GatewayResponse(**row["response"])
            self._reconcile_replayed_success(row, response)
            return replace(response, terminal_outcome_replayed=True)
        if state == "PROVIDER_TERMINAL_FAILURE":
            failure = GatewayInvocationFailure(**row["failure"])
            self._reconcile_replayed_failure(row, failure)
            failure.terminal_outcome_replayed = True
            raise failure
        if state in {"PROVIDER_SEND_STARTED", "PROVIDER_OUTCOME_UNKNOWN"}:
            raise self.settle_unknown(request)
        if state == "REQUEST_RECORDED":
            return None
        raise BenchmarkExecutionError("unknown model journal state")

    def settle_unknown(self, request: GatewayRequest) -> GatewayInvocationFailure:
        path, row = self._path_and_row(request)
        if row is None:
            raise BenchmarkExecutionError("cannot settle an absent model journal")
        lifecycle = self.request_lifecycle(request)
        if lifecycle["state"] not in {
            "PROVIDER_SEND_STARTED", "PROVIDER_OUTCOME_UNKNOWN"
        }:
            raise BenchmarkExecutionError("model request is not in an unknown outcome state")
        if row.get("schema") == "trimem/terminal-invocation-journal/2.0":
            if row.get("status") == "PROVIDER_SEND_STARTED":
                self.journal.transition_model(
                    path,
                    expected=("PROVIDER_SEND_STARTED",),
                    status="PROVIDER_OUTCOME_UNKNOWN",
                    values={"provider_send_started": True},
                )
                row = self.journal.load(path)
        else:
            write_json(path, {
                "schema": "trimem/terminal-invocation-journal/2.0",
                "kind": "model",
                "key": row["key"],
                "request_sha256": row["request_sha256"],
                "status": "PROVIDER_OUTCOME_UNKNOWN",
                "provider_send_started": True,
                "preflight": None,
                "legacy_schema": row["schema"],
                "legacy_delegate_started": bool(row.get("delegate_started")),
            })
            row = self.journal.load(path)
        preflight = self._stored_preflight(row)
        if preflight is not None and callable(getattr(self.delegate, "settle_unknown", None)):
            ledger_reservation = self.delegate.settle_unknown(request, preflight)
        elif callable(getattr(self.delegate, "settle_existing_unknown", None)):
            ledger_reservation = self.delegate.settle_existing_unknown(request)
        elif lifecycle["ledger_reservation_present"]:
            raise BenchmarkExecutionError("unknown model reservation cannot be settled")
        else:
            ledger_reservation = None
        model = getattr(getattr(self.delegate, "delegate", None), "expected_model", "unknown")
        return GatewayInvocationFailure(
            provider="openai-responses",
            model=str(model),
            status="MODEL_REQUEST_TERMINAL_OUTCOME_UNKNOWN",
            attempt=1,
            input_tokens=None,
            output_tokens=None,
            cached_input_tokens=None,
            reasoning_tokens=None,
            provider_reported_usage_available=False,
            original_provider_terminal_classification=(
                "MODEL_REQUEST_TERMINAL_OUTCOME_UNKNOWN"
            ),
            ledger_reservation=ledger_reservation,
            terminal_outcome_replayed=True,
        )

    def invoke_preflighted(
        self,
        request: GatewayRequest,
        preflight: Optional[ReservationPreflight],
    ) -> GatewayResponse:
        replayed = self.replay_terminal(request)
        if replayed is not None:
            return replayed
        request_hash = gateway_request_sha256(request)
        path, row = self._path_and_row(request)
        if row is None:
            path = self.journal.begin_model_request(
                request.logical_call_id, request_hash, preflight
            )
            row = self.journal.load(path)
        elif row.get("schema") == "trimem/terminal-invocation-journal/1.0":
            lifecycle = self.request_lifecycle(request)
            if lifecycle["state"] != "REQUEST_RECORDED":
                raise self.settle_unknown(request)
            self.journal.upgrade_legacy_model_request(path, preflight=preflight)
            row = self.journal.load(path)
        if row.get("status") != "REQUEST_RECORDED":
            raise BenchmarkExecutionError("model request is not safe to send")
        stored_preflight = self._stored_preflight(row)
        if stored_preflight is not None:
            if preflight is not None and stored_preflight != preflight:
                raise ModelPreflightFailure(
                    "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                    request_sha256=request_hash,
                    logical_call_id=request.logical_call_id,
                    details={"reason": "journal and caller preflight plans differ"},
                )
            preflight = stored_preflight
        reserve = getattr(self.delegate, "reserve_preflighted", None)
        if callable(reserve):
            if preflight is None:
                raise ModelPreflightFailure(
                    "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
                    request_sha256=request_hash,
                    logical_call_id=request.logical_call_id,
                    details={"reason": "paid model request has no preflight plan"},
                )
            reserve(request, preflight)
        self.journal.transition_model(
            path,
            expected=("REQUEST_RECORDED",),
            status="PROVIDER_SEND_STARTED",
            values={
                "provider_send_started": True,
                "ledger_reservation": (
                    BudgetedModelGateway._reservation_metadata(
                        preflight, charged_conservatively=False
                    )
                    if preflight is not None else None
                ),
            },
        )
        try:
            send = getattr(self.delegate, "send_reserved", None)
            response = (
                send(request, preflight)
                if callable(send) and preflight is not None
                else self.delegate.invoke(request)
            )
        except GatewayInvocationFailure as exc:
            self.journal.transition_model(
                path,
                expected=("PROVIDER_SEND_STARTED",),
                status="PROVIDER_TERMINAL_FAILURE",
                values={
                    "provider_send_started": True,
                    "failure": self._failure_dict(exc),
                },
            )
            reconcile = getattr(self.delegate, "reconcile_failure", None)
            if preflight is not None and callable(reconcile):
                reconcile(preflight, exc)
            raise
        except BenchmarkExecutionError:
            self.journal.transition_model(
                path,
                expected=("PROVIDER_SEND_STARTED",),
                status="PROVIDER_OUTCOME_UNKNOWN",
                values={"provider_send_started": True},
            )
            # Settle conservatively, but retain the global local-integrity
            # classification (for example, an impossible unpaid response).
            self.settle_unknown(request)
            raise
        except Exception:
            self.journal.transition_model(
                path,
                expected=("PROVIDER_SEND_STARTED",),
                status="PROVIDER_OUTCOME_UNKNOWN",
                values={"provider_send_started": True},
            )
            raise self.settle_unknown(request) from None
        self.journal.transition_model(
            path,
            expected=("PROVIDER_SEND_STARTED",),
            status="PROVIDER_TERMINAL_SUCCESS",
            values={
                "provider_send_started": True,
                "response": asdict(response),
            },
        )
        reconcile = getattr(self.delegate, "reconcile_success", None)
        if preflight is not None and callable(reconcile):
            reconcile(preflight, response)
        return response

    def invoke(self, request: GatewayRequest) -> GatewayResponse:
        return self.invoke_preflighted(request, self.preview_reservation(request))


class CellCommitJournal:
    """Hash-bound local transaction record for result/ledger/cursor finalization."""

    SCHEMA = "trimem/cell-commit-journal/1.0"
    BASE_FIELDS = frozenset(
        {
            "schema",
            "status",
            "binding",
            "binding_sha256",
            "result_record",
            "session_result",
            "transitions",
            "journal_sha256",
        }
    )
    CHECKPOINT_FIELDS = frozenset({"stream_checkpoint_sha256"})
    BINDING_FIELDS = frozenset(
        {
            "stream_id",
            "arm",
            "target_id",
            "expected_cursor",
            "task_arm_key",
            "task_arm_reservation_id",
            "result_sha256",
            "accounting_projection_sha256",
            "grader_result_sha256",
            "session_result_sha256",
            "next_cursor",
        }
    )

    def __init__(self, path: Path, binding: Mapping[str, Any]):
        if path.is_symlink():
            raise BenchmarkExecutionError("cell-commit journal path is a symbolic link")
        self.path = path.resolve()
        self.binding = dict(binding)
        self._validate_binding(self.binding)
        self.binding_sha256 = sha256_bytes(canonical_bytes(self.binding))

    @classmethod
    def _validate_binding(cls, value: Mapping[str, Any]) -> None:
        if set(value) != cls.BINDING_FIELDS:
            raise BenchmarkExecutionError("cell-commit binding field set differs")
        if any(
            not isinstance(value.get(name), str) or not value[name]
            for name in ("stream_id", "arm", "target_id", "task_arm_key")
        ):
            raise BenchmarkExecutionError("cell-commit identity is malformed")
        if any(
            not isinstance(value.get(name), str)
            or SHA256.fullmatch(str(value[name])) is None
            for name in (
                "task_arm_reservation_id",
                "result_sha256",
                "accounting_projection_sha256",
                "grader_result_sha256",
                "session_result_sha256",
            )
        ):
            raise BenchmarkExecutionError("cell-commit digest is malformed")
        cursor = value.get("expected_cursor")
        if (
            type(cursor) is not int
            or cursor < 0
            or value.get("next_cursor") != cursor + 1
        ):
            raise BenchmarkExecutionError("cell-commit cursor binding is malformed")

    @staticmethod
    def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(value)
        row.pop("journal_sha256", None)
        row["journal_sha256"] = sha256_bytes(canonical_bytes(row))
        return row

    @classmethod
    def read_verified(cls, path: Path) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise BenchmarkExecutionError(
                "cell-commit journal is not one regular file"
            )
        row = read_json(path)
        supplied = row.get("journal_sha256")
        expected = cls._sealed(row).get("journal_sha256")
        status = row.get("status")
        expected_transitions = (
            list(CELL_COMMIT_STATES[: CELL_COMMIT_STATES.index(status) + 1])
            if status in CELL_COMMIT_STATES
            else None
        )
        expected_fields = cls.BASE_FIELDS | (
            cls.CHECKPOINT_FIELDS
            if status in {"CURSOR_ADVANCED", "COMMITTED"}
            else frozenset()
        )
        if (
            row.get("schema") != cls.SCHEMA
            or status not in CELL_COMMIT_STATES
            or set(row) != expected_fields
            or not isinstance(row.get("binding"), Mapping)
            or not isinstance(row.get("binding_sha256"), str)
            or not isinstance(row.get("result_record"), Mapping)
            or not isinstance(row.get("session_result"), Mapping)
            or not isinstance(row.get("transitions"), list)
            or row["transitions"] != expected_transitions
            or supplied != expected
        ):
            raise BenchmarkExecutionError("cell-commit journal integrity failure")
        cls._validate_binding(row["binding"])
        if row["binding_sha256"] != sha256_bytes(
            canonical_bytes(row["binding"])
        ):
            raise BenchmarkExecutionError("cell-commit binding hash mismatch")
        if status in {"CURSOR_ADVANCED", "COMMITTED"} and (
            not isinstance(row.get("stream_checkpoint_sha256"), str)
            or SHA256.fullmatch(row["stream_checkpoint_sha256"]) is None
        ):
            raise BenchmarkExecutionError(
                "cell-commit stream checkpoint hash is malformed"
            )
        if (
            sha256_bytes(json_file_bytes(row["result_record"]))
            != row["binding"]["result_sha256"]
            or sha256_bytes(canonical_bytes(row["session_result"]))
            != row["binding"]["session_result_sha256"]
        ):
            raise BenchmarkExecutionError("cell-commit durable payload hash mismatch")
        session_grade = row["session_result"].get("grade")
        if (
            not isinstance(session_grade, Mapping)
            or sha256_bytes(canonical_bytes(session_grade))
            != row["binding"]["grader_result_sha256"]
        ):
            raise BenchmarkExecutionError(
                "cell-commit durable grader payload hash mismatch"
            )
        return row

    def prepare(
        self,
        *,
        result_record: Optional[Mapping[str, Any]] = None,
        session_result: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        if self.path.exists():
            row = self.read_verified(self.path)
            if (
                row.get("binding") != self.binding
                or row.get("binding_sha256") != self.binding_sha256
                or (
                    result_record is not None
                    and canonical_bytes(row["result_record"])
                    != canonical_bytes(result_record)
                )
                or (
                    session_result is not None
                    and canonical_bytes(row["session_result"])
                    != canonical_bytes(session_result)
                )
            ):
                raise BenchmarkExecutionError("cell-commit resume binding differs")
            return row
        if not isinstance(result_record, Mapping) or not isinstance(
            session_result, Mapping
        ):
            raise BenchmarkExecutionError(
                "new cell-commit journal requires both durable payloads"
            )
        row = self._sealed(
            {
                "schema": self.SCHEMA,
                "status": "PREPARED",
                "binding": self.binding,
                "binding_sha256": self.binding_sha256,
                "result_record": dict(result_record),
                "session_result": dict(session_result),
                "transitions": ["PREPARED"],
            }
        )
        write_json(self.path, row)
        return row

    def state(self) -> str:
        row = self.prepare()
        return str(row["status"])

    def transition(
        self,
        *,
        expected: Sequence[str],
        status: str,
        values: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        if status not in CELL_COMMIT_STATES:
            raise BenchmarkExecutionError("unknown cell-commit state")
        row = self.prepare()
        additions = dict(values or {})
        if status == "CURSOR_ADVANCED":
            checkpoint_sha256 = additions.get("stream_checkpoint_sha256")
            if (
                set(additions) != self.CHECKPOINT_FIELDS
                or not isinstance(checkpoint_sha256, str)
                or SHA256.fullmatch(checkpoint_sha256) is None
            ):
                raise BenchmarkExecutionError(
                    "cursor-advanced transition requires one checkpoint hash"
                )
        elif additions:
            raise BenchmarkExecutionError(
                "cell-commit transition contains unexpected evidence"
            )
        if row.get("status") == status:
            if any(row.get(name) != value for name, value in additions.items()):
                raise BenchmarkExecutionError(
                    "cell-commit idempotent transition evidence differs"
                )
            return row
        if row.get("status") not in set(expected):
            raise BenchmarkExecutionError("cell-commit transition order differs")
        updated = self._sealed(
            {
                **row,
                **additions,
                "status": status,
                "transitions": [*row["transitions"], status],
            }
        )
        write_json(self.path, updated)
        return updated

    def verify_result(
        self,
        result_path: Path,
        *,
        grader_result: GradeResult | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.prepare()
        if (
            result_path.is_symlink()
            or not result_path.is_file()
            or sha256_bytes(result_path.read_bytes())
            != row["binding"]["result_sha256"]
        ):
            raise BenchmarkExecutionError("cell-commit canonical result hash differs")
        result = read_json(result_path)
        try:
            validate_scientific_terminal_result(result)
        except ScientificTerminalContractError as exc:
            raise BenchmarkExecutionError(
                f"cell-commit scientific result is invalid: {exc}"
            ) from None
        if scientific_task_arm_key(result) != row["binding"]["task_arm_key"]:
            raise BenchmarkExecutionError("cell-commit result task-arm differs")
        if result.get("target_id") != row["binding"]["target_id"]:
            raise BenchmarkExecutionError("cell-commit result target differs")
        accounting = result.get("actual_accounting")
        if (
            not isinstance(accounting, Mapping)
            or sha256_bytes(canonical_bytes(accounting))
            != row["binding"]["accounting_projection_sha256"]
        ):
            raise BenchmarkExecutionError(
                "cell-commit accounting projection hash differs"
            )
        if grader_result is not None:
            grader_payload = (
                asdict(grader_result)
                if isinstance(grader_result, GradeResult)
                else dict(grader_result)
            )
            if (
                sha256_bytes(canonical_bytes(grader_payload))
                != row["binding"]["grader_result_sha256"]
            ):
                raise BenchmarkExecutionError("cell-commit grader-result hash differs")
        return result


DEVELOPMENT_FINALIZATION_BINDING_SCHEMA = (
    "trimem/development-finalized-stream-binding/1.0"
)


def _development_finalization_binding_path(root: Path, stream_id: str) -> Path:
    return root / f"{stream_id}.development-finalization-binding.json"


def _development_pre_finalization_checkpoint_path(
    root: Path, stream_id: str
) -> Path:
    return root / f"{stream_id}.pre-development-finalization-checkpoint.json"


def _sealed_development_finalization_binding(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    row = dict(value)
    row.pop("binding_sha256", None)
    row["binding_sha256"] = sha256_bytes(canonical_bytes(row))
    return row


def _validated_checkpoint_envelope(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if set(value) != {"payload", "digest"} or not isinstance(
        value.get("payload"), Mapping
    ):
        raise BenchmarkExecutionError("stream checkpoint envelope is malformed")
    payload = value["payload"]
    payload_sha256 = sha256_bytes(canonical_bytes(payload))
    if value.get("digest") not in {payload_sha256, "sha256:" + payload_sha256}:
        raise BenchmarkExecutionError("stream checkpoint envelope digest differs")
    return payload


def _expected_finalized_m2_policy_checkpoint(
    prior_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Deterministically replay M2's no-reuse credit from its task frontier."""

    from enterprise_memory.trimem.policy import (
        DoubleDQNConfig,
        DoubleDQNMemoryPolicy,
        MemoryState,
    )

    try:
        lifecycle_state = prior_payload.get("lifecycle_state")
        if (
            prior_payload.get("arm_id") != "M2"
            or prior_payload.get("split") != "development"
            or not isinstance(lifecycle_state, Mapping)
            or set(lifecycle_state) != {"persistence", "lifecycle"}
        ):
            raise ValueError("M2 task-stream lifecycle state is malformed")
        lifecycle_checkpoint = lifecycle_state.get("lifecycle")
        if (
            not isinstance(lifecycle_checkpoint, Mapping)
            or set(lifecycle_checkpoint) != {"payload", "digest"}
            or not isinstance(lifecycle_checkpoint.get("payload"), Mapping)
            or lifecycle_checkpoint.get("digest")
            != "sha256:"
            + sha256_bytes(canonical_bytes(lifecycle_checkpoint["payload"]))
        ):
            raise ValueError("M2 lifecycle checkpoint integrity differs")
        lifecycle_payload = lifecycle_checkpoint["payload"]
        policy_state = lifecycle_payload.get("policy")
        pending_by_memory_id = lifecycle_payload.get("pending_by_memory_id")
        reward_config = lifecycle_payload.get("reward_config")
        if (
            lifecycle_payload.get("schema")
            != "trimem/postgres-dqn-lifecycle/1.0"
            or lifecycle_payload.get("split") != "development"
            or lifecycle_payload.get("evaluation") is not False
            or not isinstance(policy_state, Mapping)
            or not isinstance(policy_state.get("payload"), Mapping)
            or not isinstance(pending_by_memory_id, Mapping)
            or not isinstance(reward_config, Mapping)
        ):
            raise ValueError("M2 lifecycle finalization inputs are malformed")
        policy_payload = policy_state["payload"]
        config_value = policy_payload.get("config")
        runtime_pending = policy_payload.get("pending")
        coefficient = reward_config.get("context_cost_coefficient")
        if (
            not isinstance(config_value, Mapping)
            or not isinstance(runtime_pending, Mapping)
            or isinstance(coefficient, bool)
            or not isinstance(coefficient, (int, float))
        ):
            raise ValueError("M2 policy finalization inputs are malformed")
        policy = DoubleDQNMemoryPolicy(DoubleDQNConfig.from_dict(config_value))
        policy.restore_runtime_state(policy_state)
        credit_ids: list[str] = []
        for pending_key in sorted(pending_by_memory_id):
            if not isinstance(pending_key, str):
                raise ValueError("M2 pending-memory identity is malformed")
            pending = pending_by_memory_id[pending_key]
            if not isinstance(pending, Mapping):
                raise ValueError("M2 pending-memory row is malformed")
            credit_id = pending.get("credit_id")
            state_value = pending.get("state")
            context_cost = pending.get("context_cost")
            if (
                not isinstance(credit_id, str)
                or not credit_id
                or not isinstance(state_value, Mapping)
                or isinstance(context_cost, bool)
                or not isinstance(context_cost, (int, float))
            ):
                raise ValueError("M2 pending-credit row is malformed")
            credit_ids.append(credit_id)
            state = MemoryState(**dict(state_value))
            policy.credit_delayed_reward(
                credit_id,
                float(coefficient) * float(context_cost),
                state,
                done=True,
                split="development",
                train_updates=1,
            )
        if (
            len(credit_ids) != len(set(credit_ids))
            or set(credit_ids) != set(runtime_pending)
            or policy.pending_credit_count != 0
        ):
            raise ValueError("M2 pending-credit ledgers differ")
        return asdict(policy.freeze_checkpoint())
    except BenchmarkExecutionError:
        raise
    except Exception as exc:
        raise BenchmarkExecutionError(
            "development final policy cannot be derived from its task frontier"
        ) from exc


def _load_development_pre_finalization_checkpoint(
    root: Path,
    stream_id: str,
    *,
    last_cell: Mapping[str, Any],
) -> dict[str, Any]:
    """Load the exact pre-finalization bytes anchored by the last cell."""

    path = _secure_retained_path(
        root,
        _development_pre_finalization_checkpoint_path(root, stream_id),
        directory=False,
    )
    raw = path.read_bytes()
    expected_sha256 = last_cell.get("stream_checkpoint_sha256")
    try:
        value = strict_json_loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise BenchmarkExecutionError(
            "development pre-finalization checkpoint is malformed"
        ) from exc
    if (
        not isinstance(value, dict)
        or raw != canonical_bytes(value)
        or not isinstance(expected_sha256, str)
        or sha256_bytes(raw) != expected_sha256
    ):
        raise BenchmarkExecutionError(
            "development pre-finalization checkpoint differs from predecessor cell"
        )
    _validated_checkpoint_envelope(value)
    return value


def _retain_development_pre_finalization_checkpoint(
    root: Path,
    stream_id: str,
    *,
    last_cell: Mapping[str, Any],
) -> dict[str, Any]:
    """Atomically retain the live TASK_STREAM checkpoint before replacement."""

    live_path, _sidecar_path = _arm_checkpoint_paths(root, stream_id)
    live_path = _secure_retained_path(root, live_path, directory=False)
    raw = live_path.read_bytes()
    retained_path = _development_pre_finalization_checkpoint_path(
        root, stream_id
    )
    if retained_path.exists() or retained_path.is_symlink():
        retained = _secure_retained_path(
            root, retained_path, directory=False
        )
        if retained.read_bytes() != raw:
            raise BenchmarkExecutionError(
                "development pre-finalization checkpoint changed during recovery"
            )
    else:
        atomic_write(retained_path, raw)
    return _load_development_pre_finalization_checkpoint(
        root,
        stream_id,
        last_cell=last_cell,
    )


def save_development_finalized_arm_checkpoint(
    root: Path,
    stream_id: str,
    checkpoint: Mapping[str, Any],
    *,
    last_cell_journal_path: Path,
) -> dict[str, Any]:
    """Hash-chain an M2 final envelope to its last committed task checkpoint."""

    last_cell = CellCommitJournal.read_verified(last_cell_journal_path)
    last_binding = last_cell["binding"]
    if (
        last_cell.get("status") != "COMMITTED"
        or last_binding.get("stream_id") != stream_id
        or last_binding.get("arm") != "M2"
    ):
        raise BenchmarkExecutionError(
            "development finalization predecessor cell differs"
        )
    prior_checkpoint = load_arm_checkpoint(root, stream_id)
    prior_payload = _validated_checkpoint_envelope(prior_checkpoint)
    if prior_payload.get("stream_state") == "DEVELOPMENT_FINALIZED":
        if canonical_bytes(prior_checkpoint) != canonical_bytes(checkpoint):
            raise BenchmarkExecutionError(
                "development finalized checkpoint changed during recovery"
            )
        return load_development_finalization_binding(
            root,
            stream_id,
            last_cell_journal_path=last_cell_journal_path,
        )
    _verified_cell_stream_checkpoint(root, stream_id, last_cell)
    retained_prior_checkpoint = _retain_development_pre_finalization_checkpoint(
        root,
        stream_id,
        last_cell=last_cell,
    )
    if canonical_bytes(retained_prior_checkpoint) != canonical_bytes(
        prior_checkpoint
    ):
        raise BenchmarkExecutionError(
            "development retained task-stream checkpoint differs"
        )
    final_payload = _validated_checkpoint_envelope(checkpoint)
    task_cursor = last_binding["next_cursor"]
    static_fields = (
        "schema",
        "namespace",
        "experiment_id",
        "split",
        "arm_id",
        "task_order_hash",
        "config_hash",
        "run_nonce",
    )
    if (
        prior_payload.get("stream_state") != "TASK_STREAM"
        or prior_payload.get("task_cursor") != task_cursor
        or prior_payload.get("next_sequence_index") != task_cursor
        or final_payload.get("stream_state") != "DEVELOPMENT_FINALIZED"
        or final_payload.get("task_cursor") != task_cursor
        or final_payload.get("next_sequence_index") != task_cursor + 1
        or final_payload.get("arm_id") != "M2"
        or not isinstance(final_payload.get("final_policy_checkpoint"), Mapping)
        or any(
            final_payload.get(name) != prior_payload.get(name)
            for name in static_fields
        )
        or final_payload.get("completed_task_digests")
        != prior_payload.get("completed_task_digests")
    ):
        raise BenchmarkExecutionError(
            "development finalization checkpoint continuity differs"
        )
    expected_final_policy = _expected_finalized_m2_policy_checkpoint(
        prior_payload
    )
    if canonical_bytes(final_payload["final_policy_checkpoint"]) != (
        canonical_bytes(expected_final_policy)
    ):
        raise BenchmarkExecutionError(
            "development final policy differs from deterministic task frontier"
        )
    final_checkpoint_sha256 = sha256_bytes(canonical_bytes(checkpoint))
    row = _sealed_development_finalization_binding(
        {
            "schema": DEVELOPMENT_FINALIZATION_BINDING_SCHEMA,
            "stream_id": stream_id,
            "task_cursor": task_cursor,
            "last_cell_commit_journal_sha256": last_cell["journal_sha256"],
            "prior_stream_checkpoint_sha256": last_cell[
                "stream_checkpoint_sha256"
            ],
            "finalized_stream_checkpoint_sha256": final_checkpoint_sha256,
            "static_identity_sha256": sha256_bytes(
                canonical_bytes(
                    {name: final_payload.get(name) for name in static_fields}
                )
            ),
            "completed_task_digests_sha256": sha256_bytes(
                canonical_bytes(final_payload.get("completed_task_digests"))
            ),
        }
    )
    # Seal the predecessor bridge before replacing the local task-stream
    # checkpoint.  Either half of an interrupted pair fails closed.
    binding_path = _development_finalization_binding_path(root, stream_id)
    if binding_path.exists() or binding_path.is_symlink():
        secured_binding_path = _secure_retained_path(
            root, binding_path, directory=False
        )
        if read_json(secured_binding_path) != row:
            raise BenchmarkExecutionError(
                "development finalization binding changed during recovery"
            )
    else:
        write_json(binding_path, row)
    save_arm_checkpoint(root, stream_id, checkpoint)
    return load_development_finalization_binding(
        root,
        stream_id,
        last_cell_journal_path=last_cell_journal_path,
    )


def load_development_finalization_binding(
    root: Path,
    stream_id: str,
    *,
    last_cell_journal_path: Path,
) -> dict[str, Any]:
    """Verify the local final envelope/predecessor cell hash chain."""

    path = _secure_retained_path(
        root,
        _development_finalization_binding_path(root, stream_id),
        directory=False,
    )
    row = read_json(path)
    expected_fields = {
        "schema",
        "stream_id",
        "task_cursor",
        "last_cell_commit_journal_sha256",
        "prior_stream_checkpoint_sha256",
        "finalized_stream_checkpoint_sha256",
        "static_identity_sha256",
        "completed_task_digests_sha256",
        "binding_sha256",
    }
    supplied = row.get("binding_sha256")
    if (
        set(row) != expected_fields
        or row.get("schema") != DEVELOPMENT_FINALIZATION_BINDING_SCHEMA
        or row.get("stream_id") != stream_id
        or supplied
        != _sealed_development_finalization_binding(row)["binding_sha256"]
        or any(
            not isinstance(row.get(name), str)
            or SHA256.fullmatch(row[name]) is None
            for name in (
                "last_cell_commit_journal_sha256",
                "prior_stream_checkpoint_sha256",
                "finalized_stream_checkpoint_sha256",
                "static_identity_sha256",
                "completed_task_digests_sha256",
            )
        )
    ):
        raise BenchmarkExecutionError(
            "development finalization binding integrity failure"
        )
    last_cell = CellCommitJournal.read_verified(last_cell_journal_path)
    last_binding = last_cell["binding"]
    checkpoint = load_arm_checkpoint(root, stream_id)
    payload = _validated_checkpoint_envelope(checkpoint)
    retained_prior_checkpoint = _load_development_pre_finalization_checkpoint(
        root,
        stream_id,
        last_cell=last_cell,
    )
    retained_prior_payload = _validated_checkpoint_envelope(
        retained_prior_checkpoint
    )
    static_fields = (
        "schema",
        "namespace",
        "experiment_id",
        "split",
        "arm_id",
        "task_order_hash",
        "config_hash",
        "run_nonce",
    )
    if (
        last_cell.get("status") != "COMMITTED"
        or last_binding.get("stream_id") != stream_id
        or last_binding.get("arm") != "M2"
        or row.get("task_cursor") != last_binding.get("next_cursor")
        or row.get("last_cell_commit_journal_sha256")
        != last_cell.get("journal_sha256")
        or row.get("prior_stream_checkpoint_sha256")
        != last_cell.get("stream_checkpoint_sha256")
        or row.get("finalized_stream_checkpoint_sha256")
        != sha256_bytes(canonical_bytes(checkpoint))
        or payload.get("stream_state") != "DEVELOPMENT_FINALIZED"
        or payload.get("task_cursor") != row.get("task_cursor")
        or payload.get("next_sequence_index") != row["task_cursor"] + 1
        or payload.get("arm_id") != "M2"
        or row.get("static_identity_sha256")
        != sha256_bytes(
            canonical_bytes({name: payload.get(name) for name in static_fields})
        )
        or row.get("completed_task_digests_sha256")
        != sha256_bytes(canonical_bytes(payload.get("completed_task_digests")))
        or retained_prior_payload.get("stream_state") != "TASK_STREAM"
        or retained_prior_payload.get("task_cursor") != row.get("task_cursor")
        or retained_prior_payload.get("next_sequence_index")
        != row.get("task_cursor")
        or any(
            retained_prior_payload.get(name) != payload.get(name)
            for name in static_fields
        )
        or retained_prior_payload.get("completed_task_digests")
        != payload.get("completed_task_digests")
    ):
        raise BenchmarkExecutionError(
            "development finalization predecessor binding differs"
        )
    expected_final_policy = _expected_finalized_m2_policy_checkpoint(
        retained_prior_payload
    )
    if canonical_bytes(payload.get("final_policy_checkpoint")) != canonical_bytes(
        expected_final_policy
    ):
        raise BenchmarkExecutionError(
            "development final policy differs from deterministic task frontier"
        )
    return row


def _unknown_grader_result(
    *, task_id: str, container_digest: str | None = None
) -> GradeResult:
    """Create the canonical non-scientific result for an ambiguous launch."""

    return GradeResult(
        task_id=task_id,
        resolved=False,
        exit_code=-1,
        stdout="",
        stderr="",
        report={
            "schema": "trimem/grader-outcome-unknown/1.0",
            "task_id": task_id,
            "resolved": False,
            "failure_stage": "grader_process_started_without_terminal_result",
            "container_start_observed": None,
            "grader_capacity_consumed_conservatively": True,
            "terminal_streams_available": False,
        },
        grader_id="official-grader-lifecycle-recovery-v1",
        container_digest=(
            container_digest or "UNKNOWN_AFTER_GRADER_PROCESS_START"
        ),
        official=True,
        wall_time_ms=0,
        container_started=True,
        status="grader_outcome_unknown_after_process_start",
    )


def close_ambiguous_grader_journal(
    path: Path,
    *,
    container_digest: str | None = None,
) -> GradeResult:
    """Close a killed grader process without starting or retrying anything."""

    row = TerminalInvocationJournal._validated_grader_row(path)
    state = row["status"]
    request_sha256 = row["request_sha256"]
    suffix = ":" + request_sha256
    key = row["key"]
    if not key.endswith(suffix) or len(key) <= len(suffix):
        raise BenchmarkExecutionError(
            "grader lifecycle task identity cannot be recovered"
        )
    task_id = key[: -len(suffix)]
    result = _unknown_grader_result(
        task_id=task_id, container_digest=container_digest
    )
    if state == "GRADER_PROCESS_STARTED":
        TerminalInvocationJournal.transition_grader(
            path,
            expected=("GRADER_PROCESS_STARTED",),
            status="GRADER_CONTAINER_STARTED",
            values={
                "official_grader_runs": 1,
                "grader_containers": 1,
                "grader_capacity_disposition": "CONSERVATIVELY_CONSUMED",
                "container_start_observed": None,
            },
        )
        state = "GRADER_CONTAINER_STARTED"
    if state != "GRADER_CONTAINER_STARTED":
        raise BenchmarkExecutionError(
            "grader outcome-unknown recovery state is invalid"
        )
    TerminalInvocationJournal.transition_grader(
        path,
        expected=("GRADER_CONTAINER_STARTED",),
        status="GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START",
        values={
            "result": asdict(result),
            "official_grader_runs": 1,
            "grader_containers": 1,
            "grader_capacity_disposition": "CONSERVATIVELY_CONSUMED",
            "container_start_observed": None,
        },
    )
    return result


class JournaledGraderGateway:
    def __init__(
        self,
        delegate: OfficialHarnessGraderGateway,
        journal: TerminalInvocationJournal,
        *,
        preflight_evidence: Optional[Mapping[str, Any]] = None,
        python_binary: str | Path = sys.executable,
    ):
        self.delegate = delegate
        self.journal = journal
        self.preflight_evidence = preflight_evidence
        self.python_binary = python_binary

    def _preflight_sha256(self) -> str:
        evidence = self.preflight_evidence
        if evidence is None:
            evidence = getattr(self.delegate, "loader_preflight_evidence", None)
        if not isinstance(evidence, Mapping):
            raise BenchmarkProcessFailure(
                "GLOBAL_ENVIRONMENT_FAILURE",
                "official grader exact loader preflight evidence is absent",
            )
        delegate_loader = getattr(self.delegate, "python_loader_evidence", None)
        delegate_environment = getattr(self.delegate, "execution_env", None)
        validated = validate_official_harness_loader_preflight_evidence(
            evidence,
            python_binary=self.python_binary,
            _runtime_loader_evidence=(
                delegate_loader if isinstance(delegate_loader, Mapping) else None
            ),
            _runtime_environment=(
                delegate_environment
                if isinstance(delegate_environment, Mapping)
                else None
            ),
        )
        if delegate_loader is not None or delegate_environment is not None:
            if not isinstance(delegate_loader, Mapping) or not isinstance(
                delegate_environment, Mapping
            ):
                raise BenchmarkProcessFailure(
                    "GLOBAL_ENVIRONMENT_FAILURE",
                    "official grader runtime loader binding is incomplete",
                )
            if (
                canonical_bytes(dict(delegate_loader))
                != canonical_bytes(dict(validated["python_loader"]))
                or sorted(delegate_environment) != validated["environment_keys"]
                or sha256_bytes(canonical_bytes(dict(delegate_environment)))
                != validated["environment_identity_sha256"]
            ):
                raise BenchmarkProcessFailure(
                    "GLOBAL_ENVIRONMENT_FAILURE",
                    "official grader runtime loader differs from exact preflight",
                )
        return sha256_bytes(canonical_bytes(validated))

    @staticmethod
    def _request_hash(request: GradeRequest) -> str:
        workspace = request.workspace
        return sha256_bytes(canonical_bytes({
            "task_id": request.task_id,
            "repository": request.repository,
            "base_commit": request.base_commit,
            "patch_sha256": sha256_bytes(request.patch.encode("utf-8")),
            "workspace_kind": workspace.kind,
            "workspace_base_commit": workspace.base_commit,
            "workspace_checkout_root": workspace.checkout_root,
        }))

    @staticmethod
    def _result(value: Mapping[str, Any]) -> GradeResult:
        try:
            return GradeResult(**dict(value))
        except (TypeError, ValueError) as exc:
            raise BenchmarkExecutionError(
                "grader lifecycle result payload is malformed"
            ) from exc

    def _validate_result(self, request: GradeRequest, result: GradeResult) -> None:
        if (
            result.task_id != request.task_id
            or result.official is not True
            or result.container_started is not True
            or type(result.resolved) is not bool
            or type(result.exit_code) is not int
            or type(result.wall_time_ms) is not int
            or result.wall_time_ms < 0
            or not isinstance(result.report, Mapping)
            or not isinstance(result.stdout, str)
            or not isinstance(result.stderr, str)
            or not isinstance(result.status, str)
            or not result.status
        ):
            raise BenchmarkProcessFailure(
                "GLOBAL_GRADER_INFRA_FAILURE",
                "official grader terminal result is not authoritative",
            )
        validator = getattr(self.delegate, "validate_captured_result", None)
        if not callable(validator):
            raise BenchmarkProcessFailure(
                "GLOBAL_GRADER_INFRA_FAILURE",
                "official grader has no retained-evidence validator",
            )
        try:
            validator(request, result)
        except Exception as exc:
            raise BenchmarkProcessFailure(
                "GLOBAL_GRADER_INFRA_FAILURE",
                "official grader retained evidence did not validate: "
                + type(exc).__name__,
            ) from exc

    def _unknown_after_process_start(
        self,
        request: GradeRequest,
        path: Path,
        *,
        state: str,
    ) -> GraderInvocationFailure:
        """Conservatively close a launched process with no terminal result.

        ``GRADER_PROCESS_STARTED`` is the durable before-delegate marker.  A
        process death after that marker cannot prove that no container was
        created, so recovery consumes exactly one grader/container slot and
        records an outcome-unknown result.  It must never call the delegate a
        second time.
        """

        target = getattr(self.delegate, "target", None)
        container_digest = getattr(target, "image", None)
        if not isinstance(container_digest, str) or not container_digest:
            container_digest = None
        result = close_ambiguous_grader_journal(
            path, container_digest=container_digest
        )
        if result.task_id != request.task_id:
            raise BenchmarkExecutionError(
                "grader outcome-unknown task identity differs"
            )
        return GraderInvocationFailure(result)

    def lifecycle(self, request: GradeRequest) -> Mapping[str, Any]:
        request_hash = self._request_hash(request)
        key = f"{request.task_id}:{request_hash}"
        path = self.journal._path("grader", key)
        if not path.exists():
            return {
                "state": "GRADER_NOT_PREPARED",
                "request_sha256": request_hash,
                "journal_present": False,
            }
        row = self.journal._validated_grader_row(path)
        if row.get("key") != key or row.get("request_sha256") != request_hash:
            raise BenchmarkExecutionError(
                "grader lifecycle journal request identity mismatch"
            )
        return {
            "state": row["status"],
            "request_sha256": request_hash,
            "journal_present": True,
        }

    def grade(self, request: GradeRequest) -> GradeResult:
        request_hash = self._request_hash(request)
        key = f"{request.task_id}:{request_hash}"
        path = self.journal.begin_grader_request(key, request_hash)
        row = self.journal._validated_grader_row(path)
        state = row["status"]
        if state == "GRADER_RESULT_VALIDATED":
            result = self._result(row["result"])
            self._validate_result(request, result)
            return result
        if state in {
            "GRADER_INFRA_FAILURE_BEFORE_CONTAINER",
            "GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START",
        }:
            raise GraderInvocationFailure(self._result(row["result"]))
        if state == "GRADER_TERMINAL_RESULT_CAPTURED":
            result = self._result(row["result"])
            self._validate_result(request, result)
            self.journal.transition_grader(
                path,
                expected=("GRADER_TERMINAL_RESULT_CAPTURED",),
                status="GRADER_RESULT_VALIDATED",
            )
            return result
        if state in {"GRADER_PROCESS_STARTED", "GRADER_CONTAINER_STARTED"}:
            raise self._unknown_after_process_start(
                request, path, state=state
            )
        if state == "GRADER_NOT_PREPARED":
            preflight_sha256 = self._preflight_sha256()
            self.journal.transition_grader(
                path,
                expected=("GRADER_NOT_PREPARED",),
                status="GRADER_PREFLIGHT_PASSED",
                values={"loader_preflight_evidence_sha256": preflight_sha256},
            )
            state = "GRADER_PREFLIGHT_PASSED"
        if state == "GRADER_PREFLIGHT_PASSED":
            self.journal.transition_grader(
                path,
                expected=("GRADER_PREFLIGHT_PASSED",),
                status="GRADER_REQUEST_RECORDED",
            )
            state = "GRADER_REQUEST_RECORDED"
        if state != "GRADER_REQUEST_RECORDED":
            raise BenchmarkExecutionError("unknown grader lifecycle state")
        self.journal.transition_grader(
            path,
            expected=("GRADER_REQUEST_RECORDED",),
            status="GRADER_PROCESS_STARTED",
        )
        try:
            result = self.delegate.grade(request)
        except GraderInvocationFailure as exc:
            result_payload = asdict(exc.result)
            if exc.result.container_started:
                self.journal.transition_grader(
                    path,
                    expected=("GRADER_PROCESS_STARTED",),
                    status="GRADER_CONTAINER_STARTED",
                    values={
                        "official_grader_runs": 1,
                        "grader_containers": 1,
                        "grader_capacity_disposition": "CONSERVATIVELY_CONSUMED",
                    },
                )
                self.journal.transition_grader(
                    path,
                    expected=("GRADER_CONTAINER_STARTED",),
                    status="GRADER_OUTCOME_UNKNOWN_AFTER_CONTAINER_START",
                    values={
                        "result": result_payload,
                        "official_grader_runs": 1,
                        "grader_containers": 1,
                        "grader_capacity_disposition": "CONSERVATIVELY_CONSUMED",
                    },
                )
            else:
                self.journal.transition_grader(
                    path,
                    expected=("GRADER_PROCESS_STARTED",),
                    status="GRADER_INFRA_FAILURE_BEFORE_CONTAINER",
                    values={
                        "result": result_payload,
                        "official_grader_runs": 0,
                        "grader_containers": 0,
                        "grader_capacity_disposition": "NOT_CONSUMED",
                    },
                )
            raise
        except Exception as exc:
            raise self._unknown_after_process_start(
                request, path, state="GRADER_PROCESS_STARTED"
            ) from exc
        if not result.container_started:
            self.journal.transition_grader(
                path,
                expected=("GRADER_PROCESS_STARTED",),
                status="GRADER_INFRA_FAILURE_BEFORE_CONTAINER",
                values={
                    "result": asdict(result),
                    "official_grader_runs": 0,
                    "grader_containers": 0,
                    "grader_capacity_disposition": "NOT_CONSUMED",
                },
            )
            raise GraderInvocationFailure(result)
        self.journal.transition_grader(
            path,
            expected=("GRADER_PROCESS_STARTED",),
            status="GRADER_CONTAINER_STARTED",
            values={
                "official_grader_runs": 1,
                "grader_containers": 1,
                "grader_capacity_disposition": "CONSERVATIVELY_CONSUMED",
            },
        )
        self.journal.transition_grader(
            path,
            expected=("GRADER_CONTAINER_STARTED",),
            status="GRADER_TERMINAL_RESULT_CAPTURED",
            values={
                "result": asdict(result),
                "official_grader_runs": 1,
                "grader_containers": 1,
                "grader_capacity_disposition": "AUTHORITATIVE_RESULT",
            },
        )
        self._validate_result(request, result)
        self.journal.transition_grader(
            path,
            expected=("GRADER_TERMINAL_RESULT_CAPTURED",),
            status="GRADER_RESULT_VALIDATED",
        )
        return result


class _EnvironmentSecret:
    def get(self, name: str) -> str:
        value = os.environ.get(name)
        if not value:
            raise BenchmarkExecutionError(f"required provider secret is absent: {name}")
        return value


def build_paid_model_gateway(
    session: Any, ledger: AtomicBudgetLedger, model_lock: Mapping[str, Any], *,
    stream_id: str, restricted_response_root: Path,
):
    import httpx
    model = model_lock.get("primary_model", {}).get("model_id")
    if model != "gpt-5.4-mini-2026-03-17":
        raise BenchmarkExecutionError("model lock does not select the frozen dated snapshot")
    roles = model_lock.get("model_roles", {})
    if (
        set(roles) != {"decomposition", "solve", "experience_extraction"}
        or any(
            not isinstance(roles.get(role), Mapping)
            or roles[role].get("model_id") != model
            for role in roles
        )
    ):
        raise BenchmarkExecutionError("all benchmark model roles must use the frozen Mini snapshot")
    runner = getattr(session, "coroutine_runner", None)
    if not callable(runner):
        raise BenchmarkExecutionError("production arm has no long-lived coroutine runner")
    client = httpx.AsyncClient()
    provider = OpenAIResponsesProvider(
        "https://api.openai.com/v1", model, _EnvironmentSecret(), family="gpt5.4",
        reasoning_effort="medium", max_retries=1, http_client=client,
        raw_response_recorder=RestrictedProviderResponseStore(restricted_response_root),
    )
    bridge = AsyncProviderModelGateway(provider, runner, expected_model=model)
    return BudgetedModelGateway(bridge, ledger, stream_id=stream_id), client


def close_paid_model_client(session: Any, client: Any) -> None:
    session.run_coroutine(client.aclose())


def _source_base_commit(row: Mapping[str, Any], benchmark_id: str) -> str:
    if benchmark_id == "swebench_verified":
        value = row.get("base_commit")
    else:
        base = row.get("base")
        value = base.get("sha") if isinstance(base, dict) else row.get("base_commit")
    return str(value or "")


def _source_instance_id(row: Mapping[str, Any], benchmark_id: str) -> str:
    if benchmark_id == "swebench_verified":
        return str(row.get("instance_id") or "")
    if row.get("instance_id"):
        return str(row["instance_id"])
    return f"{row.get('org')}__{row.get('repo')}-{row.get('number')}"


def _download_locked(spec: Mapping[str, Any], cache_root: Path) -> Path:
    benchmark_id, revision, relative = spec["benchmark_id"], spec["dataset_revision"], spec["path"]
    target = cache_root / benchmark_id / revision / Path(relative).name
    if target.is_file() and target.stat().st_size == spec["bytes"] and sha256_bytes(target.read_bytes()) == spec["sha256"]:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    url = OFFICIAL_DATASET_URLS[benchmark_id].format(revision=revision, path=relative)
    fd, temp_name = tempfile.mkstemp(prefix=".dataset-", dir=target.parent)
    digest, count = hashlib.sha256(), 0
    try:
        with os.fdopen(fd, "wb") as stream, urllib.request.urlopen(url, timeout=120) as response:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                stream.write(chunk)
                digest.update(chunk)
                count += len(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if count != spec["bytes"] or digest.hexdigest() != spec["sha256"]:
            raise BenchmarkExecutionError(f"downloaded dataset bytes/hash mismatch: {benchmark_id}")
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return target


def load_frozen_rows(split: str, cache_root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    manifest_path = ROOT / MANIFESTS[split]
    git_tracked(manifest_path)
    manifest = read_json(manifest_path)
    targets = manifest.get("targets")
    if manifest.get("status") != "FROZEN" or not isinstance(targets, list):
        raise BenchmarkExecutionError("target manifest is not frozen")
    if [row.get("order_index") for row in targets] != list(range(len(targets))):
        raise BenchmarkExecutionError("target stream order is not contiguous")
    grader_lock = read_json(ROOT / "configs/trimem_v1/grader_lock.json")
    specs = {row["benchmark_id"]: row for row in grader_lock.get("dataset_files", ())}
    selected: dict[str, dict[str, Any]] = {}
    for benchmark_id in sorted({row["benchmark_id"] for row in targets}):
        if benchmark_id not in specs:
            raise BenchmarkExecutionError(f"dataset lock is absent: {benchmark_id}")
        path = _download_locked(specs[benchmark_id], cache_root)
        if benchmark_id == "swebench_verified":
            try:
                import pyarrow.parquet as pq
            except ImportError as exc:
                raise BenchmarkExecutionError("pyarrow is required for the exact SWE-bench parquet") from exc
            source_rows: Iterable[Mapping[str, Any]] = pq.read_table(path).to_pylist()
        else:
            def rows() -> Iterable[Mapping[str, Any]]:
                with path.open("r", encoding="utf-8") as stream:
                    for line in stream:
                        if line.strip():
                            value = strict_json_loads(line)
                            if not isinstance(value, dict):
                                raise BenchmarkExecutionError("Multi-SWE-bench row is not an object")
                            yield value
            source_rows = rows()
        wanted = {row["instance_id"] for row in targets if row["benchmark_id"] == benchmark_id}
        for source in source_rows:
            instance_id = _source_instance_id(source, benchmark_id)
            if instance_id not in wanted:
                continue
            if instance_id in selected:
                raise BenchmarkExecutionError(f"duplicate selected dataset row: {instance_id}")
            selected[instance_id] = dict(source)
    if set(selected) != {row["instance_id"] for row in targets}:
        raise BenchmarkExecutionError("one or more frozen target rows are missing")
    for target in targets:
        source = selected[target["instance_id"]]
        if sha256_bytes(canonical_bytes(source)) != target["source_row_sha256"]:
            raise BenchmarkExecutionError(f"source row hash mismatch: {target['target_id']}")
        if _source_base_commit(source, target["benchmark_id"]) != target["base_commit"]:
            raise BenchmarkExecutionError(f"source row base commit mismatch: {target['target_id']}")
        if target["dataset_revision"] != specs[target["benchmark_id"]]["dataset_revision"]:
            raise BenchmarkExecutionError(f"source revision mismatch: {target['target_id']}")
    return [dict(row) for row in targets], selected


def public_instruction(row: Mapping[str, Any], benchmark_id: str) -> str:
    if benchmark_id == "swebench_verified":
        value = row.get("problem_statement")
    else:
        title, body = row.get("title"), row.get("body")
        if not isinstance(title, str) or not isinstance(body, str):
            raise BenchmarkExecutionError("Multi-SWE-bench public title/body schema mismatch")
        pieces = [title.strip(), body.strip()]
        issues = row.get("resolved_issues")
        if not isinstance(issues, list):
            raise BenchmarkExecutionError("Multi-SWE-bench resolved_issues must be a list")
        for issue in issues:
            if not isinstance(issue, Mapping):
                raise BenchmarkExecutionError("Multi-SWE-bench resolved issue is not an object")
            number, issue_title, issue_body = issue.get("number"), issue.get("title"), issue.get("body")
            if (type(number) is not int or not isinstance(issue_title, str) or
                    not (issue_body is None or isinstance(issue_body, str))):
                raise BenchmarkExecutionError("Multi-SWE-bench resolved issue public schema mismatch")
            pieces.append(
                f"Resolved issue #{number}: {issue_title.strip()}\n"
                f"{issue_body.strip() if isinstance(issue_body, str) else ''}"
            )
        value = "\n\n".join(piece for piece in pieces if piece)
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkExecutionError("public task instruction is missing")
    return value.strip()


def coding_tasks(targets: Sequence[Mapping[str, Any]], rows: Mapping[str, Mapping[str, Any]]) -> list[CodingTask]:
    org_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "trimem-v1-benchmark-org"))
    user_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "trimem-v1-benchmark-user"))
    return [CodingTask(
        task_id=target["target_id"], org_id=org_id, user_id=user_id,
        repository=target["repository"], commit=target["base_commit"],
        instruction=public_instruction(rows[target["instance_id"]], target["benchmark_id"]),
        files={}, editable_paths=(), public_test=None,
    ) for target in targets]


def repository_identity_resolver(experiment_id: str, arm: str) -> Callable[[CodingTask], Mapping[str, str]]:
    def resolve(task: CodingTask) -> Mapping[str, str]:
        return {
            "repository_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "trimem-repository:" + task.repository)),
            "solve_job_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"trimem-solve:{experiment_id}:{arm}:{task.task_id}")),
        }
    return resolve


def _run_command(argv: Sequence[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise BenchmarkExecutionError(f"command failed ({argv[0]}): {completed.stderr.strip()}")
    return completed


def _hermetic_git_command(arguments: Sequence[str]) -> list[str]:
    return [
        "git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        *arguments,
    ]


def _run_hermetic_git(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "LANG": "C",
    }
    argv = _hermetic_git_command(arguments)
    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    if completed.returncode != 0:
        raise BenchmarkExecutionError(
            f"command failed ({argv[0]}): {completed.stderr.strip()}"
        )
    return completed


def prepare_checkouts(
    tasks: Sequence[CodingTask], targets: Sequence[Mapping[str, Any]],
    images: Mapping[str, Mapping[str, Any]], root: Path, *, resume: bool,
) -> tuple[GitCheckoutWorkspaceFactory, dict[str, dict[str, Any]]]:
    if len(tasks) != len(targets):
        raise BenchmarkExecutionError("task/target workspace binding length mismatch")
    try:
        root = validate_lexical_directory_chain(
            root, label="task checkout root"
        )
        root.mkdir(parents=True, exist_ok=True)
        root = validate_lexical_directory_chain(
            root, label="task checkout root"
        )
    except HarnessLockError as exc:
        raise BenchmarkExecutionError("task checkout root is unsafe") from exc
    roots, commits, evidence = {}, {}, {}
    command_runners = {}
    for task, target in zip(tasks, targets):
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", task.task_id)
        lexical_checkout = (root / safe).absolute()
        if _is_link_or_reparse(lexical_checkout):
            raise BenchmarkExecutionError(
                f"task checkout is linked or reparsed: {task.task_id}"
            )
        checkout = lexical_checkout.resolve()
        stdout_parts, stderr_parts, argv_rows = [], [], []
        if not checkout.exists():
            if resume:
                raise BenchmarkExecutionError(f"resume checkout is missing: {task.task_id}")
            clone_arguments = ["clone", "--no-checkout", "--filter=blob:none",
                               f"https://github.com/{task.repository}.git", str(checkout)]
            clone = _hermetic_git_command(clone_arguments)
            result = _run_hermetic_git(clone_arguments)
            stdout_parts.append(result.stdout); stderr_parts.append(result.stderr); argv_rows.append(clone)
            checkout_arguments = [
                f"--git-dir={checkout / '.git'}",
                f"--work-tree={checkout}",
                "checkout",
                "--detach",
                task.commit,
            ]
            checkout_cmd = _hermetic_git_command(checkout_arguments)
            result = _run_hermetic_git(checkout_arguments)
            stdout_parts.append(result.stdout); stderr_parts.append(result.stderr); argv_rows.append(checkout_cmd)
        git_dir = checkout / ".git"
        if _is_link_or_reparse(git_dir) or not git_dir.is_dir():
            raise BenchmarkExecutionError(
                f"task checkout Git metadata is not local: {task.task_id}"
            )
        try:
            validate_safe_local_git_configuration(checkout)
        except Exception as exc:
            raise BenchmarkExecutionError(
                f"task checkout Git configuration is unsafe: {task.task_id}"
            ) from exc
        head = _run_hermetic_git(
            [
                f"--git-dir={git_dir}",
                f"--work-tree={checkout}",
                "rev-parse",
                "--verify",
                "HEAD",
            ]
        ).stdout.strip()
        if head != task.commit:
            raise BenchmarkExecutionError(f"checkout HEAD mismatch: {task.task_id}")
        status = ""
        if not resume:
            try:
                validate_pristine_checkout(checkout, task.commit)
            except HarnessLockError as exc:
                raise BenchmarkExecutionError(
                    f"new checkout is not exact and clean: {task.task_id}"
                ) from exc
        roots[task.task_id], commits[task.task_id] = checkout, task.commit
        image = images.get(str(target.get("instance_id")), {}).get("image")
        if not isinstance(image, str):
            raise BenchmarkExecutionError(f"task command image is missing: {task.task_id}")
        command_runners[task.task_id] = DockerSandboxCommandRunner(image)
        evidence[task.task_id] = {
            "argv": argv_rows, "stdout": "".join(stdout_parts), "stderr": "".join(stderr_parts),
            "head": head, "initial_status": status,
        }
    factory = GitCheckoutWorkspaceFactory(roots, commits, command_runners=command_runners)
    if factory.production_capable is not True or type(factory) is not GitCheckoutWorkspaceFactory:
        raise BenchmarkExecutionError("benchmark workspace is not the frozen Git checkout factory")
    return factory, evidence


def image_entries(*, require_benchmark: bool) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str]]]:
    lock = read_json(ROOT / "artifacts/trimem_v1/grader_image_lock.json")
    if lock.get("status") != "FROZEN" or lock.get("smoke_status") != "FROZEN":
        raise BenchmarkExecutionError("grader-smoke image digest lock is not frozen")
    rows = list(lock.get("targets", ()))
    if require_benchmark:
        benchmark = lock.get("benchmark_target_images", {})
        if benchmark.get("status") != "FROZEN" or not isinstance(benchmark.get("targets"), list):
            raise BenchmarkExecutionError("development/held-out image digests are not frozen")
        rows.extend(benchmark["targets"])
    mapped = {}
    for row in rows:
        instance_id = row.get("instance_id")
        if instance_id in mapped:
            if mapped[instance_id] != row:
                raise BenchmarkExecutionError("conflicting grader image lock")
            continue
        mapped[instance_id] = dict(row)
    support = [(row["image"], row["harness_image_tag"]) for row in lock.get("support_images", ())]
    return mapped, support


def grader_factory(
    target: Mapping[str, Any], row: Mapping[str, Any], image: Mapping[str, Any],
    harnesses: Mapping[str, Path], output_root: Path, arm: str, support: Sequence[tuple[str, str]],
    *,
    loader_preflight_evidence: Optional[Mapping[str, Any]] = None,
):
    if loader_preflight_evidence is not None:
        validate_official_harness_loader_preflight_evidence(
            loader_preflight_evidence
        )
        validate_preflight_harness_root_binding(
            loader_preflight_evidence, harnesses
        )
    harness_revision = (
        SWE_HARNESS_REVISION
        if target["benchmark_id"] == "swebench_verified"
        else MULTI_HARNESS_REVISION
    )
    frozen = FrozenOfficialTarget(
        target_id=target["target_id"], benchmark_id=target["benchmark_id"],
        instance_id=target["instance_id"], repository=target["repository"],
        base_commit=target["base_commit"], dataset_revision=target["dataset_revision"],
        source_row_sha256=target["source_row_sha256"], image=image["image"],
        harness_image_tag=image["harness_image_tag"], harness_revision=harness_revision,
    )
    multi_support = support if target["benchmark_id"].startswith("multi_swe_bench") else ()
    grader = OfficialHarnessGraderGateway(
        frozen, source_row=row, harness_root=harnesses[target["benchmark_id"]],
        output_root=output_root, model_name=f"trimem-v1-{arm}", support_images=multi_support,
    )
    if loader_preflight_evidence is not None:
        expected_loader = loader_preflight_evidence["python_loader"]
        observed_loader = grader.python_loader_evidence
        identity_fields = (
            "schema",
            "status",
            "python_binary_realpath",
            "python_binary_sha256",
            "python_binary_bytes",
            "python_version",
            "python_prefix",
            "libdir",
            "libpython_realpath",
            "libpython_sha256",
            "libpython_bytes",
        )
        if any(
            observed_loader.get(name) != expected_loader.get(name)
            for name in identity_fields
        ) or (
            sorted(grader.execution_env)
            != loader_preflight_evidence.get("environment_keys")
        ) or sha256_bytes(canonical_bytes(grader.execution_env)) != (
            loader_preflight_evidence.get("environment_identity_sha256")
        ):
            raise BenchmarkProcessFailure(
                "GLOBAL_ENVIRONMENT_FAILURE",
                "official grader loader identity differs from workflow preflight",
            )
    return grader


def observed_target_digest(grade: GradeResult) -> str:
    """Return the inspected digest, never the expected container field."""
    report = grade.report
    trimem = report.get("_trimem") if isinstance(report, Mapping) else None
    if not isinstance(trimem, Mapping):
        raise BenchmarkExecutionError(
            "official report has no canonical TriMem evidence envelope"
        )
    evidence = trimem.get("image_evidence")
    if not isinstance(evidence, list):
        raise BenchmarkExecutionError("official report has no image-inspect evidence")
    expected = grade.container_digest.rsplit("@", 1)[-1]
    matches = []
    for row in evidence:
        if not isinstance(row, Mapping) or row.get("image") != grade.container_digest:
            continue
        observed = row.get("observed")
        if row.get("expected") != expected or not isinstance(observed, list) or expected not in observed:
            raise BenchmarkExecutionError("official report image evidence does not prove digest equality")
        matches.append(expected)
    if matches != [expected]:
        raise BenchmarkExecutionError("official report must contain one exact target image observation")
    return matches[0]


def restricted_evidence_references(task_dir: Path, grader_root: Path) -> list[dict[str, Any]]:
    root = grader_root / "restricted-evidence"
    if not root.exists():
        return []
    return [evidence_reference(task_dir, path) for path in sorted(root.glob("*.bin"))]


def evidence_reference(result_dir: Path, path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {"path": path.resolve().relative_to(result_dir.resolve()).as_posix(),
            "sha256": sha256_bytes(raw), "bytes": len(raw)}


def actual_accounting(value: Mapping[str, Any], *, task_wall_time_ms: int = 0) -> dict[str, int]:
    summary = value.get("summary", {})
    kinds = summary.get("by_call_kind", {})
    tools = value.get("tools", [])
    calls = value.get("calls", [])
    if not isinstance(calls, list):
        raise BenchmarkExecutionError("call accounting is malformed")

    def charged_tokens(call: Mapping[str, Any], field: str) -> int:
        if call.get("provider_reported_usage_available") is True:
            amount = call.get(field)
            if type(amount) is not int or amount < 0:
                raise BenchmarkExecutionError("provider token accounting is malformed")
            return amount
        reservation = call.get("ledger_reservation")
        if (
            not isinstance(reservation, Mapping)
            or reservation.get("charged_conservatively") is not True
        ):
            raise BenchmarkExecutionError(
                "unknown provider usage lacks conservative ledger accounting"
            )
        if field == "input_tokens":
            amount = reservation.get("input_upper_bound")
        elif field == "output_tokens":
            amount = reservation.get("output_cap")
        else:
            amount = 0
        if type(amount) is not int or amount < 0:
            raise BenchmarkExecutionError("conservative token accounting is malformed")
        return amount

    charged = {
        field: sum(
            charged_tokens(call, field)
            for call in calls
            if isinstance(call, Mapping)
        )
        for field in (
            "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens"
        )
    }
    if len(calls) != sum(isinstance(call, Mapping) for call in calls):
        raise BenchmarkExecutionError("call accounting row is malformed")
    role_output = {
        kind: sum(
            charged_tokens(call, "output_tokens")
            for call in calls
            if call.get("call_kind") == kind
        )
        for kind in ("decompose", "solve", "extract")
    }
    solve_output = (
        role_output["solve"]
        if calls
        else int(kinds.get("solve", {}).get("output_tokens", 0))
    )
    return {
        "solve_calls": int(kinds.get("solve", {}).get("calls", 0)),
        "decomposition_calls": int(kinds.get("decompose", {}).get("calls", 0)),
        "extraction_calls": int(kinds.get("extract", {}).get("calls", 0)),
        "actual_decomposition_output_tokens": (
            role_output["decompose"]
            if calls
            else int(kinds.get("decompose", {}).get("output_tokens", 0))
        ),
        "actual_solve_output_tokens": solve_output,
        "actual_extraction_output_tokens": (
            role_output["extract"]
            if calls
            else int(kinds.get("extract", {}).get("output_tokens", 0))
        ),
        "solve_output_pool_capacity": 49_152,
        "remaining_solve_output_tokens": 49_152 - solve_output,
        "replace_text_calls": sum(
            int(isinstance(row, Mapping) and row.get("tool_name") == "replace_text")
            for row in tools
        ),
        "write_file_calls": sum(
            int(isinstance(row, Mapping) and row.get("tool_name") == "write_file")
            for row in tools
        ),
        "input_tokens": (
            charged["input_tokens"]
            if calls else int(summary.get("actual_input_tokens", 0))
        ),
        "cached_input_tokens": (
            charged["cached_input_tokens"]
            if calls else int(summary.get("actual_cached_input_tokens", 0))
        ),
        "output_tokens": (
            charged["output_tokens"]
            if calls else int(summary.get("actual_output_tokens", 0))
        ),
        "reasoning_tokens": (
            charged["reasoning_tokens"]
            if calls else int(summary.get("actual_reasoning_tokens", 0))
        ),
        "model_wall_time_ms": int(summary.get("actual_model_wall_time_ms", 0)),
        "tool_wall_time_ms": int(summary.get("actual_tool_wall_time_ms", 0)),
        "grader_wall_time_ms": int(summary.get("actual_grader_wall_time_ms", 0)),
        "task_wall_time_ms": int(task_wall_time_ms),
        "model_gateway_calls": int(summary.get("model_gateway_calls", 0)),
        "paid_model_calls": int(summary.get("paid_model_calls", 0)),
        "grader_calls": int(summary.get("grader_calls", 0)),
        "grader_containers": int(summary.get("grader_containers", 0)),
        "official_grader_runs": int(summary.get("official_grader_runs", 0)),
    }


def provider_outcome_accounting(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a public, text-free provider outcome/usage projection."""

    calls = value.get("calls", [])
    if not isinstance(calls, list):
        raise BenchmarkExecutionError("provider call accounting is malformed")
    status_distribution: dict[str, int] = {}
    known_usage = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
    }
    reservation = {
        "calls": 0,
        "input_upper_bound": 0,
        "output_cap": 0,
        "conservatively_charged_calls": 0,
    }
    available_calls = 0
    unavailable_calls = 0
    for call in calls:
        if not isinstance(call, Mapping):
            raise BenchmarkExecutionError("provider call record is malformed")
        envelope = call.get("provider_response_envelope")
        classification = (
            envelope.get("terminal_classification")
            if isinstance(envelope, Mapping)
            else call.get("status")
        )
        if not isinstance(classification, str) or not classification:
            raise BenchmarkExecutionError("provider terminal classification is missing")
        status_distribution[classification] = status_distribution.get(classification, 0) + 1
        if call.get("provider_reported_usage_available") is True:
            available_calls += 1
            for field in known_usage:
                token_value = call.get(field)
                if type(token_value) is not int or token_value < 0:
                    raise BenchmarkExecutionError("provider reported usage is malformed")
                known_usage[field] += token_value
        else:
            unavailable_calls += 1
        ledger = call.get("ledger_reservation")
        if not isinstance(ledger, Mapping):
            raise BenchmarkExecutionError("provider ledger reservation is missing")
        for field in ("input_upper_bound", "output_cap"):
            amount = ledger.get(field)
            if type(amount) is not int or amount < 0:
                raise BenchmarkExecutionError("provider ledger reservation is malformed")
            reservation[field] += amount
        reservation["calls"] += 1
        reservation["conservatively_charged_calls"] += int(
            ledger.get("charged_conservatively") is True
        )
    return {
        "provider_status_distribution": dict(sorted(status_distribution.items())),
        "incomplete_count": sum(
            count for name, count in status_distribution.items()
            if name.startswith("RESPONSE_INCOMPLETE")
        ),
        "refusal_count": status_distribution.get("RESPONSE_REFUSAL", 0),
        "structured_output_schema_failure_count": status_distribution.get(
            "STRUCTURED_OUTPUT_SCHEMA_FAILURE", 0
        ),
        "provider_reported_usage": {
            "available_calls": available_calls,
            "unavailable_calls": unavailable_calls,
            "complete": unavailable_calls == 0,
            **known_usage,
        },
        "ledger_reservation": reservation,
    }


def combine_provider_outcomes(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    usage = {
        "available_calls": 0,
        "unavailable_calls": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
    }
    reservation = {
        "calls": 0,
        "input_upper_bound": 0,
        "output_cap": 0,
        "conservatively_charged_calls": 0,
    }
    for row in rows:
        for name, count in row["provider_status_distribution"].items():
            statuses[name] = statuses.get(name, 0) + int(count)
        for field in usage:
            usage[field] += int(row["provider_reported_usage"][field])
        for field in reservation:
            reservation[field] += int(row["ledger_reservation"][field])
    return {
        "provider_status_distribution": dict(sorted(statuses.items())),
        "incomplete_count": sum(
            count for name, count in statuses.items()
            if name.startswith("RESPONSE_INCOMPLETE")
        ),
        "refusal_count": statuses.get("RESPONSE_REFUSAL", 0),
        "structured_output_schema_failure_count": statuses.get(
            "STRUCTURED_OUTPUT_SCHEMA_FAILURE", 0
        ),
        "provider_reported_usage": {
            **usage,
            "complete": usage["unavailable_calls"] == 0,
        },
        "ledger_reservation": reservation,
    }


def actual_usd_for_accounting(
    accounting: Mapping[str, int], pricing: Mapping[str, Any]
) -> str:
    cached = int(accounting["cached_input_tokens"])
    total_input = int(accounting["input_tokens"])
    if cached < 0 or total_input < cached:
        raise BenchmarkExecutionError("cached input tokens exceed total input tokens")
    million = Decimal(1_000_000)
    value = (
        Decimal(total_input - cached) * Decimal(str(pricing["input_per_million_tokens_usd"]))
        + Decimal(cached) * Decimal(str(pricing["cached_input_per_million_tokens_usd"]))
        + Decimal(int(accounting["output_tokens"]))
        * Decimal(str(pricing["output_per_million_tokens_usd"]))
    ) / million
    return format(value, ".12f")


def scientific_caps_after_protocol_canary(
    phase_cap: Mapping[str, Any],
    canary: Mapping[str, Any],
    *,
    expected_approval_sha256: str,
) -> dict[str, Any]:
    """Derive a non-transferable scientific budget after the protocol canary."""

    try:
        return scientific_cap_after_protocol_canary(
            phase_cap,
            canary,
            expected_approval_sha256=expected_approval_sha256,
        )
    except DevelopmentPhaseCapError as exc:
        raise BenchmarkExecutionError(str(exc)) from None


def validate_global_phase_accounting(
    phase_cap: Mapping[str, Any], canary: Mapping[str, Any], scientific: Mapping[str, Any]
) -> dict[str, Any]:
    """Prove the separate protocol and scientific ledgers fit the phase cap."""

    combined = {
        "model_calls": int(scientific["paid_model_calls"]) + 1,
        "paid_model_calls": int(scientific["paid_model_calls"]) + 1,
        "input_tokens": int(scientific["input_tokens"]) + int(canary["input_tokens"]),
        "cached_input_tokens": int(scientific["cached_input_tokens"])
        + int(canary["cached_input_tokens"]),
        "output_tokens": int(scientific["output_tokens"]) + int(canary["output_tokens"]),
        "total_usd": format(
            Decimal(str(scientific["total_usd"])) + Decimal(str(canary["actual_usd"])),
            ".12f",
        ),
    }
    for field in ("model_calls", "paid_model_calls", "input_tokens", "output_tokens"):
        if combined[field] > int(phase_cap[field]):
            raise BenchmarkExecutionError(f"combined protocol/scientific {field} exceeds phase cap")
    if Decimal(combined["total_usd"]) > Decimal(str(phase_cap["total_usd"])):
        raise BenchmarkExecutionError("combined protocol/scientific USD exceeds phase cap")
    return combined


def validate_phase_completion(
    output_root: Path,
    *,
    split: str,
    summaries: Sequence[Mapping[str, Any]],
    ledger: AtomicBudgetLedger,
    hard_cap: Mapping[str, Any],
    pricing: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind all terminal result, stream, session, and atomic-ledger evidence."""

    result_records = [
        read_json(path) for path in sorted(output_root.rglob("*.result.json"))
    ]
    if len(result_records) != hard_cap["task_arm_runs"]:
        raise BenchmarkExecutionError(
            "phase result count does not equal the approved exact matrix"
        )
    summary_by_arm: dict[str, Mapping[str, Any]] = {}
    for summary in summaries:
        arm = summary.get("arm")
        if not isinstance(arm, str) or not arm or arm in summary_by_arm:
            raise BenchmarkExecutionError("phase stream summaries have duplicate/invalid arms")
        summary_by_arm[arm] = summary

    empty_accounting = actual_accounting({"summary": {}})
    accounting_fields = set(empty_accounting)
    phase_accounting = {field: 0 for field in empty_accounting}
    task_arm_actual: dict[str, dict[str, Any]] = {}
    observed_keys: set[tuple[str, str]] = set()
    records_by_arm: dict[str, list[Mapping[str, Any]]] = {
        arm: [] for arm in summary_by_arm
    }
    execution_locks: dict[str, str] = {}
    phase_provider_rows: list[Mapping[str, Any]] = []
    for record in result_records:
        try:
            validate_scientific_terminal_result(record)
        except ScientificTerminalContractError as exc:
            raise BenchmarkExecutionError(
                f"phase scientific terminal result contract failed: {exc}"
            ) from None
        arm, runtime_arm, target_id = (
            record.get("arm"), record.get("runtime_arm"), record.get("target_id")
        )
        if (
            not isinstance(arm, str)
            or arm not in summary_by_arm
            or runtime_arm not in ARMS
            or not isinstance(target_id, str)
            or not target_id
            or (arm, target_id) in observed_keys
        ):
            raise BenchmarkExecutionError("phase result stream/task identity differs")
        observed_keys.add((arm, target_id))
        accounting = record.get("actual_accounting")
        if not isinstance(accounting, dict) or set(accounting) != accounting_fields or any(
            type(accounting[field]) is not int or accounting[field] < 0
            for field in accounting_fields
        ):
            raise BenchmarkExecutionError("phase result accounting shape/value differs")
        try:
            validate_scientific_role_call_accounting(record, accounting)
        except ScientificTerminalContractError as exc:
            raise BenchmarkExecutionError(
                f"phase scientific role-call accounting failed: {exc}"
            ) from None
        if (
            accounting["model_gateway_calls"]
            != accounting["solve_calls"]
            + accounting["decomposition_calls"]
            + accounting["extraction_calls"]
            or accounting["paid_model_calls"] != accounting["model_gateway_calls"]
            or (
                accounting["grader_calls"], accounting["grader_containers"],
                accounting["official_grader_runs"],
            )
            != (1, 1, 1)
        ):
            raise BenchmarkExecutionError("phase result exact call/grader workload differs")
        if (
            accounting["input_tokens"] > hard_cap["max_input_tokens_per_task_arm"]
            or accounting["model_gateway_calls"]
            > hard_cap["max_model_calls_per_task_arm"]
        ):
            raise BenchmarkExecutionError("phase result exceeds a per-task-arm hard cap")
        if accounting["output_tokens"] != sum(
            accounting[field]
            for field in (
                "actual_decomposition_output_tokens",
                "actual_solve_output_tokens",
                "actual_extraction_output_tokens",
            )
        ):
            raise BenchmarkExecutionError("phase result role output totals differ")
        if (
            accounting["solve_output_pool_capacity"] != 49_152
            or accounting["actual_solve_output_tokens"] > 49_152
            or accounting["remaining_solve_output_tokens"]
            != 49_152 - accounting["actual_solve_output_tokens"]
        ):
            raise BenchmarkExecutionError("phase result solve output pool differs")
        actual_usd = actual_usd_for_accounting(accounting, pricing)
        if record.get("actual_usd") != actual_usd:
            raise BenchmarkExecutionError("phase result USD differs from tokens/pricing")
        execution_lock_hash = record.get("execution_lock_hash")
        if (
            not isinstance(execution_lock_hash, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", execution_lock_hash) is None
            or summary_by_arm[arm].get("execution_lock_hash") != execution_lock_hash
        ):
            raise BenchmarkExecutionError("result/summary execution-lock binding differs")
        prior_lock = execution_locks.setdefault(arm, execution_lock_hash)
        if prior_lock != execution_lock_hash:
            raise BenchmarkExecutionError("execution lock changed within a stream")
        for field in accounting_fields:
            phase_accounting[field] += accounting[field]
        provider_outcomes = record.get("provider_outcomes")
        if not isinstance(provider_outcomes, Mapping):
            raise BenchmarkExecutionError("phase result provider outcomes are missing")
        phase_provider_rows.append(provider_outcomes)
        task_arm_key = f"{arm}:{runtime_arm}:{target_id}"
        task_arm_actual[task_arm_key] = {
            "input_tokens": accounting["input_tokens"],
            "cached_input_tokens": accounting["cached_input_tokens"],
            "output_tokens": accounting["output_tokens"],
            "solve_calls": accounting["solve_calls"],
            "decomposition_calls": accounting["decomposition_calls"],
            "extraction_calls": accounting["extraction_calls"],
            "model_gateway_calls": accounting["model_gateway_calls"],
            "paid_model_calls": accounting["paid_model_calls"],
            "total_usd": actual_usd,
        }
        records_by_arm[arm].append(record)

    if len(set(execution_locks.values())) != len(execution_locks):
        raise BenchmarkExecutionError("benchmark streams share an execution lock")
    for arm, summary in summary_by_arm.items():
        stream_records = records_by_arm[arm]
        expected_stream_accounting = {
            field: sum(row["actual_accounting"][field] for row in stream_records)
            for field in accounting_fields
        }
        if summary.get("actual_accounting") != expected_stream_accounting:
            raise BenchmarkExecutionError("stream summary/result accounting totals differ")
        expected_provider_outcomes = combine_provider_outcomes(
            [row["provider_outcomes"] for row in stream_records]
        )
        if summary.get("provider_outcomes") != expected_provider_outcomes:
            raise BenchmarkExecutionError("stream summary/provider outcome totals differ")
        if summary.get("actual_usd") != actual_usd_for_accounting(
            expected_stream_accounting, pricing
        ):
            raise BenchmarkExecutionError("stream summary USD differs from results")
        identity_path = _arm_identity_path(output_root, arm)
        if not identity_path.is_file():
            raise BenchmarkExecutionError("stream session identity evidence is missing")
        envelope = read_json(identity_path)
        payload, digest = envelope.get("payload"), envelope.get("digest")
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {
                "schema", "arm", "split", "experiment_id", "execution_lock_hash",
                "run_nonce",
            }
            or digest != "sha256:" + sha256_bytes(canonical_bytes(payload))
            or payload.get("schema") != "trimem/benchmark-arm-session-identity/1.0"
            or payload.get("arm") != arm
            or payload.get("split") != split
            or payload.get("execution_lock_hash") != execution_locks[arm]
        ):
            raise BenchmarkExecutionError("stream session/execution-lock identity differs")
        try:
            run_nonce = str(uuid.UUID(str(payload.get("run_nonce"))))
        except (ValueError, AttributeError) as exc:
            raise BenchmarkExecutionError("stream session nonce is invalid") from exc
        if payload.get("run_nonce") != run_nonce:
            raise BenchmarkExecutionError("stream session nonce is not canonical")

    expected_ledger_actual = {
        "paid_model_calls": phase_accounting["paid_model_calls"],
        "solve_calls": phase_accounting["solve_calls"],
        "decomposition_calls": phase_accounting["decomposition_calls"],
        "extraction_calls": phase_accounting["extraction_calls"],
        "input_tokens": phase_accounting["input_tokens"],
        "cached_input_tokens": phase_accounting["cached_input_tokens"],
        "output_tokens": phase_accounting["output_tokens"],
        "total_usd": float(actual_usd_for_accounting(phase_accounting, pricing)),
        "task_arm_runs": len(result_records),
        "grader_containers": phase_accounting["grader_containers"],
    }
    ledger.finalize(
        expected_actual=expected_ledger_actual,
        expected_task_arms=task_arm_actual,
        expected_result_records=result_records,
    )
    return {
        "actual_accounting": phase_accounting,
        "actual_usd": actual_usd_for_accounting(phase_accounting, pricing),
        "execution_locks": execution_locks,
        "provider_outcomes": combine_provider_outcomes(phase_provider_rows),
        "task_arm_runs": len(result_records),
    }


def actual_memory_metrics(result: Any, events_path: Path) -> dict[str, int]:
    recalls = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        event = strict_json_loads(line)
        if event.get("event_type") == "memory_recall":
            recalls.append(event.get("payload", {}))
    injections = tuple(result.injections)
    kinds = [str(row.get("kind")) for row in injections]
    storage = result.lifecycle_result.get("storage", {})
    if not isinstance(storage, Mapping):
        raise BenchmarkExecutionError("lifecycle storage metrics are absent")
    required = ("retained_records", "archived_records", "net_memory_growth")
    if any(type(storage.get(name)) is not int or storage[name] < 0 for name in required[:2]):
        raise BenchmarkExecutionError("lifecycle retained/archive metrics are incomplete")
    if type(storage.get("net_memory_growth")) is not int:
        raise BenchmarkExecutionError("lifecycle net-memory-growth metric is incomplete")
    if storage["net_memory_growth"] != storage["retained_records"] - storage["archived_records"]:
        raise BenchmarkExecutionError("lifecycle net-memory-growth arithmetic mismatch")
    return {
        "recall_attempts": len(recalls),
        "injected_records": len(injections),
        "episodic_injections": kinds.count("EPISODIC"),
        "user_semantic_injections": kinds.count("USER_SEMANTIC"),
        "org_semantic_injections": kinds.count("ORG_SEMANTIC"),
        "abstention_decisions": sum(
            1 for recall in recalls
            for row in recall.get("bank_trace", ())
            if isinstance(row, Mapping) and row.get("decision") == "ABSTAIN"
        ),
        "retained_records": int(storage["retained_records"]),
        "archived_records": int(storage["archived_records"]),
        "net_memory_growth": int(storage["net_memory_growth"]),
    }


def task_configuration_sha256(task: CodingTask) -> str:
    """Return the exact task component hash used by runtime checkpoints."""

    return sha256_bytes(
        canonical_bytes(
            {
                "org_id": task.org_id,
                "user_id": task.user_id,
                "public_payload": task.public_payload(),
            }
        )
    )


def _arm_checkpoint_paths(root: Path, arm: str) -> tuple[Path, Path]:
    return root / f"{arm}.stream-checkpoint.json", root / f"{arm}.stream-checkpoint.sha256"


def save_arm_checkpoint(root: Path, arm: str, checkpoint: Mapping[str, Any]) -> None:
    target, sidecar = _arm_checkpoint_paths(root, arm)
    raw = canonical_bytes(checkpoint)
    atomic_write(target, raw)
    atomic_write(sidecar, (sha256_bytes(raw) + "\n").encode("ascii"))


def load_arm_checkpoint(root: Path, arm: str) -> dict[str, Any]:
    target, sidecar = _arm_checkpoint_paths(root, arm)
    target = _secure_retained_path(root, target, directory=False)
    sidecar = _secure_retained_path(root, sidecar, directory=False)
    raw = target.read_bytes()
    if sha256_bytes(raw) != sidecar.read_text(encoding="ascii").strip():
        raise BenchmarkExecutionError("resume stream checkpoint sidecar mismatch")
    value = strict_json_loads(raw)
    if not isinstance(value, dict):
        raise BenchmarkExecutionError("resume stream checkpoint is invalid")
    return value


def _cell_stream_checkpoint_sha256(
    root: Path,
    stream_id: str,
    binding: Mapping[str, Any],
) -> str:
    """Validate the current stream checkpoint and return its canonical SHA-256."""

    next_cursor = binding.get("next_cursor")
    checkpoint = load_arm_checkpoint(root, stream_id)
    payload = checkpoint.get("payload")
    if (
        type(next_cursor) is not int
        or not isinstance(payload, Mapping)
        or payload.get("task_cursor") != next_cursor
    ):
        raise BenchmarkExecutionError(
            "cell-commit stream checkpoint cursor differs"
        )
    next_sequence_index = payload.get("next_sequence_index")
    if next_sequence_index is not None and next_sequence_index != next_cursor:
        raise BenchmarkExecutionError(
            "cell-commit stream checkpoint sequence differs"
        )
    embedded_digest = checkpoint.get("digest")
    if embedded_digest is not None:
        payload_sha256 = sha256_bytes(canonical_bytes(payload))
        if embedded_digest not in {payload_sha256, "sha256:" + payload_sha256}:
            raise BenchmarkExecutionError(
                "cell-commit stream checkpoint envelope digest differs"
            )
    return sha256_bytes(canonical_bytes(checkpoint))


def _verified_cell_stream_checkpoint(
    root: Path,
    stream_id: str,
    journal_row: Mapping[str, Any],
) -> None:
    """Bind a cursor-advanced cell to the exact durable stream checkpoint."""

    binding = journal_row.get("binding")
    if not isinstance(binding, Mapping):
        raise BenchmarkExecutionError("cell-commit checkpoint binding is absent")
    observed = _cell_stream_checkpoint_sha256(root, stream_id, binding)
    if journal_row.get("stream_checkpoint_sha256") != observed:
        raise BenchmarkExecutionError(
            "cell-commit stream checkpoint hash differs"
        )


def _task_recovery_paths(
    root: Path,
    stream_id: str,
    sequence_index: int,
    task: CodingTask,
) -> tuple[Path, str, Path]:
    safe_task_id = re.sub(r"[^A-Za-z0-9_.-]", "_", task.task_id)
    task_dir = root / stream_id / f"{sequence_index:03d}-{safe_task_id}"
    run_id = re.sub(r"[^A-Za-z0-9_-]", "_", f"{task.task_id}-{stream_id}")
    return task_dir, run_id, task_dir / "prepared-task-checkpoint.json"


def _cell_result_path(task_dir: Path, task: CodingTask) -> Path:
    safe_task_id = re.sub(r"[^A-Za-z0-9_.-]", "_", task.task_id)
    return task_dir / f"{safe_task_id}.result.json"


def _cell_commit_path(task_dir: Path) -> Path:
    return task_dir / "cell-commit-journal.json"


def _cell_commit_binding(
    *,
    stream_id: str,
    arm: str,
    target_id: str,
    sequence_index: int,
    task_arm_key: str,
    task_reservation: str,
    record: Mapping[str, Any],
    grade: GradeResult,
    session_result: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "stream_id": stream_id,
        "arm": arm,
        "target_id": target_id,
        "expected_cursor": sequence_index,
        "task_arm_key": task_arm_key,
        "task_arm_reservation_id": task_reservation,
        "result_sha256": sha256_bytes(json_file_bytes(record)),
        "accounting_projection_sha256": sha256_bytes(
            canonical_bytes(record["actual_accounting"])
        ),
        "grader_result_sha256": sha256_bytes(canonical_bytes(asdict(grade))),
        "session_result_sha256": sha256_bytes(
            canonical_bytes(session_result)
        ),
        "next_cursor": sequence_index + 1,
    }


def _verified_terminal_ledger_row(
    ledger: AtomicBudgetLedger,
    *,
    task_arm_key: str,
    reservation_id: str,
    container_started: bool,
) -> dict[str, Any]:
    row = ledger.task_arm_row(task_arm_key)
    if (
        not isinstance(row, Mapping)
        or row.get("reservation_id") != reservation_id
        or row.get("status") != SCIENTIFIC_LEDGER_TERMINAL_STATUS
        or row.get("container_started") is not container_started
    ):
        raise BenchmarkExecutionError("cell-commit task-arm ledger binding differs")
    return dict(row)


def _validate_cell_result_ledger_pair(
    record: Mapping[str, Any],
    ledger_row: Mapping[str, Any],
    *,
    task_arm_key: str,
) -> None:
    try:
        validate_result_ledger_pair(
            record,
            ledger_row,
            ledger_task_arm_key=task_arm_key,
        )
    except ScientificTerminalContractError as exc:
        raise BenchmarkExecutionError(
            f"cell-commit result/ledger accounting differs: {exc}"
        ) from None


def _validate_reserved_task_arm_result_pair(
    record: Mapping[str, Any],
    ledger_row: Mapping[str, Any],
    *,
    task_arm_key: str,
    request_rows: Sequence[Mapping[str, Any]],
) -> None:
    """Validate the complete result projection before ledger terminalization."""

    try:
        validate_scientific_terminal_result(record)
    except ScientificTerminalContractError as exc:
        raise BenchmarkExecutionError(
            "cell-commit scientific result contract differs"
        ) from exc
    accounting = record.get("actual_accounting")
    if (
        not isinstance(accounting, Mapping)
        or set(ledger_row) != RESERVED_LEDGER_TASK_ARM_FIELDS
        or ledger_row.get("status") != "RESERVED"
        or ledger_row.get("actual_input_tokens") != accounting.get("input_tokens")
        or ledger_row.get("actual_model_calls")
        != accounting.get("model_gateway_calls")
        or ledger_row.get("actual_output_tokens") != accounting.get("output_tokens")
        or ledger_row.get("actual_decomposition_output_tokens")
        != accounting.get("actual_decomposition_output_tokens")
        or ledger_row.get("actual_solve_output_tokens")
        != accounting.get("actual_solve_output_tokens")
        or ledger_row.get("actual_extraction_output_tokens")
        != accounting.get("actual_extraction_output_tokens")
        or any(
            ledger_row.get(name) != 0
            for name in (
                "outstanding_input_tokens",
                "outstanding_model_calls",
                "outstanding_output_tokens",
            )
        )
    ):
        raise BenchmarkExecutionError(
            "cell-commit reserved task-arm/result accounting differs"
        )
    for role, actual_field in TASK_ACTUAL_OUTPUT_FIELD_BY_CALL_KIND.items():
        remaining_field = TASK_REMAINING_OUTPUT_FIELD_BY_CALL_KIND[role]
        if ledger_row.get(remaining_field) != (
            TASK_OUTPUT_POOL_BY_CALL_KIND[role] - int(accounting[actual_field])
        ):
            raise BenchmarkExecutionError(
                "cell-commit reserved task-arm role pool differs"
            )
    if request_rows or accounting.get("model_gateway_calls") or record.get(
        "failure_metadata"
    ) is not None:
        try:
            validate_result_request_statuses(record, list(request_rows))
        except ScientificTerminalContractError as exc:
            raise BenchmarkExecutionError(
                "cell-commit result/request lifecycle differs"
            ) from exc


def _validated_task_grader_lifecycle(task_dir: Path) -> dict[str, Any]:
    task_dir = _secure_retained_path(task_dir, task_dir, directory=True)
    terminal_root = _secure_retained_path(
        task_dir, task_dir / "terminal-journal", directory=True
    )
    grader_root = _secure_retained_path(
        task_dir, terminal_root / "grader", directory=True
    )
    paths = sorted(grader_root.glob("*.json"))
    if len(paths) != 1:
        raise BenchmarkExecutionError(
            "cell-commit requires exactly one grader lifecycle result"
        )
    grader_path = _secure_retained_path(task_dir, paths[0], directory=False)
    row = TerminalInvocationJournal._validated_grader_row(grader_path)
    if (
        row.get("status") != "GRADER_RESULT_VALIDATED"
        or row.get("official_grader_runs") != 1
        or row.get("grader_containers") != 1
        or row.get("grader_capacity_disposition") != "AUTHORITATIVE_RESULT"
        or not isinstance(row.get("result"), Mapping)
    ):
        raise BenchmarkExecutionError(
            "cell-commit grader lifecycle is not result-validated"
        )
    return row


def _validated_task_grader_result(task_dir: Path) -> Mapping[str, Any]:
    return dict(_validated_task_grader_lifecycle(task_dir)["result"])


_AGENT_RUN_RESULT_FIELDS = frozenset(
    {
        "run_id",
        "task_id",
        "arm",
        "resolved",
        "patch",
        "graph_snapshot",
        "grade",
        "extraction",
        "injections",
        "accounting",
        "evidence_tail_hash",
        "lifecycle_result",
        "cell_status",
        "model_failure_class",
        "grader_patch_source",
        "agent_completed",
        "extraction_status",
        "failure_metadata",
    }
)
_GRADE_RESULT_FIELDS = frozenset(
    {
        "task_id",
        "resolved",
        "exit_code",
        "stdout",
        "stderr",
        "report",
        "grader_id",
        "container_digest",
        "official",
        "wall_time_ms",
        "container_started",
        "status",
    }
)
_EXPERIENCE_EXTRACTION_FIELDS = frozenset(
    {
        "episode",
        "semantic_candidate",
        "response_hash",
        "patch_hash",
        "public_evidence_hash",
    }
)

_RESULT_EVIDENCE_FIELDS = frozenset(
    {
        "stdout",
        "stderr",
        "report",
        "raw_events",
        "checkout",
        "terminal_checkpoint",
        "restricted_grader_raw",
    }
)
_FILE_EVIDENCE_REFERENCE_FIELDS = frozenset({"path", "sha256", "bytes"})
_AGENT_CONFIG_HASH_FIELDS = frozenset(
    {
        "runtime",
        "task",
        "model",
        "memory_controller",
        "grader",
        "workspace",
        "lifecycle",
    }
)


def _is_link_or_reparse(path: Path) -> bool:
    try:
        value = os.lstat(path)
    except OSError:
        return path.is_symlink()
    return stat.S_ISLNK(value.st_mode) or bool(
        getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        & getattr(value, "st_file_attributes", 0)
    )


def _secure_retained_path(
    root: Path,
    path: Path,
    *,
    directory: bool,
) -> Path:
    """Return one non-symlink retained path confined beneath ``root``."""

    lexical_root = root.absolute()
    lexical_path = path.absolute()
    if _is_link_or_reparse(lexical_root) or not lexical_root.is_dir():
        raise BenchmarkExecutionError(
            "cell-commit retained evidence root is not a regular directory"
        )
    try:
        relative = lexical_path.relative_to(lexical_root)
    except ValueError as exc:
        raise BenchmarkExecutionError(
            "cell-commit retained evidence path escapes its task directory"
        ) from exc
    current = lexical_root
    for part in relative.parts:
        current = current / part
        if _is_link_or_reparse(current):
            raise BenchmarkExecutionError(
                "cell-commit retained evidence path contains a link or reparse point"
            )
    try:
        resolved_root = lexical_root.resolve(strict=True)
        resolved = lexical_path.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise BenchmarkExecutionError(
            "cell-commit retained evidence path is unavailable or escaped"
        ) from exc
    if directory:
        if not resolved.is_dir():
            raise BenchmarkExecutionError(
                "cell-commit retained evidence directory is invalid"
            )
    elif not resolved.is_file():
        raise BenchmarkExecutionError(
            "cell-commit retained evidence file is invalid"
        )
    return resolved


def _verified_file_evidence_reference(
    task_dir: Path,
    reference: object,
    expected_path: Path,
) -> bytes:
    if (
        not isinstance(reference, Mapping)
        or set(reference) != _FILE_EVIDENCE_REFERENCE_FIELDS
        or not isinstance(reference.get("path"), str)
        or not isinstance(reference.get("sha256"), str)
        or SHA256.fullmatch(str(reference["sha256"])) is None
        or type(reference.get("bytes")) is not int
        or reference["bytes"] < 0
    ):
        raise BenchmarkExecutionError(
            "cell-commit canonical evidence reference is malformed"
        )
    retained = _secure_retained_path(task_dir, expected_path, directory=False)
    relative = retained.relative_to(task_dir.resolve(strict=True)).as_posix()
    try:
        raw = retained.read_bytes()
    except OSError as exc:
        raise BenchmarkExecutionError(
            "cell-commit canonical evidence file is unavailable"
        ) from exc
    if (
        reference["path"] != relative
        or reference["bytes"] != len(raw)
        or reference["sha256"] != sha256_bytes(raw)
    ):
        raise BenchmarkExecutionError(
            "cell-commit canonical evidence bytes differ"
        )
    return raw


def _validated_restricted_grader_references(
    task_dir: Path,
    references: object,
) -> None:
    if not isinstance(references, list):
        raise BenchmarkExecutionError(
            "cell-commit restricted grader evidence references are malformed"
        )
    restricted_root = task_dir / "official-grader" / "restricted-evidence"
    if restricted_root.is_symlink():
        raise BenchmarkExecutionError(
            "cell-commit restricted grader evidence path is a symlink"
        )
    if not restricted_root.exists():
        if references:
            raise BenchmarkExecutionError(
                "cell-commit restricted grader evidence is absent"
            )
        return
    _secure_retained_path(task_dir, restricted_root, directory=True)
    paths = sorted(restricted_root.glob("*.bin"))
    if len(paths) != len(references):
        raise BenchmarkExecutionError(
            "cell-commit restricted grader evidence set differs"
        )
    for reference, path in zip(references, paths):
        _verified_file_evidence_reference(task_dir, reference, path)


def _checkpoint_evidence_blob(
    evidence: RawEvidenceLedger,
    reference: object,
    *,
    media_type: str,
) -> bytes:
    if (
        not isinstance(reference, Mapping)
        or set(reference) != {"sha256", "bytes", "media_type"}
        or reference.get("media_type") != media_type
        or not isinstance(reference.get("sha256"), str)
        or SHA256.fullmatch(str(reference["sha256"])) is None
        or type(reference.get("bytes")) is not int
        or reference["bytes"] < 0
    ):
        raise BenchmarkExecutionError(
            "cell-commit terminal checkpoint blob reference is malformed"
        )
    path = _secure_retained_path(
        evidence.root,
        evidence.blob_dir / str(reference["sha256"]),
        directory=False,
    )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise BenchmarkExecutionError(
            "cell-commit terminal checkpoint blob is unavailable"
        ) from exc
    if (
        len(raw) != reference["bytes"]
        or sha256_bytes(raw) != reference["sha256"]
    ):
        raise BenchmarkExecutionError(
            "cell-commit terminal checkpoint blob differs"
        )
    return raw


def _validate_cell_session_result_against_done_checkpoint_impl(
    task_dir: Path,
    journal_row: Mapping[str, Any],
    result_record: Mapping[str, Any],
    *,
    grader_result: Mapping[str, Any],
    expected_target: Mapping[str, Any],
) -> AgentRunResult:
    """Cross-bind a journal's inline result to retained runtime evidence.

    The cell journal is locally sealable, so its inline ``session_result`` is
    never an authority on its own.  Process-two authorization and recovery
    both call this verifier, which reconstructs the exact ``AgentRunResult``
    from a hash-sidecar-protected DONE checkpoint and its raw evidence ledger.
    """

    session_result = journal_row.get("session_result")
    binding = journal_row.get("binding")
    if (
        not isinstance(session_result, Mapping)
        or set(session_result) != _AGENT_RUN_RESULT_FIELDS
        or not isinstance(binding, Mapping)
    ):
        raise BenchmarkExecutionError(
            "cell-commit durable session result shape differs"
        )
    grade_payload = session_result.get("grade")
    extraction_payload = session_result.get("extraction")
    injections = session_result.get("injections")
    if (
        not isinstance(grade_payload, Mapping)
        or set(grade_payload) != _GRADE_RESULT_FIELDS
        or not isinstance(extraction_payload, Mapping)
        or set(extraction_payload) != _EXPERIENCE_EXTRACTION_FIELDS
        or not isinstance(injections, list)
        or any(not isinstance(row, Mapping) for row in injections)
        or not isinstance(session_result.get("graph_snapshot"), Mapping)
        or not isinstance(session_result.get("accounting"), Mapping)
        or not isinstance(session_result.get("lifecycle_result"), Mapping)
        or type(session_result.get("resolved")) is not bool
        or type(session_result.get("agent_completed")) is not bool
        or not isinstance(session_result.get("patch"), str)
        or not isinstance(session_result.get("evidence_tail_hash"), str)
        or SHA256.fullmatch(str(session_result["evidence_tail_hash"])) is None
    ):
        raise BenchmarkExecutionError(
            "cell-commit durable session result is malformed"
        )
    try:
        grade = GradeResult(**dict(grade_payload))
        semantic = extraction_payload.get("semantic_candidate")
        extraction = ExperienceExtraction(
            episode=dict(extraction_payload["episode"]),
            semantic_candidate=(
                dict(semantic) if semantic is not None else None
            ),
            response_hash=str(extraction_payload["response_hash"]),
            patch_hash=str(extraction_payload["patch_hash"]),
            public_evidence_hash=str(
                extraction_payload["public_evidence_hash"]
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BenchmarkExecutionError(
            "cell-commit durable session result cannot be reconstructed"
        ) from exc
    expected_run_id = re.sub(
        r"[^A-Za-z0-9_-]",
        "_",
        f"{binding.get('target_id')}-{binding.get('stream_id')}",
    )
    if (
        not isinstance(session_result.get("run_id"), str)
        or session_result["run_id"] != expected_run_id
        or session_result.get("task_id") != binding.get("target_id")
        or session_result.get("arm") != binding.get("arm")
        or grade.task_id != session_result.get("task_id")
        or grade.resolved is not session_result.get("resolved")
        or canonical_bytes(grade_payload) != canonical_bytes(grader_result)
    ):
        raise BenchmarkExecutionError(
            "cell-commit durable session identity/grader differs"
        )
    if (
        not isinstance(expected_target, Mapping)
        or expected_target.get("target_id") != session_result["task_id"]
        or not isinstance(expected_target.get("base_commit"), str)
        or HEX40.fullmatch(str(expected_target["base_commit"])) is None
        or not isinstance(expected_target.get("repository"), str)
        or not expected_target["repository"]
        or not isinstance(expected_target.get("workspace_checkout_root"), str)
        or not expected_target["workspace_checkout_root"]
        or (
            "benchmark_id" in expected_target
            and result_record.get("benchmark_id")
            != expected_target.get("benchmark_id")
        )
    ):
        raise BenchmarkExecutionError(
            "cell-commit durable session differs from the frozen target"
        )
    expected_task_config = expected_target.get("task_config_sha256")
    if (
        not isinstance(expected_task_config, str)
        or SHA256.fullmatch(expected_task_config) is None
    ):
        raise BenchmarkExecutionError(
            "cell-commit frozen task configuration hash is absent"
        )

    checkpoint_dir = task_dir / "agent-checkpoints"
    evidence_root = task_dir / "evidence"
    _secure_retained_path(task_dir, checkpoint_dir, directory=True)
    _secure_retained_path(task_dir, evidence_root, directory=True)
    blob_dir = evidence_root / "blobs"
    _secure_retained_path(task_dir, blob_dir, directory=True)
    for blob_path in blob_dir.iterdir():
        retained_blob = _secure_retained_path(
            task_dir, blob_path, directory=False
        )
        if (
            SHA256.fullmatch(retained_blob.name) is None
            or sha256_bytes(retained_blob.read_bytes()) != retained_blob.name
        ):
            raise BenchmarkExecutionError(
                "cell-commit retained evidence blob set is invalid"
            )
    events_path = evidence_root / "events.jsonl"
    _secure_retained_path(task_dir, events_path, directory=False)
    checkpoint_entries = list(checkpoint_dir.iterdir())
    if any(
        entry.is_symlink() or not entry.is_file() for entry in checkpoint_entries
    ) or {entry.name for entry in checkpoint_entries} != {
        f"{expected_run_id}.json",
        f"{expected_run_id}.sha256",
    }:
        raise BenchmarkExecutionError(
            "cell-commit agent checkpoint inventory differs"
        )
    checkpoint_path = checkpoint_dir / f"{session_result['run_id']}.json"
    checkpoint_sidecar = checkpoint_dir / f"{session_result['run_id']}.sha256"
    _secure_retained_path(task_dir, checkpoint_path, directory=False)
    _secure_retained_path(task_dir, checkpoint_sidecar, directory=False)
    try:
        terminal_checkpoint = FileCheckpointStore(checkpoint_dir).load(
            str(session_result["run_id"]),
            required_config_hashes=None,
            required_evidence_hash=str(session_result["evidence_tail_hash"]),
        )
        evidence = RawEvidenceLedger(evidence_root)
        evidence_summary = evidence.verify()
    except Exception as exc:
        raise BenchmarkExecutionError(
            "cell-commit retained DONE checkpoint/evidence is invalid"
        ) from exc
    if (
        terminal_checkpoint.state != "DONE"
        or terminal_checkpoint.run_id != session_result["run_id"]
        or terminal_checkpoint.task_id != session_result["task_id"]
        or terminal_checkpoint.arm != session_result["arm"]
        or evidence_summary.get("last_event_hash")
        != session_result["evidence_tail_hash"]
        or canonical_bytes(terminal_checkpoint.graph_snapshot)
        != canonical_bytes(session_result["graph_snapshot"])
        or canonical_bytes(terminal_checkpoint.injection_ledger)
        != canonical_bytes(injections)
        or canonical_bytes(terminal_checkpoint.accounting)
        != canonical_bytes(session_result["accounting"])
    ):
        raise BenchmarkExecutionError(
            "cell-commit session result differs from retained DONE checkpoint"
        )
    checkpoint_config_hashes = terminal_checkpoint.config_hashes
    if (
        not isinstance(checkpoint_config_hashes, Mapping)
        or set(checkpoint_config_hashes) != _AGENT_CONFIG_HASH_FIELDS
        or any(
            not isinstance(value, str) or SHA256.fullmatch(value) is None
            for value in checkpoint_config_hashes.values()
        )
        or checkpoint_config_hashes.get("task") != expected_task_config
        or canonical_bytes(result_record.get("agent_config_hashes"))
        != canonical_bytes(checkpoint_config_hashes)
    ):
        raise BenchmarkExecutionError(
            "cell-commit DONE checkpoint configuration differs from frozen authority"
        )

    record_evidence = result_record.get("evidence")
    if (
        result_record.get("terminal_state") != "DONE"
        or result_record.get("terminal_checkpoint_sha256")
        != terminal_checkpoint.content_hash
        or not isinstance(record_evidence, Mapping)
        or set(record_evidence) != _RESULT_EVIDENCE_FIELDS
    ):
        raise BenchmarkExecutionError(
            "cell-commit canonical result is not bound to the DONE checkpoint"
        )
    stdout_raw = _verified_file_evidence_reference(
        task_dir, record_evidence["stdout"], task_dir / "stdout.txt"
    )
    stderr_raw = _verified_file_evidence_reference(
        task_dir, record_evidence["stderr"], task_dir / "stderr.txt"
    )
    report_raw = _verified_file_evidence_reference(
        task_dir, record_evidence["report"], task_dir / "report.json"
    )
    _verified_file_evidence_reference(
        task_dir, record_evidence["raw_events"], events_path
    )
    checkout_raw = _verified_file_evidence_reference(
        task_dir,
        record_evidence["checkout"],
        task_dir / "checkout-evidence.json",
    )
    _verified_file_evidence_reference(
        task_dir,
        record_evidence["terminal_checkpoint"],
        checkpoint_path,
    )
    _validated_restricted_grader_references(
        task_dir, record_evidence["restricted_grader_raw"]
    )
    if (
        stdout_raw != grade.stdout.encode("utf-8")
        or stderr_raw != grade.stderr.encode("utf-8")
        or report_raw != json_file_bytes(grade.report)
    ):
        raise BenchmarkExecutionError(
            "cell-commit grader evidence differs from the DONE result"
        )
    try:
        checkout = strict_json_loads(checkout_raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise BenchmarkExecutionError(
            "cell-commit checkout evidence is invalid"
        ) from exc
    if (
        not isinstance(checkout, Mapping)
        or set(checkout)
        != {"argv", "stdout", "stderr", "head", "initial_status"}
        or not isinstance(checkout.get("argv"), list)
        or any(
            not isinstance(argv, list)
            or any(not isinstance(value, str) for value in argv)
            for argv in checkout["argv"]
        )
        or any(
            not isinstance(checkout.get(name), str)
            for name in ("stdout", "stderr", "head", "initial_status")
        )
        or checkout.get("head") != expected_target["base_commit"]
        or result_record.get("checkout_evidence_sha256")
        != sha256_bytes(canonical_bytes(checkout))
    ):
        raise BenchmarkExecutionError(
            "cell-commit checkout evidence differs from the frozen target"
        )

    terminal_payload = terminal_checkpoint.terminal_payload
    if not isinstance(terminal_payload, Mapping):
        raise BenchmarkExecutionError(
            "cell-commit DONE terminal payload is malformed"
        )
    if (
        terminal_payload.get("grade_sha256")
        != sha256_bytes(canonical_bytes(grade_payload))
        or canonical_bytes(terminal_payload.get("grade"))
        != canonical_bytes(grade_payload)
        or terminal_payload.get("extraction_sha256")
        != sha256_bytes(canonical_bytes(extraction_payload))
        or canonical_bytes(terminal_payload.get("extraction"))
        != canonical_bytes(extraction_payload)
    ):
        raise BenchmarkExecutionError(
            "cell-commit grade/extraction differs from DONE checkpoint"
        )
    storage = terminal_payload.get("storage_result")
    credit = terminal_payload.get("credit_result")
    lifecycle = {"storage": storage, "credit": credit}
    if (
        not isinstance(storage, Mapping)
        or not isinstance(credit, Mapping)
        or terminal_payload.get("storage_result_sha256")
        != sha256_bytes(canonical_bytes(storage))
        or terminal_payload.get("credit_result_sha256")
        != sha256_bytes(canonical_bytes(credit))
        or canonical_bytes(lifecycle)
        != canonical_bytes(session_result["lifecycle_result"])
        or (
            "lifecycle_result" in terminal_payload
            and canonical_bytes(terminal_payload["lifecycle_result"])
            != canonical_bytes(lifecycle)
        )
    ):
        raise BenchmarkExecutionError(
            "cell-commit lifecycle result differs from DONE checkpoint"
        )

    failed = session_result.get("cell_status") != "AGENT_COMPLETED"
    patch_reference = terminal_payload.get(
        "graded_patch" if failed else "patch"
    )
    try:
        patch = _checkpoint_evidence_blob(
            evidence,
            patch_reference,
            media_type="text/plain; charset=utf-8",
        ).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise BenchmarkExecutionError(
            "cell-commit terminal checkpoint patch is not UTF-8"
        ) from exc
    if (
        patch != session_result["patch"]
        or terminal_payload.get("patch_sha256")
        != sha256_bytes(patch.encode("utf-8"))
        or extraction.patch_hash != sha256_bytes(patch.encode("utf-8"))
    ):
        raise BenchmarkExecutionError(
            "cell-commit patch differs from DONE checkpoint/evidence"
        )

    try:
        workspace_checkout_root = Path(
            str(expected_target["workspace_checkout_root"])
        ).resolve(strict=True)
    except OSError as exc:
        raise BenchmarkExecutionError(
            "cell-commit frozen grader workspace is unavailable"
        ) from exc
    grader_lifecycle = _validated_task_grader_lifecycle(task_dir)
    expected_grader_request_sha256 = sha256_bytes(
        canonical_bytes(
            {
                "task_id": session_result["task_id"],
                "repository": expected_target["repository"],
                "base_commit": expected_target["base_commit"],
                "patch_sha256": sha256_bytes(patch.encode("utf-8")),
                "workspace_kind": "git_checkout",
                "workspace_base_commit": expected_target["base_commit"],
                "workspace_checkout_root": str(workspace_checkout_root),
            }
        )
    )
    if (
        grader_lifecycle.get("request_sha256")
        != expected_grader_request_sha256
        or grader_lifecycle.get("key")
        != f"{session_result['task_id']}:{expected_grader_request_sha256}"
    ):
        raise BenchmarkExecutionError(
            "cell-commit patch differs from the retained grader request"
        )

    raw_events: list[Mapping[str, Any]] = []
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line:
                event = strict_json_loads(line)
                if not isinstance(event, Mapping):
                    raise ValueError("event is not an object")
                raw_events.append(event)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise BenchmarkExecutionError(
            "cell-commit raw evidence events are malformed"
        ) from exc
    grader_requests = [
        event.get("payload")
        for event in raw_events
        if event.get("event_type") == "grader_request"
    ]
    grader_results = [
        event.get("payload")
        for event in raw_events
        if event.get("event_type") == "grader_result"
    ]
    if (
        len(grader_requests) != 1
        or len(grader_results) != 1
        or not isinstance(grader_requests[0], Mapping)
        or not isinstance(grader_results[0], Mapping)
    ):
        raise BenchmarkExecutionError(
            "cell-commit raw grader request/result evidence is incomplete"
        )
    raw_request = grader_requests[0]
    raw_result = grader_results[0]
    if (
        set(raw_request)
        != {
            "task_id",
            "arm",
            "repository",
            "base_commit",
            "workspace_kind",
            "patch",
        }
        or raw_request.get("task_id") != session_result["task_id"]
        or raw_request.get("arm") != session_result["arm"]
        or raw_request.get("repository") != expected_target["repository"]
        or raw_request.get("base_commit") != expected_target["base_commit"]
        or raw_request.get("workspace_kind") != "git_checkout"
        or _checkpoint_evidence_blob(
            evidence,
            raw_request.get("patch"),
            media_type="text/plain; charset=utf-8",
        )
        != patch.encode("utf-8")
    ):
        raise BenchmarkExecutionError(
            "cell-commit raw grader request differs from the graded patch"
        )
    raw_result_fields = {
        "task_id": grade.task_id,
        "arm": session_result["arm"],
        "official": grade.official,
        "grader_id": grade.grader_id,
        "container_digest": grade.container_digest,
        "exit_code": grade.exit_code,
        "resolved": grade.resolved,
        "container_started": grade.container_started,
        "status": grade.status,
        "wall_time_ms": grade.wall_time_ms,
    }
    if (
        set(raw_result)
        != set(raw_result_fields) | {"stdout", "stderr", "report"}
        or any(
            raw_result.get(name) != value
            for name, value in raw_result_fields.items()
        )
    ):
        raise BenchmarkExecutionError(
            "cell-commit raw grader result identity differs"
        )
    if (
        _checkpoint_evidence_blob(
            evidence,
            raw_result.get("stdout"),
            media_type="text/plain; charset=utf-8",
        )
        != grade.stdout.encode("utf-8")
        or _checkpoint_evidence_blob(
            evidence,
            raw_result.get("stderr"),
            media_type="text/plain; charset=utf-8",
        )
        != grade.stderr.encode("utf-8")
        or _checkpoint_evidence_blob(
            evidence,
            raw_result.get("report"),
            media_type="application/json",
        )
        != canonical_bytes(grade.report)
    ):
        raise BenchmarkExecutionError(
            "cell-commit raw grader result blobs differ"
        )
    expected_terminal_fields = (
        {
            "cell_status": terminal_payload.get("cell_status"),
            "model_failure_class": terminal_payload.get("model_failure_class"),
            "grader_patch_source": terminal_payload.get("grader_patch_source"),
            "agent_completed": terminal_payload.get("agent_completed"),
            "extraction_status": terminal_payload.get("extraction_status"),
            "failure_metadata": terminal_payload.get("failure_metadata"),
        }
        if failed
        else {
            "cell_status": "AGENT_COMPLETED",
            "model_failure_class": None,
            "grader_patch_source": "MODEL_PATCH",
            "agent_completed": True,
            "extraction_status": "SUCCESS",
            "failure_metadata": None,
        }
    )
    if any(
        canonical_bytes(session_result.get(name)) != canonical_bytes(value)
        for name, value in expected_terminal_fields.items()
    ):
        raise BenchmarkExecutionError(
            "cell-commit lifecycle status differs from DONE checkpoint"
        )

    record_pairs = {
        "agent_completed": session_result["agent_completed"],
        "cell_status": session_result["cell_status"],
        "container_started": grade.container_started,
        "evidence_tail_hash": session_result["evidence_tail_hash"],
        "extraction_status": session_result["extraction_status"],
        "failure_metadata": session_result["failure_metadata"],
        "grader_exit_code": grade.exit_code,
        "grader_patch_source": session_result["grader_patch_source"],
        "grader_status": grade.status,
        "model_failure_class": session_result["model_failure_class"],
        "official_grader": grade.official,
        "resolved": session_result["resolved"],
        "runtime_arm": session_result["arm"],
        "target_id": session_result["task_id"],
    }
    if any(
        canonical_bytes(result_record.get(name)) != canonical_bytes(value)
        for name, value in record_pairs.items()
    ):
        raise BenchmarkExecutionError(
            "cell-commit canonical result differs from durable session result"
        )
    task_wall_time_ms = result_record.get("actual_accounting", {}).get(
        "task_wall_time_ms"
    ) if isinstance(result_record.get("actual_accounting"), Mapping) else None
    if type(task_wall_time_ms) is not int or canonical_bytes(
        actual_accounting(
            session_result["accounting"],
            task_wall_time_ms=task_wall_time_ms,
        )
    ) != canonical_bytes(result_record.get("actual_accounting")):
        raise BenchmarkExecutionError(
            "cell-commit canonical accounting differs from DONE checkpoint"
        )
    if canonical_bytes(provider_outcome_accounting(session_result["accounting"])) != (
        canonical_bytes(result_record.get("provider_outcomes"))
    ):
        raise BenchmarkExecutionError(
            "cell-commit canonical provider outcomes differ from DONE checkpoint"
        )
    pricing = read_json(ROOT / "configs/trimem_v1/cost_plan.json").get(
        "model_pricing"
    )
    if not isinstance(pricing, Mapping) or result_record.get(
        "actual_usd"
    ) != actual_usd_for_accounting(result_record["actual_accounting"], pricing):
        raise BenchmarkExecutionError(
            "cell-commit canonical USD differs from frozen pricing/accounting"
        )
    durable_result = AgentRunResult(
        run_id=str(session_result["run_id"]),
        task_id=str(session_result["task_id"]),
        arm=str(session_result["arm"]),
        resolved=bool(session_result["resolved"]),
        patch=str(session_result["patch"]),
        graph_snapshot=dict(session_result["graph_snapshot"]),
        grade=grade,
        extraction=extraction,
        injections=tuple(dict(row) for row in injections),
        accounting=dict(session_result["accounting"]),
        evidence_tail_hash=str(session_result["evidence_tail_hash"]),
        lifecycle_result=dict(session_result["lifecycle_result"]),
        cell_status=str(session_result["cell_status"]),
        model_failure_class=(
            str(session_result["model_failure_class"])
            if session_result["model_failure_class"] is not None
            else None
        ),
        grader_patch_source=str(session_result["grader_patch_source"]),
        agent_completed=bool(session_result["agent_completed"]),
        extraction_status=str(session_result["extraction_status"]),
        failure_metadata=(
            dict(session_result["failure_metadata"])
            if isinstance(session_result["failure_metadata"], Mapping)
            else None
        ),
    )
    if canonical_bytes(actual_memory_metrics(durable_result, events_path)) != (
        canonical_bytes(result_record.get("actual_memory_metrics"))
    ):
        raise BenchmarkExecutionError(
            "cell-commit canonical memory metrics differ from raw evidence"
        )
    return durable_result


def validate_cell_session_result_against_done_checkpoint(
    task_dir: Path,
    journal_row: Mapping[str, Any],
    result_record: Mapping[str, Any],
    *,
    grader_result: Mapping[str, Any],
    expected_target: Mapping[str, Any],
) -> AgentRunResult:
    """Fail closed on every malformed retained session/checkpoint binding."""

    try:
        return _validate_cell_session_result_against_done_checkpoint_impl(
            task_dir,
            journal_row,
            result_record,
            grader_result=grader_result,
            expected_target=expected_target,
        )
    except BenchmarkExecutionError:
        raise
    except Exception as exc:
        raise BenchmarkExecutionError(
            "cell-commit retained DONE checkpoint/session validation failed"
        ) from exc


def _commit_scientific_cell_impl(
    *,
    task_dir: Path,
    task: CodingTask,
    target_id: str,
    stream_id: str,
    arm: str,
    sequence_index: int,
    task_arm_key: str,
    task_reservation: str,
    record: Mapping[str, Any],
    result: AgentRunResult,
    ledger: AtomicBudgetLedger,
    session: Any,
    output_root: Path,
    transition_hook: Optional[Callable[[str], None]] = None,
) -> Mapping[str, Any]:
    """Idempotently finish one validated scientific cell in frozen order."""

    try:
        validate_scientific_terminal_result(record)
    except ScientificTerminalContractError as exc:
        raise BenchmarkExecutionError(
            f"cell-commit refused a non-terminal scientific result: {exc}"
        ) from None
    if (
        record.get("execution_status") != SCIENTIFIC_EXECUTION_STATUS
        or result.grade.official is not True
        or result.grade.container_started is not True
    ):
        raise BenchmarkExecutionError(
            "cell-commit requires a validated authoritative grader result"
        )
    if dict(_validated_task_grader_result(task_dir)) != asdict(result.grade):
        raise BenchmarkExecutionError(
            "cell-commit grader lifecycle/result identity differs"
        )
    session_result = asdict(result)
    binding = _cell_commit_binding(
        stream_id=stream_id,
        arm=arm,
        target_id=target_id,
        sequence_index=sequence_index,
        task_arm_key=task_arm_key,
        task_reservation=task_reservation,
        record=record,
        grade=result.grade,
        session_result=session_result,
    )
    journal = CellCommitJournal(_cell_commit_path(task_dir), binding)
    state = journal.prepare(
        result_record=record,
        session_result=session_result,
    )["status"]
    if transition_hook is not None and state == "PREPARED":
        transition_hook("PREPARED")

    result_path = _cell_result_path(task_dir, task)
    expected_result_raw = json_file_bytes(record)
    if state == "PREPARED":
        if _is_link_or_reparse(result_path):
            raise BenchmarkExecutionError(
                "cell-commit canonical result path is linked"
            )
        if result_path.exists():
            result_path = _secure_retained_path(
                task_dir, result_path, directory=False
            )
            if result_path.read_bytes() != expected_result_raw:
                raise BenchmarkExecutionError(
                    "cell-commit existing canonical result bytes differ"
                )
        else:
            atomic_write(result_path, expected_result_raw)
        journal.transition(expected=("PREPARED",), status="RESULT_WRITTEN")
        state = "RESULT_WRITTEN"
        if transition_hook is not None:
            transition_hook(state)

    journal.verify_result(result_path, grader_result=result.grade)
    if state == "RESULT_WRITTEN":
        ledger_row = ledger.task_arm_row(task_arm_key)
        if not isinstance(ledger_row, Mapping):
            raise BenchmarkExecutionError("cell-commit task-arm ledger row is missing")
        if ledger_row.get("status") == "RESERVED":
            ledger_state = ledger._read()
            request_rows = [
                request
                for request in ledger_state.get("requests", {}).values()
                if isinstance(request, Mapping)
                and request.get("task_arm_key") == task_arm_key
            ]
            # Validate the complete result/request/accounting projection while
            # the task-arm row is still reversible.  A malformed fresh result
            # must never be able to mutate the ledger to CELL_TERMINAL.
            _validate_reserved_task_arm_result_pair(
                record,
                ledger_row,
                task_arm_key=task_arm_key,
                request_rows=request_rows,
            )
            ledger.complete_task_arm(
                task_arm_key,
                task_reservation,
                status=SCIENTIFIC_LEDGER_TERMINAL_STATUS,
                container_started=True,
            )
        ledger_row = _verified_terminal_ledger_row(
            ledger,
            task_arm_key=task_arm_key,
            reservation_id=task_reservation,
            container_started=True,
        )
        _validate_cell_result_ledger_pair(
            record, ledger_row, task_arm_key=task_arm_key
        )
        journal.transition(expected=("RESULT_WRITTEN",), status="LEDGER_TERMINAL")
        state = "LEDGER_TERMINAL"
        if transition_hook is not None:
            transition_hook(state)

    if state == "LEDGER_TERMINAL":
        terminal_ledger_row = _verified_terminal_ledger_row(
            ledger,
            task_arm_key=task_arm_key,
            reservation_id=task_reservation,
            container_started=True,
        )
        _validate_cell_result_ledger_pair(
            record, terminal_ledger_row, task_arm_key=task_arm_key
        )
        if getattr(session, "task_cursor", None) != sequence_index:
            raise BenchmarkExecutionError(
                "cell-commit canonical cursor is not at the expected transition"
            )
        advance = getattr(session, "after_task_and_checkpoint", None)
        if not callable(advance):
            raise BenchmarkExecutionError(
                "production session lacks atomic task/cursor checkpoint"
            )
        stream_checkpoint = advance(task, result)
        save_arm_checkpoint(output_root, stream_id, stream_checkpoint)
        journal.transition(
            expected=("LEDGER_TERMINAL",),
            status="CURSOR_ADVANCED",
            values={
                "stream_checkpoint_sha256": sha256_bytes(
                    canonical_bytes(stream_checkpoint)
                )
            },
        )
        state = "CURSOR_ADVANCED"
        if transition_hook is not None:
            transition_hook(state)

    if state == "CURSOR_ADVANCED":
        if getattr(session, "task_cursor", None) != sequence_index + 1:
            raise BenchmarkExecutionError(
                "cell-commit cursor-advanced evidence differs from canonical cursor"
            )
        journal_row = journal.prepare()
        _verified_cell_stream_checkpoint(output_root, stream_id, journal_row)
        journal.transition(expected=("CURSOR_ADVANCED",), status="COMMITTED")
        state = "COMMITTED"
        if transition_hook is not None:
            transition_hook(state)
    if state != "COMMITTED":
        raise BenchmarkExecutionError("cell-commit did not reach COMMITTED")
    return journal.prepare()


def commit_scientific_cell(
    *,
    task_dir: Path,
    task: CodingTask,
    target_id: str,
    stream_id: str,
    arm: str,
    sequence_index: int,
    task_arm_key: str,
    task_reservation: str,
    record: Mapping[str, Any],
    result: AgentRunResult,
    ledger: AtomicBudgetLedger,
    session: Any,
    output_root: Path,
    transition_hook: Optional[Callable[[str], None]] = None,
) -> Mapping[str, Any]:
    """Commit a cell, surfacing only hash-proven recovery as resume-safe."""

    try:
        return _commit_scientific_cell_impl(
            task_dir=task_dir,
            task=task,
            target_id=target_id,
            stream_id=stream_id,
            arm=arm,
            sequence_index=sequence_index,
            task_arm_key=task_arm_key,
            task_reservation=task_reservation,
            record=record,
            result=result,
            ledger=ledger,
            session=session,
            output_root=output_root,
            transition_hook=transition_hook,
        )
    except BenchmarkExecutionError:
        raise
    except Exception as exc:
        journal_path = _cell_commit_path(task_dir)
        if journal_path.is_file():
            # Only a fully hash-verified transaction containing both durable
            # payloads can authorize the wrapper's one recovery process.
            CellCommitJournal.read_verified(journal_path)
            raise BenchmarkProcessFailure(
                "RESUME_SAFE_CELL_COMMIT_JOURNAL",
                "cell commit stopped after a recoverable durable journal state",
            ) from exc
        raise


def verify_cell_commit_frontier(
    *,
    output_root: Path,
    stream_id: str,
    arm: str,
    tasks: Sequence[CodingTask],
    expected_targets: Sequence[Mapping[str, Any]],
    ledger: AtomicBudgetLedger,
    canonical_cursor: int,
) -> int:
    """Recompute the longest contiguous result+ledger CELL_TERMINAL prefix."""

    if type(canonical_cursor) is not int or not 0 <= canonical_cursor <= len(tasks):
        raise BenchmarkExecutionError("canonical stream cursor is invalid")
    if len(expected_targets) != len(tasks) or any(
        not isinstance(target, Mapping)
        or target.get("target_id") != task.task_id
        or target.get("base_commit") != task.commit
        for task, target in zip(tasks, expected_targets)
    ):
        raise BenchmarkExecutionError(
            "cell-commit frozen target/task sequence differs"
        )
    prefix = 0
    saw_gap = False
    for index, task in enumerate(tasks):
        task_dir, _run_id, _prepared = _task_recovery_paths(
            output_root, stream_id, index, task
        )
        result_path = _cell_result_path(task_dir, task)
        journal_path = _cell_commit_path(task_dir)
        if _is_link_or_reparse(result_path) or _is_link_or_reparse(
            journal_path
        ):
            raise BenchmarkExecutionError(
                "cell-commit frontier contains a linked result or journal"
            )
        task_arm_key = f"{stream_id}:{arm}:{task.task_id}"
        ledger_row = ledger.task_arm_row(task_arm_key)
        result_terminal = False
        if result_path.is_file():
            result_path = _secure_retained_path(
                task_dir, result_path, directory=False
            )
            record = read_json(result_path)
            try:
                validate_scientific_terminal_result(record)
                result_terminal = scientific_task_arm_key(record) == task_arm_key
            except ScientificTerminalContractError:
                result_terminal = False
        ledger_terminal = (
            isinstance(ledger_row, Mapping)
            and ledger_row.get("status") == SCIENTIFIC_LEDGER_TERMINAL_STATUS
        )
        if result_terminal and ledger_terminal and not saw_gap:
            if not journal_path.is_file():
                raise BenchmarkExecutionError(
                    "terminal cell has no hash-bound cell-commit journal"
                )
            journal_row = CellCommitJournal.read_verified(journal_path)
            binding = journal_row["binding"]
            grader_result = _validated_task_grader_result(task_dir)
            if (
                binding.get("stream_id") != stream_id
                or binding.get("arm") != arm
                or binding.get("expected_cursor") != index
                or binding.get("next_cursor") != index + 1
                or binding.get("task_arm_key") != task_arm_key
                or binding.get("task_arm_reservation_id")
                != ledger_row.get("reservation_id")
                or binding.get("result_sha256")
                != sha256_bytes(result_path.read_bytes())
                or binding.get("accounting_projection_sha256")
                != sha256_bytes(canonical_bytes(record["actual_accounting"]))
                or binding.get("grader_result_sha256")
                != sha256_bytes(canonical_bytes(grader_result))
                or binding.get("target_id") != record.get("target_id")
            ):
                raise BenchmarkExecutionError("cell-commit contiguous prefix binding differs")
            validate_cell_session_result_against_done_checkpoint(
                task_dir,
                journal_row,
                record,
                grader_result=grader_result,
                expected_target={
                    **dict(expected_targets[index]),
                    "task_config_sha256": task_configuration_sha256(task),
                },
            )
            _validate_cell_result_ledger_pair(
                record, ledger_row, task_arm_key=task_arm_key
            )
            prefix += 1
        else:
            saw_gap = True
            if result_terminal != ledger_terminal:
                # The sole allowed temporary asymmetry is RESULT_WRITTEN at
                # the current frontier; the journal proves its exact hash.
                if not journal_path.is_file():
                    raise BenchmarkExecutionError(
                        "result/ledger terminal prefix is not contiguous"
                    )
                journal_row = CellCommitJournal.read_verified(journal_path)
                journal = CellCommitJournal(journal_path, journal_row["binding"])
                grader_result = _validated_task_grader_result(task_dir)
                verified_record = journal.verify_result(
                    result_path,
                    grader_result=grader_result,
                )
                validate_cell_session_result_against_done_checkpoint(
                    task_dir,
                    journal_row,
                    verified_record,
                    grader_result=grader_result,
                    expected_target={
                        **dict(expected_targets[index]),
                        "task_config_sha256": task_configuration_sha256(task),
                    },
                )
                if not (
                    index == canonical_cursor
                    and result_terminal
                    and not ledger_terminal
                    and journal_row.get("status")
                    in {"PREPARED", "RESULT_WRITTEN"}
                ):
                    raise BenchmarkExecutionError(
                        "result/ledger terminal prefix is not contiguous"
                    )
            if index > prefix and (result_terminal or ledger_terminal):
                raise BenchmarkExecutionError(
                    "scientific terminal cells contain a non-contiguous suffix"
                )

    if prefix == canonical_cursor + 1 and canonical_cursor < len(tasks):
        task_dir, _run_id, _prepared = _task_recovery_paths(
            output_root, stream_id, canonical_cursor, tasks[canonical_cursor]
        )
        row = CellCommitJournal.read_verified(_cell_commit_path(task_dir))
        if row.get("status") not in {"RESULT_WRITTEN", "LEDGER_TERMINAL"}:
            raise BenchmarkExecutionError(
                "result/ledger prefix is ahead of cursor without a recoverable journal"
            )
    elif prefix != canonical_cursor:
        raise BenchmarkExecutionError(
            "canonical cursor differs from contiguous CELL_TERMINAL prefix"
        )

    for index in range(canonical_cursor):
        task_dir, _run_id, _prepared = _task_recovery_paths(
            output_root, stream_id, index, tasks[index]
        )
        row = CellCommitJournal.read_verified(_cell_commit_path(task_dir))
        journal = CellCommitJournal(_cell_commit_path(task_dir), row["binding"])
        state = row["status"]
        if state == "LEDGER_TERMINAL":
            if index != canonical_cursor - 1:
                raise BenchmarkExecutionError(
                    "cursor passed an unsealed cell-commit checkpoint"
                )
            checkpoint_sha256 = _cell_stream_checkpoint_sha256(
                output_root, stream_id, row["binding"]
            )
            row = journal.transition(
                expected=("LEDGER_TERMINAL",),
                status="CURSOR_ADVANCED",
                values={"stream_checkpoint_sha256": checkpoint_sha256},
            )
            state = "CURSOR_ADVANCED"
        if state == "CURSOR_ADVANCED":
            if index != canonical_cursor - 1:
                raise BenchmarkExecutionError(
                    "cursor passed an uncommitted scientific cell"
                )
            _verified_cell_stream_checkpoint(output_root, stream_id, row)
            journal.transition(expected=("CURSOR_ADVANCED",), status="COMMITTED")
            state = "COMMITTED"
        elif state == "COMMITTED" and index == canonical_cursor - 1:
            current_checkpoint = load_arm_checkpoint(output_root, stream_id)
            current_payload = _validated_checkpoint_envelope(current_checkpoint)
            if current_payload.get("stream_state") == "DEVELOPMENT_FINALIZED":
                if arm != "M2":
                    raise BenchmarkExecutionError(
                        "non-M2 stream has a finalized development checkpoint"
                    )
                load_development_finalization_binding(
                    output_root,
                    stream_id,
                    last_cell_journal_path=_cell_commit_path(task_dir),
                )
            else:
                _verified_cell_stream_checkpoint(output_root, stream_id, row)
        if state != "COMMITTED":
            raise BenchmarkExecutionError(
                "canonical cursor includes an uncommitted scientific cell"
            )
    return prefix


def _recover_cell_commit_frontier_impl(
    *,
    output_root: Path,
    stream_id: str,
    arm: str,
    tasks: Sequence[CodingTask],
    expected_targets: Sequence[Mapping[str, Any]],
    ledger: AtomicBudgetLedger,
    session: Any,
    canonical_cursor: int,
) -> int:
    """Finish the one hash-bound cell transaction at the cursor, if present."""

    verify_cell_commit_frontier(
        output_root=output_root,
        stream_id=stream_id,
        arm=arm,
        tasks=tasks,
        expected_targets=expected_targets,
        ledger=ledger,
        canonical_cursor=canonical_cursor,
    )
    if canonical_cursor >= len(tasks):
        return canonical_cursor
    task = tasks[canonical_cursor]
    task_dir, _run_id, _prepared = _task_recovery_paths(
        output_root, stream_id, canonical_cursor, task
    )
    journal_path = _cell_commit_path(task_dir)
    if not journal_path.is_file():
        return canonical_cursor
    row = CellCommitJournal.read_verified(journal_path)
    binding = row["binding"]
    task_arm_key = f"{stream_id}:{arm}:{task.task_id}"
    if (
        binding.get("stream_id") != stream_id
        or binding.get("arm") != arm
        or binding.get("expected_cursor") != canonical_cursor
        or binding.get("task_arm_key") != task_arm_key
    ):
        raise BenchmarkExecutionError("recoverable cell-commit identity differs")
    journal = CellCommitJournal(journal_path, binding)
    state = str(row["status"])
    if state not in {"PREPARED", "RESULT_WRITTEN", "LEDGER_TERMINAL"}:
        raise BenchmarkExecutionError(
            "cell-commit state disagrees with the canonical cursor"
        )
    result_path = _cell_result_path(task_dir, task)
    record = dict(row["result_record"])
    session_result = dict(row["session_result"])
    try:
        grade = GradeResult(**dict(session_result["grade"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise BenchmarkExecutionError(
            "cell-commit durable session grader result is malformed"
        ) from exc
    grader_result = dict(_validated_task_grader_result(task_dir))
    if grader_result != asdict(grade):
        raise BenchmarkExecutionError(
            "cell-commit grader lifecycle/session result differs"
        )
    durable_result = validate_cell_session_result_against_done_checkpoint(
        task_dir,
        row,
        record,
        grader_result=grader_result,
        expected_target={
            **dict(expected_targets[canonical_cursor]),
            "task_config_sha256": task_configuration_sha256(task),
        },
    )
    if state == "PREPARED":
        expected_raw = json_file_bytes(record)
        if _is_link_or_reparse(result_path):
            raise BenchmarkExecutionError(
                "cell-commit canonical result path is linked"
            )
        if result_path.exists() and result_path.read_bytes() != expected_raw:
            raise BenchmarkExecutionError(
                "cell-commit existing canonical result bytes differ"
            )
        if not result_path.exists():
            atomic_write(result_path, expected_raw)
        journal.transition(expected=("PREPARED",), status="RESULT_WRITTEN")
        state = "RESULT_WRITTEN"
    journal.verify_result(result_path, grader_result=grade)
    reservation = str(binding["task_arm_reservation_id"])
    if state == "RESULT_WRITTEN":
        ledger_row = ledger.task_arm_row(task_arm_key)
        if not isinstance(ledger_row, Mapping):
            raise BenchmarkExecutionError("recoverable task-arm ledger row is missing")
        if ledger_row.get("status") == "RESERVED":
            ledger_state = ledger._read()
            request_rows = [
                request
                for request in ledger_state.get("requests", {}).values()
                if isinstance(request, Mapping)
                and request.get("task_arm_key") == task_arm_key
            ]
            _validate_reserved_task_arm_result_pair(
                record,
                ledger_row,
                task_arm_key=task_arm_key,
                request_rows=request_rows,
            )
            ledger.complete_task_arm(
                task_arm_key,
                reservation,
                status=SCIENTIFIC_LEDGER_TERMINAL_STATUS,
                container_started=True,
            )
        recovered_ledger_row = _verified_terminal_ledger_row(
            ledger,
            task_arm_key=task_arm_key,
            reservation_id=reservation,
            container_started=True,
        )
        _validate_cell_result_ledger_pair(
            record, recovered_ledger_row, task_arm_key=task_arm_key
        )
        journal.transition(expected=("RESULT_WRITTEN",), status="LEDGER_TERMINAL")
        state = "LEDGER_TERMINAL"
    if state == "LEDGER_TERMINAL":
        recovered_ledger_row = _verified_terminal_ledger_row(
            ledger,
            task_arm_key=task_arm_key,
            reservation_id=reservation,
            container_started=True,
        )
        _validate_cell_result_ledger_pair(
            record, recovered_ledger_row, task_arm_key=task_arm_key
        )
        session.before_task(task, canonical_cursor)
        session.controller_for(task)
        advance = getattr(session, "after_task_and_checkpoint", None)
        if not callable(advance):
            raise BenchmarkExecutionError(
                "production session lacks atomic task/cursor checkpoint"
            )
        checkpoint = advance(task, durable_result)
        save_arm_checkpoint(output_root, stream_id, checkpoint)
        cursor_row = journal.transition(
            expected=("LEDGER_TERMINAL",),
            status="CURSOR_ADVANCED",
            values={
                "stream_checkpoint_sha256": sha256_bytes(
                    canonical_bytes(checkpoint)
                )
            },
        )
        _verified_cell_stream_checkpoint(output_root, stream_id, cursor_row)
        journal.transition(expected=("CURSOR_ADVANCED",), status="COMMITTED")
    recovered_cursor = getattr(session, "task_cursor", None)
    if recovered_cursor != canonical_cursor + 1:
        raise BenchmarkExecutionError(
            "recovered cell-commit did not advance the canonical cursor"
        )
    verify_cell_commit_frontier(
        output_root=output_root,
        stream_id=stream_id,
        arm=arm,
        tasks=tasks,
        expected_targets=expected_targets,
        ledger=ledger,
        canonical_cursor=recovered_cursor,
    )
    return int(recovered_cursor)


def recover_cell_commit_frontier(
    *,
    output_root: Path,
    stream_id: str,
    arm: str,
    tasks: Sequence[CodingTask],
    expected_targets: Sequence[Mapping[str, Any]],
    ledger: AtomicBudgetLedger,
    session: Any,
    canonical_cursor: int,
) -> int:
    """Recover one verified commit and expose only that state as resume-safe."""

    try:
        return _recover_cell_commit_frontier_impl(
            output_root=output_root,
            stream_id=stream_id,
            arm=arm,
            tasks=tasks,
            expected_targets=expected_targets,
            ledger=ledger,
            session=session,
            canonical_cursor=canonical_cursor,
        )
    except BenchmarkExecutionError:
        raise
    except Exception as exc:
        if canonical_cursor < len(tasks):
            task_dir, _run_id, _prepared = _task_recovery_paths(
                output_root, stream_id, canonical_cursor, tasks[canonical_cursor]
            )
            journal_path = _cell_commit_path(task_dir)
            if journal_path.is_file():
                CellCommitJournal.read_verified(journal_path)
                raise BenchmarkProcessFailure(
                    "RESUME_SAFE_CELL_COMMIT_JOURNAL",
                    "cell-commit recovery stopped with a verified durable journal",
                ) from exc
        raise


def load_latest_task_recovery_proofs(
    root: Path,
    *,
    stream_id: str,
    tasks: Sequence[CodingTask],
) -> tuple[Optional[RuntimeCheckpoint], Optional[Mapping[str, Any]]]:
    """Load hash-verified local proofs before touching the canonical session.

    The prepared-task envelope is written before decomposition.  Every later
    AgentRuntime checkpoint must therefore have one; accepting an agent file
    without it would reopen the before-first-checkpoint timestamp window.
    """

    latest_agent: Optional[RuntimeCheckpoint] = None
    latest_prepared: Optional[Mapping[str, Any]] = None
    latest_agent_index = -1
    latest_prepared_index = -1
    for index, task in enumerate(tasks):
        task_dir, run_id, prepared_path = _task_recovery_paths(
            root, stream_id, index, task
        )
        prepared = None
        if prepared_path.exists():
            prepared = read_json(prepared_path)
            if not isinstance(prepared, Mapping):
                raise BenchmarkExecutionError("prepared-task checkpoint is invalid")
            latest_prepared = dict(prepared)
            latest_prepared_index = index
        checkpoint_dir = task_dir / "agent-checkpoints"
        checkpoint_path = checkpoint_dir / f"{run_id}.json"
        sidecar_path = checkpoint_dir / f"{run_id}.sha256"
        if checkpoint_path.exists() != sidecar_path.exists():
            raise BenchmarkExecutionError("agent checkpoint/sidecar is incomplete")
        if not checkpoint_path.exists():
            continue
        if prepared is None:
            raise BenchmarkExecutionError(
                "agent checkpoint has no pre-external-call prepared-task checkpoint"
            )
        checkpoint = FileCheckpointStore(checkpoint_dir).load(
            run_id, required_config_hashes=None
        )
        evidence = RawEvidenceLedger(task_dir / "evidence")
        evidence.verified_suffix(checkpoint.evidence_event_hash)
        evidence.verify()
        if checkpoint.task_id != task.task_id:
            raise BenchmarkExecutionError("agent checkpoint task identity mismatch")
        latest_agent = checkpoint
        latest_agent_index = index
    if latest_agent_index > latest_prepared_index:
        raise BenchmarkExecutionError("latest agent checkpoint lacks task preparation")
    return latest_agent, latest_prepared


def _arm_identity_path(root: Path, arm: str) -> Path:
    return root / f"{arm}.session-identity.json"


def prepare_arm_identity(
    root: Path,
    *,
    arm: str,
    split: str,
    experiment_id: str,
    execution_lock_hash: str,
    resume: bool,
) -> dict[str, Any]:
    """Persist the recovery nonce atomically before PostgreSQL is first touched."""

    path = _arm_identity_path(root, arm)
    expected = {
        "schema": "trimem/benchmark-arm-session-identity/1.0",
        "arm": arm,
        "split": split,
        "experiment_id": experiment_id,
        "execution_lock_hash": execution_lock_hash,
    }
    if resume:
        if not path.is_file():
            raise BenchmarkExecutionError("resume session identity is missing")
        envelope = read_json(path)
        payload = envelope.get("payload")
        digest = envelope.get("digest")
        if not isinstance(payload, Mapping) or digest != "sha256:" + sha256_bytes(
            canonical_bytes(payload)
        ):
            raise BenchmarkExecutionError("resume session identity digest mismatch")
        if any(payload.get(name) != value for name, value in expected.items()):
            raise BenchmarkExecutionError("resume session identity/configuration mismatch")
        try:
            run_nonce = str(uuid.UUID(str(payload.get("run_nonce"))))
        except (ValueError, AttributeError) as exc:
            raise BenchmarkExecutionError("resume session nonce is not a canonical UUID") from exc
        if payload.get("run_nonce") != run_nonce:
            raise BenchmarkExecutionError("resume session nonce is not canonical")
        return dict(payload)

    if path.exists():
        raise BenchmarkExecutionError(
            "session identity already exists; use --resume or a fresh output root"
        )
    payload = {**expected, "run_nonce": str(uuid.uuid4())}
    envelope = {
        "payload": payload,
        "digest": "sha256:" + sha256_bytes(canonical_bytes(payload)),
    }
    write_json(path, envelope)
    return payload


def build_execution_lock_hash(
    *,
    split: str,
    arm: str,
    stream_id: str,
    approval: Mapping[str, Any],
    targets: Sequence[Mapping[str, Any]],
    rows: Mapping[str, Mapping[str, Any]],
    tasks: Sequence[CodingTask],
    workspace_factory: GitCheckoutWorkspaceFactory,
    harnesses: Mapping[str, Path],
    images: Mapping[str, Mapping[str, Any]],
    model_lock: Mapping[str, Any],
    m2_manifest: Optional[Mapping[str, Any]],
    checkpoint_path: Optional[Path],
    runtime_lock: RuntimeLock,
    identity_seed_evidence: Mapping[str, Any],
    official_harness_loader_preflight: Mapping[str, Any],
) -> str:
    """Bind every execution-affecting artifact needed across task-boundary resume."""

    lock_paths = (
        ROOT / "configs/trimem_v1/model_lock.json",
        ROOT / "configs/trimem_v1/m2_policy.json",
        ROOT / "configs/trimem_v1/m2_candidate_bundles.json",
        ROOT / "configs/trimem_v1/selected_m2.json",
        ROOT / "configs/trimem_v1/grader_lock.json",
        ROOT / "configs/trimem_v1/benchmark_environment_lock.json",
        ROOT / "configs/trimem_v1/benchmark_environment.lock",
        ROOT / "configs/trimem_v1/benchmark_environment.in",
        ROOT / "artifacts/trimem_v1/grader_image_lock.json",
        ROOT / "artifacts/trimem_v1/freeze.json",
        ROOT / MANIFESTS[split],
        *(ROOT / "configs/trimem_v1/m2_candidates" / f"{candidate_id}.json"
          for candidate_id in CANDIDATE_IDS),
    )
    files = []
    for path in lock_paths:
        git_tracked(path)
        raw = path.read_bytes()
        files.append(
            {
                "path": path.resolve().relative_to(ROOT.resolve()).as_posix(),
                "sha256": sha256_bytes(raw),
                "bytes": len(raw),
            }
        )
    harness_revisions = {}
    for benchmark_id, path in sorted(harnesses.items()):
        harness_revisions[benchmark_id] = _run_command(
            ["git", "-C", str(path), "rev-parse", "HEAD"]
        ).stdout.strip()
    selected_checkpoint = None
    if checkpoint_path is not None:
        git_tracked(checkpoint_path)
        selected_checkpoint = {
            "sha256": sha256_bytes(checkpoint_path.read_bytes()),
            "bytes": checkpoint_path.stat().st_size,
        }
    task_payloads = [task.public_payload() for task in tasks]
    source_rows = {
        target["instance_id"]: rows[target["instance_id"]]
        for target in targets
    }
    selected_images = {
        target["instance_id"]: images[target["instance_id"]]
        for target in targets
    }
    payload = {
        "schema": "trimem/full-execution-lock/1.0",
        "git_head": approval["git_head"],
        "approval_artifact_sha256": approval["approval_artifact_sha256"],
        "freeze_sha256": approval["freeze_sha256"],
        "split": split,
        "arm": arm,
        "stream_id": stream_id,
        "target_sequence_sha256": sequence_sha256(list(targets)),
        "targets": list(targets),
        "source_rows": source_rows,
        "task_public_payloads": task_payloads,
        "runtime_lock_hash": runtime_lock.content_hash,
        "runtime_lock": runtime_lock.to_manifest(),
        "workspace_factory_hash": workspace_factory.content_hash,
        "model_lock": dict(model_lock),
        "m2_policy": dict(m2_manifest) if isinstance(m2_manifest, Mapping) else None,
        "selected_m2_checkpoint": selected_checkpoint,
        "identity_seed_evidence": dict(identity_seed_evidence),
        "official_harness_loader_preflight_sha256": sha256_bytes(
            canonical_bytes(official_harness_loader_preflight)
        ),
        "harness_revisions": harness_revisions,
        "grader_images": selected_images,
        "committed_files": files,
    }
    return "sha256:" + sha256_bytes(canonical_bytes(payload))


_TERMINAL_RESULT_OWNED_FIELDS = frozenset(
    {
        "actual_accounting",
        "actual_memory_metrics",
        "actual_usd",
        "agent_completed",
        "cell_status",
        "container_started",
        "evidence",
        "execution_status",
        "extraction_status",
        "failure_metadata",
        "grader_exit_code",
        "grader_patch_source",
        "grader_status",
        "model_failure_class",
        "official_grader",
        "provider_outcomes",
        "resolved",
    }
)


def build_terminal_result_record(
    *,
    result: AgentRunResult,
    actual_accounting: Mapping[str, Any],
    actual_memory_metrics: Mapping[str, Any],
    provider_outcomes: Mapping[str, Any],
    actual_usd: str,
    static_fields: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Serialize one current scientific cell through the shared contract.

    The caller supplies identity/evidence bindings, while this function owns
    every scientific terminal-status field.  That separation prevents a test
    fixture or resume path from silently overriding the producer semantics.
    """

    overlap = sorted(_TERMINAL_RESULT_OWNED_FIELDS & set(static_fields))
    if overlap:
        raise BenchmarkExecutionError(
            f"terminal result static fields override producer fields: {overlap}"
        )
    record = {
        **dict(static_fields),
        "actual_accounting": dict(actual_accounting),
        "actual_memory_metrics": dict(actual_memory_metrics),
        "provider_outcomes": dict(provider_outcomes),
        "actual_usd": actual_usd,
        "execution_status": SCIENTIFIC_EXECUTION_STATUS,
        "grader_exit_code": result.grade.exit_code,
        "grader_status": result.grade.status,
        "container_started": result.grade.container_started,
        "cell_status": result.cell_status,
        "model_failure_class": result.model_failure_class,
        "failure_metadata": (
            dict(getattr(result, "failure_metadata"))
            if getattr(result, "failure_metadata", None) is not None
            else None
        ),
        "agent_completed": result.agent_completed,
        "grader_patch_source": result.grader_patch_source,
        "extraction_status": result.extraction_status,
        "official_grader": result.grade.official,
        "resolved": result.resolved,
        "evidence": dict(evidence),
    }
    try:
        validate_scientific_terminal_result(record)
    except ScientificTerminalContractError as exc:
        raise BenchmarkExecutionError(
            f"terminal result producer contract failed: {exc}"
        ) from None
    return record


def run_arm_stream(
    *, split: str, arm: str, stream_id: str, runtime_lock: RuntimeLock,
    m2_manifest: Optional[Mapping[str, Any]], dqn_checkpoint_path: Optional[Path],
    selected_prompt_candidate_id: str,
    approval: Mapping[str, Any], targets: list[dict[str, Any]],
    rows: Mapping[str, Mapping[str, Any]], tasks: list[CodingTask], workspace_factory: GitCheckoutWorkspaceFactory,
    checkout_evidence: Mapping[str, Mapping[str, Any]], harnesses: Mapping[str, Path], output_root: Path,
    ledger: AtomicBudgetLedger, database_url: str, qdrant_url: str, resume: bool,
    identity_seed_evidence: Mapping[str, Any],
    official_harness_loader_preflight: Mapping[str, Any],
) -> dict[str, Any]:
    if arm not in ARMS or not isinstance(stream_id, str) or not stream_id:
        raise BenchmarkExecutionError("invalid benchmark runtime arm/stream identity")
    digest = sequence_sha256(targets)
    experiment_id = "trimemv1-" + approval["git_head"][:12] + "-" + re.sub(
        r"[^a-z0-9-]", "-", stream_id.lower()
    )
    seed_body = {
        key: value for key, value in identity_seed_evidence.items() if key != "digest"
    }
    if (
        identity_seed_evidence.get("schema")
        != "trimem/benchmark-identity-seed-evidence/1.0"
        or identity_seed_evidence.get("experiment_id") != experiment_id
        or identity_seed_evidence.get("stream_id") != stream_id
        or identity_seed_evidence.get("digest") != canonical_hash(seed_body)
        or len(identity_seed_evidence.get("rows", ())) != len(tasks)
        or "database_url" in json.dumps(identity_seed_evidence).casefold()
    ):
        raise BenchmarkExecutionError("admin identity seed evidence is absent or inconsistent")
    model_lock = read_json(ROOT / "configs/trimem_v1/model_lock.json")
    embedder_lock = model_lock["retrieval_embedding"]["production"]
    if arm != "M2" and (
        m2_manifest is not None or dqn_checkpoint_path is not None
    ):
        raise BenchmarkExecutionError(
            "M0/M1 cannot receive an M2 policy/checkpoint"
        )
    lifecycle_factory = None
    if arm == "M2":
        if not isinstance(m2_manifest, Mapping):
            raise BenchmarkExecutionError("M2 stream has no frozen full-policy manifest")
        m2_hash = "sha256:" + sha256_bytes(canonical_bytes(m2_manifest))
        lifecycle_factory = production_dqn_lifecycle_factory(
            repository_identity_resolver(experiment_id, stream_id),
            policy_manifest=m2_manifest,
            expected_policy_manifest_hash=m2_hash,
        )
    elif arm == "M1":
        # Every arm deliberately has its own solve-job identity.  A lookup by
        # only org/user/repository/task becomes ambiguous once another stream
        # has been seeded, so M1 must use the same exact stream-bound resolver
        # as M2 rather than the database fallback resolver.
        lifecycle_factory = production_v03_lifecycle_factory(
            identity_resolver=repository_identity_resolver(
                experiment_id, stream_id
            )
        )
    images, support = image_entries(require_benchmark=True)
    execution_lock_hash = build_execution_lock_hash(
        split=split,
        arm=arm,
        stream_id=stream_id,
        approval=approval,
        targets=targets,
        rows=rows,
        tasks=tasks,
        workspace_factory=workspace_factory,
        harnesses=harnesses,
        images=images,
        model_lock=model_lock,
        m2_manifest=m2_manifest,
        checkpoint_path=dqn_checkpoint_path,
        runtime_lock=runtime_lock,
        identity_seed_evidence=identity_seed_evidence,
        official_harness_loader_preflight=official_harness_loader_preflight,
    )
    identity = prepare_arm_identity(
        output_root,
        arm=stream_id,
        split=split,
        experiment_id=experiment_id,
        execution_lock_hash=execution_lock_hash,
        resume=resume,
    )
    run_nonce = identity["run_nonce"]
    cell_target_authorities = [
        {
            **dict(target),
            "workspace_checkout_root": str(
                workspace_factory.checkout_roots[task.task_id]
            ),
        }
        for task, target in zip(tasks, targets)
    ]
    inflight_proof: Optional[RuntimeCheckpoint] = None
    prepared_proof: Optional[Mapping[str, Any]] = None
    if resume:
        inflight_proof, prepared_proof = load_latest_task_recovery_proofs(
            output_root, stream_id=stream_id, tasks=tasks
        )
    session = open_benchmark_arm(
        database_url=database_url, qdrant_url=qdrant_url, experiment_id=experiment_id,
        split=split, arm_id=arm, task_order=tasks, dqn_checkpoint_path=dqn_checkpoint_path,
        embedder_lock=embedder_lock, evaluation=(split == "heldout"),
        lifecycle_factory=lifecycle_factory, run_nonce=run_nonce,
        execution_lock_hash=execution_lock_hash,
    )
    client = None
    try:
        if resume:
            restore_stream = getattr(session, "resume_canonical_stream", None)
            if not callable(restore_stream):
                raise BenchmarkExecutionError("production session lacks canonical crash recovery")
            checkpoint = restore_stream(
                inflight_checkpoint=inflight_proof,
                prepared_task_checkpoint=prepared_proof,
                allow_development_finalization=(
                    arm == "M2" and split == "development"
                ),
            )
            if checkpoint is not None:
                checkpoint_payload = _validated_checkpoint_envelope(checkpoint)
                if checkpoint_payload.get("stream_state") == "DEVELOPMENT_FINALIZED":
                    if not tasks:
                        raise BenchmarkExecutionError(
                            "finalized development stream has no task predecessor"
                        )
                    last_task_dir, _last_run_id, _last_prepared = (
                        _task_recovery_paths(
                            output_root,
                            stream_id,
                            len(tasks) - 1,
                            tasks[-1],
                        )
                    )
                    local_checkpoint = load_arm_checkpoint(output_root, stream_id)
                    local_payload = _validated_checkpoint_envelope(local_checkpoint)
                    if local_payload.get("stream_state") == "DEVELOPMENT_FINALIZED":
                        if canonical_bytes(local_checkpoint) != canonical_bytes(
                            checkpoint
                        ):
                            raise BenchmarkExecutionError(
                                "canonical finalized checkpoint differs from local evidence"
                            )
                        load_development_finalization_binding(
                            output_root,
                            stream_id,
                            last_cell_journal_path=_cell_commit_path(last_task_dir),
                        )
                    else:
                        save_development_finalized_arm_checkpoint(
                            output_root,
                            stream_id,
                            checkpoint,
                            last_cell_journal_path=_cell_commit_path(last_task_dir),
                        )
                else:
                    save_arm_checkpoint(output_root, stream_id, checkpoint)
            cursor = session.task_cursor
        else:
            freshness = session.assert_fresh()
            write_json(output_root / f"{stream_id}.freshness.json", freshness)
            cursor = 0
        gateway, client = build_paid_model_gateway(
            session, ledger, model_lock, stream_id=stream_id,
            restricted_response_root=(
                output_root / "restricted-provider-responses" / stream_id
            ),
        )
        verify_cell_commit_frontier(
            output_root=output_root,
            stream_id=stream_id,
            arm=arm,
            tasks=tasks,
            expected_targets=cell_target_authorities,
            ledger=ledger,
            canonical_cursor=cursor,
        )
        if resume:
            cursor = recover_cell_commit_frontier(
                output_root=output_root,
                stream_id=stream_id,
                arm=arm,
                tasks=tasks,
                expected_targets=cell_target_authorities,
                ledger=ledger,
                session=session,
                canonical_cursor=cursor,
            )
        for index in range(cursor, len(tasks)):
            task, target = tasks[index], targets[index]
            if target["instance_id"] not in images:
                raise BenchmarkExecutionError(f"grader image missing for {target['target_id']}")
            task_dir, run_id, prepared_path = _task_recovery_paths(
                output_root, stream_id, index, task
            )
            task_dir.mkdir(parents=True, exist_ok=True)
            task_arm_key = f"{stream_id}:{arm}:{task.task_id}"
            task_status = ledger.task_arm_status(task_arm_key)
            if task_status is None:
                task_reservation = ledger.reserve_task_arm(task_arm_key)
            elif resume and task_status == "RESERVED":
                task_reservation = ledger.resume_task_arm(task_arm_key)
            elif resume and task_status == SCIENTIFIC_LEDGER_TERMINAL_STATUS:
                journal_path = _cell_commit_path(task_dir)
                if not journal_path.is_file():
                    raise BenchmarkExecutionError(
                        "terminal task-arm has no cell-commit recovery journal"
                    )
                cell_row = CellCommitJournal.read_verified(journal_path)
                if cell_row.get("status") != "LEDGER_TERMINAL":
                    raise BenchmarkExecutionError(
                        "terminal task-arm is not at the recoverable cursor frontier"
                    )
                task_reservation = str(
                    cell_row["binding"]["task_arm_reservation_id"]
                )
            else:
                raise BenchmarkExecutionError("task-arm cap ledger state does not match the stream cursor")
            task_started_ns = time.perf_counter_ns()
            evidence = RawEvidenceLedger(task_dir / "evidence")
            checkpoints = FileCheckpointStore(task_dir / "agent-checkpoints")
            journal = TerminalInvocationJournal(task_dir / "terminal-journal")
            session.before_task(task, index)
            if not prepared_path.exists():
                prepare_checkpoint = getattr(
                    session, "prepared_task_checkpoint", None
                )
                if not callable(prepare_checkpoint):
                    raise BenchmarkExecutionError(
                        "production session lacks pre-external-call task checkpointing"
                    )
                write_json(prepared_path, prepare_checkpoint(task))
            controller = session.controller_for(task)
            official_grader = grader_factory(
                target, rows[target["instance_id"]], images[target["instance_id"]],
                harnesses, task_dir / "official-grader", arm, support,
                loader_preflight_evidence=official_harness_loader_preflight,
            )
            grader = JournaledGraderGateway(
                official_grader,
                journal,
                preflight_evidence=official_harness_loader_preflight,
            )
            task_gateway = JournaledModelGateway(gateway, journal)
            runtime = TriMemAgentRuntime(
                runtime_lock=runtime_lock, model_gateway=task_gateway, grader_gateway=grader,
                memory_controller=controller, evidence=evidence, checkpoint_store=checkpoints,
                lifecycle=session.lifecycle, workspace_factory=workspace_factory,
                model_config_hash=sha256_bytes(canonical_bytes({
                    "execution_lock_hash": execution_lock_hash,
                    "primary_model": model_lock.get("primary_model"),
                })),
                grader_config_hash=sha256_bytes(canonical_bytes({
                    "execution_lock_hash": execution_lock_hash,
                    "target": target,
                    "source_row_sha256": target["source_row_sha256"],
                    "grader_image": images[target["instance_id"]],
                })),
            )
            agent_checkpoint = task_dir / "agent-checkpoints" / f"{run_id}.json"
            try:
                result = runtime.run(task, arm=arm, run_id=run_id, resume=agent_checkpoint.is_file())
            except GatewayInvocationFailure as failure:
                receipt = {
                    "schema": "trimem/provider-terminal-failure-receipt/1.0",
                    "task_id": task.task_id,
                    "arm": arm,
                    "stream_id": stream_id,
                    "logical_provider_status": failure.status,
                    "original_provider_terminal_classification": (
                        failure.original_provider_terminal_classification
                    ),
                    "provider_request_id_sha256": (
                        sha256_bytes(failure.provider_request_id.encode("utf-8"))
                        if failure.provider_request_id
                        else None
                    ),
                    "response_id": failure.response_id,
                    "response_status": failure.response_status,
                    "response_error_code": failure.response_error_code,
                    "incomplete_reason": failure.incomplete_reason,
                    "output_item_types": list(failure.output_item_types),
                    "content_item_types": list(failure.content_item_types),
                    "refusal_present": failure.refusal_present,
                    "provider_reported_usage": {
                        "available": failure.provider_reported_usage_available,
                        "input_tokens": failure.input_tokens,
                        "cached_input_tokens": failure.cached_input_tokens,
                        "output_tokens": failure.output_tokens,
                        "reasoning_tokens": failure.reasoning_tokens,
                    },
                    "ledger_reservation": failure.ledger_reservation,
                    "raw_envelope_reference": failure.raw_envelope_reference,
                    "extracted_text_bytes": failure.extracted_text_bytes,
                    "structured_output_bytes": failure.structured_output_bytes,
                    "provider_response_envelope": failure.provider_response_envelope,
                    "scientific_result_available": False,
                }
                receipt_path = task_dir / "provider-failure-receipt.json"
                if receipt_path.exists() and read_json(receipt_path) != receipt:
                    raise BenchmarkExecutionError(
                        "resumed provider failure differs from its durable receipt"
                    ) from failure
                if not receipt_path.exists():
                    write_json(receipt_path, receipt)
                raise
            except GraderInvocationFailure as failure:
                # Infrastructure outcomes are campaign evidence, never scored
                # task-arm terminals.  The outstanding reservation remains
                # consumed and cannot enter the contiguous scientific prefix.
                raise BenchmarkProcessFailure(
                    "GLOBAL_GRADER_INFRA_FAILURE",
                    "official grader failed before an authoritative result: "
                    + failure.result.status,
                ) from failure
            terminal_checkpoint = checkpoints.load(
                run_id, required_config_hashes=None,
                required_evidence_hash=result.evidence_tail_hash,
            )
            if terminal_checkpoint.state != "DONE":
                raise BenchmarkExecutionError("runtime returned without an evidence-bound DONE checkpoint")

            stdout_path = task_dir / "stdout.txt"
            stderr_path = task_dir / "stderr.txt"
            report_path = task_dir / "report.json"
            checkout_path = task_dir / "checkout-evidence.json"
            atomic_write(stdout_path, result.grade.stdout.encode("utf-8"))
            atomic_write(stderr_path, result.grade.stderr.encode("utf-8"))
            write_json(report_path, result.grade.report)
            write_json(checkout_path, checkout_evidence[task.task_id])
            events_path = evidence.events_path
            memory_metrics = actual_memory_metrics(result, events_path)
            observed_digest = observed_target_digest(result.grade)
            expected_digest = images[target["instance_id"]]["expected_digest"]
            task_wall_time_ms = max(0, (time.perf_counter_ns() - task_started_ns) // 1_000_000)
            accounting = actual_accounting(
                result.accounting, task_wall_time_ms=task_wall_time_ms
            )
            provider_outcomes = provider_outcome_accounting(result.accounting)
            pricing = read_json(ROOT / "configs/trimem_v1/cost_plan.json")["model_pricing"]
            task_actual_usd = actual_usd_for_accounting(accounting, pricing)
            record = build_terminal_result_record(
                result=result,
                actual_accounting=accounting,
                actual_memory_metrics=memory_metrics,
                provider_outcomes=provider_outcomes,
                actual_usd=task_actual_usd,
                static_fields={
                "arm": stream_id, "runtime_arm": arm,
                "agent_config_hashes": dict(terminal_checkpoint.config_hashes),
                "benchmark_id": target["benchmark_id"],
                "checkout_evidence_sha256": sha256_bytes(canonical_bytes(checkout_evidence[task.task_id])),
                "execution_lock_hash": execution_lock_hash,
                "evidence_tail_hash": result.evidence_tail_hash,
                "namespace": session.namespace, "expected_image_digest": expected_digest,
                "identity_seed_digest": identity_seed_evidence["digest"],
                "observed_image_digest": observed_digest,
                "sequence_index": index, "sequence_sha256": digest, "target_id": target["target_id"],
                "terminal_checkpoint_sha256": terminal_checkpoint.content_hash,
                "terminal_state": terminal_checkpoint.state,
                "runtime_lock_sha256": "sha256:" + runtime_lock.content_hash,
                "m2_policy_manifest_sha256": (
                    "sha256:" + sha256_bytes(canonical_bytes(m2_manifest))
                    if isinstance(m2_manifest, Mapping) else None
                ),
                "selected_prompt_candidate_id": selected_prompt_candidate_id,
                "workspace_factory_hash": workspace_factory.content_hash,
                },
                evidence={
                    "stdout": evidence_reference(task_dir, stdout_path),
                    "stderr": evidence_reference(task_dir, stderr_path),
                    "report": evidence_reference(task_dir, report_path),
                    "raw_events": evidence_reference(task_dir, events_path),
                    "checkout": evidence_reference(task_dir, checkout_path),
                    "terminal_checkpoint": evidence_reference(task_dir, agent_checkpoint),
                    "restricted_grader_raw": restricted_evidence_references(
                        task_dir, task_dir / "official-grader"
                    ),
                },
            )
            commit_scientific_cell(
                task_dir=task_dir,
                task=task,
                target_id=str(target["target_id"]),
                stream_id=stream_id,
                arm=arm,
                sequence_index=index,
                task_arm_key=task_arm_key,
                task_reservation=task_reservation,
                record=record,
                result=result,
                ledger=ledger,
                session=session,
                output_root=output_root,
            )
            verify_cell_commit_frontier(
                output_root=output_root,
                stream_id=stream_id,
                arm=arm,
                tasks=tasks,
                expected_targets=cell_target_authorities,
                ledger=ledger,
                canonical_cursor=session.task_cursor,
            )
        selected_checkpoint = None
        checkpoint_file: Optional[Path] = None
        if arm == "M2" and split == "development":
            if session.development_finalized:
                selected_checkpoint = session.final_policy_checkpoint
                if not isinstance(selected_checkpoint, Mapping):
                    raise BenchmarkExecutionError("finalized stream has no frozen policy checkpoint")
            else:
                finalize = getattr(session, "finalize_development", None)
                if not callable(finalize):
                    raise BenchmarkExecutionError("production M2 session cannot finalize/freeze development")
                selected_checkpoint = finalize(expected_resume_cursor=len(tasks))
                final_envelope = session.latest_checkpoint_envelope
                if not isinstance(final_envelope, Mapping):
                    raise BenchmarkExecutionError("development finalizer was not canonically checkpointed")
                last_task_dir, _last_run_id, _last_prepared = (
                    _task_recovery_paths(
                        output_root,
                        stream_id,
                        len(tasks) - 1,
                        tasks[-1],
                    )
                )
                save_development_finalized_arm_checkpoint(
                    output_root,
                    stream_id,
                    final_envelope,
                    last_cell_journal_path=_cell_commit_path(last_task_dir),
                )
            checkpoint_file = output_root / f"{stream_id}.post-development-frozen-checkpoint.json"
            write_json(checkpoint_file, selected_checkpoint)
        result_records = [
            read_json(path) for path in sorted((output_root / stream_id).rglob("*.result.json"))
        ]
        if len(result_records) != len(tasks):
            raise BenchmarkExecutionError("stream summary cannot account for every frozen target")
        try:
            for record in result_records:
                validate_scientific_terminal_result(record)
        except ScientificTerminalContractError as exc:
            raise BenchmarkExecutionError(
                f"stream summary rejected a scientific terminal result: {exc}"
            ) from None
        empty_accounting = actual_accounting({"summary": {}})
        total_accounting = {
            field: sum(int(row["actual_accounting"][field]) for row in result_records)
            for field in empty_accounting
        }
        total_memory_metrics = {
            field: sum(int(row["actual_memory_metrics"][field]) for row in result_records)
            for field in result_records[0]["actual_memory_metrics"]
        }
        provider_outcomes = combine_provider_outcomes(
            [row["provider_outcomes"] for row in result_records]
        )
        prices = read_json(ROOT / "configs/trimem_v1/cost_plan.json")["model_pricing"]
        actual_usd = actual_usd_for_accounting(total_accounting, prices)
        summary = {
            "arm": stream_id, "runtime_arm": arm,
            "final_resume_cursor": session.task_cursor,
            "completed_target_count": len(tasks),
            "canonical_stream_cursor": session.next_sequence_index,
            "execution_lock_hash": execution_lock_hash, "namespace": session.namespace,
            "identity_seed_digest": identity_seed_evidence["digest"],
            "sequence_sha256": digest, "selected_checkpoint": selected_checkpoint,
            "selected_checkpoint_path": (
                checkpoint_file.resolve().relative_to(ROOT.resolve()).as_posix()
                if checkpoint_file is not None else None
            ),
            "candidate_id": (
                stream_id.removeprefix("M2-") if stream_id.startswith("M2-") else None
            ),
            "selected_prompt_candidate_id": selected_prompt_candidate_id,
            "runtime_lock_sha256": "sha256:" + runtime_lock.content_hash,
            "m2_policy_manifest_sha256": (
                "sha256:" + sha256_bytes(canonical_bytes(m2_manifest))
                if isinstance(m2_manifest, Mapping) else None
            ),
            "actual_accounting": total_accounting,
            "actual_memory_metrics": total_memory_metrics,
            "provider_outcomes": provider_outcomes,
            "actual_total_tokens": (
                # Responses reasoning_tokens is a reported subset of output_tokens.
                total_accounting["input_tokens"] + total_accounting["output_tokens"]
            ),
            "actual_usd": actual_usd,
            "resolved_count": sum(int(row["resolved"]) for row in result_records),
            "cell_status_counts": dict(sorted({
                name: sum(int(row["cell_status"] == name) for row in result_records)
                for name in {str(row["cell_status"]) for row in result_records}
            }.items())),
            "contained_failure_count": sum(
                int(row["cell_status"] != "AGENT_COMPLETED")
                for row in result_records
            ),
            "model_failure_count": sum(
                int(row.get("model_failure_class") is not None)
                for row in result_records
            ),
            "model_failure_distribution": dict(sorted({
                name: sum(
                    int(row.get("model_failure_class") == name)
                    for row in result_records
                )
                for name in {
                    str(row["model_failure_class"])
                    for row in result_records
                    if row.get("model_failure_class") is not None
                }
            }.items())),
            "model_failure_class_counts": dict(sorted({
                name: sum(
                    int(
                        (
                            canonical_scientific_failure_class(
                                row["model_failure_class"]
                            )
                            if row["model_failure_class"] is not None
                            else "NONE"
                        )
                        == name
                    )
                    for row in result_records
                )
                for name in {
                    (
                        canonical_scientific_failure_class(
                            row["model_failure_class"]
                        )
                        if row["model_failure_class"] is not None
                        else "NONE"
                    )
                    for row in result_records
                }
            }.items())),
            "partial_patch_count": sum(
                int(row.get("grader_patch_source") == "MODEL_PARTIAL_PATCH")
                for row in result_records
            ),
            "canonical_noop_count": sum(
                int(row.get("grader_patch_source") == "CANONICAL_FAILED_CELL_NOOP")
                for row in result_records
            ),
            "extraction_failure_count": sum(
                int(row.get("extraction_status") == "MEMORY_EXTRACTION_FAILED")
                for row in result_records
            ),
            "status": "PASS", "workspace_factory_hash": workspace_factory.content_hash,
        }
        write_json(output_root / f"{stream_id}.arm-summary.json", summary)
        return summary
    finally:
        if client is not None:
            close_paid_model_client(session, client)
        session.close()


def write_development_selection_artifacts(
    candidate_summaries: Sequence[Mapping[str, Any]], *, output_root: Path
) -> tuple[dict[str, Any], RuntimeLock, dict[str, Any]]:
    """Select deterministically and emit a reviewable post-DEV seal proposal."""

    compact = []
    for summary in candidate_summaries:
        completed = summary.get("completed_target_count")
        cell_counts = summary.get("cell_status_counts")
        failure_counts = summary.get("model_failure_class_counts")
        if (
            type(completed) is not int
            or completed <= 0
            or not isinstance(cell_counts, Mapping)
            or set(cell_counts) - set(SCIENTIFIC_CELL_STATUSES)
            or any(type(value) is not int or value < 0 for value in cell_counts.values())
            or sum(cell_counts.values()) != completed
            or summary.get("contained_failure_count")
            != completed - int(cell_counts.get("AGENT_COMPLETED", 0))
            or not isinstance(failure_counts, Mapping)
            or sum(failure_counts.values()) != completed
        ):
            raise BenchmarkExecutionError(
                "development candidate terminal summary is incomplete or malformed"
            )
        checkpoint_path = ROOT / str(summary.get("selected_checkpoint_path", ""))
        checkpoint = summary.get("selected_checkpoint")
        if not checkpoint_path.is_file() or not isinstance(checkpoint, Mapping):
            raise BenchmarkExecutionError("development candidate has no frozen final checkpoint")
        if read_json(checkpoint_path) != checkpoint:
            raise BenchmarkExecutionError("development candidate checkpoint file/content mismatch")
        compact.append({
            "candidate_id": summary.get("candidate_id"),
            "completed_target_count": summary.get("completed_target_count"),
            "final_resume_cursor": summary.get("final_resume_cursor"),
            "resolved_count": summary.get("resolved_count"),
            "actual_total_tokens": summary.get("actual_total_tokens"),
            "actual_usd": summary.get("actual_usd"),
            "sequence_sha256": summary.get("sequence_sha256"),
            "runtime_lock_sha256": summary.get("runtime_lock_sha256"),
            "m2_policy_manifest_sha256": summary.get("m2_policy_manifest_sha256"),
            "checkpoint_source_path": summary.get("selected_checkpoint_path"),
            "checkpoint_source_file_sha256": sha256_bytes(checkpoint_path.read_bytes()),
            "checkpoint_digest": checkpoint.get("digest"),
            "namespace": summary.get("namespace"),
        })
    selection = select_development_candidate(compact)
    selected_id = str(selection["selected_candidate_id"])
    selected_summary = next(row for row in candidate_summaries if row.get("candidate_id") == selected_id)
    selected_source = ROOT / str(selected_summary["selected_checkpoint_path"])
    promotion_root = ROOT / "artifacts/trimem_v1/development_selection"
    checkpoint_path = promotion_root / "selected_m2_checkpoint.json"
    atomic_write(checkpoint_path, selected_source.read_bytes())
    checkpoint = read_json(checkpoint_path)
    evidence = {
        "schema": "trimem/development-m2-selection-evidence/1.0",
        "status": "COMPLETE_PENDING_COMMIT_FREEZE_AND_HELDOUT_APPROVAL",
        "candidate_bundle_sha256": "sha256:" + sha256_bytes(
            canonical_bytes(load_m2_candidate_bundle())
        ),
        "candidate_summaries": compact,
        "selection": selection,
    }
    evidence_path = promotion_root / "development_selection_evidence.json"
    write_json(evidence_path, evidence)
    candidate = candidate_row(selected_id)
    proposal = {
        "schema": "trimem/selected-m2/1.0",
        "status": "FROZEN_AFTER_DEVELOPMENT",
        "candidate_bundle_path": "configs/trimem_v1/m2_candidate_bundles.json",
        "selected_candidate_id": selected_id,
        "selected_full_policy_path": candidate["full_policy_path"],
        "selected_full_policy_file_sha256": candidate["full_policy_file_sha256"],
        "selected_runtime_lock_sha256": candidate["runtime_lock_sha256"],
        "selected_checkpoint_path": checkpoint_path.relative_to(ROOT).as_posix(),
        "selected_checkpoint_file_sha256": sha256_bytes(checkpoint_path.read_bytes()),
        "selected_checkpoint_digest": checkpoint.get("digest"),
        "development_selection_evidence_path": evidence_path.relative_to(ROOT).as_posix(),
        "development_selection_evidence_sha256": sha256_bytes(evidence_path.read_bytes()),
        "heldout_execution": "PENDING_SEPARATE_EXEC_APPROVAL",
    }
    write_json(promotion_root / "selected_m2.proposed.json", proposal)
    write_json(output_root / "development-selection.json", evidence)
    return proposal, runtime_lock_for(selected_id), load_candidate_policy(selected_id)


def process_disposition_for_exception(exc: BaseException) -> str:
    """Return the closed disposition consumed by the same-attempt wrapper."""

    if isinstance(exc, BenchmarkProcessFailure):
        return exc.disposition
    if isinstance(exc, GraderInvocationFailure):
        return "GLOBAL_GRADER_INFRA_FAILURE"
    if isinstance(exc, ApprovalValidationError):
        return "GLOBAL_CREDENTIAL_FAILURE"
    if isinstance(exc, ModelPreflightFailure):
        if exc.classification == "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE":
            return "GLOBAL_LEDGER_INTEGRITY_FAILURE"
        return "UNKNOWN_FAILURE"
    message = str(exc).casefold()
    if any(token in message for token in ("credential", "api key", "approval")):
        return "GLOBAL_CREDENTIAL_FAILURE"
    if any(token in message for token in ("model identity", "model lock", "model differs")):
        return "GLOBAL_MODEL_IDENTITY_FAILURE"
    if any(token in message for token in ("budget ledger", "task-arm ledger", "ledger integrity")):
        return "GLOBAL_LEDGER_INTEGRITY_FAILURE"
    if any(
        token in message
        for token in (
            "grader",
            "official harness",
            "container start",
            "image digest",
        )
    ):
        return "GLOBAL_GRADER_INFRA_FAILURE"
    if any(token in message for token in ("evidence", "checkpoint", "cell-commit")):
        return "GLOBAL_EVIDENCE_FAILURE"
    if any(
        token in message
        for token in ("environment", "loader", "libpython", "python launch")
    ):
        return "GLOBAL_ENVIRONMENT_FAILURE"
    return "UNKNOWN_FAILURE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=SPLITS, required=True)
    parser.add_argument("--approval-file", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        validate_benchmark_environment()
        official_harness_loader_preflight = (
            load_official_harness_loader_preflight()
        )
        approval = validate_exec_approval(args.split, args.approval_file)
        manifest_targets, rows = load_frozen_rows(args.split, ROOT / ".trimem-exec/datasets")
        tasks = coding_tasks(manifest_targets, rows)
        output = ROOT / "artifacts/trimem_v1/benchmark_exec" / args.split
        output.mkdir(parents=True, exist_ok=True)
        write_external_approval_evidence(
            output,
            split=args.split,
            approval_path=args.approval_file,
            validated=approval,
        )
        cost = read_json(ROOT / "configs/trimem_v1/cost_plan.json")
        protocol_canary: Optional[dict[str, Any]] = None
        scientific_hard_cap: Mapping[str, Any] = approval["hard_cap"]
        if args.split == "development":
            canary_path = output / PROTOCOL_CANARY_RELATIVE_PATH
            if not canary_path.is_file():
                raise BenchmarkExecutionError(
                    "successful protocol canary evidence is required before DEV"
                )
            protocol_canary = read_json(canary_path)
            scientific_hard_cap = scientific_caps_after_protocol_canary(
                approval["hard_cap"],
                protocol_canary,
                expected_approval_sha256=approval["approval_artifact_sha256"],
            )
        if args.split == "development":
            selected_state = validate_selected_m2(require_frozen=False)
            if selected_state.get("status") != "PRE_DEVELOPMENT":
                raise BenchmarkExecutionError(
                    "development execution requires PRE_DEVELOPMENT selection state"
                )
            load_m2_candidate_bundle()
            planned_stream_ids = [
                *(f"M2-{candidate_id}" for candidate_id in CANDIDATE_IDS), "M0", "M1"
            ]
        else:
            validate_selected_m2(require_frozen=True)
            planned_stream_ids = list(ARMS)

        # Provision every stream's deterministic FK identities before any
        # harness, workspace, model, grader, or runtime object is opened. The
        # admin DSN is removed from the process environment immediately and
        # each seed call disposes its admin engine before returning.
        admin_database_url = os.environ.pop("TRIMEM_ADMIN_DATABASE_URL", "")
        runtime_database_url = os.environ.get("TRIMEM_DATABASE_URL", "")
        validate_database_role_boundary(admin_database_url, runtime_database_url)
        seed_evidence_by_stream: dict[str, Mapping[str, Any]] = {}
        seed_root = output / "identity-seeds"
        for planned_stream_id in planned_stream_ids:
            experiment_id = "trimemv1-" + approval["git_head"][:12] + "-" + re.sub(
                r"[^a-z0-9-]", "-", planned_stream_id.lower()
            )
            evidence = seed_benchmark_identities(
                admin_database_url=admin_database_url,
                experiment_id=experiment_id,
                stream_id=planned_stream_id,
                tasks=tasks,
                identity_resolver=repository_identity_resolver(
                    experiment_id, planned_stream_id
                ),
            )
            if "postgresql" in json.dumps(evidence).casefold() or "password" in json.dumps(evidence).casefold():
                raise BenchmarkExecutionError("identity seed evidence contains database credentials")
            seed_evidence_by_stream[planned_stream_id] = dict(evidence)
            write_json(seed_root / f"{planned_stream_id}.json", evidence)
        del admin_database_url
        if "TRIMEM_ADMIN_DATABASE_URL" in os.environ:
            raise BenchmarkExecutionError("admin database URL remained in runtime environment")

        harnesses = prepare_harnesses(ROOT / ".trimem-exec/harnesses")
        validate_preflight_harness_root_binding(
            official_harness_loader_preflight, harnesses
        )
        approval_digest = approval["approval_artifact_sha256"]
        ledger = AtomicBudgetLedger(
            output / "budget-ledger.json",
            approval_digest=approval_digest, caps=scientific_hard_cap, pricing=cost["model_pricing"],
        )
        benchmark_images, _ = image_entries(require_benchmark=True)
        summaries: list[dict[str, Any]] = []
        common_workspace_factory_hash: Optional[str] = None

        def run_stream(
            *, runtime_arm: str, stream_id: str, runtime_lock: RuntimeLock,
            m2_manifest: Optional[Mapping[str, Any]], checkpoint_path: Optional[Path],
            prompt_candidate_id: str,
        ) -> dict[str, Any]:
            nonlocal common_workspace_factory_hash
            # The identity is durably written before the namespace claim.  It is
            # therefore the earliest recovery marker; freshness is deliberately
            # later and may be absent when the process dies between claim and
            # the first task checkpoint.
            stream_resume = args.resume and (
                (output / f"{stream_id}.freshness.json").is_file()
                or _arm_identity_path(output, stream_id).is_file()
            )
            workspace, checkout_evidence = prepare_checkouts(
                tasks, manifest_targets, benchmark_images,
                ROOT / ".trimem-exec/checkouts" / args.split / stream_id,
                resume=stream_resume,
            )
            if common_workspace_factory_hash is None:
                common_workspace_factory_hash = workspace.content_hash
            elif workspace.content_hash != common_workspace_factory_hash:
                raise BenchmarkExecutionError("benchmark streams have different workspace/tool factory hashes")
            return run_arm_stream(
                split=args.split, arm=runtime_arm, stream_id=stream_id,
                runtime_lock=runtime_lock, m2_manifest=m2_manifest,
                dqn_checkpoint_path=checkpoint_path,
                selected_prompt_candidate_id=prompt_candidate_id,
                approval=approval, targets=manifest_targets,
                rows=rows, tasks=tasks, workspace_factory=workspace,
                checkout_evidence=checkout_evidence, harnesses=harnesses,
                output_root=output, ledger=ledger,
                database_url=runtime_database_url,
                qdrant_url=os.environ.get("TRIMEM_QDRANT_URL", ""), resume=stream_resume,
                identity_seed_evidence=seed_evidence_by_stream[stream_id],
                official_harness_loader_preflight=(
                    official_harness_loader_preflight
                ),
            )

        # One process/job owns one phase-scoped ledger. Every online memory
        # stream is serial and has its own namespace; there is no task matrix.
        if args.split == "development":
            candidate_summaries = []
            for candidate_id in CANDIDATE_IDS:
                candidate_summary = run_stream(
                    runtime_arm="M2", stream_id=f"M2-{candidate_id}",
                    runtime_lock=runtime_lock_for(candidate_id),
                    m2_manifest=load_candidate_policy(candidate_id), checkpoint_path=None,
                    prompt_candidate_id=candidate_id,
                )
                candidate_summaries.append(candidate_summary)
                summaries.append(candidate_summary)
            proposal, selected_runtime_lock, _ = write_development_selection_artifacts(
                candidate_summaries, output_root=output
            )
            selected_candidate_id = str(proposal["selected_candidate_id"])
            for arm in ("M0", "M1"):
                summaries.append(run_stream(
                    runtime_arm=arm, stream_id=arm, runtime_lock=selected_runtime_lock,
                    m2_manifest=None, checkpoint_path=None,
                    prompt_candidate_id=selected_candidate_id,
                ))
        else:
            selected = validate_selected_m2(require_frozen=True)
            selected_candidate_id = str(selected["selected_candidate_id"])
            selected_runtime_lock = runtime_lock_for(selected_candidate_id)
            selected_policy = load_candidate_policy(selected_candidate_id)
            selected_checkpoint_path = ROOT / str(selected["selected_checkpoint_path"])
            for arm in ARMS:
                summaries.append(run_stream(
                    runtime_arm=arm, stream_id=arm, runtime_lock=selected_runtime_lock,
                    m2_manifest=selected_policy if arm == "M2" else None,
                    checkpoint_path=selected_checkpoint_path if arm == "M2" else None,
                    prompt_candidate_id=selected_candidate_id,
                ))
        phase_evidence = validate_phase_completion(
            output,
            split=args.split,
            summaries=summaries,
            ledger=ledger,
            hard_cap=scientific_hard_cap,
            pricing=cost["model_pricing"],
        )
        if protocol_canary is not None:
            phase_evidence["protocol_canary"] = protocol_canary
            phase_evidence["global_actual_accounting"] = validate_global_phase_accounting(
                approval["hard_cap"],
                protocol_canary,
                {
                    "paid_model_calls": phase_evidence["actual_accounting"]["paid_model_calls"],
                    "input_tokens": phase_evidence["actual_accounting"]["input_tokens"],
                    "cached_input_tokens": phase_evidence["actual_accounting"]["cached_input_tokens"],
                    "output_tokens": phase_evidence["actual_accounting"]["output_tokens"],
                    "total_usd": phase_evidence["actual_usd"],
                },
            )
        print(json.dumps(
            {
                "phase_evidence": phase_evidence,
                "process_disposition": "SUCCESS",
                "streams": summaries,
                "status": "PASS",
            },
            ensure_ascii=False,
            sort_keys=True,
        ))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "process_disposition": process_disposition_for_exception(exc),
                    "status": "FAIL",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
