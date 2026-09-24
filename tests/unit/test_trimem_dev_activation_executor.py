from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_dev_activation_diagnostic as diagnostic  # noqa: E402
import trimem_dev_activation_executor as executor  # noqa: E402
import trimem_benchmark_run as benchmark  # noqa: E402
import trimem_dev_activation_approval as approval_builder  # noqa: E402
import trimem_dev_activation_gate as activation_gate  # noqa: E402

from enterprise_memory.trimem.adaptive_horizon import AdaptiveHorizonPolicy  # noqa: E402
from enterprise_memory.trimem.agent_runtime import (  # noqa: E402
    CANONICAL_FAILED_CELL_NOOP,
    CodingTask,
)
from enterprise_memory.trimem.gateway import (  # noqa: E402
    GatewayInvocationFailure,
    GatewayResponse,
    ModelPreflightFailure,
    ReplayModelGateway,
)
from enterprise_memory.trimem.grader import GradeResult  # noqa: E402
from enterprise_memory.trimem.ppr import DeterministicHashEmbedder  # noqa: E402
from enterprise_memory.trimem.retrieval import (  # noqa: E402
    RetrievalConfig,
    RetrievalSessionState,
    TriMemoryRetriever,
)
from enterprise_memory.trimem.runtime_lock import RuntimeLock  # noqa: E402
from enterprise_memory.trimem.workspace import InMemoryWorkspaceFactory  # noqa: E402
from enterprise_memory.trimem.working_graph import (  # noqa: E402
    ShortTermWorkingGraph,
    SubtaskSpec,
)
from trimem_m2_candidates import runtime_lock_for  # noqa: E402


SOURCE_BANK_SHA256 = "a" * 64
SOURCE_SNAPSHOT_SHA256 = "b" * 64
EXECUTION_IDENTITY_SHA256 = "c" * 64
TEST_API_KEY = "sk-trimem-diagnostic-test-key-0000000000000000"


def _execution_contract() -> executor.ExecutionContract:
    manifest, policy, cells, _ = diagnostic.load_and_validate_contract(
        ROOT,
        require_source_bank=False,
        require_tracked=False,
    )
    assignments = {}
    records = {}
    for target in manifest["targets"]:
        memory_id = f"memory-{target['order_index']:02d}"
        records[memory_id] = {
            "memory_id": memory_id,
            "source_task_id": f"historical-{target['order_index']:02d}",
            "payload_sha256": format(target["order_index"] + 1, "064x"),
        }
        assignments[target["target_id"]] = {
            "target_id": target["target_id"],
            "target_repository": target["repository"],
            "target_problem_provenance_sha256": format(
                target["order_index"] + 101, "064x"
            ),
            "target_public_instruction_sha256": format(
                target["order_index"] + 201, "064x"
            ),
            "candidate_count": 1,
            "candidates": [
                {
                    "memory_id": memory_id,
                    "source_task_id": f"historical-{target['order_index']:02d}",
                    "score": {
                        "errors_overlap": 0,
                        "apis_overlap": 0,
                        "symbols_overlap": 0,
                        "paths_overlap": 0,
                        "tokens_overlap": 0,
                    },
                }
            ],
        }
    return executor.ExecutionContract(
        manifest=manifest,
        policy=policy,
        expected_cells=tuple(cells),
        source_bank_manifest_sha256=SOURCE_BANK_SHA256,
        source_bank_snapshot_sha256=SOURCE_SNAPSHOT_SHA256,
        source_bank_manifest_path=(
            "configs/trimem_v1/dev_activation_source_bank_manifest.json"
        ),
        assignments_by_target=assignments,
        records_by_memory_id=records,
        matrix_raw_sha256=diagnostic.file_sha256(
            ROOT / diagnostic.MATRIX_PATH
        ),
        policy_raw_sha256=diagnostic.file_sha256(ROOT / diagnostic.POLICY_PATH),
    )


def _test_capabilities() -> dict:
    return {
        "schema": executor.CAPABILITY_SCHEMA,
        "executor_id": "credential-free-fixture",
        "executor_kind": "CREDENTIAL_FREE_TEST_DOUBLE",
        "one_cell_per_invocation": True,
        "durable_resume": True,
        "fresh_namespace_per_cell": True,
        "read_only_source_bank": True,
        "contained_failure_to_official_grader": True,
        "official_grader_required": True,
        "reused_benchmark_primitives": [],
    }


class _FakeCellExecutor:
    def __init__(
        self,
        *,
        fail_once_at: int | None = None,
        contained_failure_at: int | None = None,
        malformed_at: int | None = None,
    ) -> None:
        self.fail_once_at = fail_once_at
        self.contained_failure_at = contained_failure_at
        self.malformed_at = malformed_at
        self.failed = False
        self.calls: list[tuple[int, bool, str]] = []

    def capabilities(self) -> dict:
        return _test_capabilities()

    def execute_cell(
        self,
        request,
        *,
        resume: bool,
        journal_root: Path,
    ) -> dict:
        index = request["cell_index"]
        self.calls.append((index, resume, str(journal_root)))
        if self.fail_once_at == index and not self.failed:
            self.failed = True
            raise RuntimeError("synthetic process interruption")

        arm = request["arm_id"]
        source = request["source_bank"]
        memory_id = None if source is None else source["candidate_memory_ids"][0]
        decisions = []
        injections = []
        if arm in {"C1", "C2"}:
            reason = "BELOW_CONFIDENCE_THRESHOLD" if arm == "C1" else "INJECTED"
            decisions = [
                {
                    "recall_attempt_id": f"{request['cell_id']}:S1:HISTORICAL_VERIFIED",
                    "target_id": request["target_id"],
                    "subtask_id": "S1",
                    "bank_type": "HISTORICAL_VERIFIED",
                    "candidate_count_before_filter": 1,
                    "candidate_count_after_filter": 1,
                    "top_candidate_id": memory_id,
                    "top_embedding_score": 0.4,
                    "top_ppr_score": 0.2,
                    "threshold": {"min_confidence": 0.25, "min_margin": 0.01},
                    "Q_USE": None,
                    "Q_ABSTAIN": None,
                    "router_policy": "N/A",
                    "final_reason_code": reason,
                }
            ]
            if arm == "C2":
                injections = [
                    {
                        "memory_id": memory_id,
                        "source_task_id": "source-task",
                        "source_repository": "example/repo",
                        "target_repository": "example/repo",
                        "bank_type": "HISTORICAL_VERIFIED",
                        "subtask_id": "S1",
                        "repo_overlap": True,
                        "active_subtask_projection_sha256": "e" * 64,
                        "active_subtask_declared_file_overlap": [],
                        "active_subtask_declared_symbol_overlap": [],
                        "active_subtask_declared_api_overlap": [],
                        "active_subtask_declared_error_overlap": [],
                        "pre_execution_target_issue_overlap": dict(
                            request["source_bank"] and {key: 0 for key in (
                                "errors_overlap", "apis_overlap", "symbols_overlap",
                                "paths_overlap", "tokens_overlap",
                            )}
                        ),
                    }
                ]

        contained = index == self.contained_failure_at
        cell = {
            "schema": "trimem/dev-activation-cell/1.0",
            "diagnostic_id": request["diagnostic_id"],
            "cell_id": request["cell_id"],
            "cell_index": index,
            "arm_id": arm,
            "target_id": request["target_id"],
            "target_order_index": request["target_order_index"],
            "source_bank_manifest_sha256": (
                None if source is None else source["manifest_raw_sha256"]
            ),
            "official_grader_evidence_sha256": "d" * 64,
            "terminal": True,
            "terminal_reason_code": (
                "MODEL_FAILURE_CONTINUED_TO_GRADER"
                if contained
                else "PER_SUBTASK_STEP_CAP_REACHED"
            ),
            "official_grader_resolved": False,
            "diagnostic_resolved": False,
            "patch_class": "CANONICAL_NOOP",
            "model_failure_code": "MODEL_TIMEOUT" if contained else None,
            "extraction_status": "SUCCESS",
            "extraction_failure_code": None,
            "injections": injections,
            "recall_decisions": decisions,
            "adaptive_horizon": {
                "extensions_granted": 0,
                "progress_event_ids": [],
                "per_subtask_extensions": {"S1": 0},
                "agent_completed_count": 0,
                "per_subtask_step_cap_reached_count": 1,
            },
            "accounting": {
                "decomposition_calls": 1,
                "solve_calls": 8,
                "extraction_calls": 1,
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 50,
                "paid_model_calls": 10,
                "model_wall_time_ms": 10,
                "tool_wall_time_ms": 20,
                "grader_wall_time_ms": 30,
                "grader_calls": 1,
                "grader_containers": 1,
                "official_grader_runs": 1,
                "task_wall_time_ms": 60,
                "total_usd": "0.001",
            },
        }
        if index == self.malformed_at:
            cell["official_grader_resolved"] = None
        return cell


