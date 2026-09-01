from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
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
import trimem_grader_smoke as grader_smoke  # noqa: E402
import trimem_grader_smoke_protocol as smoke_protocol  # noqa: E402
import trimem_m2_candidates as candidates  # noqa: E402
import trimem_official_grader as official_grader  # noqa: E402
import trimem_public_artifact as public_artifact  # noqa: E402
import trimem_pull_locked_images as image_pull  # noqa: E402
import trimem_run_with_resume as resume_runner  # noqa: E402
import trimem_select_targets as selector  # noqa: E402
import trimem_verify_ready as readiness  # noqa: E402
from enterprise_memory.trimem.workspace import WorkspaceGraderContext  # noqa: E402


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
        "grader_smoke": "01f9e41f1ce3f285c651c3bc857a1f7422ed7e0f9ccfb451b42aedf9a4aef52e",
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
    assert requirements["current_status"] == {
        "GRADER_EXEC_PACKAGE": "CORRECTION_IN_PROGRESS",
        "OFFICIAL_GRADER_VIABILITY": "NOT_YET_ESTABLISHED",
        "PERFORMANCE": "NOT_MEASURED",
        "TRIMEM_SYSTEM_IMPLEMENTATION": "CREDENTIAL_FREE_GREEN",
    }
    pending = requirements["explicitly_allowed_pending_at_pre_exec_ready"]
    assert "PENDING_EXEC_APPROVAL" in pending["official_grader_smoke"]
    assert "PRE_DEVELOPMENT" in pending["selected_m2_checkpoint"]
    service_boundary = requirements["credential_free_service_ci_boundary"]
    assert "ALLOWED_PRE_EXEC" in service_boundary
    assert "digest-pinned PostgreSQL and Qdrant support services" in service_boundary
    assert "official grader/benchmark target images" in service_boundary
    request = _read(ROOT / "configs/trimem_v1/benchmark_exec_request.json")
    assert request["readiness_gate"].endswith(
        "--level benchmark-approval --require-git-tracked"
    )
    assert "official grader/benchmark target image pull or run" in request["prohibited_before_approval"]
    assert "Docker image pull or run" not in request["prohibited_before_approval"]
    assert requirements["execution_counters"] == {
        "grader_containers": 0,
        "model_gateway_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
    }
    protection = _read(
        ROOT / "artifacts/trimem_v1/grader_smoke_environment_protection.json"
    )
    assert protection["configured_before_sentinel"] is True
    assert protection["environment"] == {
        "can_admins_bypass": False,
        "id": 20971935382,
        "name": "trimem-grader-smoke-exec",
    }
    assert protection["protection_rule"]["type"] == "required_reviewers"
    assert protection["branch_policy"]["name"] == "codex/trimem-coder-v1"
    assert protection["secret_state_before_sentinel"]["installed_secret_names"] == []


def test_benchmark_approval_cannot_disable_git_tracked_freeze(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    observed: list[bool] = []
    monkeypatch.setattr(
        readiness,
        "validate_static",
        lambda require_git_tracked: observed.append(require_git_tracked) or {},
    )
    monkeypatch.setattr(readiness, "preapproval_blockers", lambda: [])
    monkeypatch.setattr(
        sys,
        "argv",
        ["trimem_verify_ready.py", "--level", "benchmark-approval"],
    )
    assert readiness.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert observed == [True]
    assert report["git_tracked_freeze_required"] is True
    assert "endpoint" not in report
    assert report["official_grader_viability"] == "NOT_YET_ESTABLISHED"


def test_freeze_allowlist_closes_all_trimem_execution_surfaces() -> None:
    frozen = set(freeze.frozen_paths(ROOT))
    assert "COMPANY_HANDOFF_MANIFEST.json" not in frozen
    assert "docs/STATUS.yaml" not in frozen
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


def test_frozen_noop_baseline_audit_proves_all_six_exact_base_trees() -> None:
    audit = _read(ROOT / "artifacts/trimem_v1/noop_baseline_six_commit_audit.json")
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    body = {key: value for key, value in audit.items() if key != "audit_sha256"}
    assert audit["status"] == "PASS"
    assert audit["noop_baseline"] == smoke_protocol.NOOP_BASELINE_LOCK
    assert audit["manifest_target_set_sha256"] == manifest["target_set_sha256"]
    assert audit["audit_sha256"] == hashlib.sha256(_canonical(body)).hexdigest()
    assert len(audit["rows"]) == 6
    assert {
        (row["repository"], row["instance_id"], row["base_commit"])
        for row in audit["rows"]
    } == {
        (row["repository"], row["instance_id"], row["base_commit"])
        for row in manifest["targets"]
        if row["probe"] == "GOLD"
    }
    for row in audit["rows"]:
        assert row["root_marker_absent_at_base"] is True
        assert row["patch_applies_cached"] is True
        assert row["isolated_temporary_index"] is True
        assert row["staged_marker_sha256"] == hashlib.sha256(
            smoke_protocol.NOOP_BASELINE_CONTENT
        ).hexdigest()
        assert row["changed_paths"] == [smoke_protocol.NOOP_BASELINE_PATH]
        assert row["forbidden_source_test_build_or_package_paths_touched"] == []
        assert re.fullmatch(r"[0-9a-f]{40}", row["base_tree"])


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
    smoke = workflows[2].read_text(encoding="utf-8")
    assert "workflow_dispatch:" in smoke and "pull_request:" not in smoke
    assert "push:" in smoke
    assert "      - codex/trimem-coder-v1" in smoke
    assert "      - artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST.json" in smoke
    assert "branch-trigger-preflight:" in smoke
    assert "environment: trimem-grader-smoke-exec" in smoke
    assert "bounded-disk exact GOLD and NOOP_BASELINE pairs" in smoke
    assert smoke.count(
        "--image-evidence-dir artifacts/trimem_v1/grader_smoke_exec/image-materialization"
    ) == 2
    assert "--cleanup-grader-smoke" in smoke
    benchmark = workflows[3].read_text(encoding="utf-8")
    assert "workflow_dispatch:" in benchmark
    assert all(trigger not in benchmark for trigger in ("pull_request:", "push:", "schedule:"))
    for path in workflows[2:]:
        text = path.read_text(encoding="utf-8")
        assert "openssl enc -aes-256-cbc" in text
        assert "restricted-encrypted" in text
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


def test_bounded_disk_image_helpers_pull_inspect_and_remove_only_exact_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = "example/image@sha256:" + "a" * 64
    tag = "example/image:frozen-harness-tag"
    calls: list[list[str]] = []

    def fake_run(argv, root, index, stage):
        calls.append(list(argv))
        stdout = json.dumps([image]) if stage == "inspect" else ""
        return (
            type("Completed", (), {"returncode": 0, "stdout": stdout, "stderr": ""})(),
            {
                "stdout": {"path": f"{index:03d}-{stage}/stdout.txt", "bytes": len(stdout), "sha256": "b" * 64},
                "stderr": {"path": f"{index:03d}-{stage}/stderr.txt", "bytes": 0, "sha256": "c" * 64},
            },
        )

    monkeypatch.setattr(image_pull, "_run", fake_run)
    observed = image_pull.pull_and_observe_image(image, tmp_path, 4)
    removed = image_pull.remove_materialized_image(image, [tag], tmp_path, 5)
    assert observed["expected_digest"] == "sha256:" + "a" * 64
    assert removed["references"] == [tag, image]
    assert calls == [
        ["docker", "pull", image],
        ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image],
        ["docker", "image", "rm", "--force", tag, image],
    ]
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="not exact"):
        image_pull.remove_materialized_image(image, ["bad tag"], tmp_path, 6)


