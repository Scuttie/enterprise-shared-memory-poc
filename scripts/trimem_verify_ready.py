"""Fail-closed TriMem V1 readiness and external EXEC gate verifier.

``benchmark-approval`` is deliberately pre-EXEC: official smoke, development
selection/checkpoint and approvals remain pending. ``benchmark-exec`` is a
later phase gate and validates a protected approval outside the repository.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime
import hashlib
import inspect
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from enterprise_memory.trimem.agent_runtime import TriMemAgentRuntime  # noqa: E402
from enterprise_memory.trimem.benchmark_seed import seed_benchmark_identities  # noqa: E402
from enterprise_memory.trimem.git_workspace import DockerSandboxCommandRunner, GitCheckoutWorkspaceFactory  # noqa: E402
from enterprise_memory.trimem.arms import CurrentV03MemoryController  # noqa: E402
from enterprise_memory.trimem.postgres_retrieval import production_v03_controller_factory  # noqa: E402
from enterprise_memory.trimem.production_runtime import BenchmarkArmSession, open_benchmark_arm  # noqa: E402
from enterprise_memory.trimem.production_v03_lifecycle import (  # noqa: E402
    LIVE_V03_IMPLEMENTATION_HASH,
    LIVE_V03_IMPLEMENTATION_MANIFEST,
    LiveV03Runtime,
    PostgresV03ExperienceLifecycle,
    production_v03_lifecycle_factory,
)
from enterprise_memory.trimem.runtime_lock import RuntimeLock  # noqa: E402
from trimem_benchmark_run import (  # noqa: E402
    AtomicBudgetLedger, BudgetedModelGateway, JournaledGraderGateway,
    JournaledModelGateway, validate_exec_approval,
)
from trimem_freeze import FROZEN_PATHS, check_freeze  # noqa: E402
from trimem_grader_smoke_protocol import (  # noqa: E402
    NOOP_BASELINE_CONTENT,
    NOOP_BASELINE_LOCK,
    NOOP_BASELINE_PATH,
)
from trimem_m2_candidates import CANDIDATE_IDS, load_bundle, validate_selected_m2  # noqa: E402
from trimem_verify_credential_free import verify_bundle  # noqa: E402


CONFIG = ROOT / "configs/trimem_v1"
ARTIFACT = ROOT / "artifacts/trimem_v1"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DIGEST_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")


class ReadinessError(ValueError):
    pass


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
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"invalid UTF-8 JSON: {path.relative_to(ROOT).as_posix()}") from exc
    if not isinstance(value, dict):
        raise ReadinessError(f"JSON root is not an object: {path.relative_to(ROOT).as_posix()}")
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReadinessError(message)


def exact_hash(value: Any, message: str, length: int = 64) -> str:
    pattern = HEX64 if length == 64 else HEX40
    require(isinstance(value, str) and pattern.fullmatch(value) is not None, message)
    require(len(set(value)) > 2, message + " (placeholder-like)")
    return value


def strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def validate_sources() -> None:
    audit = read_json(ARTIFACT / "upstream_source_audit.json")
    require(audit.get("official_primary_sources_only") is True, "source audit is not official-primary-only")
    expected = {
        "swebench_verified": ("78f471bf655a3137b2e8a75af1501690ec009ec3", "030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25"),
        "multi_swe_bench_mini": ("d0fab3ccc7dff232fcaac234cf8af9a2efeaccf6", "6644b9c9ebaf5e5b37cb9d81c4dce688c101f07436aed9d50fc55c85b164c3b2"),
        "multi_swe_bench_flash": ("b0485dbebaf8a1317ebf140e80e6fc6c02d3502b", "48d6d02cc976a71a06b494cc60581d92e82c06c2793c0d412c52c63e6956bebe"),
    }
    rows = {row.get("benchmark_id"): row for row in audit.get("benchmarks", ()) if isinstance(row, Mapping)}
    require(set(rows) == set(expected), "official benchmark source set mismatch")
    for name, (revision, data_hash) in expected.items():
        dataset, harness = rows[name].get("dataset", {}), rows[name].get("harness", {})
        require(dataset.get("revision") == revision, f"dataset revision drift: {name}")
        require(dataset.get("data_file", {}).get("lfs_oid_sha256") == data_hash, f"dataset file digest drift: {name}")
        exact_hash(harness.get("revision"), f"harness revision is not exact: {name}", 40)
    grader = read_json(CONFIG / "grader_lock.json")
    terms = grader.get("dataset_terms_boundary", {})
    require(terms.get("no_dataset_redistribution") is True, "dataset no-redistribution boundary is missing")
    require("DATASET_LICENSE_NOT_DECLARED" in str(terms.get("swebench_verified")), "SWE license absence is overstated")
    require("not legal clearance" in str(terms.get("execution_approval_requirement")), "legal approval boundary is missing")


def validate_targets() -> dict[str, list[dict[str, Any]]]:
    plan = read_json(CONFIG / "selection_plan.json")
    require(plan.get("schema") == "trimem/selection-plan/3.0", "selector v3 is not frozen")
    require(plan.get("row_score") == "sha256(seed|trimem-selector-v3|split|benchmark_id|instance_id), ascending lowercase bytes", "selector score is not public-identity-only")
    require(plan.get("source_policy", {}).get("per_slot_nonce_or_override_allowed") is False, "selector permits per-slot override")
    forbidden_text = " ".join(strings(plan)).lower()
    require("salt" not in forbidden_text and "nonce" not in forbidden_text.replace("per_slot_nonce_or_override_allowed", ""), "selector contains a salt/nonce escape hatch")
    manifests = {
        name: read_json(CONFIG / f"{name}_manifest.json")
        for name in ("development", "heldout")
    }
    smoke = read_json(CONFIG / "grader_smoke_manifest.json")
    manifests["grader-smoke"] = smoke
    require(
        "pooled resolved_count" in str(
            manifests["development"].get("tuning_selection_objective", "")
        )
        and "not the held-out primary endpoint" in str(
            manifests["development"].get("tuning_selection_objective", "")
        ),
        "development joint-tuning objective is not separated from held-out primary reporting",
    )
    expected_counts = {"development": 12, "heldout": 27, "grader-smoke": 12}
    result: dict[str, list[dict[str, Any]]] = {}
    for name, manifest in manifests.items():
        targets = manifest.get("targets")
        require(isinstance(targets, list) and len(targets) == expected_counts[name], f"{name} target count mismatch")
        require(manifest.get("status") in {"FROZEN", "FROZEN_TARGET_SET_EXECUTION_PENDING"}, f"{name} target set is not frozen")
        target_ids = [row.get("target_id") for row in targets]
        require(len(set(target_ids)) == len(target_ids), f"{name} target IDs are duplicated")
        require(
            hashlib.sha256(canonical(targets)).hexdigest() == manifest.get("target_set_sha256"),
            f"{name} canonical target-set digest mismatch",
        )
        for index, row in enumerate(targets):
            exact_hash(row.get("dataset_revision"), f"{name} dataset revision missing", 40)
            exact_hash(row.get("source_row_sha256"), f"{name} source row hash missing")
            exact_hash(row.get("base_commit"), f"{name} base commit missing", 40)
            if name != "grader-smoke":
                require(row.get("order_index") == index, f"{name} frozen order mismatch")
        if name != "grader-smoke":
            roles = manifest.get("benchmark_roles")
            require(isinstance(roles, list) and len(roles) == 3, f"{name} benchmark roles are missing")
            role_ids = [row.get("benchmark_id") for row in roles]
            require(len(set(role_ids)) == len(roles), f"{name} benchmark roles are duplicated")
            counts = Counter(row.get("benchmark_id") for row in targets)
            revisions = {
                benchmark_id: {row.get("dataset_revision") for row in targets if row.get("benchmark_id") == benchmark_id}
                for benchmark_id in counts
            }
            for role in roles:
                benchmark_id = role.get("benchmark_id")
                require(
                    set(role) == {"benchmark_id", "dataset_id", "dataset_revision", "role", "target_count"}
                    and counts.get(benchmark_id) == role.get("target_count")
                    and revisions.get(benchmark_id) == {role.get("dataset_revision")}
                    and role.get("role") in {"PRIMARY", "SECONDARY"},
                    f"{name} benchmark role/count/revision drift",
                )
            require(
                [row.get("benchmark_id") for row in roles if row.get("role") == "PRIMARY"]
                == ["swebench_verified"]
                and all(
                    row.get("role") == "SECONDARY"
                    for row in roles
                    if str(row.get("benchmark_id", "")).startswith("multi_swe_bench_")
                ),
                f"{name} primary/secondary endpoint roles drift",
            )
        result[name] = targets
    smoke_manifest = manifests["grader-smoke"]
    require(
        smoke_manifest.get("matrix_kind")
        == "single_serial_six_instance_gold_noop_campaign",
        "smoke manifest does not describe the single serial campaign",
    )
    pairs = Counter(
        (row["benchmark_id"], row["instance_id"])
        for row in result["grader-smoke"]
    )
    require(
        len(pairs) == 6 and set(pairs.values()) == {2},
        "smoke is not six GOLD/NOOP_BASELINE pairs",
    )
    for offset in range(0, len(result["grader-smoke"]), 2):
        gold, noop = result["grader-smoke"][offset : offset + 2]
        require(
            (gold.get("benchmark_id"), gold.get("instance_id"))
            == (noop.get("benchmark_id"), noop.get("instance_id"))
            and [gold.get("probe"), noop.get("probe")]
            == ["GOLD", "NOOP_BASELINE"],
            "smoke execution order is not deterministic GOLD then NOOP_BASELINE",
        )
    smoke_ids = {instance for _, instance in pairs}
    development_ids = {row["instance_id"] for row in result["development"]}
    heldout_ids = {row["instance_id"] for row in result["heldout"]}
    require(not (smoke_ids & development_ids or smoke_ids & heldout_ids or development_ids & heldout_ids), "target set instance overlap is nonzero")
    return result


def validate_images(targets: Mapping[str, list[dict[str, Any]]]) -> None:
    lock = read_json(ARTIFACT / "grader_image_lock.json")
    require(lock.get("status") == lock.get("smoke_status") == "FROZEN", "smoke image digests are not frozen")
    benchmark = lock.get("benchmark_target_images", {})
    require(benchmark.get("status") == "FROZEN" and benchmark.get("target_count") == 39, "all 39 benchmark images are not frozen")
    smoke_rows, benchmark_rows = lock.get("targets"), benchmark.get("targets")
    support_rows = lock.get("support_images")
    require(isinstance(smoke_rows, list) and len(smoke_rows) == 6, "smoke image lock count mismatch")
    require(isinstance(benchmark_rows, list) and len(benchmark_rows) == 39, "benchmark image lock count mismatch")
    require(isinstance(support_rows, list) and len(support_rows) == 1, "support image lock mismatch")
    expected_smoke = {row["instance_id"] for row in targets["grader-smoke"]}
    expected_benchmark = {row["instance_id"] for name in ("development", "heldout") for row in targets[name]}
    require({row.get("instance_id") for row in smoke_rows} == expected_smoke, "smoke image set drift")
    require({row.get("instance_id") for row in benchmark_rows} == expected_benchmark, "benchmark image set drift")
    for row in [*smoke_rows, *benchmark_rows, *support_rows]:
        image = row.get("image")
        require(isinstance(image, str) and DIGEST_IMAGE.fullmatch(image) is not None, "grader image is not digest-pinned")
        require(row.get("expected_digest") == image.rsplit("@", 1)[1], "image expected digest mismatch")
        exact_hash(row.get("registry_response_sha256"), "registry response provenance hash missing")
        require(str(row.get("registry_evidence_url", "")).startswith("https://hub.docker.com/v2/repositories/"), "image provenance is not official registry metadata")
    observation = lock.get("digest_observation", {})
    require(observation.get("docker_pull_or_run_performed") is False, "pre-EXEC image lock claims a Docker pull/run")
    started, completed = observation.get("query_started_at_utc"), observation.get("query_completed_at_utc")
    try:
        started_at = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        completed_at = datetime.fromisoformat(str(completed).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReadinessError("registry query timestamps are not exact") from exc
    require(started_at <= completed_at and "T00:00:00Z" not in str(started), "registry query timestamp is placeholder-like")
    material = "\n".join("|".join(str(row.get(key, "")) for key in (
        "benchmark_id", "instance_id", "registry_evidence_url", "expected_digest",
        "registry_last_updated_utc", "registry_response_sha256",
    )) for row in [*smoke_rows, *benchmark_rows, *support_rows])
    require(hashlib.sha256(material.encode("utf-8")).hexdigest() == observation.get("metadata_snapshot_sha256"), "registry metadata snapshot hash mismatch")


def validate_noop_baseline_audit(
    targets: Mapping[str, list[dict[str, Any]]]
) -> None:
    audit = read_json(ARTIFACT / "noop_baseline_six_commit_audit.json")
    body = {key: value for key, value in audit.items() if key != "audit_sha256"}
    require(
        audit.get("schema") == "trimem/noop-baseline-six-commit-audit/1.0"
        and audit.get("status") == "PASS"
        and audit.get("noop_baseline") == NOOP_BASELINE_LOCK
        and audit.get("manifest_target_set_sha256")
        == hashlib.sha256(canonical(targets["grader-smoke"])).hexdigest()
        and audit.get("audit_sha256")
        == hashlib.sha256(canonical(body)).hexdigest(),
        "NOOP_BASELINE six-base audit seal is invalid",
    )
    expected = {
        (row["repository"], row["instance_id"], row["base_commit"])
        for row in targets["grader-smoke"]
        if row.get("probe") == "GOLD"
    }
    rows = audit.get("rows")
    require(
        isinstance(rows, list) and len(rows) == 6,
        "NOOP_BASELINE audit row count is not six",
    )
    observed = set()
    for row in rows:
        require(isinstance(row, dict), "NOOP_BASELINE audit row is malformed")
        observed.add(
            (row.get("repository"), row.get("instance_id"), row.get("base_commit"))
        )
        require(
            row.get("root_marker_absent_at_base") is True
            and row.get("patch_applies_cached") is True
            and row.get("isolated_temporary_index") is True
            and row.get("changed_paths") == [NOOP_BASELINE_PATH]
            and row.get("forbidden_source_test_build_or_package_paths_touched") == []
            and row.get("staged_marker_sha256")
            == hashlib.sha256(NOOP_BASELINE_CONTENT).hexdigest()
            and isinstance(row.get("base_tree"), str)
            and HEX40.fullmatch(row["base_tree"]) is not None,
            "NOOP_BASELINE audit does not prove one safe new-file-only patch",
        )
    require(
        observed == expected,
        "NOOP_BASELINE audit target set differs from the smoke manifest",
    )


def validate_model_cost_environment() -> None:
    model = read_json(CONFIG / "model_lock.json")
    primary = model.get("primary_model", {})
    require(model.get("status") == "FROZEN_PRE_EXEC_EXECUTION_PENDING_APPROVAL", "model lock status is overstated")
    require(primary.get("model_id") == "gpt-5.4-2026-03-05" and primary.get("status") == "FROZEN", "dated model snapshot is not frozen")
    require((primary.get("input_price_per_million_tokens_usd"), primary.get("cached_input_price_per_million_tokens_usd"), primary.get("output_price_per_million_tokens_usd")) == (2.5, 0.25, 15.0), "official model pricing drift")
    require("gpt-5.6" not in " ".join(strings(model)), "unselected floating performance alternative remains")
    schema = model.get("request_schema")
    require(hashlib.sha256(canonical(schema)).hexdigest() == model.get("request_schema_sha256"), "request schema hash mismatch")
    guard = model.get("long_context_surcharge_guard", {})
    require(guard.get("maximum_reserved_input_tokens_per_call") == 262000 and guard.get("contract") == "NO_LONG_CONTEXT_SURCHARGE", "long-context surcharge guard drift")
    embedder = model.get("retrieval_embedding", {}).get("production", {})
    require((embedder.get("model_id"), embedder.get("revision"), embedder.get("dimension"), embedder.get("license")) == (
        "sentence-transformers/all-MiniLM-L6-v2", "1110a243fdf4706b3f48f1d95db1a4f5529b4d41", 384, "Apache-2.0"
    ), "production embedder lock drift")
    require(model.get("retrieval_embedding", {}).get("credential_free_fixture", {}).get("benchmark_execution_allowed") is False, "hash embedder is allowed in benchmark")
    require(model.get("actual_execution") == {"model_gateway_calls": 0, "paid_model_calls": 0}, "pre-EXEC model counters are nonzero")

    cost = read_json(CONFIG / "cost_plan.json")
    require(cost.get("schema") == "trimem/cost-plan/1.1", "cost plan schema is stale")
    counts = cost.get("run_counts", {})
    require((counts.get("development_physical_task_arm_runs"), counts.get("heldout_physical_task_arm_runs"), counts.get("total_physical_task_arm_runs")) == (72, 81, 153), "physical run counts do not include four-candidate tuning")
    expected, hard = cost.get("expected_cost", {}), cost.get("proposed_hard_cap", {})
    require((expected.get("model_calls"), expected.get("input_tokens"), expected.get("output_tokens"), expected.get("total_usd")) == (2142, 25092000, 918000, 76.5), "expected cost arithmetic drift")
    require((hard.get("model_calls"), hard.get("input_tokens"), hard.get("output_tokens"), hard.get("total_usd")) == (3978, 76500000, 8068608, 320.0), "proposed hard-cap arithmetic drift")
    phases = cost.get("phase_hard_caps", {})
    require(phases.get("DEVELOPMENT_TUNING", {}).get("task_arm_runs") == 72 and phases.get("HELDOUT_BENCHMARK", {}).get("task_arm_runs") == 81 and phases.get("GRADER_SMOKE", {}).get("benchmark_grader_containers") == 12, "phase hard caps are incomplete")
    require(all(value == 0 for value in cost.get("actual_to_date", {}).values()), "pre-EXEC cost counters are nonzero")

    environment = read_json(CONFIG / "benchmark_environment_lock.json")
    dependency = environment.get("dependency_lock", {})
    for field, path in (("input_sha256", CONFIG / "benchmark_environment.in"), ("lock_sha256", CONFIG / "benchmark_environment.lock")):
        require(hashlib.sha256(path.read_bytes()).hexdigest() == dependency.get(field), f"benchmark environment {field} mismatch")
    runner = environment.get("runner", {})
    require(runner.get("benchmark_exec_runner_labels") == ["self-hosted", "linux", "x64", "ubuntu-24.04", "trimem-benchmark"] and runner.get("benchmark_exec_max_job_minutes") == 7200, "long-running protected benchmark runner is not frozen")
    require(environment.get("embedding_execution", {}).get("benchmark_hash_embedder_allowed") is False, "benchmark environment allows the fixture embedder")


def validate_readiness_plan(targets: Mapping[str, list[dict[str, Any]]]) -> None:
    plan = read_json(ARTIFACT / "readiness_requirements.json")
    require(plan.get("schema") == "trimem/readiness-requirements/1.1", "readiness requirements are stale")
    service_boundary = str(plan.get("credential_free_service_ci_boundary", ""))
    require(
        "ALLOWED_PRE_EXEC" in service_boundary
        and "digest-pinned PostgreSQL and Qdrant support services" in service_boundary
        and "official grader/benchmark target images" in service_boundary,
        "credential-free support-service/official-target execution boundary is absent",
    )
    m1_boundary = str(plan.get("m1_current_v03_boundary", ""))
    require(
        "CONTRACT_CANDIDATE" in m1_boundary
        and "no direct Qdrant write" in m1_boundary
        and "no immediate fresh-solve carryover" in m1_boundary,
        "M1 current-v0.3 atomic-outbox/no-immediate-carryover boundary is absent",
    )
    require(
        any(
            "per-arm/per-benchmark" in str(item)
            and "pooled totals descriptive only" in str(item)
            for item in plan.get("benchmark_approval_requires", ())
        ),
        "primary/secondary per-benchmark aggregation readiness requirement is absent",
    )
    pending = plan.get("explicitly_allowed_pending_at_pre_exec_ready", {})
    require("PENDING_EXEC_APPROVAL" in str(pending.get("official_grader_smoke")), "pre-EXEC smoke pending state is absent")
    require("PRE_DEVELOPMENT" in str(pending.get("selected_m2_checkpoint")), "pre-EXEC checkpoint state is circular")
    counts = plan.get("frozen_counts", {})
    require((counts.get("development_physical_task_arm_runs"), counts.get("heldout_physical_task_arm_runs"), counts.get("total_benchmark_physical_task_arm_runs")) == (72, 81, 153), "readiness physical-run counts drift")
    digests = plan.get("target_set_sha256", {})
    for name, key in (("development", "development"), ("heldout", "heldout"), ("grader-smoke", "grader_smoke")):
        expected = hashlib.sha256(canonical(targets[name])).hexdigest()
        require(digests.get(key) == expected, f"readiness target-set binding drift: {name}")
    require(all(value == 0 for value in plan.get("execution_counters", {}).values()), "readiness execution counters are nonzero")


def validate_runtime_and_candidates() -> None:
    bundle = load_bundle()
    require(bundle.get("candidate_order") == list(CANDIDATE_IDS), "M2 candidate order drift")
    require(bundle.get("development_contract", {}).get("candidate_task_arm_runs") == 48, "M2 candidate run count drift")
    require(bundle.get("development_contract", {}).get("component_ablation_claim") == "PROHIBITED", "candidate runs may be mislabeled ablations")
    selected = validate_selected_m2(require_frozen=False)
    require(selected.get("status") in {"PRE_DEVELOPMENT", "FROZEN_AFTER_DEVELOPMENT"}, "selected M2 state is invalid")
    arms = read_json(CONFIG / "arms.json")
    require(arms.get("development_streams") == ["M2-baseline", "M2-precision", "M2-recall", "M2-balanced", "M0", "M1"], "development stream contract drift")
    require(arms.get("runtime_ceiling") == RuntimeLock().to_manifest()["limits"], "runtime ceiling differs from source")
    m1_rows = [row for row in arms.get("arms", []) if row.get("arm_id") == "M1"]
    require(len(m1_rows) == 1, "M1 arm contract is missing or duplicated")
    m1 = m1_rows[0]
    baseline_commit = LIVE_V03_IMPLEMENTATION_MANIFEST["source_commit"]
    baseline_path = "src/enterprise_memory/service/durable.py"
    baseline_spec = f"{baseline_commit}:{baseline_path}"
    blob_id = subprocess.run(
        ["git", "rev-parse", baseline_spec],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    blob = subprocess.run(
        ["git", "show", baseline_spec],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    require(blob_id.returncode == 0 and blob.returncode == 0, "M1 baseline durable git object is unavailable")
    try:
        baseline_source = blob.stdout.decode("utf-8")
        module = ast.parse(baseline_source)
        finalizer_node = next(
            node for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "finalize_success_atomic"
        )
    except (UnicodeDecodeError, SyntaxError, StopIteration) as exc:
        raise ReadinessError("M1 baseline finalizer source cannot be verified") from exc
    finalizer_source = "".join(
        baseline_source.splitlines(keepends=True)[
            finalizer_node.lineno - 1: finalizer_node.end_lineno
        ]
    ).encode("utf-8")
    require(
        LIVE_V03_IMPLEMENTATION_MANIFEST.get("baseline_durable_git_blob_sha1")
        == blob_id.stdout.strip()
        and LIVE_V03_IMPLEMENTATION_MANIFEST.get("baseline_durable_blob_sha256")
        == hashlib.sha256(blob.stdout).hexdigest()
        and LIVE_V03_IMPLEMENTATION_MANIFEST.get(
            "baseline_finalize_success_atomic_ast_sha256"
        ) == hashlib.sha256(finalizer_source).hexdigest(),
        "M1 baseline durable/finalizer git provenance drift",
    )
    current_finalizer_source = inspect.getsource(
        __import__(
            "enterprise_memory.service.durable", fromlist=["finalize_success_atomic"]
        ).finalize_success_atomic
    )
    require(
        current_finalizer_source.count("persist_private_episode_candidate(") == 1
        and LIVE_V03_IMPLEMENTATION_MANIFEST.get("retention_path")
        == "service.durable.persist_private_episode_candidate(connection)"
        and LIVE_V03_IMPLEMENTATION_MANIFEST.get("fresh_solve_immediate_carryover") is False,
        "M1 behavior-preserving shared-helper/no-immediate-carryover lock drift",
    )
    require(
        m1.get("description") == "CURRENT_V03_MEMORY"
        and m1.get("baseline_git_commit") == LIVE_V03_IMPLEMENTATION_MANIFEST["source_commit"]
        and m1.get("live_implementation_hash") == LIVE_V03_IMPLEMENTATION_HASH
        and m1.get("production_lifecycle_configuration_hash")
        == PostgresV03ExperienceLifecycle.configuration_hash,
        "M1 live-v0.3 implementation/configuration lock drift",
    )
    require(
        m1.get("retained_episode_shape")
        == ["task_id", "repo_id", "commit", "outcome", "injected_memory_ids"]
        and m1.get("fresh_solve_episode_private_view")
        == "NOT_INDEXED_BY_CURRENT_SOLVE_PATH"
        and m1.get("fresh_solve_immediate_carryover") is False
        and m1.get("candidate_outbox_event_type") == "CONTRACT_CANDIDATE"
        and "no direct Qdrant indexing" in str(m1.get("retention_path"))
        and m1.get("extractor_output_changes_retention") is False
        and m1.get("benchmark_grade_changes_retention") is False
        and m1.get("shared_publication") is False,
        "M1 solve-worker retention/private-view fidelity contract drift",
    )
    m1_lifecycle_source = inspect.getsource(production_v03_lifecycle_factory)
    m1_controller_source = inspect.getsource(production_v03_controller_factory)
    require(
        "LiveV03Runtime" in m1_lifecycle_source
        and "CurrentV03MemoryController" in m1_controller_source
        and "runtime.recall_plan" in m1_controller_source
        and all(
            callable(getattr(LiveV03Runtime, name, None))
            for name in (
                "retention_descriptor", "retain_episode", "recall_plan",
                "verify_pending_retention",
            )
        )
        and callable(
            getattr(PostgresV03ExperienceLifecycle, "verify_inflight_external_state", None)
        )
        and CurrentV03MemoryController.__name__ == "CurrentV03MemoryController",
        "M1 live validated-search/injection/recovery route is incomplete",
    )

    tool = read_json(CONFIG / "tool_environment_lock.json")
    require(tool.get("status") == "FROZEN", "tool environment lock is not frozen")
    require(tool.get("runtime_lock_manifest") == RuntimeLock().to_manifest() and tool.get("runtime_lock_content_hash") == RuntimeLock().content_hash, "tool/runtime lock drift")
    for relative, expected in tool.get("source_files", {}).items():
        path = ROOT / relative
        require(path.is_file() and len(path.read_bytes()) == expected.get("bytes") and hashlib.sha256(path.read_bytes()).hexdigest() == expected.get("sha256"), f"tool source lock drift: {relative}")
    docker = tool.get("docker_command_runner", {})
    require((docker.get("container_workspace"), docker.get("pull"), docker.get("network"), docker.get("root_filesystem"), docker.get("host_environment_forwarded_to_container")) == ("/testbed", "never", "none", "read-only", False), "production command sandbox lock drift")
    require(tool.get("benchmark_workspace", {}).get("all_tasks_require_digest_bound_command_runner") is True, "production workspace can omit command runner")

    required_methods = ("after_task_and_checkpoint", "resume_canonical_stream", "finalize_development", "run_coroutine")
    require(all(callable(getattr(BenchmarkArmSession, name, None)) for name in required_methods), "production session lifecycle/resume surface is incomplete")
    require(callable(open_benchmark_arm), "production benchmark factory is missing")
    require(
        DockerSandboxCommandRunner.__name__ == "DockerSandboxCommandRunner"
        and getattr(GitCheckoutWorkspaceFactory, "production_capable", None)
        is not True,
        "workspace factory production capability must be instance-bound to complete runners",
    )
    runtime_source = inspect.getsource(TriMemAgentRuntime.run)
    require(all(state in runtime_source for state in ("PATCH_FINALIZED", "GRADED", "EXTRACTED", "LIFECYCLE_STORED", "LIFECYCLE_CREDITED", "DONE")), "terminal checkpoint phase set is incomplete")
    require(all(item is not None for item in (AtomicBudgetLedger, BudgetedModelGateway, JournaledModelGateway, JournaledGraderGateway)), "budget/journal execution boundary is missing")
    benchmark_source = (ROOT / "scripts/trimem_benchmark_run.py").read_text(encoding="utf-8")
    aggregate_source = (ROOT / "scripts/trimem_benchmark_matrix.py").read_text(encoding="utf-8")
    require(callable(seed_benchmark_identities) and "os.environ.pop(\"TRIMEM_ADMIN_DATABASE_URL\"" in benchmark_source and "identity_seed_evidence=" in benchmark_source, "admin-only deterministic benchmark identity seed boundary is missing")
    require(
        '\"benchmark_id\": target[\"benchmark_id\"]' in benchmark_source
        and "_benchmark_endpoint_totals" in aggregate_source
        and "DESCRIPTIVE_POOLED_ALL_BENCHMARKS" in aggregate_source,
        "per-benchmark primary/secondary endpoint aggregation is not frozen",
    )


def validate_workflows() -> None:
    automatic = [ROOT / ".github/workflows/ci-trimem.yml", ROOT / ".github/workflows/ci-trimem-e2e.yml"]
    smoke_workflow = ROOT / ".github/workflows/trimem-grader-smoke.yml"
    benchmark_workflow = ROOT / ".github/workflows/trimem-benchmark.yml"
    manual = [smoke_workflow, benchmark_workflow]
    for path in [*automatic, *manual]:
        text = path.read_text(encoding="utf-8")
        for forbidden in ("continue-on-error", "|| true", ":latest"):
            require(forbidden not in text, f"forbidden workflow construct {forbidden}: {path.name}")
        require("inputs:" not in text, f"workflow has free-form inputs: {path.name}")
        for match in re.finditer(r"uses:\s*([^\s]+)", text):
            require(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", match.group(1)) is not None, f"workflow action is not commit-pinned: {path.name}")
    for path in automatic:
        text = path.read_text(encoding="utf-8")
        require("pull_request:" in text and "trimem_pytest_no_skip.py" in text, f"automatic no-skip PR CI missing: {path.name}")
    static = automatic[0].read_text(encoding="utf-8")
    require("tests/unit/test_trimem_*.py" in static and "tests/trimem/e2e/test_full_replay.py" in static, "static CI does not discover all TriMem units/full replay")
    service = automatic[1].read_text(encoding="utf-8")
    require("test_real_services_e2e.py" in service and "postgres@sha256:" in service and "qdrant/qdrant@sha256:" in service, "real PostgreSQL/Qdrant CI is absent")
    require("postgres_bootstrap.py" in service and "TRIMEM_TEST_DATABASE_URL: postgresql+asyncpg://api_service:api_pw@" in service and "TRIMEM_TEST_ADMIN_DATABASE_URL: postgresql+asyncpg://postgres:postgres@" in service, "real-service role/RLS boundary is not wired")
    smoke = smoke_workflow.read_text(encoding="utf-8")
    require("workflow_dispatch:" in smoke and "pull_request:" not in smoke and "schedule:" not in smoke, "smoke workflow has an unauthorized trigger")
    require(
        "push:" in smoke
        and "      - codex/trimem-coder-v1" in smoke
        and "      - artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST.json" in smoke,
        "smoke workflow exact branch-local sentinel trigger is absent",
    )
    require(
        "branch-trigger-preflight:" in smoke
        and "needs: branch-trigger-preflight" in smoke
        and "trimem_grader_smoke_trigger_preflight.py" in smoke,
        "smoke branch trigger is not fail-closed before the protected job",
    )
    require(
        "environment: trimem-grader-smoke-exec" in smoke,
        "smoke job is not held by the protected environment",
    )
    smoke_secrets = set(
        re.findall(r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)", smoke)
    )
    require(
        smoke_secrets
        == {"TRIMEM_EXEC_APPROVAL_B64", "TRIMEM_EVIDENCE_PASSPHRASE"},
        "smoke workflow secret surface is not the exact control/evidence pair",
    )
    benchmark_text = benchmark_workflow.read_text(encoding="utf-8")
    require(
        "workflow_dispatch:" in benchmark_text
        and all(
            trigger not in benchmark_text
            for trigger in ("pull_request:", "push:", "schedule:")
        ),
        "benchmark EXEC workflow is not manual-only",
    )
    for path in manual:
        text = path.read_text(encoding="utf-8")
        require("trimem_public_artifact.py" in text and "openssl enc -aes-256-cbc" in text, f"EXEC evidence protection path incomplete: {path.name}")
        require("if: always()" in text and "trimem_cleanup_exec.py" in text, f"EXEC plaintext cleanup path is absent: {path.name}")
    require(
        "bounded-disk exact GOLD and NOOP_BASELINE pairs" in smoke
        and smoke.count(
            "--image-evidence-dir artifacts/trimem_v1/grader_smoke_exec/image-materialization"
        ) == 2
        and "--cleanup-grader-smoke" in smoke
        and "Remove only frozen smoke image references" in smoke,
        "smoke workflow does not use bounded-disk serial image materialization",
    )
    benchmark = manual[1].read_text(encoding="utf-8")
    require("trimem_pull_locked_images.py" in benchmark, "benchmark digest-only image pull is absent")
    require("runs-on: [self-hosted, linux, x64, ubuntu-24.04, trimem-benchmark]" in benchmark and "timeout-minutes: 7200" in benchmark, "long serial benchmark is not on protected 5-day runner")
    require("matrix:" not in benchmark, "online benchmark is incorrectly task/arm sharded")
    require("trimem_run_with_resume.py" in benchmark and "trimem_benchmark_run.py\n" not in benchmark, "same-attempt benchmark recovery wrapper is not the workflow entrypoint")
    require("postgres_bootstrap.py" in benchmark and "TRIMEM_DATABASE_URL: postgresql+asyncpg://api_service:api_pw@" in benchmark and "TRIMEM_ADMIN_DATABASE_URL: postgresql+asyncpg://postgres:postgres@" in benchmark, "benchmark admin/runtime RLS identities are not separated")
    environment = read_json(
        ARTIFACT / "grader_smoke_environment_protection.json"
    )
    require(
        environment.get("status") == "CONFIGURED"
        and environment.get("configured_before_sentinel") is True,
        "grader-smoke protected environment was not documented before sentinel",
    )
    environment_row = environment.get("environment", {})
    reviewer_rule = environment.get("protection_rule", {})
    branch_policy = environment.get("branch_policy", {})
    require(
        environment_row.get("name") == "trimem-grader-smoke-exec"
        and environment_row.get("can_admins_bypass") is False
        and reviewer_rule.get("type") == "required_reviewers"
        and bool(reviewer_rule.get("reviewers"))
        and branch_policy.get("name") == "codex/trimem-coder-v1"
        and branch_policy.get("type") == "branch",
        "grader-smoke protected environment proof is incomplete",
    )
    secret_state = environment.get("secret_state_before_sentinel", {})
    require(
        secret_state.get("installed_secret_names") == []
        and set(secret_state.get("required_later", ()))
        == {"TRIMEM_EXEC_APPROVAL_B64", "TRIMEM_EVIDENCE_PASSPHRASE"},
        "grader-smoke pre-sentinel environment-secret state is not exact",
    )


def validate_eol_policy() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    require("scripts/trimem_*.py text eol=lf" in attributes and "configs/trimem_v1/** text eol=lf" in attributes, "cross-platform LF freeze policy is absent")
    representative = (
        ".gitattributes", "alembic.ini", "DEPENDENCY_PROVENANCE.json", "requirements.lock",
        "pyproject.toml", "configs/trimem_v1/model_lock.json", "scripts/trimem_freeze.py",
        "scripts/check_migration_head.py", "docs/TRIMEM_V1_SYSTEM.md",
        ".github/workflows/ci-trimem.yml", "migrations/env.py",
        "migrations/sql/0001_up.sql", "migrations/versions/0001_initial_production_schema.py",
        "src/enterprise_memory/providers/openai_responses.py",
        "src/enterprise_memory/providers/base.py",
        "src/enterprise_memory/providers/redaction.py",
        "src/enterprise_memory/indexing/embeddings.py",
        "src/enterprise_memory/indexing/validated_search.py",
        "src/enterprise_memory/service/injection.py",
        "src/enterprise_memory/service/app.py", "src/enterprise_memory/trimem/agent_runtime.py",
        "tests/openai/test_openai_provider.py", "tests/unit/test_release_hygiene.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
    )
    completed = subprocess.run(
        ["git", "check-attr", "eol", "--", *representative],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    require(completed.returncode == 0 and completed.stdout.count("eol: lf") == len(representative), "git LF attributes do not cover frozen text")
    blobs = sorted((ARTIFACT / "credential_free_e2e").glob("*/evidence/blobs/*"))
    require(bool(blobs), "credential-free content-addressed evidence blobs are missing")
    blob_relative = blobs[0].relative_to(ROOT).as_posix()
    blob_attr = subprocess.run(
        ["git", "check-attr", "text", "--", blob_relative], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    require(blob_attr.returncode == 0 and "text: unset" in blob_attr.stdout, "content-addressed evidence blobs are not binary-stable")


def validate_static(require_git_tracked: bool) -> dict[str, Any]:
    check_freeze(ROOT, require_git_tracked=require_git_tracked)
    validate_eol_policy()
    validate_sources()
    targets = validate_targets()
    validate_readiness_plan(targets)
    validate_images(targets)
    validate_noop_baseline_audit(targets)
    validate_model_cost_environment()
    validate_runtime_and_candidates()
    validate_workflows()
    credential = verify_bundle(ARTIFACT / "credential_free_e2e")
    request = read_json(CONFIG / "benchmark_exec_request.json")
    require(request.get("approval_state") == "PENDING_EXEC_APPROVAL", "committed request must stay pending")
    request_actual = request.get("actual_execution")
    require(
        isinstance(request_actual, dict)
        and all(type(value) is int for value in request_actual.values())
        and request_actual == {
            "benchmark_target_image_pulls": 0,
            "grader_containers": 0,
            "official_grader_runs": 0,
            "paid_model_calls": 0,
            "task_arm_runs": 0,
        },
        "committed preapproval execution counter schema/value differs",
    )
    prohibited = request.get("prohibited_before_approval", [])
    require(
        "official grader/benchmark target image pull or run" in prohibited
        and "Docker image pull or run" not in prohibited,
        "pre-EXEC prohibition incorrectly blocks credential-free support-service CI",
    )
    required = set(request.get("required_approval_fields", ()))
    require({"approved_workflow_run_id", "approved_workflow_run_attempt"} <= required, "single-dispatch EXEC approval binding is absent")
    smoke = read_json(ARTIFACT / "grader_smoke_result.json")
    require(set(smoke) == {
        "schema", "status", "trimem_system_implementation", "grader_exec_package",
        "official_grader_viability", "performance", "expected_unique_instances",
        "expected_target_count", "expected_condition_rows", "actual_execution",
    }, "grader smoke result field set differs")
    require(
        smoke.get("schema") == "trimem/grader-smoke-result/1.0"
        and smoke.get("trimem_system_implementation") == "CREDENTIAL_FREE_GREEN"
        and smoke.get("performance") == "NOT_MEASURED"
        and smoke.get("expected_unique_instances") == 6
        and smoke.get("expected_target_count") == 12
        and smoke.get("expected_condition_rows")
        == {"GOLD": 6, "NOOP_BASELINE": 6},
        "grader smoke result static contract differs",
    )
    smoke_actual = smoke.get("actual_execution")
    pre_smoke_actual = {
        "docker_pulls": 0,
        "grader_containers": 0,
        "input_tokens": 0,
        "model_calls": 0,
        "official_grader_runs": 0,
        "output_tokens": 0,
        "paid_model_calls": 0,
        "total_usd": 0,
    }
    passed_smoke_actual = {
        **pre_smoke_actual,
        "docker_pulls": 7,
        "grader_containers": 12,
        "official_grader_runs": 12,
    }
    smoke_state = (
        smoke.get("status"), smoke.get("grader_exec_package"),
        smoke.get("official_grader_viability"),
    )
    require(
        isinstance(smoke_actual, dict)
        and all(type(value) is int for value in smoke_actual.values())
        and (
        (
            smoke_state
            == (
                "CORRECTION_IN_PROGRESS", "CORRECTION_IN_PROGRESS",
                "NOT_YET_ESTABLISHED",
            )
            and smoke_actual == pre_smoke_actual
        )
        or (
            smoke_state == ("PASS", "PASS", "ESTABLISHED")
            and smoke_actual == passed_smoke_actual
        )
        ),
        "grader smoke state/counter contract is invalid",
    )
    return {
        "credential_free_bundle_hash": credential["bundle_hash"],
        "development_physical_runs": 72,
        "heldout_physical_runs": 81,
        "support_image_digests_frozen": 1,
        "target_image_digests_frozen": 45,
        "model_calls": smoke_actual["model_calls"],
        "official_grader_runs": smoke_actual["official_grader_runs"],
        "paid_model_calls": smoke_actual["paid_model_calls"],
    }


def preapproval_blockers() -> list[str]:
    blockers = []
    selected = validate_selected_m2(require_frozen=False)
    if selected.get("status") != "PRE_DEVELOPMENT":
        blockers.append("pre-development selection placeholder is not exact")
    smoke = read_json(ARTIFACT / "grader_smoke_result.json")
    smoke_state = (
        smoke.get("status"),
        smoke.get("official_grader_viability"),
    )
    if smoke_state not in {
        ("CORRECTION_IN_PROGRESS", "NOT_YET_ESTABLISHED"),
        ("PASS", "ESTABLISHED"),
    }:
        blockers.append("grader-smoke correction/viability state is inconsistent")
    request = read_json(CONFIG / "benchmark_exec_request.json")
    if request.get("approval_state") != "PENDING_EXEC_APPROVAL":
        blockers.append("committed external approval request is not pending")
    return blockers


def execution_blockers(approval_file: Path) -> tuple[list[str], str | None]:
    try:
        document = read_json(approval_file)
        phase = document.get("approval", {}).get("approved_phase")
        name = {"GRADER_SMOKE": "grader-smoke", "DEVELOPMENT_TUNING": "development", "HELDOUT_BENCHMARK": "heldout"}.get(phase)
        if name is None:
            return ["external approval phase is unknown"], None
        validate_exec_approval(name, approval_file)
    except (OSError, ValueError) as exc:
        return [str(exc)], None
    smoke = read_json(ARTIFACT / "grader_smoke_result.json")
    if name in {"development", "heldout"} and smoke.get("status") != "PASS":
        return ["official GOLD+NOOP_BASELINE smoke PASS is required before benchmark execution"], name
    selected = validate_selected_m2(require_frozen=False)
    if name == "development" and selected.get("status") != "PRE_DEVELOPMENT":
        return ["development requires the exact PRE_DEVELOPMENT selection state"], name
    if name == "heldout":
        try:
            validate_selected_m2(require_frozen=True)
        except ValueError as exc:
            return [str(exc)], name
    return [], name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", choices=("static", "benchmark-approval", "grader-smoke-exec", "benchmark-exec"), default="static")
    parser.add_argument("--require-git-tracked", action="store_true")
    parser.add_argument("--approval-file", type=Path)
    args = parser.parse_args()
    try:
        # Every approval or execution endpoint must prove that the entire
        # frozen closure is committed.  The flag remains useful for strict
        # local static checks, but cannot weaken an approval-level gate when
        # omitted by a caller.
        require_git_tracked = args.require_git_tracked or args.level != "static"
        evidence = validate_static(require_git_tracked)
        blockers: list[str] = []
        phase = None
        if args.level == "benchmark-approval":
            blockers = preapproval_blockers()
        elif args.level in {"grader-smoke-exec", "benchmark-exec"}:
            if args.approval_file is None:
                blockers = ["external immutable approval file is required"]
            else:
                blockers, phase = execution_blockers(args.approval_file.resolve())
            if args.level == "grader-smoke-exec" and phase not in {None, "grader-smoke"}:
                blockers.append("grader-smoke gate received a non-smoke approval")
            if args.level == "benchmark-exec" and phase not in {None, "development", "heldout"}:
                blockers.append("benchmark gate received a non-benchmark approval")
        report = {
            **evidence,
            "blockers": blockers,
            "level": args.level,
            "approved_phase": phase,
            "git_tracked_freeze_required": require_git_tracked,
            "grader_exec_package": "CORRECTION_IN_PROGRESS",
            "official_grader_viability": "NOT_YET_ESTABLISHED" if args.level == "benchmark-approval" else "EXECUTION_GATED",
            "performance": "NOT_MEASURED",
            "status": "PASS" if not blockers else "FAIL_CLOSED",
            "trimem_system_implementation": "CREDENTIAL_FREE_GREEN",
        }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if not blockers else 1
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "level": args.level, "status": "FAIL"}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