def test_requests_freeze_arm_mapping_fresh_cells_and_equal_c1_c2_views() -> None:
    requests = executor.build_cell_requests(
        _execution_contract(),
        execution_identity_sha256=EXECUTION_IDENTITY_SHA256,
    )
    assert len(requests) == 36
    assert [row["cell_index"] for row in requests] == list(range(36))
    assert [row["arm_id"] for row in requests[::12]] == ["C0", "C1", "C2"]
    assert len({row["experiment_id"] for row in requests}) == 36

    by_cell = {(row["arm_id"], row["target_id"]): row for row in requests}
    for target in _execution_contract().manifest["targets"]:
        target_id = target["target_id"]
        c0 = by_cell[("C0", target_id)]
        c1 = by_cell[("C1", target_id)]
        c2 = by_cell[("C2", target_id)]
        assert c0["runtime_arm"] == "M0"
        assert c0["source_bank"] is None
        assert c0["retrieval"]["selection_mode"] is None
        assert c1["runtime_arm"] == c2["runtime_arm"] == "M2"
        assert c1["retrieval"]["selection_mode"] == "CURRENT_GATE"
        assert c2["retrieval"]["selection_mode"] == "FORCED_SAFE_TOP1"
        assert c1["retrieval"]["require_safe_pool_metadata"] is True
        assert c2["retrieval"]["require_safe_pool_metadata"] is True
        assert diagnostic.canonical_bytes(c1["source_bank"]) == diagnostic.canonical_bytes(
            c2["source_bank"]
        )
        assert c1["source_bank"]["mutation_allowed"] is False
        assert c0["hard_caps"] == {
            "model_calls": 26,
            "paid_model_calls": 26,
            "decomposition_calls": 1,
            "solve_calls": 24,
            "extraction_calls": 1,
            "input_tokens": 500_000,
            "output_tokens": 65_536,
            "grader_calls": 1,
            "grader_containers": 1,
            "official_grader_runs": 1,
            "protocol_canary_calls": 0,
        }


def test_serial_adapter_accepts_contained_model_failure_and_continues(tmp_path: Path) -> None:
    backend = _FakeCellExecutor(contained_failure_at=7)
    outcome = executor.execute_diagnostic(
        contract=_execution_contract(),
        executor=backend,
        output_root=tmp_path / "run",
        execution_identity_sha256=EXECUTION_IDENTITY_SHA256,
        allow_test_executor=True,
    )
    assert [index for index, _, _ in backend.calls] == list(range(36))
    assert all(not resumed for _, resumed, _ in backend.calls)
    assert outcome.completed_cell_count == 36
    assert outcome.resumed_cell_count == 0
    assert outcome.aggregate["status"] == "COMPLETE_36_OF_36_OFFICIAL_CELLS"
    assert outcome.result["cells"][7]["terminal_reason_code"] == (
        "MODEL_FAILURE_CONTINUED_TO_GRADER"
    )
    assert outcome.result["cells"][8]["cell_index"] == 8
    assert (tmp_path / "run" / "results.json").is_file()
    assert (tmp_path / "run" / "aggregate.json").is_file()


def test_resume_skips_completed_cells_and_resumes_only_ambiguous_intent(
    tmp_path: Path,
) -> None:
    backend = _FakeCellExecutor(fail_once_at=5)
    output = tmp_path / "run"
    with pytest.raises(
        executor.DiagnosticExecutorError,
        match="stopped before an official terminal result",
    ):
        executor.execute_diagnostic(
            contract=_execution_contract(),
            executor=backend,
            output_root=output,
            execution_identity_sha256=EXECUTION_IDENTITY_SHA256,
            allow_test_executor=True,
        )
    assert [index for index, _, _ in backend.calls] == list(range(6))

    outcome = executor.execute_diagnostic(
        contract=_execution_contract(),
        executor=backend,
        output_root=output,
        execution_identity_sha256=EXECUTION_IDENTITY_SHA256,
        resume=True,
        allow_test_executor=True,
    )
    counts = Counter(index for index, _, _ in backend.calls)
    assert counts[0] == 1
    assert counts[4] == 1
    assert counts[5] == 2
    assert next(resumed for index, resumed, _ in backend.calls if index == 5 and resumed)
    assert outcome.completed_cell_count == 36
    assert outcome.resumed_cell_count == 5


def test_malformed_nonofficial_cell_stops_before_later_cells(tmp_path: Path) -> None:
    backend = _FakeCellExecutor(malformed_at=3)
    with pytest.raises(executor.DiagnosticExecutorError, match="official grader result is unknown"):
        executor.execute_diagnostic(
            contract=_execution_contract(),
            executor=backend,
            output_root=tmp_path / "run",
            execution_identity_sha256=EXECUTION_IDENTITY_SHA256,
            allow_test_executor=True,
        )
    assert [index for index, _, _ in backend.calls] == [0, 1, 2, 3]
    assert not (tmp_path / "run" / "cells" / "03" / "result.json").exists()
    assert not (tmp_path / "run" / "results.json").exists()


def test_resume_rejects_tampered_durable_cell(tmp_path: Path) -> None:
    output = tmp_path / "run"
    backend = _FakeCellExecutor()
    executor.execute_diagnostic(
        contract=_execution_contract(),
        executor=backend,
        output_root=output,
        execution_identity_sha256=EXECUTION_IDENTITY_SHA256,
        allow_test_executor=True,
    )
    path = output / "cells" / "00" / "result.json"
    journal = json.loads(path.read_text(encoding="utf-8"))
    journal["cell"]["accounting"]["input_tokens"] += 1
    path.write_text(json.dumps(journal), encoding="utf-8")
    with pytest.raises(executor.DiagnosticExecutorError, match="result journal binding drift"):
        executor.execute_diagnostic(
            contract=_execution_contract(),
            executor=_FakeCellExecutor(),
            output_root=output,
            execution_identity_sha256=EXECUTION_IDENTITY_SHA256,
            resume=True,
            allow_test_executor=True,
        )


def test_test_executor_requires_explicit_credential_free_opt_in(tmp_path: Path) -> None:
    with pytest.raises(executor.DiagnosticExecutorError, match="not authorized"):
        executor.execute_diagnostic(
            contract=_execution_contract(),
            executor=_FakeCellExecutor(),
            output_root=tmp_path / "run",
            execution_identity_sha256=EXECUTION_IDENTITY_SHA256,
        )
    assert not (tmp_path / "run").exists()


def test_production_capability_receipt_locks_existing_primitives() -> None:
    capabilities = executor.production_capabilities("reviewed-one-cell-backend-v1")
    assert capabilities["executor_kind"] == "OFFICIAL_PRODUCTION_CELL"
    assert tuple(capabilities["reused_benchmark_primitives"]) == (
        executor.REUSABLE_BENCHMARK_PRIMITIVES
    )
    assert capabilities["contained_failure_to_official_grader"] is True


def test_execution_contract_loads_frozen_source_bank() -> None:
    contract = executor.load_execution_contract(ROOT, require_tracked=False)

    assert contract.source_bank_manifest_sha256 == (
        "8a0600e8d18f5234bd35d675f8e5cb8eb827aac4e4498547db02fc689a83d309"
    )
    assert contract.source_bank_snapshot_sha256 == (
        "55fe3c03ef545181986605166247f78896c5fcd2db37535d19f574781c16be1e"
    )
    assert len(contract.records_by_memory_id) == 12
    assert len(contract.assignments_by_target) == 12