def test_workflow_fallback_cleanup_touches_only_fourteen_frozen_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, root, index, stage):
        calls.append(list(argv))
        completed = type(
            "Completed", (), {"returncode": 0, "stdout": "[]", "stderr": ""}
        )()
        refs = {
            stream: {
                "path": f"{index:03d}-{stage}/{stream}.txt",
                "bytes": 0,
                "sha256": "a" * 64,
            }
            for stream in ("stdout", "stderr")
        }
        return completed, refs

    monkeypatch.setattr(image_pull, "_run", fake_run)
    report = image_pull.cleanup_grader_smoke_images(tmp_path)
    inspected = [call[-1] for call in calls if call[:3] == ["docker", "image", "inspect"]]
    removed = [call[-1] for call in calls if call[:4] == ["docker", "image", "rm", "--force"]]
    assert len(inspected) == len(set(inspected)) == 14
    assert removed == inspected
    assert report["exact_reference_count"] == 14
    assert report["removed_reference_count"] == 14
    assert report["already_absent_reference_count"] == 0


def test_smoke_image_lifecycle_pulls_each_identity_once_and_removes_exact_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    images, support = benchmark_run.image_entries(require_benchmark=False)
    calls: list[tuple[str, str, tuple[str, ...]]] = []

    def fake_pull(image: str, evidence_root: Path, index: int) -> dict:
        calls.append(("PULL", image, ()))
        return {
            "image": image,
            "expected_digest": image.rsplit("@", 1)[1],
            "observed_digests": [image.rsplit("@", 1)[1]],
            "pull": {"stdout": {}, "stderr": {}},
            "inspect": {"stdout": {}, "stderr": {}},
        }

    def fake_remove(
        image: str, tags: list[str], evidence_root: Path, index: int
    ) -> dict:
        calls.append(("REMOVE", image, tuple(tags)))
        return {
            "image": image,
            "references": [*tags, image],
            "remove": {"stdout": {}, "stderr": {}},
            "status": "PASS",
        }

    monkeypatch.setattr(grader_smoke, "pull_and_observe_image", fake_pull)
    monkeypatch.setattr(grader_smoke, "remove_materialized_image", fake_remove)
    lifecycle = grader_smoke._SerialImageLifecycle(
        approval={
            "phase": "GRADER_SMOKE",
            "approval_artifact_sha256": "a" * 64,
            "git_head": "b" * 40,
        },
        evidence_root=tmp_path,
        targets=manifest["targets"],
        images=images,
        support=support,
    )
    for index, target in enumerate(manifest["targets"]):
        lifecycle.before_target(index, target)
        lifecycle.after_target(index, target)
    lifecycle.finish()

    target_rows = manifest["targets"][0::2]
    target_images = [images[row["instance_id"]]["image"] for row in target_rows]
    support_image, support_tag = support[0]
    assert [image for action, image, _ in calls if action == "PULL"] == [
        *target_images[:2], support_image, *target_images[2:]
    ]
    assert [image for action, image, _ in calls if action == "REMOVE"] == [
        *target_images, support_image
    ]
    assert calls[-1] == ("REMOVE", support_image, (support_tag,))
    report = _read(tmp_path / "image-lifecycle-report.json")
    assert report["status"] == "PASS"
    assert report["actual"] == {
        "exact_image_removals": 7,
        "max_resident_support_images": 1,
        "max_resident_target_images": 1,
        "resident_support_images": 0,
        "resident_target_images": 0,
        "support_image_pulls": 1,
        "target_image_pulls": 6,
    }


def test_smoke_image_lifecycle_cleans_pull_success_inspect_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    images, support = benchmark_run.image_entries(require_benchmark=False)
    stages: list[str] = []

    def fake_run(argv, root, index, stage):
        stages.append(stage)
        stdout = "[]" if stage == "inspect" else ""
        completed = type(
            "Completed", (), {"returncode": 0, "stdout": stdout, "stderr": ""}
        )()
        refs = {
            stream: {
                "path": f"{index:03d}-{stage}/{stream}.txt",
                "bytes": len(stdout) if stream == "stdout" else 0,
                "sha256": "a" * 64,
            }
            for stream in ("stdout", "stderr")
        }
        return completed, refs

    monkeypatch.setattr(image_pull, "_run", fake_run)
    lifecycle = grader_smoke._SerialImageLifecycle(
        approval={"phase": "GRADER_SMOKE", "approval_artifact_sha256": "a" * 64, "git_head": "b" * 40},
        evidence_root=tmp_path,
        targets=manifest["targets"], images=images, support=support,
    )
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="digest mismatch") as captured:
        lifecycle.before_target(0, manifest["targets"][0])
    lifecycle.abort(captured.value)
    report = _read(tmp_path / "image-lifecycle-report.json")
    assert stages == ["pull", "inspect", "remove"]
    assert report["status"] == "FAILED"
    assert report["actual"]["resident_target_images"] == 0
    assert report["events"][0]["action"] == "PULL_TARGET_FAILED"
    assert report["events"][1]["action"] == "REMOVE_TARGET"


