from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import trimem_benchmark_run as benchmark_run  # noqa: E402
import trimem_benchmark_matrix as benchmark_matrix  # noqa: E402
import trimem_cleanup_exec as cleanup_exec  # noqa: E402
import trimem_freeze as freeze  # noqa: E402
import trimem_m2_candidates as candidates  # noqa: E402
import trimem_public_artifact as public_artifact  # noqa: E402
import trimem_pull_locked_images as image_pull  # noqa: E402
import trimem_run_with_resume as resume_runner  # noqa: E402
import trimem_select_targets as selector  # noqa: E402
import trimem_verify_ready as readiness  # noqa: E402


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_all_execution_config_readers_reject_duplicate_json_keys(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"maximum_budget_is_not_actual_compute":true,"maximum_budget_is_not_actual_compute":false}', encoding="utf-8")
    with pytest.raises((ValueError, readiness.ReadinessError), match="duplicate JSON key"):
        readiness.read_json(duplicate)
    with pytest.raises((ValueError, candidates.CandidateContractError), match="duplicate JSON key"):
        candidates.read_json(duplicate)
    with pytest.raises((ValueError, selector.SelectionError), match="duplicate JSON key"):
        selector.read_object(duplicate)
    arms = readiness.read_json(ROOT / "configs/trimem_v1/arms.json")
    assert arms["comparability_contract"]["maximum_budget_is_not_actual_compute"] is True


def test_resume_metric_and_aggregate_json_boundaries_reject_duplicate_keys(tmp_path: Path) -> None:
    with pytest.raises(benchmark_matrix.MatrixError, match="duplicate JSON key"):
        benchmark_matrix._strict_loads('{"resolved":true,"resolved":false}')
    checkpoint = tmp_path / "M0.stream-checkpoint.json"
    sidecar = tmp_path / "M0.stream-checkpoint.sha256"
    raw = b'{"payload":{},"payload":{}}'
    checkpoint.write_bytes(raw)
    sidecar.write_text(hashlib.sha256(raw).hexdigest(), encoding="ascii")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        benchmark_run.load_arm_checkpoint(tmp_path, "M0")
    events = tmp_path / "events.ndjson"
    events.write_text('{"event_type":"memory_recall","event_type":"other"}\n', encoding="utf-8")
    result = type("Result", (), {
        "injections": (),
        "lifecycle_result": {"storage": {
            "retained_records": 0, "archived_records": 0, "net_memory_growth": 0,
        }},
    })()
    with pytest.raises(ValueError, match="duplicate JSON key"):
        benchmark_run.actual_memory_metrics(result, events)


def test_target_set_digests_bind_exact_ordered_rows() -> None:
    expected = {
        "development": "e7da59b3c2638c89da4e333a7391851e992c122acac11bc9edf60619cfd5eff2",
        "heldout": "abd3f182acef8f37018e5f05ab9ba185b7b1efbc111dee273e66a38e6ab16267",
        "grader_smoke": "2c91358e9c78cd26f989f875c755b62cb30037c407ada214148064411e7ac809",
    }
    for name, digest in expected.items():
        manifest = _read(ROOT / f"configs/trimem_v1/{name}_manifest.json")
        assert manifest["target_set_sha256"] == digest
        assert hashlib.sha256(_canonical(manifest["targets"])).hexdigest() == digest


def test_benchmark_roles_freeze_primary_secondary_endpoints_before_results() -> None:
    for name in ("development", "heldout"):
        manifest = _read(ROOT / f"configs/trimem_v1/{name}_manifest.json")
        roles = benchmark_matrix._validate_benchmark_roles(
            manifest, manifest["targets"]
        )
        assert [row["benchmark_id"] for row in roles if row["role"] == "PRIMARY"] == [
            "swebench_verified"
        ]
        assert all(
            row["role"] == "SECONDARY"
            for row in roles
            if row["benchmark_id"].startswith("multi_swe_bench_")
        )

        tampered = deepcopy(manifest)
        tampered["benchmark_roles"][0]["target_count"] += 1
        with pytest.raises(benchmark_matrix.MatrixError, match="count/revision"):
            benchmark_matrix._validate_benchmark_roles(
                tampered, tampered["targets"]
            )
    development = _read(ROOT / "configs/trimem_v1/development_manifest.json")
    assert "pooled resolved_count" in development["tuning_selection_objective"]
    assert "not the held-out primary endpoint" in development[
        "tuning_selection_objective"
    ]


