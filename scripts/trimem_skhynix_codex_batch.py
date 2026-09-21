"""Freeze and aggregate a paired native-agent evaluation, without model calls.

Freeze after preparing every evaluation run and before any solver action.
Training results remain separate from the evaluation denominator.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trimem_skhynix_codex as broker

SCHEMA = "skhynix/native-codex-batch/1.0"


def verify_result_receipt(plan, run: Path, cell: str, *, legacy_training=False):
    """Read existing evidence only; never invoke a solver, grader or container."""
    if cell not in broker.CELLS or plan["cells"] != broker.CELLS:
        raise ValueError("Unknown training/evaluation cell")
    root = run / "cells" / cell
    result = broker.read(root / "public-result.json")
    if not legacy_training:
        broker.validate_result(plan, cell, result)
    plan_sha = broker.sha(broker.canonical(plan))
    if (result.get("plan_sha256") != plan_sha or result.get("cell") != cell or
            result.get("arm") != broker.CELLS[cell] or
            result.get("target_id") != plan["public_task"]["task_id"] or
            result.get("experiment_id", plan["experiment_id"]) != plan["experiment_id"] or
            result.get("official") is not True or result.get("grader_status") != "success" or
            type(result.get("resolved")) is not bool):
        raise ValueError("Official result identity differs")
    private_path = root / "grader-private.json"
    private = broker.read(private_path)
    if (result.get("grader_private_sha256") != broker.sha(private_path.read_bytes()) or
            type(private.get("resolved")) is not bool or private["resolved"] != result["resolved"]):
        raise ValueError("Official result disagrees with private grader receipt")
    submission, state = broker.read(root / "submission.json"), broker.read(root / "state.json")
    patch = (root / "submission.diff").read_bytes()
    if (submission.get("plan_sha256") != plan_sha or submission.get("cell") != cell or
            submission.get("arm") != broker.CELLS[cell] or
            submission.get("target_id") != result["target_id"] or
            submission.get("experiment_id", plan["experiment_id"]) != plan["experiment_id"] or
            submission.get("actions") != state.get("actions") or state.get("status") != "SUBMITTED" or
            submission.get("patch_sha256") != broker.sha(patch) or
            submission.get("patch_utf8_bytes") != len(patch)):
        raise ValueError("Submission identity or sealed patch differs")
    events, tail = broker.audit_events(root)
    memories = [event["result"]["result"] for event in events
                if event["request"].get("op") == "recall" and event["result"]["ok"]]
    injections = {item["memory_id"]: item for response in memories
                  for item in response.get("injections", [])}
    commands = [event for event in events if event["request"].get("name") == "run_command"]
    expected = {"patch_sha256": broker.sha(patch), "patch_utf8_bytes": len(patch),
                "agent_completed": submission["agent_completed"], "actions": len(events),
                "tool_event_tail_sha256": tail,
                "tool_errors": sum(not event["result"]["ok"] for event in events),
                "memory_queries": len(memories), "memory_injections": len(injections),
                "memory_bytes": sum(item["byte_count"] for item in injections.values()),
                "injected_memory_ids": sorted(injections), "command_count": len(commands),
                "successful_commands": sum(event["result"]["ok"] and
                    event["result"]["result"].get("exit_code") == 0 for event in commands)}
    if any(result.get(key) != value for key, value in expected.items()):
        raise ValueError("Official result summaries disagree with sealed tool receipts")
    return result


def id_set(value, label):
    if (not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value)
            or len(set(value)) != len(value)):
        raise ValueError(f"{label} must contain distinct task IDs")
    return set(value)


def validate_split(contract, training_ids, evaluation_ids):
    binding = contract["frozen_memory_bank"]
    path = Path(binding["path"])
    if broker.sha(path.read_bytes()) != binding["sha256"]:
        raise ValueError("Frozen bank bytes differ")
    bank = broker.read(path)
    if (id_set(bank.get("training_task_ids"), "Bank training") != training_ids or
            id_set(bank.get("evaluation_task_ids"), "Bank evaluation") != evaluation_ids):
        raise ValueError("Frozen bank and batch training/evaluation split differ")
    declarations = bank.get("evaluation_targets")
    if (not isinstance(declarations, list) or
            id_set([item.get("task_id") for item in declarations], "Bank evaluation targets") != evaluation_ids or
            bank.get("cold_start") is not False or not isinstance(bank.get("records"), list) or
            not {record["source"]["task_id"] for record in bank["records"]}.issubset(training_ids)):
        raise ValueError("Learned record sources or declared evaluation targets differ from batch split")
    supplemental = contract.get("supplemental_manifest")
    if supplemental:
        path = Path(supplemental["path"])
        if broker.sha(path.read_bytes()) != supplemental["sha256"]:
            raise ValueError("Supplemental manifest bytes differ")
        manifest = broker.read(path)
        declared_eval = {target["target_id"] for target in manifest["targets"] if target["role"] == "EVALUATION"}
        declared_train = {target["target_id"] for target in manifest["targets"] if target["role"] == "TRAINING"}
        prior = manifest["prior_training_target"]
        import trimem_skhynix_native_dataset as dataset
        native004 = dataset.canonical(manifest.get("selection")) == dataset.canonical(dataset.NATIVE004_SELECTION)
        native005 = dataset.canonical(manifest.get("selection")) == dataset.canonical(dataset.NATIVE005_SELECTION)
        if (native004 or native005) and (prior is not None or manifest.get("additional_prior_training_targets") != []):
            profile = "native004" if native004 else "native005"
            raise ValueError(f"Independent {profile} profile forbids prior training")
        if prior is not None:
            declared_train.add(prior["target_id"])
        else:
            if not (native004 or native005):
                raise ValueError("Only the independent native004 profile or native005 profile permits no prior training")
        declared_train.update(item["target_id"] for item in manifest.get("additional_prior_training_targets", []))
        if declared_eval != evaluation_ids or declared_train != training_ids:
            raise ValueError("Supplemental manifest roles differ from batch split")


def freeze(output: Path, evaluation_runs: list[Path], training_cells: list[tuple[Path, str]]):
    if output.exists():
        raise ValueError("Use a new batch plan path")
    if not evaluation_runs or len(set(p.resolve() for p in evaluation_runs)) != len(evaluation_runs):
        raise ValueError("Evaluation runs must be nonempty and unique")
    training = []
    for run, cell in training_cells:
        # Training may have executed an earlier frozen implementation.
        plan = broker.read(run / "plan.json")
        plan_sha = broker.sha(broker.canonical(plan))
        if (run / "plan.sha256").read_text().strip() != plan_sha:
            raise ValueError("Training plan hash differs")
        path = run / "cells" / cell / "public-result.json"
        result = verify_result_receipt(plan, run, cell, legacy_training=True)
        training.append({"run_root": str(run.resolve()), "cell": cell,
                         "target_id": result["target_id"], "resolved": result["resolved"],
                         "result_sha256": broker.sha(path.read_bytes()), "plan_sha256": plan_sha})
    train_ids = {row["target_id"] for row in training}
    if not train_ids or len(train_ids) != len(training):
        raise ValueError("Training cells must describe distinct tasks")
    rows = []
    common = None
    for run in evaluation_runs:
        run = run.resolve()
        plan = broker.load_plan(run)
        if plan.get("procedure_declaration") is not None:
            raise ValueError("Evaluation cannot receive the training procedure instructions outside memory")
        task_id = plan["public_task"]["task_id"]
        if task_id in train_ids or any(row["target_id"] == task_id for row in rows):
            raise ValueError("Evaluation overlaps training or another evaluation task")
        bank = plan.get("frozen_memory_bank")
        if not bank:
            raise ValueError("Evaluation requires a frozen learned bank")
        contract = {"limits": plan["limits"], "cells": plan["cells"],
                    "model": plan["requested_solver_model"], "frozen_memory_bank": bank,
                    "source_hashes": plan["source_hashes"],
                    **{key: plan.get(key) for key in ("supplemental_manifest", "public_python", "execution",
                                                      "l0_projection", "memory_learning", "host_isolation")}}
        if common is not None and contract != common:
            raise ValueError("Evaluation model, limits, bank, or source differ")
        common = contract
        for cell in plan["cells"]:
            root = run / "cells" / cell
            state = broker.read(root / "state.json")
            if (state["status"] != "OPEN" or state["actions"] != 0 or
                    state["started_at"] is not None or state.get("pending") or
                    (root / "submission.json").exists() or (root / "public-result.json").exists()):
                raise ValueError("Freeze must precede every evaluation solver action")
            events, _ = broker.audit_events(root)
            if events or broker.workspace_for(plan, run, cell).patch():
                raise ValueError("Freeze requires empty tool history and clean evaluation checkouts")
        rows.append({"run_root": str(run), "target_id": task_id,
                     "plan_sha256": broker.sha(broker.canonical(plan))})
    validate_split(common, train_ids, {row["target_id"] for row in rows})
    selection_claim = "Identity-selected supplemental dataset; no evaluation outcomes used in selection or bank construction"
    if common.get("supplemental_manifest"):
        manifest = broker.read(Path(common["supplemental_manifest"]["path"]))
        import trimem_skhynix_native_dataset as dataset
        if manifest.get("selection") == dataset.NATIVE004_SELECTION:
            selection_claim = ("Public-title-informed exploratory hand-selected printing/codegen sample; "
                               "not ID-only, random, or difficulty-proven; no evaluation outcomes used "
                               "in selection or bank construction")
        elif manifest.get("selection") == dataset.NATIVE005_SELECTION:
            selection_claim = ("Public-runner-hash, Python-runtime and base-ancestry filtered ascending-ID exploratory sample; "
                               "public titles observed but not used by the selection algorithm; "
                               "not ID-only, random, or difficulty-proven; no evaluation outcomes used "
                               "in selection or bank construction")
    value = {"schema": SCHEMA, "training": training, "evaluation": rows,
             "contract": common, "planned_targets": len(rows),
             "planned_cells": len(rows) * len(common["cells"]),
             "selection": selection_claim,
             "separate_model_api_calls": 0, "codex_tokens_and_cost": None}
    broker.write(output, value)
    output.with_suffix(output.suffix + ".sha256").write_text(
        broker.sha(broker.canonical(value)) + "\n", encoding="ascii")
    return value


def aggregate(plan_path: Path, output: Path):
    batch = broker.read(plan_path)
    if (batch.get("schema") != SCHEMA or
            plan_path.with_suffix(plan_path.suffix + ".sha256").read_text().strip() !=
            broker.sha(broker.canonical(batch))):
        raise ValueError("Frozen batch plan changed")
    rows, paired = [], []
    for item in batch["training"]:
        run = Path(item["run_root"])
        training_plan = broker.read(run / "plan.json")
        if (broker.sha(broker.canonical(training_plan)) != item["plan_sha256"] or
                broker.sha((run / "cells" / item["cell"] / "public-result.json").read_bytes()) != item["result_sha256"]):
            raise ValueError("Training evidence changed after batch freeze")
        verify_result_receipt(training_plan, run, item["cell"], legacy_training=True)
    validate_split(batch["contract"], {item["target_id"] for item in batch["training"]},
                   {item["target_id"] for item in batch["evaluation"]})
    for item in batch["evaluation"]:
        run = Path(item["run_root"])
        plan = broker.load_plan(run)
        if broker.sha(broker.canonical(plan)) != item["plan_sha256"]:
            raise ValueError("Evaluation plan changed after batch freeze")
        found = []
        for cell in plan["cells"]:
            path = run / "cells" / cell / "public-result.json"
            if path.exists():
                row = verify_result_receipt(plan, run, cell)
                rows.append(row)
                found.append(row)
        if len(found) == len(plan["cells"]):
            paired.append(item["target_id"])
    complete = len(rows) == batch["planned_cells"]
    comparison = None
    if complete:
        comparison = {}
        for arm in batch["contract"]["cells"].values():
            selected = [row for row in rows if row["arm"] == arm]
            resolved = sum(row["resolved"] for row in selected)
            comparison[arm] = {"resolved": resolved, "n": len(selected),
                               "solve_rate": resolved / len(selected),
                               "actions": sum(row["actions"] for row in selected),
                               "memory_injections": sum(row["memory_injections"] for row in selected),
                               "memory_bytes": sum(row["memory_bytes"] for row in selected)}
        baseline = comparison["NO_MEMORY"]["solve_rate"]
        for result in comparison.values():
            result["difference_percentage_points"] = 100 * (result["solve_rate"] - baseline)
    value = {"schema": SCHEMA, "status": "COMPLETE" if complete else "INCOMPLETE",
             "batch_plan_sha256": broker.sha(broker.canonical(batch)),
             "planned_targets": batch["planned_targets"], "planned_cells": batch["planned_cells"],
             "completed_cells": len(rows), "fully_paired_targets": paired,
             "comparison": comparison, "cells": rows,
             "separate_model_api_calls": 0, "codex_tokens_and_cost": None,
             "limitations": ["Small deterministic subset; no population solve-rate claim.",
                             "Native context does not implement TriMem L0 projection.",
                             "Broker-only host access is protocol-enforced, not OS-denied.",
                             "No bank changes or online learning during evaluation."]}
    broker.write(output, value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("freeze")
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--evaluation-run", type=Path, action="append", required=True)
    prep.add_argument("--training-cell", nargs=2, action="append", required=True, metavar=("RUN_ROOT", "CELL"))
    report = sub.add_parser("aggregate")
    report.add_argument("--plan", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    broker.block_model_client()
    if args.command == "freeze":
        result = freeze(args.output, args.evaluation_run, [(Path(run), cell) for run, cell in args.training_cell])
    else:
        result = aggregate(args.plan, args.output)
    print(broker.canonical(result).decode())


if __name__ == "__main__":
    main()