def test_smoke_image_lifecycle_abort_removes_target_and_multi_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    images, support = benchmark_run.image_entries(require_benchmark=False)
    calls: list[tuple[str, str]] = []

    def fake_pull(image: str, evidence_root: Path, index: int) -> dict:
        calls.append(("PULL", image))
        digest = image.rsplit("@", 1)[1]
        return {"image": image, "expected_digest": digest, "observed_digests": [digest], "pull": {}, "inspect": {}}

    def fake_remove(image: str, tags: list[str], evidence_root: Path, index: int) -> dict:
        calls.append(("REMOVE", image))
        return {"image": image, "references": [*tags, image], "remove": {}, "status": "PASS"}

    monkeypatch.setattr(grader_smoke, "pull_and_observe_image", fake_pull)
    monkeypatch.setattr(grader_smoke, "remove_materialized_image", fake_remove)
    lifecycle = grader_smoke._SerialImageLifecycle(
        approval={"phase": "GRADER_SMOKE", "approval_artifact_sha256": "a" * 64, "git_head": "b" * 40},
        evidence_root=tmp_path,
        targets=manifest["targets"], images=images, support=support,
    )
    for index, target in enumerate(manifest["targets"][:4]):
        lifecycle.before_target(index, target)
        lifecycle.after_target(index, target)
    lifecycle.before_target(4, manifest["targets"][4])
    lifecycle.abort(RuntimeError("synthetic post-pull failure"))
    report = _read(tmp_path / "image-lifecycle-report.json")
    support_image = support[0][0]
    multi_image = images[manifest["targets"][4]["instance_id"]]["image"]
    assert calls[-2:] == [("REMOVE", multi_image), ("REMOVE", support_image)]
    assert report["status"] == "FAILED"
    assert report["actual"]["resident_target_images"] == 0
    assert report["actual"]["resident_support_images"] == 0


def test_smoke_image_lifecycle_cleanup_failure_is_truthful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    images, support = benchmark_run.image_entries(require_benchmark=False)

    def fake_pull(image: str, evidence_root: Path, index: int) -> dict:
        digest = image.rsplit("@", 1)[1]
        return {"image": image, "expected_digest": digest, "observed_digests": [digest], "pull": {}, "inspect": {}}

    def fail_remove(*args, **kwargs):
        raise benchmark_run.BenchmarkExecutionError("synthetic removal failure")

    monkeypatch.setattr(grader_smoke, "pull_and_observe_image", fake_pull)
    monkeypatch.setattr(grader_smoke, "remove_materialized_image", fail_remove)
    lifecycle = grader_smoke._SerialImageLifecycle(
        approval={"phase": "GRADER_SMOKE", "approval_artifact_sha256": "a" * 64, "git_head": "b" * 40},
        evidence_root=tmp_path,
        targets=manifest["targets"], images=images, support=support,
    )
    lifecycle.before_target(0, manifest["targets"][0])
    with pytest.raises(benchmark_run.BenchmarkExecutionError) as captured:
        lifecycle.after_target(1, manifest["targets"][1])
    lifecycle.abort(captured.value)
    report = _read(tmp_path / "image-lifecycle-report.json")
    assert report["status"] == "CLEANUP_FAILED"
    assert report["actual"]["resident_target_images"] == 1
    assert report["actual"]["exact_image_removals"] == 0
    assert report["failure"]["cleanup_failures"]