def test_arm_by_benchmark_pass_at_1_is_separate_from_pooled_totals() -> None:
    roles = [
        {
            "benchmark_id": "swebench_verified",
            "dataset_id": "primary",
            "dataset_revision": "a" * 40,
            "role": "PRIMARY",
            "target_count": 2,
        },
        {
            "benchmark_id": "multi_swe_bench_mini",
            "dataset_id": "secondary",
            "dataset_revision": "b" * 40,
            "role": "SECONDARY",
            "target_count": 1,
        },
    ]
    outcomes = [
        {"arm": "M0", "benchmark_id": "swebench_verified", "resolved": True},
        {"arm": "M0", "benchmark_id": "swebench_verified", "resolved": False},
        {"arm": "M0", "benchmark_id": "multi_swe_bench_mini", "resolved": True},
    ]
    totals = benchmark_matrix._benchmark_endpoint_totals(
        outcomes, ("M0",), roles
    )
    assert totals[0]["reporting_role"] == "PRIMARY"
    assert (totals[0]["n"], totals[0]["resolved_count"], totals[0]["pass_at_1"]) == (
        2, 1, "0.500000000000"
    )
    assert totals[1]["reporting_role"] == "SECONDARY"
    assert totals[1]["pass_at_1"] == "1.000000000000"
    with pytest.raises(benchmark_matrix.MatrixError, match="target counts"):
        benchmark_matrix._benchmark_endpoint_totals(outcomes[:-1], ("M0",), roles)


def test_selector_score_uses_only_public_identity() -> None:
    public = {"instance_id": "org__repo-1", "patch": "secret-a", "test_patch": "secret-b"}
    changed_hidden = {**public, "patch": "different", "test_patch": "different"}
    assert selector._score("seed", "development", "swebench_verified", public) == selector._score(
        "seed", "development", "swebench_verified", changed_hidden
    )
    plan = _read(ROOT / "configs/trimem_v1/selection_plan.json")
    assert plan["schema"] == "trimem/selection-plan/3.0"
    assert "source_row_sha256" not in plan["row_score"]
    assert "salt" not in json.dumps(plan).lower()


def test_four_candidate_bundle_is_executable_and_preserves_hard_retrieval_limits() -> None:
    bundle = candidates.load_bundle()
    assert bundle["candidate_order"] == list(candidates.CANDIDATE_IDS)
    assert bundle["development_contract"]["candidate_task_arm_runs"] == 48
    hashes = set()
    for candidate_id in candidates.CANDIDATE_IDS:
        policy = candidates.load_candidate_policy(candidate_id)
        assert policy["retrieval"]["max_episodic_per_active_node"] == 1
        assert policy["retrieval"]["max_semantic_per_active_node"] == 1
        hashes.add(candidates.digest_value(policy))
        assert "candidate" not in candidates.PROMPT_SUFFIXES[candidate_id].lower()
        assert "development" not in candidates.PROMPT_SUFFIXES[candidate_id].lower()
    assert len(hashes) == 4


def test_cost_and_pre_exec_readiness_are_two_phase_and_non_circular() -> None:
    cost = _read(ROOT / "configs/trimem_v1/cost_plan.json")
    assert cost["run_counts"]["development_physical_task_arm_runs"] == 72
    assert cost["run_counts"]["heldout_physical_task_arm_runs"] == 81
    assert cost["run_counts"]["total_physical_task_arm_runs"] == 153
    requirements = _read(ROOT / "artifacts/trimem_v1/readiness_requirements.json")
    pending = requirements["explicitly_allowed_pending_at_pre_exec_ready"]
    assert "PENDING_EXEC_APPROVAL" in pending["official_grader_smoke"]
    assert "PRE_DEVELOPMENT" in pending["selected_m2_checkpoint"]
    service_boundary = requirements["credential_free_service_ci_boundary"]
    assert "ALLOWED_PRE_EXEC" in service_boundary
    assert "digest-pinned PostgreSQL and Qdrant support services" in service_boundary
    assert "official grader/benchmark target images" in service_boundary
    request = _read(ROOT / "configs/trimem_v1/benchmark_exec_request.json")
    assert "official grader/benchmark target image pull or run" in request["prohibited_before_approval"]
    assert "Docker image pull or run" not in request["prohibited_before_approval"]
    assert requirements["execution_counters"] == {
        "grader_containers": 0,
        "model_gateway_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
    }