def test_committed_real_bank_all_12_forced_safe_views_are_usable_and_c1_c2_equal() -> None:
    contract = executor.load_execution_contract(ROOT, require_tracked=False)
    requests = executor.build_cell_requests(
        contract, execution_identity_sha256=EXECUTION_IDENTITY_SHA256
    )
    tasks = {
        target["target_id"]: CodingTask(
            task_id=target["target_id"],
            org_id="diagnostic-isolated",
            user_id="diagnostic-reader",
            repository=target["repository"],
            commit=target["base_commit"],
            instruction="Apply the public repository repair safely.",
            files={},
            editable_paths=(),
        )
        for target in contract.manifest["targets"]
    }
    for offset, target in enumerate(contract.manifest["targets"]):
        task = tasks[target["target_id"]]
        c1 = executor.ManifestBackedDiagnosticSourceBankStore(
            contract=contract,
            request=requests[12 + offset],
            task=task,
            repository_root=ROOT,
        )
        c2 = executor.ManifestBackedDiagnosticSourceBankStore(
            contract=contract,
            request=requests[24 + offset],
            task=task,
            repository_root=ROOT,
        )
        assert c1.execution_views == c2.execution_views
        assert c1.content_hash == c2.content_hash
        assert max(map(len, c2.execution_views.values())) < 12_000
        graph = ShortTermWorkingGraph(
            task.task_id, task.instruction, task.repository
        )
        node = graph.add_subtask(
            SubtaskSpec(
                node_id="S1",
                objective="apply a historical source repair",
                operation="validate repair evidence",
                files=(),
            )
        )
        graph.activate(node.node_id)
        decision = TriMemoryRetriever(
            c2,
            RetrievalConfig(
                embedding_dimensions=384,
                context_budget_bytes=12_000,
            ),
            embedder=DeterministicHashEmbedder(384),
            selection_mode="FORCED_SAFE_TOP1",
            diagnostic_telemetry=True,
            require_safe_pool_metadata=True,
        ).recall(
            graph,
            RetrievalSessionState(task.task_id),
            user_id=task.user_id,
            org_id=task.org_id,
            repository=task.repository,
        )
        assert len(decision.injections) == 1


def _production_wiring_fixture():
    base = _execution_contract()
    records = {}
    assignments = {}
    payloads = {}
    tasks = {}
    for target in base.manifest["targets"]:
        index = int(target["order_index"])
        memory_id = f"source-memory-{index:02d}"
        source_task_id = f"historical-source-{index:02d}"
        source_commit = format(index + 1, "040x")
        source_row_sha = format(index + 101, "064x")
        diff = (
            "diff --git a/value.py b/value.py\n"
            "--- a/value.py\n"
            "+++ b/value.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 1\n"
            "+VALUE = 2\n"
        )
        payload = {
            "schema": "trimem/dev-activation-source-payload/1.0",
            "source_task_id": source_task_id,
            "source_repository": target["repository"],
            "source_row_sha256": source_row_sha,
            "source_public_issue": (
                "Historical public issue: update VALUE while preserving its public API."
            ),
            "source_fix_patch": diff,
            "source_fix_patch_sha256": __import__("hashlib").sha256(
                diff.encode("utf-8")
            ).hexdigest(),
            "features": {
                "changed_paths": ["value.py"],
                "symbols": ["VALUE"],
                "apis": [],
                "errors": [],
            },
        }
        raw = diagnostic.canonical_bytes(payload)
        payload_sha = __import__("hashlib").sha256(raw).hexdigest()
        payloads[memory_id] = raw
        records[memory_id] = {
            "memory_id": memory_id,
            "source_task_id": source_task_id,
            "source_dataset_id": "fixture-public-source",
            "source_dataset_revision": source_commit,
            "source_row_sha256": source_row_sha,
            "source_repository": target["repository"],
            "source_base_commit": "f" * 40,
            "source_commit": source_commit,
            "source_timestamp": "2025-01-02T03:04:05Z",
            "bank_type": "ORG_SEMANTIC",
            "changed_paths": ["value.py"],
            "symbols": ["VALUE"],
            "apis": [],
            "errors": [],
            "verified": True,
            "reviewed": True,
            "source_outcome": "passed",
            "source_fix_verification_signal": (
                "UPSTREAM_MERGED_FIX_PATCH_EQUIVALENT"
            ),
            "verification_evidence_sha256": "d" * 64,
            "chronology_and_version_evidence_sha256": "e" * 64,
            "provenance_sha256": "a" * 64,
            "payload_sha256": payload_sha,
            "payload_path": f"payloads/{payload_sha}.json",
            "permission_scope": "PUBLIC_READ",
            "tenant_scope": "BENCHMARK_ISOLATED",
            "repository_scope": "EXACT_SOURCE_AND_TARGET_REPOSITORY",
            "version_scope": "EXACT_SOURCE_COMMIT",
            "path_scope": "**",
            "quarantined": False,
            "target_derived": False,
        }
        assignments[target["target_id"]] = {
            "target_id": target["target_id"],
            "target_repository": target["repository"],
            "target_problem_provenance_sha256": format(index + 301, "064x"),
            "target_public_instruction_sha256": __import__("hashlib").sha256(
                b"Update VALUE and preserve its public API."
            ).hexdigest(),
            "candidate_count": 1,
            "candidates": [
                {
                    "memory_id": memory_id,
                    "source_task_id": source_task_id,
                    "score": {
                        "errors_overlap": 0,
                        "apis_overlap": 0,
                        "symbols_overlap": 1,
                        "paths_overlap": 1,
                        "tokens_overlap": 1,
                    },
                }
            ],
        }
        tasks[target["target_id"]] = CodingTask(
            task_id=target["target_id"],
            org_id="diagnostic-org",
            user_id="diagnostic-reader",
            repository=target["repository"],
            commit=target["base_commit"],
            instruction="Update VALUE and preserve its public API.",
            files={"value.py": "VALUE = 1\n"},
            editable_paths=("value.py",),
        )
    contract = executor.ExecutionContract(
        manifest=base.manifest,
        policy=base.policy,
        expected_cells=base.expected_cells,
        source_bank_manifest_sha256=base.source_bank_manifest_sha256,
        source_bank_snapshot_sha256=base.source_bank_snapshot_sha256,
        source_bank_manifest_path=base.source_bank_manifest_path,
        assignments_by_target=assignments,
        records_by_memory_id=records,
        matrix_raw_sha256=base.matrix_raw_sha256,
        policy_raw_sha256=base.policy_raw_sha256,
    )
    return contract, payloads, tasks


def _selected_recall_config() -> RetrievalConfig:
    retrieval = json.loads(
        (ROOT / "configs/trimem_v1/m2_candidates/recall.json").read_text(
            encoding="utf-8"
        )
    )["retrieval"]
    return RetrievalConfig(
        min_confidence=retrieval["min_confidence"],
        min_margin=retrieval["min_margin"],
        episode_complete_threshold=retrieval["episode_complete_threshold"],
        max_episodic_per_node=retrieval["max_episodic_per_active_node"],
        max_semantic_per_node=retrieval["max_semantic_per_active_node"],
        max_task_injections=retrieval["max_task_injections"],
        context_budget_bytes=retrieval["context_budget_bytes"],
        embedding_dimensions=retrieval["embedding_dimensions"],
        embedding_weight=retrieval["embedding_weight"],
        lexical_weight=retrieval["lexical_weight"],
        ppr_damping=retrieval["ppr_damping"],
        ppr_iterations=retrieval["ppr_iterations"],
    )