def test_smoke_aggregate_seals_exact_image_lifecycle_and_raw_stages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    images, support = benchmark_run.image_entries(require_benchmark=False)
    image_root = tmp_path / "image-materialization"
    results = tmp_path / "results"
    results.mkdir()
    approval_hash, head = "a" * 64, "b" * 40
    (results / "external-approval-evidence.json").write_text(
        json.dumps({
            "approval_artifact_sha256": approval_hash,
            "git_head": head,
            "phase": "GRADER_SMOKE",
        }),
        encoding="utf-8",
    )

    def streams(index: int, stage: str) -> dict:
        value = {}
        for stream, raw in (("stdout", f"{stage}\n".encode()), ("stderr", b"")):
            path = image_root / f"{index:03d}-{stage}/{stream}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            value[stream] = {
                "path": path.relative_to(image_root).as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
        return value

    def fake_pull(image: str, evidence_root: Path, index: int) -> dict:
        digest = image.rsplit("@", 1)[1]
        return {
            "image": image,
            "expected_digest": digest,
            "observed_digests": [digest],
            "pull": streams(index, "pull"),
            "inspect": streams(index, "inspect"),
        }

    def fake_remove(image: str, tags: list[str], evidence_root: Path, index: int) -> dict:
        return {
            "image": image,
            "references": [*tags, image],
            "remove": streams(index, "remove"),
            "status": "PASS",
        }

    monkeypatch.setattr(grader_smoke, "pull_and_observe_image", fake_pull)
    monkeypatch.setattr(grader_smoke, "remove_materialized_image", fake_remove)
    lifecycle = grader_smoke._SerialImageLifecycle(
        approval={"phase": "GRADER_SMOKE", "approval_artifact_sha256": approval_hash, "git_head": head},
        evidence_root=image_root,
        targets=manifest["targets"], images=images, support=support,
    )
    for index, target in enumerate(manifest["targets"]):
        lifecycle.before_target(index, target)
        lifecycle.after_target(index, target)
    lifecycle.finish()
    sealed = benchmark_matrix._validate_smoke_image_lifecycle(results, image_root)
    assert sealed["status"] == "PASS" and sealed["event_count"] == 14

    report_path = image_root / "image-lifecycle-report.json"
    report = _read(report_path)
    report["events"].pop()
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(benchmark_matrix.MatrixError, match="event count"):
        benchmark_matrix._validate_smoke_image_lifecycle(results, image_root)


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
    sentinel_path = artifact / "exec_requests/GRADER_SMOKE_EXEC_REQUEST.json"
    sentinel_path.parent.mkdir(parents=True)
    sentinel = {
        "schema": "trimem/grader-smoke-branch-trigger/1.0",
        "request_id": "TRIMEM_V1_GRADER_SMOKE_EXEC_001",
        "phase": "GRADER_SMOKE",
        "frozen_request_sha256": "sha256:"
        + hashlib.sha256(request_path.read_bytes()).hexdigest(),
    }
    sentinel_path.write_text(json.dumps(sentinel), encoding="utf-8")
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
        "approved_grader_containers": hard["benchmark_grader_containers"],
        "approved_workflow_run_id": "8123456789",
        "approved_workflow_run_attempt": "1",
        "approved_legal_terms_acceptance": True,
        "approval_actor": "benchmark-owner",
        "approval_timestamp": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
    }
    document = {
        "schema": "trimem/external-exec-approval/1.0",
        "request_id": sentinel["request_id"],
        "approved_request_sha256": hashlib.sha256(sentinel_path.read_bytes()).hexdigest(),
        "approval": approval,
    }
    path = tmp_path / "approval.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(benchmark_run, "ROOT", repository)
    monkeypatch.setattr(benchmark_run, "git_tracked", lambda _path: None)
    monkeypatch.setattr(benchmark_run, "git_head", lambda: "c" * 40)
    monkeypatch.setattr(
        benchmark_run,
        "validate_grader_smoke_sentinel",
        lambda path: sentinel if path == sentinel_path else pytest.fail("wrong sentinel"),
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "8123456789")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    assert benchmark_run.validate_exec_approval("grader-smoke", path)["approved_workflow_run_id"] == "8123456789"
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="run attempt"):
        benchmark_run.validate_exec_approval("grader-smoke", path)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    document["approval"]["approved_task_arm_runs"] = False
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="approved_task_arm_runs"):
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
    head = "b" * 40
    repository = tmp_path / "repository"
    sentinel = repository / "artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST.json"
    frozen = repository / "artifacts/trimem_v1/freeze.json"
    config = repository / "configs/trimem_v1"
    sentinel.parent.mkdir(parents=True)
    frozen.parent.mkdir(parents=True, exist_ok=True)
    config.mkdir(parents=True)
    request_id = "TRIMEM_V1_GRADER_SMOKE_EXEC_001"
    sentinel.write_text(
        json.dumps({"request_id": request_id, "request": "exact-sentinel"}) + "\n",
        encoding="utf-8",
    )
    frozen.write_text('{"freeze":"exact"}\n', encoding="utf-8")
    policy = _read(ROOT / "configs/trimem_v1/benchmark_exec_request.json")
    hard = _read(ROOT / "configs/trimem_v1/cost_plan.json")["phase_hard_caps"]["GRADER_SMOKE"]
    (config / "benchmark_exec_request.json").write_text(
        json.dumps(policy), encoding="utf-8"
    )
    (config / "cost_plan.json").write_text(
        json.dumps({"phase_hard_caps": {"GRADER_SMOKE": hard}}), encoding="utf-8"
    )
    monkeypatch.setattr(benchmark_matrix, "ROOT", repository)
    monkeypatch.setattr(
        benchmark_matrix.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, head + "\n", ""),
    )
    request_digest = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    freeze_digest = hashlib.sha256(frozen.read_bytes()).hexdigest()
    approval_raw = _canonical({
        "schema": "trimem/external-exec-approval/1.0",
        "request_id": request_id,
        "approved_request_sha256": request_digest,
        "approval": {
            "approved_freeze_sha256": freeze_digest,
            "approved_git_commit": head,
            "approved_phase": "GRADER_SMOKE",
            "approved_task_arm_runs": hard["task_arm_runs"],
            "approved_paid_model_call_cap": hard["paid_model_calls"],
            "approved_input_token_cap": hard["input_tokens"],
            "approved_output_token_cap": hard["output_tokens"],
            "approved_currency_hard_cap": hard["total_usd"],
            "approved_grader_containers": hard["benchmark_grader_containers"],
            "approved_workflow_run_id": "8123456789",
            "approved_workflow_run_attempt": "3",
            "approved_legal_terms_acceptance": True,
            "approval_actor": "benchmark-owner",
            "approval_timestamp": (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            ).isoformat().replace("+00:00", "Z"),
        },
    }) + b"\n"
    (tmp_path / "restricted-external-approval.json").write_bytes(approval_raw)
    evidence = {
        "approval_artifact_sha256": hashlib.sha256(approval_raw).hexdigest(),
        "approved_request_sha256": request_digest,
        "approved_workflow_run_id": "8123456789",
        "approved_workflow_run_attempt": "3",
        "freeze_sha256": freeze_digest,
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
    evidence["phase"] = "GRADER_SMOKE"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    (tmp_path / "restricted-external-approval.json").write_bytes(approval_raw + b" ")
    with pytest.raises(benchmark_matrix.MatrixError, match="restricted exact"):
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


def test_grader_smoke_protocol_is_one_nonempty_interleaved_baseline() -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    targets = grader_smoke._smoke_targets(manifest)
    assert manifest["matrix_kind"] == smoke_protocol.MATRIX_KIND
    assert manifest["noop_baseline"] == smoke_protocol.NOOP_BASELINE_LOCK
    assert len(smoke_protocol.NOOP_BASELINE_PATCH) == 165
    assert hashlib.sha256(smoke_protocol.NOOP_BASELINE_PATCH).hexdigest() == (
        "0f4fb705a73dd7e804773b35e2ab0e4e2f17248c571e69333e9b8de7c2025775"
    )
    assert [row["probe"] for row in targets] == list(smoke_protocol.PROBE_SEQUENCE)
    assert [row["order_index"] for row in targets] == list(range(12))
    for gold, noop in zip(targets[0::2], targets[1::2]):
        assert gold["instance_id"] == noop["instance_id"]
        assert gold["target_id"].endswith("--gold")
        assert noop["target_id"].endswith("--noop-baseline")
        assert grader_smoke._patch_for_target(noop, {}, manifest).encode() == (
            smoke_protocol.NOOP_BASELINE_PATCH
        )


def test_grader_smoke_rejects_empty_gold_before_grader_factory() -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    target = manifest["targets"][0]
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="lacks patch"):
        grader_smoke._patch_for_target(target, {"patch": " \n"}, manifest)


def test_official_gateway_rejects_empty_patch_before_image_or_evaluator() -> None:
    target = _frozen_official_target("swebench_verified")
    gateway = object.__new__(official_grader.OfficialHarnessGraderGateway)
    gateway.target = target
    calls: list[str] = []
    gateway._verify_and_tag = lambda *args, **kwargs: calls.append("image")
    for patch in ("", " \n\t"):
        request = official_grader.GradeRequest(
            task_id=target.target_id,
            repository=target.repository,
            base_commit=target.base_commit,
            patch=patch,
            workspace=WorkspaceGraderContext(
                kind="test", repository_files={}, base_commit=target.base_commit,
            ),
        )
        with pytest.raises(ValueError, match="empty patch"):
            gateway.grade(request)
    assert calls == []