def test_freeze_allowlist_closes_all_trimem_execution_surfaces() -> None:
    frozen = set(freeze.frozen_paths(ROOT))
    discovered = {
        path.relative_to(ROOT).as_posix()
        for base, pattern in (
            (ROOT / "src/enterprise_memory/trimem", "*.py"),
            (ROOT / "scripts", "trimem_*.py"),
            (ROOT / "tests/unit", "test_trimem_*.py"),
        )
        for path in base.glob(pattern)
    }
    discovered.add("scripts/run_trimem_replay_e2e.py")
    discovered.update(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "configs/trimem_v1").rglob("*") if path.is_file()
    )
    discovered.update(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "migrations/versions").glob("*.py")
    )
    discovered.update(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "migrations/sql").glob("*_up.*")
    )
    assert discovered <= frozen
    assert {
        ".gitattributes", "alembic.ini", "DEPENDENCY_PROVENANCE.json", "requirements.lock",
        "src/enterprise_memory/service/app.py", "src/enterprise_memory/providers/openai_responses.py",
        "docs/TRIMEM_V1_SYSTEM.md", "tests/trimem/test_real_services_e2e.py",
        "src/enterprise_memory/providers/base.py",
        "src/enterprise_memory/providers/redaction.py",
        "src/enterprise_memory/indexing/canonical_loaders.py",
        "src/enterprise_memory/indexing/embeddings.py",
        "src/enterprise_memory/indexing/__init__.py",
        "src/enterprise_memory/indexing/drift.py",
        "src/enterprise_memory/indexing/reindex.py",
        "src/enterprise_memory/indexing/index_worker.py",
        "src/enterprise_memory/indexing/models.py",
        "src/enterprise_memory/indexing/projection.py",
        "src/enterprise_memory/indexing/qdrant_indexes.py",
        "src/enterprise_memory/indexing/validated_search.py",
        "src/enterprise_memory/persistence/tenant_context.py",
        "src/enterprise_memory/persistence/__init__.py",
        "src/enterprise_memory/persistence/postgres/__init__.py",
        "src/enterprise_memory/persistence/postgres/repos.py",
        "src/enterprise_memory/providers/__init__.py",
        "src/enterprise_memory/service/durable.py",
        "src/enterprise_memory/service/injection.py",
        "src/enterprise_memory/service/private_view.py",
        "src/enterprise_memory/service/__init__.py",
        "src/enterprise_memory/contracts/codec.py",
        "src/enterprise_memory/contracts/schema.py",
        "src/enterprise_memory/promotion/security_scan.py",
    } <= frozen
    assert not any(path.endswith("freeze.json") for path in frozen)
    referenced_blobs = set(freeze.referenced_blob_paths(ROOT))
    assert referenced_blobs
    assert referenced_blobs <= frozen
    assert all("/evidence/blobs/" in path for path in referenced_blobs)
    assert all((ROOT / path).is_file() for path in frozen)
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "artifacts/trimem_v1/**/evidence/blobs/** -text" in attributes


def test_freeze_contains_clean_import_execution_closure() -> None:
    script = r'''
import json
import pathlib
import sys
import enterprise_memory.trimem.production_runtime
import enterprise_memory.providers.openai_responses
import trimem_benchmark_run
import trimem_verify_ready
root = pathlib.Path.cwd().resolve()
paths = sorted({
    pathlib.Path(module.__file__).resolve().relative_to(root).as_posix()
    for name, module in sys.modules.items()
    if name.startswith("enterprise_memory")
    and getattr(module, "__file__", None)
    and root in pathlib.Path(module.__file__).resolve().parents
})
print(json.dumps(paths))
'''
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(ROOT / "src"), str(ROOT / "scripts"))
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    imported = set(json.loads(completed.stdout))
    assert imported
    assert imported <= set(freeze.frozen_paths(ROOT))
    assert "src/enterprise_memory/indexing/embeddings.py" in imported