def test_production_constructor_rejects_nonselected_runtime_and_retrieval() -> None:
    contract, payloads, tasks = _production_wiring_fixture()
    common = {
        "contract": contract,
        "tasks_by_target_id": tasks,
        "repository_root": ROOT,
        "workspace_factory": lambda *_args: (InMemoryWorkspaceFactory(), {}),
        "model_gateway_factory": lambda *_args: executor.ManagedModelGateway(None),
        "grader_gateway_factory": lambda *_args: None,
        "pricing": {
            "input_per_million_tokens_usd": 0.75,
            "cached_input_per_million_tokens_usd": 0.075,
            "output_per_million_tokens_usd": 4.5,
        },
        "model_config_hash": "1" * 64,
        "grader_config_hash": lambda _request: "2" * 64,
        "expected_image_digest": lambda _request: "sha256:" + "3" * 64,
            "ledger": object(),
            "embedder_preflight_sha256": "4" * 64,
            "retrieval_rehearsal_sha256": "6" * 64,
            "image_reinspection_sha256": "5" * 64,
            "solver_sandbox_rehearsal_sha256": "7" * 64,
            "payload_bytes": payloads,
    }
    with pytest.raises(
        executor.DiagnosticExecutorError,
        match="frozen adaptive recall lock",
    ):
        executor.OfficialProductionCellExecutor(
            runtime_lock=replace(
                RuntimeLock(), adaptive_horizon=AdaptiveHorizonPolicy(enabled=True)
            ),
            retrieval_config=_selected_recall_config(),
            embedder_factory=lambda: DeterministicHashEmbedder(384),
            **common,
        )

    selected_lock = replace(
        runtime_lock_for("recall"),
        adaptive_horizon=AdaptiveHorizonPolicy(enabled=True),
    )
    with pytest.raises(
        executor.DiagnosticExecutorError,
        match="selected recall policy",
    ):
        executor.OfficialProductionCellExecutor(
            runtime_lock=selected_lock,
            retrieval_config=RetrievalConfig(embedding_dimensions=384),
            embedder_factory=lambda: DeterministicHashEmbedder(384),
            **common,
        )
    accepted = executor.OfficialProductionCellExecutor(
        runtime_lock=selected_lock,
        retrieval_config=_selected_recall_config(),
        embedder_factory=lambda: DeterministicHashEmbedder(384),
        **common,
    )
    assert accepted.capabilities()["executor_kind"] == "OFFICIAL_PRODUCTION_CELL"


class _OfficialFixtureGrader:
    def __init__(self) -> None:
        self.calls = 0
        self.patches = []

    def grade(self, request):
        self.calls += 1
        self.patches.append(request.patch)
        return GradeResult(
            task_id=request.task_id,
            resolved=False,
            exit_code=1,
            stdout="official-shaped unresolved fixture",
            stderr="",
            report={"task_id": request.task_id, "resolved": False},
            grader_id="official-credential-free-fixture-v1",
            container_digest="fixture@sha256:" + "f" * 64,
            official=True,
            wall_time_ms=1,
            container_started=True,
            status="success",
        )


def _production_wiring_model(request) -> str:
    if request.call_kind == "decompose":
        return json.dumps(
            {
                "subtasks": [
                    {
                        "id": "S1",
                        "objective": "update the exported VALUE while preserving its API",
                        "predicted_operation": "replace the exported value literal",
                        "depends_on": [],
                        "files": ["value.py"],
                        "symbols": ["VALUE"],
                    }
                ]
            }
        )
    if request.call_kind == "solve":
        _, marker, state = request.prompt.partition("\n\nSTATE:\n")
        assert marker
        memories = json.loads(state)["memory_for_active_subtask_only"]
        assert len(memories) == 1
        assert "UNTRUSTED PUBLIC HISTORICAL MEMORY" in memories[0]["exact_text"]
        assert "bounded_source_diff_hunks" in memories[0]["exact_text"]
        return json.dumps(
            {
                "tool": "complete_subtask",
                "arguments": {"evidence": "historical repair evidence reviewed"},
            }
        )
    return json.dumps(
        {
            "episode": {
                "summary": "The public task remained unresolved.",
                "action": "Reviewed historical source repair evidence.",
                "outcome": "failed",
            },
            "semantic_candidate": None,
        }
    )


def test_official_production_executor_wires_real_runtime_recall_grader_and_evidence(
    tmp_path: Path,
) -> None:
    contract, payloads, tasks = _production_wiring_fixture()
    graders = []

    def workspace_factory(_request, _task, _root, _resume):
        return InMemoryWorkspaceFactory(), {"mode": "credential-free-fresh-workspace"}

    def model_factory(_request, _task, _root):
        return executor.ManagedModelGateway(
            ReplayModelGateway(_production_wiring_model)
        )

    def grader_factory(_request, _task, _root):
        grader = _OfficialFixtureGrader()
        graders.append(grader)
        return grader

    lock = replace(
        RuntimeLock(),
        adaptive_horizon=AdaptiveHorizonPolicy(enabled=True),
    )
    backend = executor.OfficialProductionCellExecutor(
        contract=contract,
        runtime_lock=lock,
        tasks_by_target_id=tasks,
        repository_root=tmp_path,
        workspace_factory=workspace_factory,
        model_gateway_factory=model_factory,
        grader_gateway_factory=grader_factory,
        retrieval_config=RetrievalConfig(
            min_confidence=0.25,
            min_margin=0.0,
            context_budget_bytes=12_000,
        ),
        embedder_factory=lambda: DeterministicHashEmbedder(128),
        pricing={
            "input_per_million_tokens_usd": 0.75,
            "cached_input_per_million_tokens_usd": 0.075,
            "output_per_million_tokens_usd": 4.5,
        },
        model_config_hash="1" * 64,
        grader_config_hash=lambda _request: "2" * 64,
        expected_image_digest=lambda _request: None,
        payload_bytes=payloads,
        credential_free_test_mode=True,
    )
    request = executor.build_cell_requests(
        contract, execution_identity_sha256=EXECUTION_IDENTITY_SHA256
    )[24]
    cell = backend.execute_cell(
        request,
        resume=False,
        journal_root=tmp_path / "backend",
    )

    assert request["arm_id"] == "C2"
    assert graders[0].calls == 1
    assert cell["official_grader_resolved"] is False
    assert cell["terminal_reason_code"] == "AGENT_COMPLETED"
    assert cell["accounting"]["decomposition_calls"] == 1
    assert cell["accounting"]["solve_calls"] == 1
    assert cell["accounting"]["extraction_calls"] == 1
    assert cell["accounting"]["official_grader_runs"] == 1
    assert len(cell["injections"]) == 1
    assert cell["injections"][0]["bank_type"] == "ORG_SEMANTIC"
    assert cell["recall_decisions"][-1]["final_reason_code"] == "INJECTED"
    assert (tmp_path / "backend" / "evidence" / "events.jsonl").is_file()
    assert (tmp_path / "backend" / "official-grader-evidence.json").is_file()
    assert (tmp_path / "backend" / "production-cell-result.json").is_file()


def test_production_runtime_contains_step_cap_and_officially_grades_noop(
    tmp_path: Path,
) -> None:
    contract, payloads, tasks = _production_wiring_fixture()
    graders = []

    def no_progress_model(request):
        if request.call_kind == "decompose":
            return json.dumps(
                {
                    "subtasks": [
                        {
                            "id": "S1",
                            "objective": "inspect the exported VALUE without changing its API",
                            "predicted_operation": "inspect the exported value literal",
                            "depends_on": [],
                            "files": ["value.py"],
                        }
                    ]
                }
            )
        if request.call_kind == "solve":
            return json.dumps(
                {"tool": "read_file", "arguments": {"path": "value.py"}}
            )
        return json.dumps(
            {
                "episode": {
                    "summary": "The step cap ended a no-progress attempt.",
                    "action": "Repeated a read-only inspection.",
                    "outcome": "failed",
                },
                "semantic_candidate": None,
            }
        )

    def grader_factory(_request, _task, _root):
        grader = _OfficialFixtureGrader()
        graders.append(grader)
        return grader

    backend = executor.OfficialProductionCellExecutor(
        contract=contract,
        runtime_lock=replace(
            RuntimeLock(),
            adaptive_horizon=AdaptiveHorizonPolicy(enabled=True),
        ),
        tasks_by_target_id=tasks,
        repository_root=tmp_path,
        workspace_factory=lambda _request, _task, _root, _resume: (
            InMemoryWorkspaceFactory(),
            {"mode": "credential-free-fresh-workspace"},
        ),
        model_gateway_factory=lambda _request, _task, _root: (
            executor.ManagedModelGateway(ReplayModelGateway(no_progress_model))
        ),
        grader_gateway_factory=grader_factory,
        retrieval_config=RetrievalConfig(),
        embedder_factory=lambda: DeterministicHashEmbedder(128),
        pricing={
            "input_per_million_tokens_usd": 0.75,
            "cached_input_per_million_tokens_usd": 0.075,
            "output_per_million_tokens_usd": 4.5,
        },
        model_config_hash="1" * 64,
        grader_config_hash=lambda _request: "2" * 64,
        expected_image_digest=lambda _request: None,
        payload_bytes=payloads,
        credential_free_test_mode=True,
    )
    request = executor.build_cell_requests(
        contract, execution_identity_sha256=EXECUTION_IDENTITY_SHA256
    )[0]
    cell = backend.execute_cell(
        request,
        resume=False,
        journal_root=tmp_path / "failed-backend",
    )

    assert cell["terminal_reason_code"] == "PER_SUBTASK_STEP_CAP_REACHED"
    assert cell["model_failure_code"] is None
    assert cell["patch_class"] == "CANONICAL_NOOP"
    assert cell["official_grader_resolved"] is False
    assert cell["accounting"]["solve_calls"] == 8
    assert cell["accounting"]["extraction_calls"] == 1
    assert cell["accounting"]["official_grader_runs"] == 1
    assert graders[0].calls == 1
    assert graders[0].patches == [CANONICAL_FAILED_CELL_NOOP]