def test_noop_baseline_patch_applies_as_one_file_only_index_change(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "trimem@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "TriMem Test"], check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "commit", "--allow-empty", "-m", "base"],
        check=True, capture_output=True,
    )
    patch = tmp_path / "noop.patch"
    patch.write_bytes(smoke_protocol.NOOP_BASELINE_PATCH)
    subprocess.run(
        ["git", "-C", str(repository), "apply", "--cached", "--check", str(patch)], check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "apply", "--cached", str(patch)], check=True,
    )
    changed = subprocess.run(
        ["git", "-C", str(repository), "diff", "--cached", "--name-status", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    marker = subprocess.run(
        ["git", "-C", str(repository), "show", ":0:.trimem_grader_noop"],
        check=True, capture_output=True,
    ).stdout
    assert changed == ["A\t.trimem_grader_noop"]
    assert marker == smoke_protocol.NOOP_BASELINE_CONTENT


def _frozen_official_target(benchmark_id: str) -> official_grader.FrozenOfficialTarget:
    swe = benchmark_id == "swebench_verified"
    return official_grader.FrozenOfficialTarget(
        target_id="target",
        benchmark_id=benchmark_id,
        instance_id="astropy__astropy-13579" if swe else "vuejs__core-8911",
        repository="astropy/astropy" if swe else "vuejs/core",
        base_commit="a" * 40,
        dataset_revision="b" * 40,
        source_row_sha256="c" * 64,
        image="example.invalid/grader@sha256:" + "d" * 64,
        harness_image_tag="example.invalid/grader:locked",
        harness_revision=(
            official_grader.SWE_HARNESS_REVISION
            if swe else official_grader.MULTI_HARNESS_REVISION
        ),
    )


def test_swe_actual_test_evidence_requires_complete_f2p_and_zero_regressions() -> None:
    target = _frozen_official_target("swebench_verified")
    source = {"FAIL_TO_PASS": ["f2p"], "PASS_TO_PASS": ["p2p"]}
    status = {
        target.instance_id: {
            "patch_exists": True,
            "patch_is_None": False,
            "patch_successfully_applied": True,
            "infra_failure": False,
            "resolved": True,
            "tests_status": {
                "FAIL_TO_PASS": {"success": ["f2p"], "failure": []},
                "PASS_TO_PASS": {"success": ["p2p"], "failure": []},
            },
        }
    }
    summary = official_grader.validate_official_test_evidence(
        target,
        source_row=source,
        test_output_raw=b"real pytest output\n",
        test_status_raw=_canonical(status),
        resolved=True,
    )
    assert summary["fail_to_pass_classified"] == summary["fail_to_pass_expected"] == 1
    assert summary["pass_to_pass_regressions"] == 0

    regressed = deepcopy(status)
    regressed[target.instance_id]["tests_status"]["PASS_TO_PASS"] = {
        "success": [], "failure": ["p2p"],
    }
    with pytest.raises(official_grader.OfficialGraderError, match="regression"):
        official_grader.validate_official_test_evidence(
            target,
            source_row=source,
            test_output_raw=b"real pytest output\n",
            test_status_raw=_canonical(regressed),
            resolved=True,
        )
    for field, value in (("patch_is_None", True), ("infra_failure", True)):
        invalid = deepcopy(status)
        invalid[target.instance_id][field] = value
        with pytest.raises(official_grader.OfficialGraderError, match="status/result"):
            official_grader.validate_official_test_evidence(
                target,
                source_row=source,
                test_output_raw=b"real pytest output\n",
                test_status_raw=_canonical(invalid),
                resolved=True,
            )


def _multi_result(*, passed: tuple[str, ...] = (), failed: tuple[str, ...] = ()) -> dict:
    return {
        "passed_count": len(passed),
        "failed_count": len(failed),
        "skipped_count": 0,
        "passed_tests": list(passed),
        "failed_tests": list(failed),
        "skipped_tests": [],
    }


def test_multi_actual_test_evidence_requires_nonempty_official_classification() -> None:
    target = _frozen_official_target("multi_swe_bench_mini")
    status = {
        "org": "vuejs", "repo": "core", "number": 8911, "valid": False,
        "run_result": _multi_result(passed=("run",)),
        "test_patch_result": _multi_result(passed=("test",)),
        "fix_patch_result": _multi_result(failed=("fix",)),
        "fixed_tests": {}, "p2p_tests": {}, "f2p_tests": {}, "s2p_tests": {}, "n2p_tests": {},
    }
    summary = official_grader.validate_official_test_evidence(
        target,
        source_row={},
        test_output_raw=b"actual multi test output\n",
        test_status_raw=_canonical(status),
        resolved=False,
    )
    assert summary["fix_tests_classified"] == 1
    empty = deepcopy(status)
    empty["fix_patch_result"] = _multi_result()
    with pytest.raises(official_grader.OfficialGraderError, match="no classified tests"):
        official_grader.validate_official_test_evidence(
            target,
            source_row={},
            test_output_raw=b"actual multi test output\n",
            test_status_raw=_canonical(empty),
            resolved=False,
        )


def test_official_harness_invocations_bind_actual_test_evidence_paths(tmp_path: Path) -> None:
    harness = tmp_path / "harness"
    model = "trimem/smoke"
    swe_row = {
        "instance_id": "astropy__astropy-13579",
        "repo": "astropy/astropy",
        "base_commit": "a" * 40,
    }
    swe_target = replace(
        _frozen_official_target("swebench_verified"),
        source_row_sha256=official_grader.canonical_row_hash(swe_row),
    )
    swe = official_grader.build_harness_invocation(
        swe_target, row=swe_row, patch="patch", harness_root=harness,
        run_root=tmp_path / "swe-run", model_name=model,
    )
    run_id = hashlib.sha256(f"{swe_target.target_id}:{model}".encode()).hexdigest()[:20]
    expected_swe = (
        harness / "logs/run_evaluation" / run_id / "trimem__smoke" / swe_target.instance_id
    )
    assert swe.test_output_path == expected_swe / "test_output.txt"
    assert swe.test_status_path == expected_swe / "report.json"

    multi_row = {
        "org": "vuejs", "repo": "core", "number": 8911,
        "base": {"sha": "a" * 40},
    }
    multi_target = replace(
        _frozen_official_target("multi_swe_bench_mini"),
        source_row_sha256=official_grader.canonical_row_hash(multi_row),
    )
    multi_root = tmp_path / "multi-run"
    multi = official_grader.build_harness_invocation(
        multi_target, row=multi_row, patch="patch", harness_root=harness,
        run_root=multi_root, model_name=model,
    )
    expected_multi = multi_root / "work/vuejs/core/evals/pr-8911"
    assert multi.test_output_path == expected_multi / "fix-patch-run.log"
    assert multi.test_status_path == expected_multi / "report.json"


def test_official_final_reports_reject_bool_counters_and_duplicate_ids() -> None:
    swe = _frozen_official_target("swebench_verified")
    swe_report = {
        "schema_version": 2, "total_instances": 1, "submitted_instances": 1,
        "completed_instances": 1, "resolved_instances": 0, "unresolved_instances": 1,
        "infra_failure_instances": 0, "ambiguous_failure_instances": 0,
        "empty_patch_instances": 0, "error_instances": 0,
        "submitted_ids": [swe.instance_id], "completed_ids": [swe.instance_id],
        "incomplete_ids": [], "resolved_ids": [], "unresolved_ids": [swe.instance_id],
        "empty_patch_ids": [], "error_ids": [], "infra_failure_ids": [],
        "ambiguous_failure_ids": [],
    }
    assert official_grader.parse_official_report(swe, swe_report) is False
    swe_report["empty_patch_instances"] = False
    with pytest.raises(official_grader.OfficialGraderError, match="non-empty-patch"):
        official_grader.parse_official_report(swe, swe_report)

    multi = _frozen_official_target("multi_swe_bench_mini")
    canonical_id = "vuejs/core:pr-8911"
    multi_report = {
        "total_instances": 1, "submitted_instances": 1, "completed_instances": 1,
        "incomplete_instances": 0, "resolved_instances": 0, "unresolved_instances": 1,
        "empty_patch_instances": 0, "error_instances": 0,
        "submitted_ids": [canonical_id], "completed_ids": [canonical_id],
        "incomplete_ids": [], "resolved_ids": [], "unresolved_ids": [canonical_id],
        "empty_patch_ids": [], "error_ids": [],
    }
    assert official_grader.parse_official_report(multi, multi_report) is False
    multi_report["unresolved_ids"] = [canonical_id, canonical_id]
    multi_report["unresolved_instances"] = 2
    with pytest.raises(official_grader.OfficialGraderError, match="duplicated"):
        official_grader.parse_official_report(multi, multi_report)


def _smoke_blob(task: Path, name: str, raw: bytes) -> dict:
    path = task / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {
        "path": path.relative_to(task).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _smoke_json_blob(task: Path, name: str, value: dict) -> dict:
    return _smoke_blob(task, name, _canonical(value))


def _baseline_smoke_evidence_fixture(tmp_path: Path) -> tuple[Path, dict, dict, dict]:
    task = tmp_path / "baseline-task"
    task.mkdir()
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    target = {
        **manifest["targets"][1],
        "image": "example.invalid/grader@sha256:" + "d" * 64,
    }
    source_row = {"FAIL_TO_PASS": ["f2p"], "PASS_TO_PASS": ["p2p"]}
    applied = _smoke_blob(
        task, "restricted-input/applied.patch", smoke_protocol.NOOP_BASELINE_PATCH
    )
    test_output_raw = b"actual official pytest output\n"
    test_output = _smoke_blob(task, "official-grader/restricted-evidence/test.bin", test_output_raw)
    status_value = {
        target["instance_id"]: {
            "patch_exists": True,
            "patch_is_None": False,
            "patch_successfully_applied": True,
            "infra_failure": False,
            "resolved": False,
            "tests_status": {
                "FAIL_TO_PASS": {"success": [], "failure": ["f2p"]},
                "PASS_TO_PASS": {"success": ["p2p"], "failure": []},
            },
        }
    }
    status_raw = _canonical(status_value)
    status = _smoke_blob(
        task, "official-grader/restricted-evidence/status.bin", status_raw
    )
    inspect_stdout = _smoke_blob(
        task, "official-grader/restricted-evidence/inspect-stdout.bin", b"inspect\n"
    )
    inspect_stderr = _smoke_blob(
        task, "official-grader/restricted-evidence/inspect-stderr.bin", b""
    )
    tag_stdout = _smoke_blob(
        task, "official-grader/restricted-evidence/tag-stdout.bin", b""
    )
    tag_stderr = _smoke_blob(
        task, "official-grader/restricted-evidence/tag-stderr.bin", b""
    )
    harness_stdout = _smoke_blob(
        task, "official-grader/restricted-evidence/harness-stdout.bin", b"harness\n"
    )
    harness_stderr = _smoke_blob(
        task, "official-grader/restricted-evidence/harness-stderr.bin", b""
    )
    summary = {
        "schema": "trimem/official-test-status-summary/1.0",
        "benchmark_id": target["benchmark_id"],
        "source": "SWE_PER_INSTANCE_REPORT",
        "fail_to_pass_expected": 1,
        "fail_to_pass_classified": 1,
        "fail_to_pass_failures": 1,
        "pass_to_pass_expected": 1,
        "pass_to_pass_classified": 1,
        "pass_to_pass_regressions": 0,
        "expected_test_spec_sha256": hashlib.sha256(_canonical({
            "FAIL_TO_PASS": ["f2p"], "PASS_TO_PASS": ["p2p"],
        })).hexdigest(),
        "resolved": False,
    }
    patch_doc = {
        "schema": "trimem/grader-smoke-patch-evidence/1.0",
        "mode": "OFFICIAL_GRADER_SMOKE_PRIVATE_PATCH",
        "probe": "NOOP_BASELINE",
        "patch_bytes": len(smoke_protocol.NOOP_BASELINE_PATCH),
        "patch_nonempty": True,
        "patch_sha256": smoke_protocol.NOOP_BASELINE_PATCH_SHA256,
        "restricted_applied_patch": applied,
        "noop_baseline_changed_paths": [smoke_protocol.NOOP_BASELINE_PATH],
        "source_row_sha256": target["source_row_sha256"],
        "applied_patch_bytes_retained": "RESTRICTED_EVIDENCE_ONLY",
        "gold_or_test_bytes_public": False,
    }
    tests_doc = {
        "schema": "trimem/grader-smoke-tests-evidence/1.0",
        "official_test_status": {"bytes": len(status_raw), "sha256": status["sha256"]},
        "probe": "NOOP_BASELINE",
        "summary": summary,
        "target_id": target["target_id"],
        "test_output": {"bytes": len(test_output_raw), "sha256": test_output["sha256"]},
    }
    harness_revision = official_grader.SWE_HARNESS_REVISION
    grader_id = f"official-{target['benchmark_id']}@{harness_revision}"
    image_digest = target["image"].rsplit("@", 1)[1]
    container_doc = {
        "schema": "trimem/grader-smoke-container-evidence/1.0",
        "container_digest": target["image"], "container_started": True,
        "exit_code": 0, "official": True, "status": "success",
        "target_id": target["target_id"],
    }
    evaluator_doc = {
        "schema": "trimem/grader-smoke-evaluator-evidence/1.0",
        "benchmark_id": target["benchmark_id"],
        "dataset_revision": target["dataset_revision"],
        "grader_id": grader_id,
        "harness_revision": harness_revision,
        "source_row_sha256": target["source_row_sha256"],
        "target_id": target["target_id"],
    }
    digest_doc = {
        "schema": "trimem/grader-smoke-digest-evidence/1.0",
        "container_digest": target["image"],
        "expected_image_digest": image_digest,
        "observed_image_digest": image_digest,
        "target_id": target["target_id"],
    }
    report_doc = {
        "schema_version": 2,
        "total_instances": 1, "submitted_instances": 1, "completed_instances": 1,
        "resolved_instances": 0, "unresolved_instances": 1,
        "infra_failure_instances": 0, "ambiguous_failure_instances": 0,
        "empty_patch_instances": 0, "error_instances": 0,
        "submitted_ids": [target["instance_id"]], "completed_ids": [target["instance_id"]],
        "incomplete_ids": [], "resolved_ids": [], "unresolved_ids": [target["instance_id"]],
        "empty_patch_ids": [], "error_ids": [], "infra_failure_ids": [],
        "ambiguous_failure_ids": [],
        "_trimem": {
            "benchmark_id": target["benchmark_id"],
            "dataset_revision": target["dataset_revision"],
            "harness_revision": harness_revision,
            "source_row_sha256": target["source_row_sha256"],
            "image_evidence": [{
                "image": target["image"], "expected": image_digest,
                "observed": [image_digest],
                "inspect_restricted_raw_streams": {
                    "stdout": {**inspect_stdout, "path": "restricted-evidence/inspect-stdout.bin"},
                    "stderr": {**inspect_stderr, "path": "restricted-evidence/inspect-stderr.bin"},
                },
                "tag_restricted_raw_streams": {
                    "stdout": {**tag_stdout, "path": "restricted-evidence/tag-stdout.bin"},
                    "stderr": {**tag_stderr, "path": "restricted-evidence/tag-stderr.bin"},
                },
            }],
            "harness_restricted_raw_streams": {
                "stdout": {**harness_stdout, "path": "restricted-evidence/harness-stdout.bin"},
                "stderr": {**harness_stderr, "path": "restricted-evidence/harness-stderr.bin"},
            },
            "test_evidence": {
                "test_output": {**test_output, "path": "restricted-evidence/test.bin"},
                "official_test_status": {**status, "path": "restricted-evidence/status.bin"},
                "summary": summary,
            },
        },
    }
    evidence = {
        "patch": _smoke_json_blob(task, "patch-evidence.json", patch_doc),
        "tests": _smoke_json_blob(task, "tests-evidence.json", tests_doc),
        "container": _smoke_json_blob(task, "container-evidence.json", container_doc),
        "evaluator": _smoke_json_blob(task, "evaluator-evidence.json", evaluator_doc),
        "report": _smoke_json_blob(task, "report.json", report_doc),
        "digest": _smoke_json_blob(task, "digest-evidence.json", digest_doc),
        "stdout": _smoke_blob(task, "stdout.txt", b""),
        "stderr": _smoke_blob(task, "stderr.txt", b""),
        "applied_patch": applied,
        "test_output": test_output,
        "official_test_status": status,
        "restricted_grader_raw": [
            harness_stderr, harness_stdout, inspect_stderr, inspect_stdout,
            status, tag_stderr, tag_stdout, test_output,
        ],
    }
    record = {
        "target_id": target["target_id"], "benchmark_id": target["benchmark_id"],
        "order_index": target["order_index"], "arm": "NOOP_BASELINE",
        "probe": "NOOP_BASELINE", "execution_status": "SUCCESS", "grader_exit_code": 0,
        "grader_id": grader_id, "grader_status": "success",
        "grader_container_digest": target["image"], "container_started": True,
        "official_grader": True, "resolved": False,
        "patch_bytes": len(smoke_protocol.NOOP_BASELINE_PATCH),
        "patch_sha256": smoke_protocol.NOOP_BASELINE_PATCH_SHA256,
        "expected_image_digest": image_digest, "observed_image_digest": image_digest,
        "actual_accounting": {
            "model_gateway_calls": 0, "paid_model_calls": 0, "grader_calls": 1,
            "grader_containers": 1, "official_grader_runs": 1,
        },
        "evidence": evidence,
    }
    result_file = task / f"{target['target_id']}.result.json"
    result_file.write_bytes(_canonical(record))
    return result_file, record, target, source_row


def test_smoke_evidence_validator_binds_all_required_actual_evidence(tmp_path: Path) -> None:
    result_file, record, target, source = _baseline_smoke_evidence_fixture(tmp_path)
    sealed = benchmark_matrix._validate_smoke_evidence(
        result_file, record, target, source, official_grader.SWE_HARNESS_REVISION
    )
    assert sealed["applied_patch_sha256"] == smoke_protocol.NOOP_BASELINE_PATCH_SHA256
    assert benchmark_matrix._report_image_digest(result_file, record, target["image"]) == (
        "sha256:" + "d" * 64
    )
    benchmark_matrix._restricted_evidence(result_file, record)


def test_smoke_restricted_raw_evidence_cannot_remove_report_group_and_files(
    tmp_path: Path,
) -> None:
    result_file, record, _target, _source = _baseline_smoke_evidence_fixture(tmp_path)
    report_ref = record["evidence"]["report"]
    report_path = result_file.parent / report_ref["path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    del report["_trimem"]["harness_restricted_raw_streams"]
    record["evidence"]["report"] = _smoke_json_blob(
        result_file.parent, report_ref["path"], report
    )
    record["evidence"]["restricted_grader_raw"] = [
        reference
        for reference in record["evidence"]["restricted_grader_raw"]
        if "harness-" not in reference["path"]
    ]
    with pytest.raises(benchmark_matrix.MatrixError, match="official harness raw stream"):
        benchmark_matrix._restricted_evidence(result_file, record)


@pytest.mark.parametrize(
    ("evidence_name", "field", "value", "message"),
    [
        ("patch", "patch_nonempty", False, "applied-patch"),
        ("tests", "probe", "GOLD", "tests evidence"),
        ("container", "status", "failure", "container evidence"),
        ("container", "exit_code", False, "container evidence"),
        ("evaluator", "source_row_sha256", "f" * 64, "evaluator"),
        ("report", "empty_patch_ids", ["astropy__astropy-13579"], "final official report"),
        ("digest", "observed_image_digest", "f" * 64, "digest evidence"),
    ],
)
def test_smoke_evidence_validator_rejects_semantic_tampering(
    tmp_path: Path, evidence_name: str, field: str, value: object, message: str
) -> None:
    result_file, record, target, source = _baseline_smoke_evidence_fixture(tmp_path)
    reference = record["evidence"][evidence_name]
    evidence_path = result_file.parent / reference["path"]
    document = json.loads(evidence_path.read_text(encoding="utf-8"))
    document[field] = value
    record["evidence"][evidence_name] = _smoke_json_blob(
        result_file.parent, reference["path"], document
    )
    with pytest.raises(benchmark_matrix.MatrixError, match=message):
        benchmark_matrix._validate_smoke_evidence(
            result_file, record, target, source, official_grader.SWE_HARNESS_REVISION
        )


def test_smoke_evidence_validator_rejects_hash_consistent_baseline_patch_substitution(
    tmp_path: Path,
) -> None:
    result_file, record, target, source = _baseline_smoke_evidence_fixture(tmp_path)
    substituted = smoke_protocol.NOOP_BASELINE_PATCH + b"# extra\n"
    applied = _smoke_blob(result_file.parent, "restricted-input/applied.patch", substituted)
    record["evidence"]["applied_patch"] = applied
    record["patch_bytes"] = len(substituted)
    record["patch_sha256"] = applied["sha256"]
    patch_path = result_file.parent / record["evidence"]["patch"]["path"]
    patch_doc = json.loads(patch_path.read_text(encoding="utf-8"))
    patch_doc.update({
        "patch_bytes": len(substituted), "patch_sha256": applied["sha256"],
        "restricted_applied_patch": applied,
    })
    record["evidence"]["patch"] = _smoke_json_blob(
        result_file.parent, record["evidence"]["patch"]["path"], patch_doc
    )
    with pytest.raises(benchmark_matrix.MatrixError, match="frozen bytes"):
        benchmark_matrix._validate_smoke_evidence(
            result_file, record, target, source, official_grader.SWE_HARNESS_REVISION
        )


def test_smoke_evidence_validator_rejects_empty_actual_test_output(tmp_path: Path) -> None:
    result_file, record, target, source = _baseline_smoke_evidence_fixture(tmp_path)
    record["evidence"]["test_output"] = _smoke_blob(
        result_file.parent, "official-grader/restricted-evidence/test.bin", b"\n"
    )
    with pytest.raises(benchmark_matrix.MatrixError, match="actual official test evidence is empty"):
        benchmark_matrix._validate_smoke_evidence(
            result_file, record, target, source, official_grader.SWE_HARNESS_REVISION
        )


def test_smoke_evidence_validator_rejects_empty_official_test_status(
    tmp_path: Path,
) -> None:
    result_file, record, target, source = _baseline_smoke_evidence_fixture(tmp_path)
    record["evidence"]["official_test_status"] = _smoke_blob(
        result_file.parent, "official-grader/restricted-evidence/status.bin", b"\n"
    )
    with pytest.raises(benchmark_matrix.MatrixError, match="actual official test evidence is empty"):
        benchmark_matrix._validate_smoke_evidence(
            result_file, record, target, source, official_grader.SWE_HARNESS_REVISION
        )


def test_smoke_evidence_validator_rejects_missing_mandatory_reference(
    tmp_path: Path,
) -> None:
    result_file, record, target, source = _baseline_smoke_evidence_fixture(tmp_path)
    del record["evidence"]["evaluator"]
    with pytest.raises(benchmark_matrix.MatrixError, match="missing evaluator evidence"):
        benchmark_matrix._validate_smoke_evidence(
            result_file, record, target, source, official_grader.SWE_HARNESS_REVISION
        )


def _aggregate_count_fixture() -> tuple[list[dict], list[tuple[Path, dict]]]:
    targets: list[dict] = []
    records: list[tuple[Path, dict]] = []
    image = "example.invalid/grader@sha256:" + "d" * 64
    for identity in range(6):
        for probe, resolved in (("GOLD", True), ("NOOP_BASELINE", False)):
            order = len(targets)
            target_id = f"benchmark--instance-{identity}--{probe.lower().replace('_', '-')}"
            target = {
                "target_id": target_id,
                "benchmark_id": "swebench_verified",
                "instance_id": f"org__repo-{identity}",
                "probe": probe,
                "expected_resolved": resolved,
                "order_index": order,
                "image": image,
            }
            targets.append(target)
            records.append((Path(f"{order:02d}.result.json"), {
                "target_id": target_id,
                "execution_status": "SUCCESS",
                "grader_exit_code": 0,
                "grader_status": "success",
                "container_started": True,
                "official_grader": True,
                "expected_image_digest": "sha256:" + "d" * 64,
                "observed_image_digest": "sha256:" + "d" * 64,
                "resolved": resolved,
            }))
    return targets, records


def test_smoke_aggregate_requires_exact_six_by_six_and_preserves_manifest_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    targets, records = _aggregate_count_fixture()
    monkeypatch.setattr(benchmark_matrix, "execution_matrix", lambda name: targets)
    monkeypatch.setattr(
        benchmark_matrix, "_smoke_source_rows", lambda rows: {row["target_id"]: {} for row in rows}
    )
    monkeypatch.setattr(
        benchmark_matrix, "_locked_harness_revisions",
        lambda: {"swebench_verified": official_grader.SWE_HARNESS_REVISION},
    )
    monkeypatch.setattr(benchmark_matrix, "_result_records", lambda root: records)
    monkeypatch.setattr(
        benchmark_matrix, "_report_image_digest",
        lambda path, record, image: image.rsplit("@", 1)[1],
    )
    monkeypatch.setattr(benchmark_matrix, "_evidence_file", lambda *args: b"")
    monkeypatch.setattr(benchmark_matrix, "_restricted_evidence", lambda *args: None)
    monkeypatch.setattr(
        benchmark_matrix,
        "_validate_smoke_evidence",
        lambda path, record, target, source, revision: {
            "applied_patch_sha256": "a" * 64,
            "official_test_output_sha256": "b" * 64,
            "official_test_status_sha256": "c" * 64,
        },
    )
    result = benchmark_matrix._aggregate_smoke(tmp_path)
    assert result["probe_counts"] == {"GOLD": 6, "NOOP_BASELINE": 6}
    assert result["resolved_counts"] == {"GOLD": 6, "NOOP_BASELINE": 0}
    assert result["unresolved_counts"] == {"GOLD": 0, "NOOP_BASELINE": 6}
    assert result["empty_patch_ids"] == []
    assert all(count == 12 for count in result["evidence_counts"].values())
    assert [row["target_id"] for row in result["outcomes"]] == [
        row["target_id"] for row in targets
    ]

    targets[-1]["probe"] = "GOLD"
    targets[-1]["expected_resolved"] = True
    records[-1][1]["resolved"] = True
    with pytest.raises(benchmark_matrix.MatrixError, match="exact 6/6"):
        benchmark_matrix._aggregate_smoke(tmp_path)