def test_workflows_are_pinned_no_input_fail_closed_and_protect_raw_evidence() -> None:
    workflows = [
        ROOT / ".github/workflows/ci-trimem.yml",
        ROOT / ".github/workflows/ci-trimem-e2e.yml",
        ROOT / ".github/workflows/trimem-grader-smoke.yml",
        ROOT / ".github/workflows/trimem-benchmark.yml",
    ]
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        assert "continue-on-error" not in text
        assert "|| true" not in text
        assert ":latest" not in text
        assert "inputs:" not in text
        assert all(
            re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", match.group(1))
            for match in re.finditer(r"uses:\s*([^\s]+)", text)
        )
    static = workflows[0].read_text(encoding="utf-8")
    assert "tests/unit/test_trimem_*.py" in static
    assert "tests/trimem/e2e/test_full_replay.py" in static
    service = workflows[1].read_text(encoding="utf-8")
    assert "test_real_services_e2e.py" in service
    assert "python scripts/postgres_bootstrap.py" in service
    assert "TRIMEM_TEST_DATABASE_URL: postgresql+asyncpg://api_service:api_pw@" in service
    assert "TRIMEM_TEST_ADMIN_DATABASE_URL: postgresql+asyncpg://postgres:postgres@" in service
    for path in workflows[2:]:
        text = path.read_text(encoding="utf-8")
        assert "workflow_dispatch:" in text and "pull_request:" not in text and "push:" not in text
        assert "openssl enc -aes-256-cbc" in text
        assert "restricted-encrypted" in text
    benchmark = workflows[3].read_text(encoding="utf-8")
    assert "runs-on: [self-hosted, linux, x64, ubuntu-24.04, trimem-benchmark]" in benchmark
    assert "timeout-minutes: 7200" in benchmark
    assert "matrix:" not in benchmark
    assert "trimem_run_with_resume.py" in benchmark
    assert "trimem_cleanup_exec.py --phase benchmark" in benchmark
    assert "python scripts/postgres_bootstrap.py" in benchmark
    assert "TRIMEM_DATABASE_URL: postgresql+asyncpg://api_service:api_pw@" in benchmark
    assert "TRIMEM_ADMIN_DATABASE_URL: postgresql+asyncpg://postgres:postgres@" in benchmark
    assert "trimem_cleanup_exec.py --phase grader-smoke" in workflows[2].read_text(encoding="utf-8")


def test_same_attempt_driver_retries_exactly_once_and_propagates_final_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsysbinary
) -> None:
    monkeypatch.setattr(resume_runner, "ROOT", tmp_path)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        code = 23 if len(calls) == 1 else 29
        return type("Completed", (), {
            "returncode": code,
            "stdout": f"stdout-{len(calls)}".encode(),
            "stderr": f"stderr-{len(calls)}".encode(),
        })()

    monkeypatch.setattr(resume_runner.subprocess, "run", fake_run)
    assert resume_runner.run_with_one_resume("development", tmp_path.parent / "approval.json") == 29
    assert len(calls) == 2
    assert "--resume" not in calls[0] and calls[1][-1] == "--resume"
    evidence = _read(tmp_path / "artifacts/trimem_v1/benchmark_exec/development/driver-evidence/attempts.json")
    assert [row["exit_code"] for row in evidence["attempts"]] == [23, 29]
    assert evidence["maximum_resume_attempts"] == 1 and evidence["status"] == "FAIL"
    captured = capsysbinary.readouterr()
    assert b"stdout-1" in captured.out and b"stdout-2" in captured.out
    assert b"stderr-1" in captured.err and b"stderr-2" in captured.err