def test_credential_free_production_wiring_completes_all_36_official_cells(
    tmp_path: Path,
) -> None:
    contract, payloads, tasks = _production_wiring_fixture()
    calls = Counter()
    graders = []

    def model(request):
        calls[request.call_kind] += 1
        if request.call_kind == "decompose":
            return json.dumps(
                {
                    "subtasks": [
                        {
                            "id": "S1",
                            "objective": "inspect the exported VALUE contract",
                            "predicted_operation": "inspect the exported value",
                            "depends_on": [],
                            "files": ["value.py"],
                            "symbols": ["VALUE"],
                        }
                    ]
                }
            )
        if request.call_kind == "solve":
            return json.dumps(
                {
                    "tool": "complete_subtask",
                    "arguments": {"evidence": "fixture inspection complete"},
                }
            )
        return json.dumps(
            {
                "episode": {
                    "summary": "The credential-free official-shaped cell ended.",
                    "action": "Inspected the fixture contract.",
                    "outcome": "failed",
                },
                "semantic_candidate": None,
            }
        )

    def grader_factory(_request, _task, _root):
        grader = _OfficialFixtureGrader()
        graders.append(grader)
        return grader

    backend = executor.OfficialProductionCellExecutor(
        contract=contract,
        runtime_lock=replace(
            RuntimeLock(), adaptive_horizon=AdaptiveHorizonPolicy(enabled=True)
        ),
        tasks_by_target_id=tasks,
        repository_root=tmp_path,
        workspace_factory=lambda _request, _task, _root, _resume: (
            InMemoryWorkspaceFactory(),
            {"mode": "credential-free-fresh-workspace"},
        ),
        model_gateway_factory=lambda _request, _task, _root: (
            executor.ManagedModelGateway(ReplayModelGateway(model))
        ),
        grader_gateway_factory=grader_factory,
        retrieval_config=RetrievalConfig(
            min_confidence=0.25,
            min_margin=0.0,
            context_budget_bytes=12_000,
        ),
        embedder_factory=lambda: DeterministicHashEmbedder(128),
        pricing={
            "input_per_million_tokens_usd": 0.75,
            "cached_input_per_million_tokens_usd": 0.075,
            "output_per_million_tokens_usd": 4.5,
        },
        model_config_hash="1" * 64,
        grader_config_hash=lambda _request: "2" * 64,
        expected_image_digest=lambda _request: None,
        payload_bytes=payloads,
        credential_free_test_mode=True,
    )
    outcome = executor.execute_diagnostic(
        contract=contract,
        executor=backend,
        output_root=tmp_path / "all-cells",
        execution_identity_sha256=EXECUTION_IDENTITY_SHA256,
        allow_test_executor=True,
    )

    assert outcome.completed_cell_count == 36
    assert outcome.aggregate["status"] == "COMPLETE_36_OF_36_OFFICIAL_CELLS"
    assert backend.executed_cells == [
        row["cell_id"]
        for row in executor.build_cell_requests(
            contract, execution_identity_sha256=EXECUTION_IDENTITY_SHA256
        )
    ]
    assert len(graders) == 36
    assert sum(grader.calls for grader in graders) == 36
    assert calls == Counter({"decompose": 36, "solve": 36, "extract": 36})
    assert all(cell["terminal"] is True for cell in outcome.result["cells"])
    assert all(
        (tmp_path / "all-cells" / "cells" / f"{index:02d}" / "result.json").is_file()
        for index in range(36)
    )


class _PatchAwareOfficialFixtureGrader(_OfficialFixtureGrader):
    def grade(self, request):
        self.calls += 1
        self.patches.append(request.patch)
        resolved = "VALUE = 2" in request.patch
        return GradeResult(
            task_id=request.task_id,
            resolved=resolved,
            exit_code=0 if resolved else 1,
            stdout="official-shaped fixture",
            stderr="",
            report={"task_id": request.task_id, "resolved": resolved},
            grader_id="official-credential-free-fixture-v1",
            container_digest="fixture@sha256:" + "f" * 64,
            official=True,
            wall_time_ms=1,
            container_started=True,
            status="success",
        )


def _diagnostic_backend_for_gateway(tmp_path: Path, gateway) -> tuple:
    contract, payloads, tasks = _production_wiring_fixture()
    grader = _PatchAwareOfficialFixtureGrader()
    backend = executor.OfficialProductionCellExecutor(
        contract=contract,
        runtime_lock=replace(
            RuntimeLock(), adaptive_horizon=AdaptiveHorizonPolicy(enabled=True)
        ),
        tasks_by_target_id=tasks,
        repository_root=tmp_path,
        workspace_factory=lambda *_args: (
            InMemoryWorkspaceFactory(), {"mode": "credential-free"}
        ),
        model_gateway_factory=lambda *_args: executor.ManagedModelGateway(gateway),
        grader_gateway_factory=lambda *_args: grader,
        retrieval_config=RetrievalConfig(),
        embedder_factory=lambda: DeterministicHashEmbedder(128),
        pricing={
            "input_per_million_tokens_usd": 0.75,
            "cached_input_per_million_tokens_usd": 0.075,
            "output_per_million_tokens_usd": 4.5,
        },
        model_config_hash="1" * 64,
        grader_config_hash=lambda _request: "2" * 64,
        expected_image_digest=lambda _request: None,
        payload_bytes=payloads,
        credential_free_test_mode=True,
    )
    request = executor.build_cell_requests(
        contract, execution_identity_sha256=EXECUTION_IDENTITY_SHA256
    )[0]
    return backend, request, grader


def _valid_decomposition() -> str:
    return json.dumps(
        {
            "subtasks": [
                {
                    "id": "S1",
                    "objective": "update VALUE",
                    "predicted_operation": "replace literal",
                    "depends_on": [],
                    "files": ["value.py"],
                    "symbols": ["VALUE"],
                }
            ]
        }
    )


def _valid_extraction(outcome: str = "failed") -> str:
    return json.dumps(
        {
            "episode": {
                "summary": "The diagnostic cell terminated.",
                "action": "Applied the bounded repair attempt.",
                "outcome": outcome,
            },
            "semantic_candidate": None,
        }
    )


def _provider_failure(status: str) -> GatewayInvocationFailure:
    return GatewayInvocationFailure(
        provider="credential-free-fixture",
        model="credential-free-fixture",
        status=status,
        attempt=1,
        input_tokens=3,
        output_tokens=1,
        cached_input_tokens=0,
        reasoning_tokens=0,
        wall_time_ms=1,
    )


