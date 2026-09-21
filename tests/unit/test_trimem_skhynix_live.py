"""Scientific aggregation, real-source wiring, and pre-spend pilot checks."""
from __future__ import annotations

from decimal import Decimal
import io
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_benchmark_run as benchmark
import trimem_skhynix_live as live
import trimem_skhynix_source_bank as sources
from enterprise_memory.trimem.agent_runtime import CodingTask, NoMemoryController
from enterprise_memory.trimem.arms import ActiveNodeTriMemController
from enterprise_memory.trimem.ppr import DeterministicHashEmbedder
from enterprise_memory.trimem.skill_runtime import SkillFirstMemoryController


def plan(count=12):
    return {"schema": live.SCHEMA, "arms": list(live.ARMS),
            "targets": [{"target_id": f"target-{i}"} for i in range(count)]}


def cell(arm, target, resolved=False, **changes):
    value = {
        "arm": arm, "target_id": target, "resolved": resolved,
        "official": True, "status": "AGENT_COMPLETED",
        "grader_status": "success", "container_started": True,
        "accounting": {"paid_model_calls": 3, "input_tokens": 100, "output_tokens": 50},
        "usd": "0.001", "injections": 0,
    }
    value.update(changes)
    return value


def test_complete_rates_are_paired_and_report_exact_delta_and_pvalue():
    rows = [cell(arm, f"target-{i}", resolved=(arm == "SKHYNIX" and i < 3))
            for i in range(12) for arm in live.ARMS]
    report = live.aggregate(plan(), rows, status="COMPLETE")
    assert report["completed_cells"] == report["planned_cells"] == 36
    assert report["arms"]["SKHYNIX"]["paired_resolved"] == 3
    assert report["arms"]["SKHYNIX"]["paired_solve_rate"] == 0.25
    assert report["arms"]["NO_MEMORY"]["paired_solve_rate"] == 0
    for comparison in report["contrasts"]:
        assert comparison["paired_n"] == 12
        assert comparison["delta_percentage_points"] == 25
        assert comparison["fail_to_pass"] == 3
        assert comparison["pass_to_fail"] == 0
        assert comparison["mcnemar_exact_two_sided_p"] == 0.25
    assert report["arms"]["SKHYNIX"]["usd"] == "0.012"
    assert report["arms"]["SKHYNIX"]["model_calls"] == 36
    assert report["skill_library_entries"] == 0


def test_incomplete_cells_do_not_become_invented_failures_or_unpaired_controls():
    rows = [cell(arm, "target-0", resolved=(arm == "SKHYNIX")) for arm in live.ARMS]
    rows += [cell("NO_MEMORY", "target-1", resolved=True)]
    report = live.aggregate(plan(2), rows, status="INCOMPLETE")
    assert report["completed_cells"] == 4
    assert report["fully_paired_target_ids"] == ["target-0"]
    baseline = report["arms"]["NO_MEMORY"]
    assert baseline["completed"] == 2 and baseline["completed_resolved"] == 1
    assert baseline["paired_targets"] == 1 and baseline["paired_resolved"] == 0
    assert baseline["paired_solve_rate"] == 0
    assert report["contrasts"][0]["delta_percentage_points"] == 100


def test_no_complete_triplet_means_no_claimed_solve_rate():
    report = live.aggregate(plan(2), [cell("NO_MEMORY", "target-0", True)], status="INCOMPLETE")
    assert report["fully_paired_target_ids"] == []
    assert all(row["paired_solve_rate"] is None for row in report["arms"].values())
    assert all(row["delta_percentage_points"] is None for row in report["contrasts"])
    assert all(row["mcnemar_exact_two_sided_p"] is None for row in report["contrasts"])


@pytest.mark.parametrize("changes", [
    {"official": False}, {"official": 1}, {"resolved": 1}, {"resolved": None},
    {"target_id": "unregistered-target"}, {"arm": "REPLAY"},
])
def test_only_expected_official_boolean_outcomes_are_eligible(changes):
    row = cell("NO_MEMORY", "target-0")
    row.update(changes)
    with pytest.raises(ValueError):
        live.aggregate(plan(1), [row], status="INCOMPLETE")


@pytest.mark.parametrize("status", ["INFRA_FAILURE", "INFRASTRUCTURE_FAILURE", "NOT_EXECUTED"])
def test_infrastructure_status_cannot_be_presented_as_a_failed_solution(status):
    with pytest.raises(ValueError):
        live.aggregate(plan(1), [cell("NO_MEMORY", "target-0", status=status)], status="INCOMPLETE")


def test_duplicate_result_cells_are_rejected():
    row = cell("NO_MEMORY", "target-0")
    with pytest.raises(ValueError):
        live.aggregate(plan(1), [row, row], status="INCOMPLETE")


def test_duplicate_planned_targets_cannot_inflate_the_denominator():
    value = plan(1)
    value["targets"] *= 2
    with pytest.raises(ValueError):
        live.aggregate(value, [cell(arm, "target-0") for arm in live.ARMS], status="INCOMPLETE")


def test_complete_status_requires_every_planned_official_cell():
    with pytest.raises(ValueError):
        live.aggregate(plan(1), [cell("NO_MEMORY", "target-0")], status="COMPLETE")