def test_exec_cleanup_removes_only_fixed_scoped_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = tmp_path / "repository"
    runner_temp = tmp_path / "runner-temp"
    (repository / ".trimem-exec/datasets").mkdir(parents=True)
    (repository / "artifacts/trimem_v1/benchmark_exec/development").mkdir(parents=True)
    (repository / "artifacts/trimem_v1/development_selection").mkdir(parents=True)
    runner_temp.mkdir()
    (runner_temp / "trimem-exec-approval.json").write_text("secret", encoding="utf-8")
    (runner_temp / "trimem-benchmark-restricted.tar.enc").write_bytes(b"encrypted")
    keep = repository / "configs/keep.txt"
    keep.parent.mkdir()
    keep.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(cleanup_exec, "ROOT", repository)
    cleanup_exec.cleanup("benchmark", runner_temp)
    assert not (repository / ".trimem-exec").exists()
    assert not (repository / "artifacts/trimem_v1/benchmark_exec").exists()
    assert not (repository / "artifacts/trimem_v1/development_selection").exists()
    assert not (runner_temp / "trimem-exec-approval.json").exists()
    assert keep.read_text(encoding="utf-8") == "keep"


def test_image_pull_timeout_preserves_partial_stdout_and_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*args, **kwargs):
        raise image_pull.subprocess.TimeoutExpired(
            cmd=args[0], timeout=3600, output=b"partial-out", stderr=b"partial-err"
        )

    monkeypatch.setattr(image_pull.subprocess, "run", timeout)
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="timed out"):
        image_pull._run(["docker", "pull", "repo@sha256:" + "a" * 64], tmp_path, 0, "pull")
    stage = _read(tmp_path / "000-pull/stage.json")
    assert stage["status"] == "TIMEOUT" and stage["returncode"] is None
    assert (tmp_path / "000-pull/stdout.txt").read_text(encoding="utf-8") == "partial-out"
    assert (tmp_path / "000-pull/stderr.txt").read_text(encoding="utf-8") == "partial-err"


def test_external_approval_is_bound_to_single_workflow_dispatch_and_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    config = repository / "configs/trimem_v1"
    artifact = repository / "artifacts/trimem_v1"
    config.mkdir(parents=True)
    artifact.mkdir(parents=True)
    (config / "grader_smoke_manifest.json").write_text("{}", encoding="utf-8")
    request = _read(ROOT / "configs/trimem_v1/benchmark_exec_request.json")
    hard = _read(ROOT / "configs/trimem_v1/cost_plan.json")["phase_hard_caps"]["GRADER_SMOKE"]
    request_path = config / "benchmark_exec_request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    (config / "cost_plan.json").write_text(json.dumps({"phase_hard_caps": {"GRADER_SMOKE": hard}}), encoding="utf-8")
    freeze_path = artifact / "freeze.json"
    freeze_path.write_text('{"synthetic":"freeze"}', encoding="utf-8")
    approval = {
        "approved_git_commit": "c" * 40,
        "approved_freeze_sha256": hashlib.sha256(freeze_path.read_bytes()).hexdigest(),
        "approved_phase": "GRADER_SMOKE",
        "approved_task_arm_runs": hard["task_arm_runs"],
        "approved_paid_model_call_cap": hard["paid_model_calls"],
        "approved_input_token_cap": hard["input_tokens"],
        "approved_output_token_cap": hard["output_tokens"],
        "approved_currency_hard_cap": hard["total_usd"],
        "approved_workflow_run_id": "8123456789",
        "approved_workflow_run_attempt": "1",
        "approved_legal_terms_acceptance": True,
        "approval_actor": "benchmark-owner",
        "approval_timestamp": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
    }
    document = {
        "schema": "trimem/external-exec-approval/1.0",
        "request_id": request["request_id"],
        "approved_request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
        "approval": approval,
    }
    path = tmp_path / "approval.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(benchmark_run, "ROOT", repository)
    monkeypatch.setattr(benchmark_run, "git_tracked", lambda _path: None)
    monkeypatch.setattr(benchmark_run, "git_head", lambda: "c" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "8123456789")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    assert benchmark_run.validate_exec_approval("grader-smoke", path)["approved_workflow_run_id"] == "8123456789"
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="run attempt"):
        benchmark_run.validate_exec_approval("grader-smoke", path)


def test_cached_and_uncached_input_cost_is_exact_per_task() -> None:
    accounting = {
        "input_tokens": 1_000_000,
        "cached_input_tokens": 250_000,
        "output_tokens": 100_000,
    }
    pricing = {
        "input_per_million_tokens_usd": 2.5,
        "cached_input_per_million_tokens_usd": 0.25,
        "output_per_million_tokens_usd": 15.0,
    }
    assert benchmark_run.actual_usd_for_accounting(accounting, pricing) == "3.437500000000"