@pytest.mark.parametrize("failing_role", ["decompose", "solve"])
def test_coding_model_failure_is_officially_graded_and_continued(
    tmp_path: Path, failing_role: str
) -> None:
    def response(request):
        if request.call_kind == failing_role:
            raise _provider_failure("RESPONSE_INCOMPLETE_MAX_OUTPUT_TOKENS")
        if request.call_kind == "decompose":
            return _valid_decomposition()
        if request.call_kind == "solve":
            return json.dumps(
                {"tool": "complete_subtask", "arguments": {"evidence": "done"}}
            )
        return _valid_extraction()

    backend, request, grader = _diagnostic_backend_for_gateway(
        tmp_path, ReplayModelGateway(response)
    )
    cell = backend.execute_cell(
        request, resume=False, journal_root=tmp_path / failing_role
    )
    assert grader.calls == 1
    assert cell["terminal_reason_code"] == "MODEL_FAILURE_CONTINUED_TO_GRADER"
    assert cell["official_grader_resolved"] is False
    assert cell["diagnostic_resolved"] is False
    assert cell["model_failure_code"]


def test_extraction_failure_is_separate_and_preserves_official_pass(
    tmp_path: Path,
) -> None:
    solve_calls = 0

    def response(request):
        nonlocal solve_calls
        if request.call_kind == "decompose":
            return _valid_decomposition()
        if request.call_kind == "extract":
            raise _provider_failure("RESPONSE_REFUSAL")
        solve_calls += 1
        if solve_calls == 1:
            return json.dumps(
                {
                    "tool": "write_file",
                    "arguments": {"path": "value.py", "content": "VALUE = 2\n"},
                }
            )
        return json.dumps(
            {"tool": "complete_subtask", "arguments": {"evidence": "updated"}}
        )

    backend, request, grader = _diagnostic_backend_for_gateway(
        tmp_path, ReplayModelGateway(response)
    )
    cell = backend.execute_cell(
        request, resume=False, journal_root=tmp_path / "extract-failure"
    )
    assert grader.calls == 1
    assert cell["official_grader_resolved"] is True
    assert cell["diagnostic_resolved"] is False
    assert cell["terminal_reason_code"] == "EXTRACTION_FAILURE_AFTER_OFFICIAL_GRADE"
    assert cell["model_failure_code"] is None
    assert cell["extraction_status"] == "MEMORY_EXTRACTION_FAILED"
    assert cell["extraction_failure_code"] == "RESPONSE_REFUSAL"


class _DecompositionPreflightGateway:
    def __init__(self) -> None:
        self.provider_calls = 0

    def preview_reservation(self, request):
        if request.call_kind == "decompose":
            raise ModelPreflightFailure("TASK_INPUT_CONTEXT_BUDGET_EXCEEDED")
        return None

    def invoke(self, request):
        self.provider_calls += 1
        if request.call_kind == "extract":
            return GatewayResponse(
                text=_valid_extraction(), provider="fixture", model="fixture",
                input_tokens=3, output_tokens=1, wall_time_ms=1, paid=False,
            )
        raise AssertionError("unexpected provider call")


def test_decomposition_preflight_failure_records_zero_decomposition_calls(
    tmp_path: Path,
) -> None:
    gateway = _DecompositionPreflightGateway()
    backend, request, grader = _diagnostic_backend_for_gateway(tmp_path, gateway)
    cell = backend.execute_cell(
        request, resume=False, journal_root=tmp_path / "preflight-failure"
    )
    assert grader.calls == 1
    assert gateway.provider_calls == 1  # extraction only; decompose never transmitted
    assert cell["accounting"]["decomposition_calls"] == 0
    assert cell["accounting"]["extraction_calls"] == 1
    assert cell["model_failure_code"] == "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED"


def test_step_cap_and_extraction_failure_are_orthogonal_and_next_cell_runs(
    tmp_path: Path,
) -> None:
    def response(request):
        if request.call_kind == "decompose":
            return _valid_decomposition()
        if request.call_kind == "solve":
            return json.dumps(
                {"tool": "read_file", "arguments": {"path": "value.py"}}
            )
        raise _provider_failure("RESPONSE_REFUSAL")

    backend, request, grader = _diagnostic_backend_for_gateway(
        tmp_path, ReplayModelGateway(response)
    )
    first = backend.execute_cell(
        request, resume=False, journal_root=tmp_path / "combined-first"
    )
    assert first["terminal_reason_code"] == "PER_SUBTASK_STEP_CAP_REACHED"
    assert first["model_failure_code"] is None
    assert first["extraction_status"] == "MEMORY_EXTRACTION_FAILED"
    assert first["extraction_failure_code"] == "RESPONSE_REFUSAL"
    assert first["official_grader_resolved"] is False
    assert first["diagnostic_resolved"] is False

    contract = backend.contract
    second_request = executor.build_cell_requests(
        contract, execution_identity_sha256=EXECUTION_IDENTITY_SHA256
    )[1]
    second = backend.execute_cell(
        second_request, resume=False, journal_root=tmp_path / "combined-second"
    )
    assert second["terminal"] is True
    assert grader.calls == 2


class _UnitEmbedder:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def provenance(self):
        return {
            "model_id": "fixture-model",
            "revision": "fixture-revision",
            "dimensions": 384,
            "normalized": True,
            "production": True,
        }

    def embed(self, _text):
        self.calls += 1
        if self.fail:
            raise RuntimeError("lazy load failed")
        return (1.0,) + (0.0,) * 383


def test_embedder_prewarm_persists_hash_and_fails_before_any_spend(
    tmp_path: Path,
) -> None:
    lock = {
        "model_id": "fixture-model",
        "revision": "fixture-revision",
        "dimension": 384,
    }
    evidence = tmp_path / "control" / "embedder.json"
    embedder = _UnitEmbedder()
    digest = executor.prewarm_production_embedder(
        embedder, evidence_path=evidence, expected_lock=lock, resume=False
    )
    assert digest == executor.hashlib.sha256(evidence.read_bytes()).hexdigest()
    assert executor.prewarm_production_embedder(
        embedder, evidence_path=evidence, expected_lock=lock, resume=True
    ) == digest
    failing = _UnitEmbedder(fail=True)
    with pytest.raises(executor.DiagnosticExecutorError, match="prewarm failed"):
        executor.prewarm_production_embedder(
            failing,
            evidence_path=tmp_path / "failed.json",
            expected_lock=lock,
            resume=False,
        )
    assert failing.calls == 1
    assert not (tmp_path / "failed.json").exists()


def test_exact_retrieval_rehearsal_exercises_all_12_c1_c2_routes(
    tmp_path: Path,
) -> None:
    contract, payloads, tasks = _production_wiring_fixture()
    requests = executor.build_cell_requests(
        contract, execution_identity_sha256=EXECUTION_IDENTITY_SHA256
    )
    evidence = tmp_path / "control" / "retrieval-rehearsal.json"
    embedder = _UnitEmbedder()
    digest = executor.rehearse_production_retrieval(
        contract=contract,
        requests=requests,
        tasks_by_target_id=tasks,
        repository_root=ROOT,
        payload_bytes=payloads,
        retrieval_config=_selected_recall_config(),
        embedder=embedder,
        embedder_preflight_sha256="4" * 64,
        retrieval_policy_raw_sha256=(
            "1985ca2cceaa6ebdc02d4bd320b318a47a8144f64bde5ad0da8367c777d3d85c"
        ),
        evidence_path=evidence,
        resume=False,
    )
    document = diagnostic.strict_json_load(evidence)
    assert digest == executor.hashlib.sha256(evidence.read_bytes()).hexdigest()
    assert document["status"] == "PASS_ALL_12_EXACT_READER_ROUTES"
    assert document["target_count"] == 12
    assert all(
        row["forced_safe_top1"]["candidate_count_after_filter"] == 1
        and row["forced_safe_top1"]["final_reason_code"] == "INJECTED"
        and row["forced_injection_sha256"] == row["execution_view_sha256"]
        and row["forced_injection_bytes"] == row["execution_view_bytes"]
        for row in document["targets"]
    )
    assert executor.rehearse_production_retrieval(
        contract=contract,
        requests=requests,
        tasks_by_target_id=tasks,
        repository_root=ROOT,
        payload_bytes=payloads,
        retrieval_config=_selected_recall_config(),
        embedder=embedder,
        embedder_preflight_sha256="4" * 64,
        retrieval_policy_raw_sha256=(
            "1985ca2cceaa6ebdc02d4bd320b318a47a8144f64bde5ad0da8367c777d3d85c"
        ),
        evidence_path=evidence,
        resume=True,
    ) == digest