def test_wilson_intervals_handle_no_observations_and_boundaries():
    assert live.wilson(0, 0) is None
    assert live.wilson(0, 12) == pytest.approx([0, 0.24249400665524085])
    assert live.wilson(12, 12) == pytest.approx([0.7575059933447592, 1])


@pytest.mark.parametrize("usd", [0, -1, 5.00001, "nan", "inf", "-inf"])
def test_pilot_budget_rejects_nonpositive_nonfinite_and_over_five_dollars(usd):
    with pytest.raises(ValueError):
        live.budget_caps(36, usd)


@pytest.mark.parametrize("count", [0, -1, 3.5, True])
def test_budget_cell_count_must_be_a_positive_integer(count):
    with pytest.raises(ValueError):
        live.budget_caps(count, 5)


def test_budget_roles_add_up_and_real_ledger_accepts_exact_pricing(tmp_path):
    caps = live.budget_caps(36, 5)
    limits = live.runtime_lock().limits
    assert caps["model_calls"] == caps["paid_model_calls"] == (
        caps["solve_calls"] + caps["decomposition_calls"] + caps["extraction_calls"])
    assert caps["solve_calls"] == 36 * limits.max_solve_calls
    assert caps["decomposition_calls"] == 36 * limits.max_decomposition_calls
    assert caps["extraction_calls"] == 36 * limits.max_extraction_calls
    assert caps["task_arm_runs"] == caps["benchmark_grader_containers"] == 36
    expected = (Decimal(caps["input_tokens"]) * Decimal("0.75") +
                Decimal(caps["output_tokens"]) * Decimal("4.5")) / Decimal(1_000_000)
    assert Decimal(str(caps["uncached_token_cost_ceiling_usd"])) == expected
    ledger = benchmark.AtomicBudgetLedger(tmp_path / "ledger.json", approval_digest="a" * 64,
                                         caps=caps, pricing=live.PRICING)
    assert ledger._read()["actual"]["paid_model_calls"] == 0
    assert ledger._read()["caps"]["total_usd"] == 5


def test_real_ledger_blocks_request_above_remaining_dollar_budget_before_calls(tmp_path):
    caps = live.budget_caps(3, 0.001)
    ledger = benchmark.AtomicBudgetLedger(tmp_path / "ledger.json", approval_digest="b" * 64,
                                         caps=caps, pricing=live.PRICING)
    key = "pilot:M0:target-0"
    ledger.reserve_task_arm(key)
    with pytest.raises(benchmark.ModelPreflightFailure):
        ledger.preview_reservation("pilot:decompose:0001", request_sha256="c" * 64,
                                   task_arm_key=key, call_kind="decompose",
                                   input_upper_bound=1_000, output_cap=4_096)
    assert ledger._read()["actual"]["paid_model_calls"] == 0
    assert ledger._read()["outstanding"]["paid_model_calls"] == 0


@pytest.fixture(scope="module")
def bank():
    return sources.load_validated_source_bank(ROOT)


@pytest.mark.parametrize("index", [0, 6])
def test_controller_wiring_preserves_real_source_content_and_language(bank, tmp_path, monkeypatch, index):
    import enterprise_memory.trimem.ppr as ppr
    monkeypatch.setattr(ppr, "PinnedSentenceTransformerPPR", lambda: DeterministicHashEmbedder(384))
    cache = json.loads((ROOT / sources.historical.CHRONOLOGY_PATH).read_text(encoding="utf-8"))
    public = cache["targets"][index]
    target = bank.targets_by_id[public["target_id"]]
    task = CodingTask(task_id=public["target_id"], org_id="live-pilot", user_id="reader",
                      repository=target["repository"], commit=target["base_commit"],
                      instruction=public["public_instruction"], files={}, editable_paths=())
    baseline, old_store, _ = live._controller("EXISTING_M2", task, bank, tmp_path / "old")
    treatment, store, report = live._controller("SKHYNIX", task, bank, tmp_path / "new")
    assert isinstance(baseline, ActiveNodeTriMemController)
    assert old_store is None
    with store:
        assert isinstance(treatment, SkillFirstMemoryController)
        assert treatment.language == target["language"]
        snap = store.snapshot(org_id=task.org_id, user_id=task.user_id, repository=task.repository,
                              revision=task.commit, language=target["language"])
        assert {row.content.encode("utf-8") for row in snap.repository_knowledge} == set(baseline.retriever.store.execution_views.values())
        assert report["verified_skill_count"] == report["imported_episode_count"] == 0
    no_memory, empty_store, empty_report = live._controller("NO_MEMORY", task, bank, tmp_path / "empty")
    assert isinstance(no_memory, NoMemoryController)
    assert empty_store is None and empty_report["records"] == 0


def test_unknown_arm_is_rejected_before_embedding_or_source_loading(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "build_legacy_source_store", lambda *a, **kw: pytest.fail("unknown arm reached source loading"))
    with pytest.raises(ValueError):
        live._controller("MISTYPED_ARM", object(), object(), tmp_path)


def test_missing_credential_is_rejected_without_constructing_a_paid_client(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(live.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"")))
    monkeypatch.setattr(benchmark, "build_paid_model_gateway", lambda *a, **kw: pytest.fail("paid client constructed"))
    with pytest.raises(ValueError):
        live._load_key_stdin()
    assert "OPENAI_API_KEY" not in live.os.environ