def _stream_total_fixture() -> tuple[list[dict], dict, dict]:
    pricing = {
        "input_per_million_tokens_usd": 2.5,
        "cached_input_per_million_tokens_usd": 0.25,
        "output_per_million_tokens_usd": 15.0,
    }
    first_accounting = {field: 0 for field in benchmark_matrix.ACCOUNTING_FIELDS}
    first_accounting.update({
        "solve_calls": 2,
        "decomposition_calls": 1,
        "extraction_calls": 1,
        "input_tokens": 1_000,
        "cached_input_tokens": 200,
        "output_tokens": 100,
        "model_gateway_calls": 4,
        "paid_model_calls": 4,
        "grader_calls": 1,
        "grader_containers": 1,
        "official_grader_runs": 1,
    })
    second_accounting = {field: 0 for field in benchmark_matrix.ACCOUNTING_FIELDS}
    second_accounting.update({
        "solve_calls": 3,
        "decomposition_calls": 1,
        "extraction_calls": 1,
        "input_tokens": 2_000,
        "output_tokens": 200,
        "model_gateway_calls": 5,
        "paid_model_calls": 5,
        "grader_calls": 1,
        "grader_containers": 1,
        "official_grader_runs": 1,
    })
    first_memory = {field: 0 for field in benchmark_matrix.MEMORY_FIELDS}
    first_memory.update({
        "recall_attempts": 2,
        "injected_records": 1,
        "episodic_injections": 1,
        "retained_records": 2,
        "archived_records": 1,
        "net_memory_growth": 1,
    })
    second_memory = {field: 0 for field in benchmark_matrix.MEMORY_FIELDS}
    second_memory.update({
        "recall_attempts": 3,
        "injected_records": 1,
        "user_semantic_injections": 1,
        "retained_records": 1,
        "net_memory_growth": 1,
    })
    records = [
        {
            "actual_accounting": first_accounting,
            "actual_memory_metrics": first_memory,
            "actual_usd": "0.003550000000",
            "resolved": True,
        },
        {
            "actual_accounting": second_accounting,
            "actual_memory_metrics": second_memory,
            "actual_usd": "0.008000000000",
            "resolved": False,
        },
    ]
    summary = {
        "actual_accounting": {
            field: first_accounting[field] + second_accounting[field]
            for field in benchmark_matrix.ACCOUNTING_FIELDS
        },
        "actual_memory_metrics": {
            field: first_memory[field] + second_memory[field]
            for field in benchmark_matrix.MEMORY_FIELDS
        },
        "actual_total_tokens": 3_300,
        "actual_usd": "0.011550000000",
        "resolved_count": 1,
    }
    return records, summary, pricing


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("actual_accounting", "input_tokens"),
        ("actual_memory_metrics", "recall_attempts"),
        (None, "resolved_count"),
        (None, "actual_total_tokens"),
        (None, "actual_usd"),
    ],
)
def test_stream_summary_tampering_is_rejected(
    tmp_path: Path, section: str | None, field: str
) -> None:
    records, summary, pricing = _stream_total_fixture()
    benchmark_matrix._validate_stream_summary_totals(
        tmp_path / "M1.arm-summary.json", summary, records, pricing
    )
    tampered = deepcopy(summary)
    if section is None:
        tampered[field] = (
            "0.011550000001" if field == "actual_usd" else int(tampered[field]) + 1
        )
    else:
        tampered[section][field] += 1
    with pytest.raises(benchmark_matrix.MatrixError, match="task/stream"):
        benchmark_matrix._validate_stream_summary_totals(
            tmp_path / "M1.arm-summary.json", tampered, records, pricing
        )


@pytest.mark.parametrize("section", ["actual_accounting", "actual_memory_metrics"])
def test_stream_summary_rejects_unknown_raw_metric_fields(
    tmp_path: Path, section: str
) -> None:
    records, summary, pricing = _stream_total_fixture()
    records[0][section]["unfrozen_extra_metric"] = 1
    with pytest.raises(benchmark_matrix.MatrixError, match="shape differs"):
        benchmark_matrix._validate_stream_summary_totals(
            tmp_path / "M1.arm-summary.json", summary, records, pricing
        )