def test_retrieval_rehearsal_failure_precedes_ledger_and_paid_gateway(
    tmp_path: Path,
) -> None:
    contract, payloads, tasks = _production_wiring_fixture()
    requests = executor.build_cell_requests(
        contract, execution_identity_sha256=EXECUTION_IDENTITY_SHA256
    )

    def broken_retriever(*_args, **_kwargs):
        raise RuntimeError("ranker construction failed")

    evidence = tmp_path / "retrieval-rehearsal.json"
    with pytest.raises(
        executor.DiagnosticExecutorError, match="failed before spend"
    ):
        executor.rehearse_production_retrieval(
            contract=contract,
            requests=requests,
            tasks_by_target_id=tasks,
            repository_root=ROOT,
            payload_bytes=payloads,
            retrieval_config=_selected_recall_config(),
            embedder=_UnitEmbedder(),
            embedder_preflight_sha256="4" * 64,
            retrieval_policy_raw_sha256="5" * 64,
            evidence_path=evidence,
            resume=False,
            retriever_factory=broken_retriever,
        )
    assert not evidence.exists()

    production_source = inspect.getsource(
        executor.prepare_official_production_execution
    )
    assert production_source.index("prewarm_production_embedder(") < (
        production_source.index("rehearse_production_retrieval(")
    ) < production_source.index("raw_ledger = benchmark.AtomicBudgetLedger(")
    assert production_source.index("rehearse_production_retrieval(") < (
        production_source.index("benchmark.build_paid_model_gateway(")
    )


def test_paid_openai_transport_does_not_trust_host_proxy_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    observed = {}

    class Client:
        async def aclose(self):
            return None

    client = Client()

    def client_factory(**kwargs):
        observed.update(kwargs)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    ):
        monkeypatch.setenv(name, "poisoned-host-routing")
    gateway, actual_client = benchmark.build_paid_model_gateway(
        SimpleNamespace(coroutine_runner=lambda coroutine: coroutine),
        object(),
        benchmark.read_json(ROOT / "configs/trimem_v1/model_lock.json"),
        stream_id="C0",
        restricted_response_root=tmp_path / "provider-evidence",
    )
    assert gateway is not None
    assert actual_client is client
    assert observed == {"trust_env": False}


def _zero_model_ledger_fixture(tmp_path: Path, *, leave_reserved: bool = False):
    contract = _execution_contract()
    requests = executor.build_cell_requests(
        contract, execution_identity_sha256=EXECUTION_IDENTITY_SHA256
    )
    caps = dict(contract.policy["hard_caps"])
    raw = benchmark.AtomicBudgetLedger(
        tmp_path / "budget-ledger.json",
        approval_digest=EXECUTION_IDENTITY_SHA256,
        caps=executor._DiagnosticCapMapping(caps),
        pricing={
            "input_per_million_tokens_usd": 0.75,
            "cached_input_per_million_tokens_usd": 0.075,
            "output_per_million_tokens_usd": 4.5,
        },
    )
    ledger = executor.DiagnosticAtomicBudgetLedger(
        raw, approved_hard_caps=caps
    )
    fake = _FakeCellExecutor()
    cells = []
    for offset, request in enumerate(requests):
        key = (
            f"{request['experiment_id']}:{request['runtime_arm']}:"
            f"{request['target_id']}"
        )
        reservation = raw.reserve_task_arm(key)
        if not leave_reserved or offset != 35:
            raw.complete_task_arm(
                key,
                reservation,
                status=benchmark.SCIENTIFIC_LEDGER_TERMINAL_STATUS,
                container_started=True,
            )
        cell = fake.execute_cell(
            request,
            resume=False,
            journal_root=tmp_path / "fake" / str(offset),
        )
        for field in (
            "decomposition_calls", "solve_calls", "extraction_calls",
            "input_tokens", "cached_input_tokens", "output_tokens",
            "paid_model_calls", "model_wall_time_ms", "tool_wall_time_ms",
        ):
            cell["accounting"][field] = 0
        cell["accounting"]["total_usd"] = "0.000000000000"
        cells.append(cell)
    return caps, raw, ledger, requests, cells


def test_diagnostic_ledger_preserves_approved_cap_identity_and_finalizes_36(
    tmp_path: Path,
) -> None:
    caps, raw, ledger, requests, cells = _zero_model_ledger_fixture(tmp_path)
    assert raw.approved_hard_cap == caps
    assert "benchmark_grader_containers" not in raw.approved_hard_cap
    assert raw.caps["grader_containers"] == caps["grader_containers"]
    report = ledger.finalize_diagnostic(requests=requests, cells=cells)
    assert report["status"] == "PASS_EXACT_36_TERMINAL_RECONCILED"
    assert report["actual"]["task_arm_runs"] == 36
    assert report["actual"]["grader_containers"] == 36

    cells[0]["accounting"]["paid_model_calls"] = 1
    with pytest.raises(executor.DiagnosticExecutorError, match="ledger/cell"):
        ledger.finalize_diagnostic(requests=requests, cells=cells)


def test_diagnostic_ledger_rejects_nonterminal_task_or_outstanding_capacity(
    tmp_path: Path,
) -> None:
    _caps, _raw, ledger, requests, cells = _zero_model_ledger_fixture(
        tmp_path, leave_reserved=True
    )
    with pytest.raises(executor.DiagnosticExecutorError, match="not terminal"):
        ledger.finalize_diagnostic(requests=requests, cells=cells)


def test_preinitialized_binding_allows_preparation_files_before_execute(
    tmp_path: Path,
) -> None:
    contract = _execution_contract()
    output = tmp_path / "production-order"
    executor.initialize_execution_binding(
        contract=contract,
        capabilities=_test_capabilities(),
        output_root=output,
        execution_identity_sha256=EXECUTION_IDENTITY_SHA256,
        resume=False,
        allow_test_executor=True,
    )
    (output / "budget-ledger.json").write_text("preparation", encoding="utf-8")
    outcome = executor.execute_diagnostic(
        contract=contract,
        executor=_FakeCellExecutor(),
        output_root=output,
        execution_identity_sha256=EXECUTION_IDENTITY_SHA256,
        allow_test_executor=True,
        preinitialized_binding=True,
    )
    assert outcome.completed_cell_count == 36


class _ProductionShapedFinalizingExecutor(_FakeCellExecutor):
    def capabilities(self) -> dict:
        return executor.production_capabilities("credential-free-finalizer-fixture")

    def finalize_matrix(self, *, requests, cells, output_root, resume):
        assert len(requests) == len(cells) == 36
        report = {
            "schema": "fixture/ledger-finalization/1.0",
            "status": "PASS",
        }
        path = output_root / "control" / "ledger-finalization.json"
        executor._atomic_write_json(path, report)
        return {"evidence_sha256": executor.hashlib.sha256(path.read_bytes()).hexdigest()}


def test_production_finalization_hash_reaggregates_byte_identically(
    tmp_path: Path,
) -> None:
    contract = _execution_contract()
    outcome = executor.execute_diagnostic(
        contract=contract,
        executor=_ProductionShapedFinalizingExecutor(),
        output_root=tmp_path / "finalized",
        execution_identity_sha256=EXECUTION_IDENTITY_SHA256,
    )
    digest = outcome.result["atomic_budget_ledger_finalization_sha256"]
    assert outcome.aggregate["atomic_budget_ledger_finalization_sha256"] == digest
    recomputed = diagnostic.aggregate_results(
        outcome.result,
        contract.manifest,
        contract.policy,
        source_bank_sha256=contract.source_bank_manifest_sha256,
    )
    assert diagnostic.canonical_bytes(recomputed) == diagnostic.canonical_bytes(
        dict(outcome.aggregate)
    )


