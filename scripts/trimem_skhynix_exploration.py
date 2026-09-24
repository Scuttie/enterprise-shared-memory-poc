"""Evaluate visible exploration budgets and repeated-read guidance with real graders.

This is an exploratory experiment. It does not reuse an old execution approval
or modify the frozen historical campaign. Only public DEV inputs reach models.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

ARMS = ("NO_MEMORY", "EXISTING_M2", "SKHYNIX")
SCHEMA = "skhynix/local-dev-comparison/1.0"
EXPERIMENT_ID = "skhynix-dev-live-002"
PREVIOUS_PLAN_SHA256 = "a7e499d01263564cba3fa9183b0872778e0306ae78431cfdb9117face9176722"
PREVIOUS_REPORT_SHA256 = "a6fde126cdd0e545e6e478ce4740b7038803df10052ee23433e9f8439cba46e0"
MODEL = "gpt-5.4-mini-2026-03-17"
PRICING = {"model_id": MODEL, "input_per_million_tokens_usd": 0.75,
           "cached_input_per_million_tokens_usd": 0.075,
           "output_per_million_tokens_usd": 4.5}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    from trimem_benchmark_run import write_json as atomic_write_json
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, value)


def source_hashes():
    paths = list((ROOT / "src/enterprise_memory").rglob("*.py"))
    paths += list((ROOT / "scripts").glob("*.py"))
    paths += [ROOT / "configs/trimem_v1/model_lock.json",
              ROOT / "configs/trimem_v1/m2_candidates/recall.json",
              ROOT / "artifacts/trimem_v1/freeze.json"]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def runtime_lock():
    from enterprise_memory.trimem.adaptive_horizon import AdaptiveHorizonPolicy
    from trimem_m2_candidates import runtime_lock_for
    prior = runtime_lock_for("recall")
    limits = replace(prior.limits, max_steps_per_subtask=24, max_solve_calls=48, max_agent_steps=48)
    return replace(prior, limits=limits, adaptive_horizon=AdaptiveHorizonPolicy(enabled=False))


def exploration_policy():
    from enterprise_memory.trimem.exploration_runtime import ExplorationPolicy
    return ExplorationPolicy()


def prior_evidence():
    path = ROOT / "artifacts/skhynix_v1/live_001/report.json"
    report = read_json(path)
    if (report["status"] != "COMPLETE" or report["completed_cells"] != 36 or
            report["plan_sha256"] != PREVIOUS_PLAN_SHA256 or
            hashlib.sha256(path.read_bytes()).hexdigest() != PREVIOUS_REPORT_SHA256):
        raise ValueError("previous experiment evidence differs")
    if digest(read_json(path.with_name("plan.json"))) != PREVIOUS_PLAN_SHA256:
        raise ValueError("previous experiment plan differs")
    return {"report_path": path.relative_to(ROOT).as_posix(),
            "report_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "plan_sha256": PREVIOUS_PLAN_SHA256,
            "interpretation": "Historical same-target comparison; runtime budgets and guidance changed together."}


def verify_exploration_plan(plan):
    if (plan.get("experiment_id") != EXPERIMENT_ID or
            plan.get("exploration_policy") != exploration_policy().manifest() or
            plan.get("previous_run") != prior_evidence()):
        raise ValueError("exploration policy or historical binding differs")
    previous = read_json(ROOT / "artifacts/skhynix_v1/live_001/plan.json")
    if (plan["targets"] != previous["targets"] or plan["model_lock"] != previous["model_lock"] or
            plan["pricing"] != previous["pricing"] or plan["source_bank_file_sha256"] != previous["source_bank_file_sha256"]):
        raise ValueError("paired reevaluation target, model, pricing or bank changed")


def require_fresh_roots(output, workspace):
    for path in (Path(output).resolve(), Path(workspace).resolve()):
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            raise ValueError("new experiment requires empty output and workspace roots")



def budget_caps(cell_count, usd_cap):
    if type(cell_count) is not int or cell_count <= 0:
        raise ValueError("cell count must be positive")
    cost = Decimal(str(usd_cap))
    if not cost.is_finite() or not 0 < cost <= 10:
        raise ValueError("this pilot is limited to a maximum of US$10 (default US$5)")
    limits = runtime_lock().limits
    calls_per_cell = limits.max_solve_calls + limits.max_decomposition_calls + limits.max_extraction_calls
    input_cap = cell_count * calls_per_cell * 262_000
    output_cap = cell_count * limits.max_total_output_tokens_per_task_arm
    uncached = (Decimal(input_cap) * Decimal("0.75") + Decimal(output_cap) * Decimal("4.5")) / 1_000_000
    return {
        "paid_model_calls": cell_count * calls_per_cell,
        "model_calls": cell_count * calls_per_cell,
        "solve_calls": cell_count * limits.max_solve_calls,
        "decomposition_calls": cell_count * limits.max_decomposition_calls,
        "extraction_calls": cell_count * limits.max_extraction_calls,
        "input_tokens": input_cap, "output_tokens": output_cap,
        "total_usd": float(cost), "uncached_token_cost_ceiling_usd": float(uncached),
        "task_arm_runs": cell_count, "benchmark_grader_containers": cell_count,
        "max_input_tokens_per_task_arm": calls_per_cell * 262_000,
        "max_model_calls_per_task_arm": calls_per_cell,
    }


def wilson(successes, count):
    if not count:
        return None
    z = 1.959963984540054
    p = successes / count
    denominator = 1 + z * z / count
    center = (p + z * z / (2 * count)) / denominator
    half = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [max(0.0, center - half), min(1.0, center + half)]


def aggregate(plan, cells, *, status, ledger=None):
    """Never count an unexecuted/infra-failed cell as an incorrect solution."""
    target_ids = [target["target_id"] for target in plan["targets"]]
    if len(set(target_ids)) != len(target_ids):
        raise ValueError("duplicate planned target")
    by_key = {}
    for row in cells:
        key = (row["arm"], row["target_id"])
        if key in by_key or key[0] not in ARMS or key[1] not in target_ids:
            raise ValueError("duplicate or unexpected result cell")
        if row.get("official") is not True or type(row.get("resolved")) is not bool:
            raise ValueError("solve rate requires an actual official result")
        if row.get("status") not in {"AGENT_COMPLETED", "CELL_SCIENTIFIC_FAILURE", "MEMORY_EXTRACTION_FAILED"}:
            raise ValueError("solve rate requires a scientific terminal result")
        by_key[key] = row
    if status == "COMPLETE" and len(cells) != len(target_ids) * len(ARMS):
        raise ValueError("complete report requires every planned cell")
    paired_ids = [target for target in target_ids if all((arm, target) in by_key for arm in ARMS)]
    arms = {}
    for arm in ARMS:
        rows = [row for (name, _), row in by_key.items() if name == arm]
        paired = [by_key[(arm, target)] for target in paired_ids]
        successes = sum(row["resolved"] for row in paired)
        arms[arm] = {
            "completed": len(rows), "planned": len(target_ids),
            "completed_resolved": sum(row["resolved"] for row in rows),
            "paired_targets": len(paired), "paired_resolved": successes,
            "paired_solve_rate": successes / len(paired) if paired else None,
            "wilson_95_interval": wilson(successes, len(paired)),
            "model_calls": sum(row["accounting"]["paid_model_calls"] for row in rows),
            "input_tokens": sum(row["accounting"]["input_tokens"] for row in rows),
            "output_tokens": sum(row["accounting"]["output_tokens"] for row in rows),
            "usd": str(sum((Decimal(row["usd"]) for row in rows), Decimal(0))),
            "injections": sum(row["injections"] for row in rows),
        }
    contrasts = []
    for baseline in ("NO_MEMORY", "EXISTING_M2"):
        wins = sum(by_key[("SKHYNIX", t)]["resolved"] and not by_key[(baseline, t)]["resolved"] for t in paired_ids)
        losses = sum(not by_key[("SKHYNIX", t)]["resolved"] and by_key[(baseline, t)]["resolved"] for t in paired_ids)
        discordant = wins + losses
        probability = (min(1.0, 2 * sum(math.comb(discordant, k) for k in range(min(wins, losses) + 1)) /
                           2 ** discordant) if discordant else 1.0)
        contrasts.append({"baseline": baseline, "treatment": "SKHYNIX", "paired_n": len(paired_ids),
                          "fail_to_pass": wins, "pass_to_fail": losses,
                          "delta_percentage_points": 100 * (wins - losses) / len(paired_ids) if paired_ids else None,
                          "mcnemar_exact_two_sided_p": probability if paired_ids else None})
    return {"schema": SCHEMA, "status": status, "plan_sha256": digest(plan),
            "model": MODEL, "scientific_role": "EXPLORATORY_DEV_PILOT",
            "interpretation": "Fresh paired official solve rates; no held-out or mature Skill Library claim. SKHYNIX changes context management and retrieval together.",
            "planned_cells": len(target_ids) * len(ARMS), "completed_cells": len(cells),
            "fully_paired_target_ids": paired_ids, "arms": arms, "contrasts": contrasts,
            "cells": cells, "budget_ledger": ledger,
            "runtime_profile": "EXPLORATION_BUDGET_AND_GUIDANCE",
            "exploration_policy": plan.get("exploration_policy"),
            "previous_run": plan.get("previous_run"),
            "skill_library_entries": 0,
            "skill_coverage_note": "Historical merged PRs supply repository knowledge only; verified reusable procedures are not fabricated."}


def _environment(plan, output):
    from trimem_skhynix_environment import prepare_local_environment
    return prepare_local_environment(
        workspace_root=Path(plan["paths"]["workspace_root"]), output_root=output,
        dataset_cache_root=Path(plan["paths"]["dataset_cache_root"]),
        harness_root=Path(plan["paths"]["harness_root"]),
        loader_preflight_path=(Path(plan["paths"]["loader_preflight_path"])
                               if plan["paths"].get("loader_preflight_path") else None),
        arms=ARMS,
    )


def prepare(args):
    import trimem_benchmark_run as benchmark
    from enterprise_memory.trimem.ppr import PinnedSentenceTransformerPPR
    from trimem_skhynix_source_bank import load_validated_source_bank

    output = args.output_root.resolve()
    require_fresh_roots(output, args.workspace_root)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "plan.json").exists() or (output / "budget-ledger.json").exists():
        raise ValueError("an existing plan cannot be replaced")
    targets, _ = benchmark.load_frozen_rows("development", args.dataset_cache_root)
    bank = load_validated_source_bank()
    model_lock = read_json(ROOT / "configs/trimem_v1/model_lock.json")
    if model_lock["primary_model"]["model_id"] != MODEL:
        raise ValueError("model snapshot changed")
    plan = {
        "schema": SCHEMA, "experiment_id": EXPERIMENT_ID,
        "exploration_policy": exploration_policy().manifest(),
        "previous_run": prior_evidence(),
        "authorization": "User approved exploration-budget, remaining-step and repeat-search improvements followed by a same-model reevaluation in this session.",
        "scope": "NEW_LOCAL_EXPLORATORY_DEV_ONLY", "arms": list(ARMS),
        "execution_order": "target-major; fixed arm order; each arm receives a fresh workspace and bank",
        "targets": targets, "model": MODEL, "model_lock": model_lock, "pricing": PRICING,
        "runtime_lock": runtime_lock().to_manifest(),
        "budget": budget_caps(len(targets) * len(ARMS), args.usd_cap),
        "source_hashes": source_hashes(),
        "source_bank": "configs/trimem_v1/dev_activation_source_bank_manifest.json",
        "source_bank_file_sha256": hashlib.sha256((ROOT / "configs/trimem_v1/dev_activation_source_bank_manifest.json").read_bytes()).hexdigest(),
        "memory_bank_scope": "HISTORICAL_PR_REPOSITORY_KNOWLEDGE_ONLY_ZERO_PROCEDURAL_SKILLS",
        "base_git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "paths": {"workspace_root": str(args.workspace_root.resolve()),
                  "dataset_cache_root": str(args.dataset_cache_root.resolve()),
                  "harness_root": str(args.harness_root.resolve()),
                  "loader_preflight_path": str(args.loader_preflight_path.resolve()) if args.loader_preflight_path else None},
        "prices_source": "https://developers.openai.com/api/docs/models/gpt-5.4-mini",
    }
    verify_exploration_plan(plan)
    env = _environment(plan, output)
    if [task.task_id for task in env.tasks] != [target["target_id"] for target in targets]:
        raise ValueError("environment task order differs from plan")
    plan["environment_preflight"] = env.summary
    embedder = PinnedSentenceTransformerPPR()
    embedding = embedder.embed("coding repository memory retrieval preflight")
    if len(embedding) != 384 or not all(math.isfinite(number) for number in embedding):
        raise ValueError("existing M2 embedding preflight failed")
    plan["embedding_preflight"] = {"provenance": dict(embedder.provenance()),
                                   "probe_sha256": digest(embedding)}
    # The planner reports no solve rate and constructs no provider client.
    write_json(output / "plan.json", plan)
    write_json(output / "report.json", aggregate(plan, [], status="READY_FOR_LOCAL_EXECUTION"))
    print(json.dumps({"status": "READY", "plan_sha256": digest(plan),
                      "targets": len(targets), "cells": len(targets) * len(ARMS),
                      "usd_cap": args.usd_cap, "paid_model_calls": 0}), flush=True)


def _controller(arm, task, bank, output):
    from enterprise_memory.trimem.agent_runtime import NoMemoryController
    from enterprise_memory.trimem.arms import ActiveNodeTriMemController
    from enterprise_memory.trimem.ppr import PinnedSentenceTransformerPPR
    from enterprise_memory.trimem.retrieval import RetrievalConfig, TriMemoryRetriever
    from enterprise_memory.trimem.skill_runtime import SkillFirstMemoryController
    from trimem_skhynix_source_bank import build_legacy_source_store, build_seeded_store

    if arm not in ARMS:
        raise ValueError("unknown comparison arm")
    if arm == "NO_MEMORY":
        return NoMemoryController(), None, {"records": 0}
    if arm == "SKHYNIX":
        path = output / "source-memory.sqlite3"
        if path.exists():
            from enterprise_memory.trimem.skill_memory import SkillMemoryStore
            expected, report = build_seeded_store(":memory:", task, bank=bank)
            expected.close()
            store = SkillMemoryStore(path)
            snapshot = store.snapshot(org_id=task.org_id, user_id=task.user_id,
                                      repository=task.repository, revision=task.commit,
                                      language=report["language"])
            if snapshot.content_hash != report["seed_snapshot_sha256"]:
                store.close()
                raise ValueError("resumed source bank differs from validated immutable seed")
        else:
            store, report = build_seeded_store(path, task, bank=bank)
        return SkillFirstMemoryController(store, task_id=task.task_id,
                                          language=report.get("language", "")), store, report
    policy = read_json(ROOT / "configs/trimem_v1/m2_candidates/recall.json")["retrieval"]
    config = RetrievalConfig(
        min_confidence=policy["min_confidence"], min_margin=policy["min_margin"],
        episode_complete_threshold=policy["episode_complete_threshold"],
        max_episodic_per_node=policy["max_episodic_per_active_node"],
        max_semantic_per_node=policy["max_semantic_per_active_node"],
        max_task_injections=policy["max_task_injections"], context_budget_bytes=policy["context_budget_bytes"],
        embedding_dimensions=policy["embedding_dimensions"], embedding_weight=policy["embedding_weight"],
        lexical_weight=policy["lexical_weight"], ppr_damping=policy["ppr_damping"],
        ppr_iterations=policy["ppr_iterations"],
    )
    source = build_legacy_source_store(task, bank=bank)
    retriever = TriMemoryRetriever(source, config, embedder=PinnedSentenceTransformerPPR(),
                                  diagnostic_telemetry=True, require_safe_pool_metadata=True)
    return ActiveNodeTriMemController(retriever, task_id=task.task_id), None, {"source_hash": source.content_hash}


def _load_key_stdin():
    from enterprise_memory.providers.openai_credential import validate_openai_api_key
    raw = sys.stdin.buffer.read(1_024)
    key = validate_openai_api_key(raw)
    os.environ["OPENAI_API_KEY"] = key.decode("ascii")


def run(args):
    import trimem_benchmark_run as benchmark
    from enterprise_memory.trimem.accounting import RawEvidenceLedger
    from enterprise_memory.trimem.agent_runtime import NullExperienceLifecycle
    from enterprise_memory.trimem.checkpoint import FileCheckpointStore
    from enterprise_memory.trimem.exploration_runtime import (ExplorationTriMemAgentRuntime, ExplorationSkhynixAgentRuntime)
    from trimem_dev_activation_executor import _StandaloneProviderSession
    from trimem_skhynix_source_bank import load_validated_source_bank

    output = args.output_root.resolve()
    plan = read_json(output / "plan.json")
    verify_exploration_plan(plan)
    if plan["source_hashes"] != source_hashes() or plan["runtime_lock"] != runtime_lock().to_manifest():
        raise ValueError("execution source differs from the prepared plan")
    if plan["arms"] != list(ARMS) or plan["schema"] != SCHEMA:
        raise ValueError("unknown experiment plan")
    if plan["budget"] != budget_caps(len(plan["targets"]) * len(ARMS), plan["budget"]["total_usd"]):
        raise ValueError("invalid pilot budget")
    # Credentials arrive over a pipe, never in argv, source, logs or output files.
    env = _environment(plan, output)
    bank = load_validated_source_bank()
    if [task.task_id for task in env.tasks] != [target["target_id"] for target in plan["targets"]]:
        raise ValueError("runtime target order differs")
    ledger = benchmark.AtomicBudgetLedger(output / "budget-ledger.json", approval_digest=digest(plan),
                                          caps=plan["budget"], pricing=PRICING)
    cells = []
    report_status = "RUNNING"
    try:
        _load_key_stdin()
        for index, task in enumerate(env.tasks):
            for arm in ARMS:
                verify_exploration_plan(plan)
                if plan["source_hashes"] != source_hashes():
                    raise ValueError("source changed during execution")
                cell_root = output / "cells" / f"{index:02d}" / arm
                cell_root.mkdir(parents=True, exist_ok=True)
                result_path = cell_root / "public-result.json"
                stream_id = plan["experiment_id"] + f"-{index:02d}-{arm}"
                runtime_arm = "M0" if arm == "NO_MEMORY" else "M2"
                task_key = f"{stream_id}:{runtime_arm}:{task.task_id}"
                if result_path.exists():
                    prior = read_json(result_path)
                    if prior.get("plan_sha256") != digest(plan) or prior.get("target_id") != task.task_id or prior.get("arm") != arm:
                        raise ValueError("prior result identity differs")
                    if ledger.task_arm_status(task_key) == "RESERVED":
                        reservation = ledger.resume_task_arm(task_key)
                        ledger.complete_task_arm(task_key, reservation, status=benchmark.SCIENTIFIC_LEDGER_TERMINAL_STATUS,
                                                 container_started=True)
                    cells.append(prior)
                    continue
                print(json.dumps({"event": "CELL_PREPARE", "target": task.task_id, "arm": arm,
                                  "completed": len(cells)}), flush=True)
                checkpoint_exists = (cell_root / "agent-checkpoints" / f"{stream_id}.json").exists()
                state = ledger.task_arm_status(task_key)
                if checkpoint_exists and state is None:
                    raise ValueError("checkpoint lacks this experiment's budget reservation")
                prepared = env.prepare_cell(arm, task, resume=checkpoint_exists and state == "RESERVED")
                controller, memory_store, bank_report = _controller(arm, task, bank, cell_root)
                write_json(cell_root / "bank-projection.json", bank_report)
                state = ledger.task_arm_status(task_key)
                reservation = ledger.reserve_task_arm(task_key) if state is None else ledger.resume_task_arm(task_key)
                session = _StandaloneProviderSession("skhynix-" + stream_id)
                client = None
                started = time.perf_counter_ns()
                try:
                    gateway, client = benchmark.build_paid_model_gateway(
                        session, ledger, plan["model_lock"], stream_id=stream_id,
                        restricted_response_root=cell_root / "restricted-provider-responses")
                    journal = benchmark.TerminalInvocationJournal(cell_root / "terminal-journal")
                    grader = benchmark.JournaledGraderGateway(
                        prepared.grader, journal, preflight_evidence=env.loader_preflight,
                        python_binary=str(env.loader_preflight["python_loader"]["python_binary"]))
                    evidence = RawEvidenceLedger(cell_root / "evidence")
                    checkpoints = FileCheckpointStore(cell_root / "agent-checkpoints")
                    cls = ExplorationSkhynixAgentRuntime if arm == "SKHYNIX" else ExplorationTriMemAgentRuntime
                    runtime = cls(runtime_lock=runtime_lock(), exploration_policy=exploration_policy(),
                                  model_gateway=benchmark.JournaledModelGateway(gateway, journal),
                                  grader_gateway=grader, memory_controller=controller,
                                  evidence=evidence, checkpoint_store=checkpoints,
                                  lifecycle=NullExperienceLifecycle(),
                                  workspace_factory=prepared.workspace_factory,
                                  model_config_hash=digest(plan["model_lock"]),
                                  grader_config_hash=digest({"target": prepared.target, "loader": env.loader_preflight}))
                    result = runtime.run(task, arm=runtime_arm, run_id=stream_id,
                                         resume=(cell_root / "agent-checkpoints" / f"{stream_id}.json").exists())
                    if result.grade.official is not True or result.grade.container_started is not True:
                        raise ValueError("actual official grading was not performed")
                    evidence.verify()
                    accounting = benchmark.actual_accounting(result.accounting,
                        task_wall_time_ms=(time.perf_counter_ns() - started) // 1_000_000)
                    row = {"plan_sha256": digest(plan), "arm": arm, "target_id": task.task_id,
                           "repository": task.repository, "resolved": result.resolved,
                           "official": True, "status": result.cell_status,
                           "model_failure_class": result.model_failure_class,
                           "agent_completed": result.agent_completed,
                           "patch_sha256": hashlib.sha256(result.patch.encode()).hexdigest(),
                           "patch_utf8_bytes": len(result.patch.encode()),
                           "grader_patch_source": result.grader_patch_source,
                           "accounting": accounting,
                           "usd": benchmark.actual_usd_for_accounting(accounting, PRICING),
                           "injections": len(result.injections),
                           "injected_memory_ids": [item["memory_id"] for item in result.injections],
                           "evidence_tail_hash": result.evidence_tail_hash,
                           "observed_image_digest": benchmark.observed_target_digest(result.grade)}
                    write_json(result_path, row)
                    ledger.complete_task_arm(task_key, reservation,
                        status=benchmark.SCIENTIFIC_LEDGER_TERMINAL_STATUS, container_started=True)
                    cells.append(row)
                    print(json.dumps({"event": "CELL_COMPLETE", "target": task.task_id,
                                      "arm": arm, "resolved": result.resolved, "usd": row["usd"],
                                      "injections": row["injections"], "completed": len(cells)}), flush=True)
                finally:
                    if client is not None:
                        benchmark.close_paid_model_client(session, client)
                    session.close()
                    if memory_store is not None:
                        memory_store.close()
                write_json(output / "report.json", aggregate(plan, cells, status="RUNNING",
                    ledger=ledger._read()["actual"]))
            release = getattr(env, "release_target", None)
            if callable(release):
                release(task)
        report_status = "COMPLETE"
    except Exception as exc:
        report_status = "INCOMPLETE"
        # Exception text may originate from a provider; only a class is public.
        write_json(output / "failure.json", {"exception_type": type(exc).__name__,
                                              "completed_cells": len(cells), "plan_sha256": digest(plan),
                                              "failure_class": (exc.classification if isinstance(exc, benchmark.ModelPreflightFailure) else None)})
        raise
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
        current = ledger._read()
        write_json(output / "report.json", aggregate(plan, cells, status=report_status,
            ledger={"actual": current["actual"], "outstanding": current["outstanding"]}))
        if report_status == "COMPLETE":
            write_json(output / "image-cleanup.json", {"images": env.release_owned_images()})
    print(json.dumps({"status": report_status, "completed_cells": len(cells),
                      "accounting": ledger._read()["actual"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--output-root", type=Path, required=True)
    prepare_parser.add_argument("--workspace-root", type=Path, required=True)
    prepare_parser.add_argument("--dataset-cache-root", type=Path, required=True)
    prepare_parser.add_argument("--harness-root", type=Path, required=True)
    prepare_parser.add_argument("--loader-preflight-path", type=Path)
    prepare_parser.add_argument("--usd-cap", type=float, default=5.0)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args)
    else:
        run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