def test_task_actual_usd_is_recomputed_from_frozen_pricing() -> None:
    records, _summary, pricing = _stream_total_fixture()
    assert benchmark_matrix._actual_usd_from_accounting(
        records[0]["actual_accounting"], pricing
    ) == records[0]["actual_usd"]


def test_aggregate_revalidates_exact_workflow_approval_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "8123456789")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    evidence = {
        "approval_artifact_sha256": "a" * 64,
        "approved_request_sha256": hashlib.sha256(
            (ROOT / "configs/trimem_v1/benchmark_exec_request.json").read_bytes()
        ).hexdigest(),
        "approved_workflow_run_id": "8123456789",
        "approved_workflow_run_attempt": "3",
        "freeze_sha256": hashlib.sha256(
            (ROOT / "artifacts/trimem_v1/freeze.json").read_bytes()
        ).hexdigest(),
        "git_head": head,
        "phase": "GRADER_SMOKE",
    }
    path = tmp_path / "external-approval-evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    assert benchmark_matrix._approval_binding("grader-smoke", tmp_path) == {
        key: str(evidence[key]) for key in sorted(evidence)
    }
    evidence["phase"] = "HELDOUT_BENCHMARK"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(benchmark_matrix.MatrixError, match="phase"):
        benchmark_matrix._approval_binding("grader-smoke", tmp_path)


def test_benchmark_database_role_boundary_is_exact() -> None:
    benchmark_run.validate_database_role_boundary(
        "postgresql+asyncpg://postgres:admin@db.example:5432/trimem",
        "postgresql+asyncpg://api_service:runtime@db.example:5432/trimem",
    )
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="roles"):
        benchmark_run.validate_database_role_boundary(
            "postgresql+asyncpg://postgres:admin@db.example:5432/trimem",
            "postgresql+asyncpg://api_service_shadow:runtime@db.example:5432/trimem",
        )
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="endpoints"):
        benchmark_run.validate_database_role_boundary(
            "postgresql+asyncpg://postgres:admin@db.example:5432/trimem",
            "postgresql+asyncpg://api_service:runtime@other.example:5432/trimem",
        )


@pytest.mark.parametrize("arm", ["M0", "M1"])
def test_non_m2_stream_rejects_m2_artifacts_before_session_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    arm: str,
) -> None:
    experiment_id = "trimemv1-aaaaaaaaaaaa-" + arm.lower()
    seed_body = {
        "schema": "trimem/benchmark-identity-seed-evidence/1.0",
        "experiment_id": experiment_id,
        "stream_id": arm,
        "rows": [],
    }
    monkeypatch.setattr(
        benchmark_run,
        "read_json",
        lambda _path: {
            "retrieval_embedding": {"production": {"model_id": "unused"}}
        },
    )
    with pytest.raises(
        benchmark_run.BenchmarkExecutionError,
        match="cannot receive an M2 policy/checkpoint",
    ):
        benchmark_run.run_arm_stream(
            split="development",
            arm=arm,
            stream_id=arm,
            runtime_lock=object(),
            m2_manifest={"unexpected": True},
            dqn_checkpoint_path=tmp_path / "unexpected-checkpoint.json",
            selected_prompt_candidate_id="baseline",
            approval={"git_head": "a" * 40},
            targets=[],
            rows={},
            tasks=[],
            workspace_factory=object(),
            checkout_evidence={},
            harnesses={},
            output_root=tmp_path,
            ledger=object(),
            database_url="unused",
            qdrant_url="unused",
            resume=False,
            identity_seed_evidence={
                **seed_body,
                "digest": benchmark_run.canonical_hash(seed_body),
            },
        )