def test_partial_image_materialization_rolls_back_attempted_set_and_cleanup_is_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import trimem_pull_locked_images as puller

    monkeypatch.setattr(executor, "ROOT", tmp_path)
    contract = _execution_contract()
    selected = [
        f"registry.example/image-{index}@sha256:{str(index + 1) * 64}"
        for index in range(3)
    ]
    images = {
        target["instance_id"]: {
            "image": selected[target["order_index"] % 3],
            "harness_image_tag": f"fixture:{target['order_index']}",
        }
        for target in contract.manifest["targets"]
    }
    monkeypatch.setattr(
        executor,
        "_expected_diagnostic_images",
        lambda _contract: (images, [], selected),
    )
    removed = []

    def pull(image, _root, index):
        if index == 1:
            raise RuntimeError("inspect failed after pull")
        return {"image": image, "status": "PASS"}

    def remove(reference, _root, _index):
        removed.append(reference)
        return {"reference": reference, "status": "REMOVED"}

    monkeypatch.setattr(puller, "pull_and_observe_image", pull)
    monkeypatch.setattr(puller, "_cleanup_reference", remove)
    root = tmp_path / "materialization"
    with pytest.raises(executor.DiagnosticExecutorError, match="rolled back"):
        executor.materialize_diagnostic_images(
            contract=contract,
            approval_artifact_sha256=EXECUTION_IDENTITY_SHA256,
            evidence_root=root,
        )
    assert selected[1] in removed and selected[0] in removed
    failure = diagnostic.strict_json_load(root / "failure-report.json")
    assert failure["status"] == "ROLLED_BACK_EXACT_ATTEMPTED_SET"
    cleanup = executor.cleanup_diagnostic_images(
        contract=contract,
        image_materialization_report=root / "report.json",
        evidence_root=tmp_path / "cleanup",
    )
    assert cleanup["status"] == "PASS_ALREADY_ROLLED_BACK"
    removed_at_failure = len(removed)
    assert len(removed) == removed_at_failure


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [
        (1, b""),
        (0, json.dumps(["registry.example/image@sha256:" + "b" * 64]).encode()),
    ],
)
def test_live_image_reinspection_fails_closed_on_missing_or_drifted_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: bytes,
) -> None:
    import trimem_pull_locked_images as puller

    image = "registry.example/image@sha256:" + "a" * 64
    monkeypatch.setattr(
        executor,
        "_expected_diagnostic_images",
        lambda _contract: ({}, [], [image]),
    )
    monkeypatch.setattr(
        puller,
        "_run",
        lambda *_args: (
            SimpleNamespace(returncode=returncode, stdout=stdout),
            {"stdout": {"sha256": "1" * 64}, "stderr": {"sha256": "2" * 64}},
        ),
    )
    with pytest.raises(executor.DiagnosticExecutorError, match="live diagnostic image"):
        executor.reinspect_diagnostic_images(
            contract=_execution_contract(),
            approval_artifact_sha256=EXECUTION_IDENTITY_SHA256,
            evidence_root=tmp_path / "live",
        )


def test_executor_boundary_rechecks_current_openai_key_commitment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = _execution_contract()
    now = datetime.now(timezone.utc)
    repository = "Scuttie/enterprise-shared-memory-poc"
    run_id = 123456
    head = "a" * 40
    document = approval_builder.build_approval_document(
        diagnostic_id=contract.manifest["diagnostic_id"],
        repository=repository,
        git_head=head,
        workflow_run_id=run_id,
        matrix_raw_sha256=contract.matrix_raw_sha256,
        policy_raw_sha256=contract.policy_raw_sha256,
        source_bank_manifest_sha256=contract.source_bank_manifest_sha256,
        model_id=contract.policy["frozen_inputs"]["model_lock"]["model_id"],
        hard_caps=contract.policy["hard_caps"],
        approval_actor="fixture-approver",
        approval_nonce="e" * 32,
        approved_at_utc=now.isoformat().replace("+00:00", "Z"),
        expires_at_utc=(now + timedelta(hours=1)).isoformat().replace(
            "+00:00", "Z"
        ),
        openai_api_key=TEST_API_KEY,
    )
    path = tmp_path / "approval.json"
    path.write_bytes(activation_gate.canonical_approval_bytes(document))
    monkeypatch.setattr(activation_gate, "_git_head", lambda _root: head)
    monkeypatch.setenv("OPENAI_API_KEY", TEST_API_KEY + "-wrong")
    with pytest.raises(executor.DiagnosticExecutorError, match="credential"):
        executor.load_and_validate_materialized_approval(
            contract=contract,
            approval_path=path,
            repository=repository,
            workflow_run_id=run_id,
            workflow_run_attempt=2,
            workflow_event="push",
            now=now,
            verify_openai_credential=True,
        )
    monkeypatch.setenv("OPENAI_API_KEY", TEST_API_KEY)
    approval, _digest = executor.load_and_validate_materialized_approval(
        contract=contract,
        approval_path=path,
        repository=repository,
        workflow_run_id=run_id,
        workflow_run_attempt=2,
        workflow_event="push",
        now=now,
        verify_openai_credential=True,
    )
    assert approval["approved_model_id"].endswith("2026-03-17")

    path.write_bytes(json.dumps(document, indent=2).encode("utf-8"))
    with pytest.raises(executor.DiagnosticExecutorError, match="not canonical"):
        executor.load_and_validate_materialized_approval(
            contract=contract,
            approval_path=path,
            repository=repository,
            workflow_run_id=run_id,
            workflow_run_attempt=2,
            workflow_event="push",
            now=now,
            verify_openai_credential=True,
        )


@pytest.mark.parametrize("resume", [False, True])
def test_execute_cli_establishes_binding_before_prepare_and_passes_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resume: bool
) -> None:
    contract = _execution_contract()
    calls = []
    fake_backend = object()
    monkeypatch.setattr(executor, "load_execution_contract", lambda *_a, **_k: contract)
    monkeypatch.setattr(
        executor,
        "load_and_validate_materialized_approval",
        lambda **kwargs: (
            calls.append(("approval", kwargs))
            or ({"hard_caps": contract.policy["hard_caps"]}, EXECUTION_IDENTITY_SHA256)
        ),
    )
    monkeypatch.setattr(
        executor,
        "initialize_execution_binding",
        lambda **kwargs: calls.append(("binding", kwargs)) or {},
    )
    monkeypatch.setattr(
        executor,
        "prepare_official_production_execution",
        lambda **kwargs: (
            calls.append(("prepare", kwargs))
            or executor.PreparedProductionExecution(
                executor=fake_backend,
                execution_identity_sha256=EXECUTION_IDENTITY_SHA256,
                approval={},
                embedder_preflight_sha256="1" * 64,
                retrieval_rehearsal_sha256="3" * 64,
                image_reinspection_sha256="2" * 64,
                solver_sandbox_rehearsal_sha256="4" * 64,
            )
        ),
    )
    monkeypatch.setattr(
        executor,
        "execute_diagnostic",
        lambda **kwargs: (
            calls.append(("execute", kwargs))
            or executor.ExecutionOutcome(
                result={},
                aggregate={"status": "COMPLETE_36_OF_36_OFFICIAL_CELLS"},
                completed_cell_count=36,
                resumed_cell_count=0,
            )
        ),
    )
    output = ROOT / "artifacts" / "trimem_v1" / "dev_activation_diagnostic" / "cli-test"
    argv = [
        "execute", "--approval-file", str(tmp_path / "approval.json"),
        "--repository", "Scuttie/enterprise-shared-memory-poc",
        "--workflow-run-id", "1", "--workflow-run-attempt", "2",
        "--workflow-event", "push", "--output-root", str(output),
        "--workspace-root", ".trimem-exec/devdiag-workspaces",
    ]
    if resume:
        argv.append("--resume")
    assert executor.main(argv) == 0
    assert [name for name, _kwargs in calls] == [
        "approval", "binding", "prepare", "execute"
    ]
    assert calls[0][1]["verify_openai_credential"] is True
    assert calls[1][1]["resume"] is resume
    assert calls[2][1]["workspace_root"] == Path(
        ".trimem-exec/devdiag-workspaces"
    )
    assert calls[2][1]["resume"] is resume
    assert calls[3][1]["preinitialized_binding"] is True