def _sealed_public_aggregate(tmp_path: Path) -> Path:
    digest = "a" * 64
    body = {
        "schema": "trimem/verified-aggregate/1.0",
        "manifest": "heldout",
        "status": "PASS",
        "outcomes": [{
            "target_id": "t",
            "arm": "M0",
            "resolved": False,
            "actual_accounting": {"task_wall_time_ms": 17},
            "actual_memory_metrics": {"recall_attempts": 0},
            "actual_usd": "0.000000000000",
        }],
        "stream_totals": [{
            "arm": "M0",
            "actual_accounting": {"task_wall_time_ms": 17},
            "actual_memory_metrics": {"recall_attempts": 0},
            "actual_usd": "0.000000000000",
            "identity_seed_digest": "sha256:" + digest,
            "resolved_count": 0,
        }],
        "benchmark_roles": [{
            "benchmark_id": "swebench_verified",
            "dataset_id": "SWE-bench/SWE-bench_Verified",
            "dataset_revision": "c" * 40,
            "role": "PRIMARY",
            "target_count": 1,
        }],
        "benchmark_totals": [{
            "arm": "M0",
            "benchmark_id": "swebench_verified",
            "dataset_revision": "c" * 40,
            "endpoint": "official_resolved_pass_at_1",
            "n": 1,
            "pass_at_1": "0.000000000000",
            "reporting_role": "PRIMARY",
            "resolved_count": 0,
        }],
        "primary_endpoints": [{
            "arm": "M0",
            "benchmark_id": "swebench_verified",
            "dataset_revision": "c" * 40,
            "endpoint": "official_resolved_pass_at_1",
            "n": 1,
            "pass_at_1": "0.000000000000",
            "reporting_role": "PRIMARY",
            "resolved_count": 0,
        }],
        "secondary_endpoints": [],
        "approval_binding": {
            "approval_artifact_sha256": digest,
            "approved_request_sha256": digest,
            "freeze_sha256": digest,
            "git_head": "b" * 40,
            "phase": "HELDOUT_BENCHMARK",
            "approved_workflow_run_id": "8123456789",
            "approved_workflow_run_attempt": "1",
        },
    }
    aggregate = tmp_path / "aggregate.json"
    aggregate.write_text(json.dumps({
        **body,
        "aggregate_sha256": hashlib.sha256(
            json.dumps(
                body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
    }), encoding="utf-8")
    return aggregate


def test_public_artifact_consumes_only_sealed_aggregate(tmp_path: Path) -> None:
    source = tmp_path / "restricted"
    source.mkdir()
    record = {
        "target_id": "t", "arm": "M0", "runtime_arm": "M0",
        "execution_status": "SUCCESS", "official_grader": True, "resolved": False,
        "actual_accounting": {"task_wall_time_ms": 999999},
        "patch": "TOP_SECRET_GOLD", "test_patch": "TOP_SECRET_TEST",
    }
    raw_result = source / "t.result.json"
    raw_result.write_text(json.dumps(record), encoding="utf-8")
    aggregate = _sealed_public_aggregate(tmp_path)
    output = tmp_path / "public.json"
    public_artifact.package(aggregate, output)
    first = output.read_bytes()

    # Raw records can change after aggregation without entering the public
    # package; only the already-sealed aggregate is consumed.
    record["actual_accounting"]["task_wall_time_ms"] = 123456789
    record["raw_report"] = "LATE_PRIVATE_TAMPER"
    raw_result.write_text(json.dumps(record), encoding="utf-8")
    public_artifact.package(aggregate, output)
    assert output.read_bytes() == first

    text = output.read_text(encoding="utf-8")
    value = json.loads(text)
    assert "TOP_SECRET" not in text and "LATE_PRIVATE_TAMPER" not in text
    assert value["outcomes"][0]["actual_usd"] == "0.000000000000"
    assert value["outcomes"][0]["actual_accounting"]["task_wall_time_ms"] == 17
    assert value["primary_endpoints"][0]["benchmark_id"] == "swebench_verified"
    assert value["approval_binding"]["approved_workflow_run_id"] == "8123456789"


def test_public_artifact_rejects_post_aggregate_payload_tampering(tmp_path: Path) -> None:
    aggregate = _sealed_public_aggregate(tmp_path)
    value = json.loads(aggregate.read_text(encoding="utf-8"))
    value["outcomes"][0]["resolved"] = True
    aggregate.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(public_artifact.PublicArtifactError, match="aggregate seal"):
        public_artifact.package(aggregate, tmp_path / "public.json")
