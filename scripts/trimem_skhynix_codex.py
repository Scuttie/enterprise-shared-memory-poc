"""Native Codex pilot: public tools and patch submission, with no model client.

The manager prepares and grades; fresh Codex threads use only ``action``.
Command containers isolate repository execution. Native threads still inherit
host tools, so thread-level file access restrictions are a protocol, not an OS
security boundary. Native context management is not the TriMem L0 projection.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
CELLS = {"A": "NO_MEMORY", "B": "EXISTING_M2", "C": "SKHYNIX"}
SCHEMA = "skhynix/native-codex-pilot/1.0"
TARGET = "swebench_verified--sympy__sympy-23262"
DEFAULT_EXPERIMENT_ID = "skhynix-native-codex-001"
TOOLS = {"list_files", "read_file", "search", "write_file", "replace_text", "run_command"}
LIMITS = {"repository_actions": 120, "wall_seconds": 1200,
          "memory_injections": 3, "memory_bytes": 12000}


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(canonical(value) + b"\n")
    os.replace(temp, path)


def source_hashes():
    paths = [*ROOT.glob("src/enterprise_memory/**/*.py"), *ROOT.glob("scripts/*.py")]
    paths += [ROOT / "configs/trimem_v1/m2_candidates/recall.json",
              ROOT / "artifacts/trimem_v1/freeze.json"]
    return {p.relative_to(ROOT).as_posix(): sha(p.read_bytes()) for p in sorted(paths)}


def block_model_client():
    # A guard against accidentally re-entering the paid orchestration route.
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import trimem_benchmark_run as benchmark

    def unavailable(*args, **kwargs):
        raise RuntimeError("DIRECT_MODEL_API_DISABLED_IN_NATIVE_CODEX_PILOT")

    benchmark.build_paid_model_gateway = unavailable


def environment(plan, run):
    from trimem_skhynix_environment import prepare_local_environment
    paths = plan["paths"]
    supplemental = frozen_input_kwargs(plan, "supplemental_manifest", "supplemental_manifest")
    return prepare_local_environment(
        workspace_root=paths["workspace_root"], output_root=run / "environment",
        dataset_cache_root=paths["dataset_cache_root"], harness_root=paths["harness_root"],
        loader_preflight_path=paths.get("loader_preflight_path"),
        **supplemental,
    )


def task_from_plan(plan):
    from enterprise_memory.trimem.agent_runtime import CodingTask
    p = plan["public_task"]
    return CodingTask(p["task_id"], plan["experiment_id"], plan.get("solver_user_id", "native-codex-solver"),
                      p["repository"], p["commit"], p["instruction"], {}, ())


def validate_experiment_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("Experiment ID must contain 1..128 safe identifier characters")
    return value


def validate_solver_user_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise ValueError("Solver user ID must contain 1..128 safe identifier characters")
    return value


def frozen_input(path):
    if path is None:
        return None
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError("Frozen input must be a file")
    return {"path": str(path), "sha256": sha(path.read_bytes())}


def frozen_input_kwargs(plan, key, prefix):
    item = plan.get(key)
    if item is None:
        return {}
    if (not isinstance(item, dict) or set(item) != {"path", "sha256"} or
            not isinstance(item["path"], str) or not Path(item["path"]).is_absolute() or
            not isinstance(item["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])):
        raise ValueError("Frozen input identity is invalid")
    path = Path(item["path"])
    if not path.is_file() or sha(path.read_bytes()) != item["sha256"]:
        raise ValueError("Frozen input bytes changed")
    return {f"{prefix}_path": path, f"{prefix}_sha256": item["sha256"]}


def planned_target_id(plan):
    public, target = plan["public_task"], plan["target"]
    target_id = public["task_id"]
    if (not isinstance(target_id, str) or not target_id or len(target_id) > 256 or
            target_id != target["target_id"] or public["repository"] != target["repository"] or
            public["commit"] != target["base_commit"]):
        raise ValueError("Frozen target and public task identity differ")
    return target_id


def load_plan(run: Path):
    plan = read(run / "plan.json")
    if (run / "plan.sha256").read_text().strip() != sha(canonical(plan)):
        raise ValueError("Frozen pilot plan changed")
    if plan["schema"] != SCHEMA or plan["source_hashes"] != source_hashes():
        raise ValueError("Pilot source or plan schema changed")
    validate_experiment_id(plan["experiment_id"])
    validate_solver_user_id(plan.get("solver_user_id", "native-codex-solver"))
    planned_target_id(plan)
    frozen_input_kwargs(plan, "frozen_memory_bank", "frozen_bank")
    frozen_input_kwargs(plan, "supplemental_manifest", "supplemental_manifest")
    procedure_declaration(plan)
    controlled_lessons(plan)
    if (plan["cells"] != CELLS or
            plan["limits"] != LIMITS or plan["requested_solver_model"] != "gpt-6-astra"):
        raise ValueError("Pilot identity changed")
    certificate = workflow_runtime_certificate(plan)
    if certificate is not None:
        for cell in CELLS:
            config = read(cell_root(run, cell) / "workspace.json")
            if (config["plan_sha256"] != sha(canonical(plan)) or
                    config["image"] != certificate["source_image"]):
                raise ValueError("Workflow certificate differs from the frozen cell runtime")
    return plan


def workflow_runtime_certificate(plan):
    reference = plan.get("frozen_memory_bank")
    if reference is None or read(Path(reference["path"])).get("schema") != "skhynix/native-learned-bank/2.0":
        return None
    from trimem_skhynix_codex_learning import load_frozen_bank
    from trimem_skhynix_codex_skill_bank import runtime_certificate_for_bank
    bank = load_frozen_bank(Path(reference["path"]), reference["sha256"], task_from_plan(plan))
    certificate = runtime_certificate_for_bank(bank)
    if certificate["python_executable"] != plan["public_python"]:
        raise ValueError("Workflow certificate differs from the declared public Python")
    return certificate


def procedure_declaration(plan):
    if plan.get("procedure_declaration") is None:
        return None
    from trimem_skhynix_codex_procedures import load_declaration
    frozen_input_kwargs(plan, "procedure_declaration", "procedure_declaration")
    item = plan["procedure_declaration"]
    return load_declaration(Path(item["path"]), item["sha256"], planned_target_id(plan))


def controlled_lessons(plan):
    if plan.get("controlled_lesson_manifest") is None:
        return None
    if plan.get("frozen_memory_bank") is not None or plan.get("procedure_declaration") is not None:
        raise ValueError("Controlled lessons are exclusive with a memory bank or procedure declaration")
    from trimem_skhynix_codex_controlled_lessons import load_controlled_manifest, LABELS, ROLE
    frozen_input_kwargs(plan, "controlled_lesson_manifest", "controlled_lesson_manifest")
    if plan.get("experimental_arms") != LABELS or plan.get("scientific_role") != ROLE:
        raise ValueError("Controlled lesson experimental labels differ")
    item = plan["controlled_lesson_manifest"]
    return load_controlled_manifest(Path(item["path"]), item["sha256"], task_from_plan(plan))


def begin_procedure(plan, run, cell, state, request, events):
    from trimem_skhynix_codex_procedures import validate_bindings, capture_workspace
    declaration = procedure_declaration(plan)
    if declaration is None:
        raise ValueError("This cell has no predeclared training procedure")
    root = cell_root(run, cell)
    path = root / "procedure-binding.json"
    if path.exists():
        raise ValueError("Procedure bindings were already frozen")
    if any(event["request"].get("op") == "tool" and
           event["request"].get("name") in ("write_file", "replace_text", "run_command") for event in events):
        raise ValueError("Procedure must be bound before the first edit or command")
    workspace = workspace_for(plan, run, cell)
    if workspace.patch():
        raise ValueError("Procedure bindings require a clean initial checkout")
    bindings = validate_bindings(declaration, request.get("bindings"), plan["public_python"])
    from enterprise_memory.trimem.skill_memory import ProcedureTemplate
    result = {"declaration_sha256": plan["procedure_declaration"]["sha256"],
              "template_hash": ProcedureTemplate(**declaration["template"]).content_hash,
              "bindings": bindings, "sequence": state["actions"],
              "workspace_snapshot": capture_workspace(workspace, bindings)}
    if "test_name" in bindings:
        from trimem_skhynix_codex_procedures import validate_named_base
        validate_named_base(result["workspace_snapshot"], bindings["test_name"])
    write(path, result)
    return result


def procedure_snapshot(plan, run, cell, events):
    path = cell_root(run, cell) / "procedure-binding.json"
    if plan.get("procedure_declaration") is None:
        return None
    from trimem_skhynix_codex_procedures import capture_workspace
    beginnings = [event["result"]["result"] for event in events
                  if event["request"].get("op") == "begin_procedure" and event["result"].get("ok")]
    if not path.exists():
        if beginnings:
            raise ValueError("Original procedure binding file is missing")
        return None
    binding = read(path)
    if beginnings != [binding] or binding["declaration_sha256"] != plan["procedure_declaration"]["sha256"]:
        raise ValueError("Procedure bindings differ from their original journal receipt")
    return capture_workspace(workspace_for(plan, run, cell), binding["bindings"])


def cell_root(run, cell):
    if cell not in CELLS:
        raise ValueError("Unknown cell")
    return run / "cells" / cell


def workspace_for(plan, run, cell):
    from enterprise_memory.trimem.git_workspace import DockerSandboxCommandRunner, GitCheckoutWorkspace
    config = read(cell_root(run, cell) / "workspace.json")
    if config["plan_sha256"] != sha(canonical(plan)):
        raise ValueError("Workspace plan mismatch")
    runner = DockerSandboxCommandRunner(
        config["image"], masked_image_files=tuple(config["masked_image_files"]),
        masked_image_directories=tuple(config["masked_image_directories"]),
    )
    if runner.content_hash != config["command_runner_sha256"]:
        raise ValueError("Command sandbox differs from preparation")
    return GitCheckoutWorkspace(config["checkout_root"], base_commit=plan["public_task"]["commit"],
                                command_runner=runner)


@contextmanager
def locked(path):
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def remaining(plan, state, now):
    start = state.get("started_at")
    return {"actions_remaining": max(0, plan["limits"]["repository_actions"] - state["actions"]),
            "seconds_remaining": max(0, int(plan["limits"]["wall_seconds"] -
                                            (now - start if start is not None else 0)))}


def check_action_budget(plan, state, now):
    if state["status"] != "OPEN":
        raise ValueError("Cell is sealed; no further solver actions")
    budget = remaining(plan, state, now)
    if budget["actions_remaining"] <= 0 or budget["seconds_remaining"] <= 0:
        raise ValueError("SOLVER_ACTION_OR_TIME_LIMIT; manager may seal partial patch")


def append_event(root, state, request, result):
    event = {"sequence": state["actions"], "time": time.time(), "request": request, "result": result,
             "previous_sha256": state["tail_sha256"]}
    digest = sha(canonical(event))
    with (root / "tool-events.jsonl").open("ab") as stream:
        stream.write(canonical({**event, "sha256": digest}) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    state["tail_sha256"] = digest


def seal_submission(plan, run, cell, state, *, summary, agent_completed, expected_patch_sha256=None):
    root = cell_root(run, cell)
    if (root / "submission.json").exists():
        raise ValueError("A patch was already submitted")
    patch = workspace_for(plan, run, cell).patch().encode("utf-8")
    if expected_patch_sha256 is not None and sha(patch) != expected_patch_sha256:
        raise ValueError("Procedure snapshot and submitted patch differ")
    (root / "submission.diff").write_bytes(patch)
    submission = {"schema": SCHEMA, "cell": cell, "arm": CELLS[cell],
                  "experiment_id": plan["experiment_id"],
                  "target_id": planned_target_id(plan), "plan_sha256": sha(canonical(plan)),
                  "patch_sha256": sha(patch), "patch_utf8_bytes": len(patch),
                  "agent_completed": agent_completed, "summary": summary,
                  "actions": state["actions"], "started_at": state["started_at"],
                  "submitted_at": time.time(), "separate_model_api_calls": 0}
    write(root / "submission.json", submission)
    state["status"] = "SUBMITTED"
    return {"status": "SUBMITTED", "patch_sha256": sha(patch), "patch_utf8_bytes": len(patch)}


def perform_action(plan, run, cell, request):
    if not isinstance(request, dict) or not isinstance(request.get("op"), str):
        raise ValueError("Expected an object with an op string")
    root = cell_root(run, cell)
    controlled = controlled_lessons(plan)
    with locked(root / "action.lock"):
        state = read(root / "state.json")
        check_action_budget(plan, state, time.time())
        completed_events = audit_events(root)[0] if plan.get("procedure_declaration") is not None or controlled is not None else []
        if controlled is not None:
            from trimem_skhynix_codex_controlled_lessons import restore_delivery
            delivery = restore_delivery(plan, run, cell, completed_events, controlled)
        if state["started_at"] is None:
            state["started_at"] = time.time()
        state["actions"] += 1
        # A pending marker prevents unjournaled edits from being silently resumed.
        if state.get("pending"):
            raise ValueError("Previous action has no receipt; manager review required")
        state["pending"] = sha(canonical(request))
        write(root / "state.json", state)
        try:
            op = request["op"]
            if controlled is not None and op in ("tool", "diff", "submit") and not delivery["successful_recalls"]:
                raise ValueError("Begin with a valid recall before repository tools or submission")
            if op == "info":
                result = read(root / "public-task.json")
            elif op == "begin_procedure":
                result = begin_procedure(plan, run, cell, state, request, completed_events)
            elif op == "tool":
                name, arguments = request.get("name"), request.get("arguments")
                if name not in TOOLS or not isinstance(arguments, dict):
                    raise ValueError("Only declared repository tools are available")
                before_snapshot = None
                if name == "run_command":
                    timeout = arguments.get("timeout_seconds")
                    timeout = 60 if timeout is None else timeout
                    if type(timeout) is not int or not 1 <= timeout <= 120:
                        raise ValueError("Command timeout must be an integer in 1..120")
                    seconds = remaining(plan, state, time.time())["seconds_remaining"]
                    if seconds <= 0:
                        raise ValueError("SOLVER_TIME_LIMIT")
                    arguments = {**arguments, "timeout_seconds": min(timeout, seconds)}
                    before_snapshot = procedure_snapshot(plan, run, cell, completed_events)
                result = workspace_for(plan, run, cell).execute(name, arguments)
                if name == "run_command":
                    result["effective_timeout_seconds"] = arguments["timeout_seconds"]
                    if before_snapshot is not None:
                        result["procedure_snapshot_before"] = before_snapshot
                if name in ("run_command", "write_file", "replace_text"):
                    snapshot = procedure_snapshot(plan, run, cell, completed_events)
                    if snapshot is not None:
                        result["procedure_snapshot"] = snapshot
            elif op == "recall":
                if controlled is not None:
                    from trimem_skhynix_codex_controlled_lessons import recall_controlled
                    result = recall_controlled(plan, run, cell, request.get("query"), completed_events, controlled, state["actions"])
                else:
                    from trimem_skhynix_codex_memory import recall_memory
                    result = recall_memory(root, task_from_plan(plan), CELLS[cell], request["query"], ROOT,
                        **frozen_input_kwargs(plan, "frozen_memory_bank", "frozen_bank"))
            elif op == "diff":
                patch = workspace_for(plan, run, cell).patch()
                result = {"patch": patch[:32000], "truncated": len(patch) > 32000,
                          "patch_sha256": sha(patch.encode()), "patch_utf8_bytes": len(patch.encode())}
            elif op == "submit":
                summary = request.get("summary")
                if not isinstance(summary, str) or not summary.strip() or len(summary) > 8000:
                    raise ValueError("A nonempty bounded completion summary is required")
                snapshot = procedure_snapshot(plan, run, cell, completed_events)
                result = seal_submission(plan, run, cell, state, summary=summary, agent_completed=True,
                    expected_patch_sha256=snapshot["patch_sha256"] if snapshot is not None else None)
                if snapshot is not None:
                    result["procedure_snapshot"] = snapshot
            else:
                raise ValueError("Unknown operation")
            response = {"ok": True, "result": result}
        except Exception as exc:
            # Public tool exceptions only. No provider client or grader is reachable here.
            response = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:2000]}
        response["budget"] = remaining(plan, state, time.time())
        append_event(root, state, request, response)
        state.pop("pending", None)
        write(root / "state.json", state)
        return response


def prepare(args):
    from trimem_skhynix_codex_memory import initialize_memory
    from trimem_skhynix_source_bank import load_validated_source_bank
    experiment_id = validate_experiment_id(getattr(args, "experiment_id", DEFAULT_EXPERIMENT_ID))
    solver_user_id = validate_solver_user_id(getattr(args, "solver_user_id", "native-codex-solver"))
    target_id = getattr(args, "target_id", TARGET)
    if not isinstance(target_id, str) or not target_id or len(target_id) > 256:
        raise ValueError("A bounded target ID from the prepared dataset is required")
    run, work = args.run_root.resolve(), args.workspace_root.resolve()
    for path in (run, work):
        if path.exists() and any(path.iterdir()):
            raise ValueError("Pilot requires fresh output and workspace roots")
    if run == work or run in work.parents or work in run.parents:
        raise ValueError("Evidence and workspaces must be disjoint")
    run.mkdir(parents=True, exist_ok=True)
    plan = {"schema": SCHEMA, "experiment_id": experiment_id, "solver_user_id": solver_user_id,
            "solver_identity_role": "Native agent contributor identifier; not evidence of distinct human users",
            "cells": CELLS,
            "requested_solver_model": "gpt-6-astra", "model_snapshot_attested": False,
            "execution": "fresh Codex subagent per cell; fork_turns=none",
            "separate_model_api_calls": 0, "codex_tokens_and_cost": None,
            "limits": dict(LIMITS),
            "scope": "one previously examined DEV target; integration pilot, not a heldout estimate",
            "l0_projection": "native Codex context; existing SkhynixAgentRuntime projection NOT applied",
            "host_isolation": "fresh conversation plus protocol-restricted broker; host tools remain available",
            "sandbox": "base-only separate checkouts; command containers pinned, nonroot, network none",
            "memory_learning": "immutable historical PR bank; no online Gate A/B or L3 skills",
            "target_selection": "Explicit target from the prepared dataset; one target per execution directory",
            "empty_patch_policy": "official grading of separately marked canonical noop",
            "source_hashes": source_hashes(),
            "base_git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                capture_output=True, text=True, check=True).stdout.strip(),
            "paths": {"workspace_root": str(work), "dataset_cache_root": str(args.dataset_cache_root.resolve()),
                      "harness_root": str(args.harness_root.resolve()),
                      "loader_preflight_path": str(args.loader_preflight_path.resolve()) if args.loader_preflight_path else None},
            "public_python": args.public_python,
            "public_test_guidance": "Use run_command with the repository's public tests. run_public_tests is not exposed."}
    plan["supplemental_manifest"] = frozen_input(getattr(args, "supplemental_manifest", None))
    plan["frozen_memory_bank"] = frozen_input(getattr(args, "frozen_memory_bank", None))
    plan["procedure_declaration"] = frozen_input(getattr(args, "procedure_declaration", None))
    if getattr(args, "controlled_lesson_manifest", None) is not None:
        from trimem_skhynix_codex_controlled_lessons import LABELS, ROLE
        if plan["frozen_memory_bank"] is not None or plan["procedure_declaration"] is not None:
            raise ValueError("Controlled lessons are exclusive with a memory bank or procedure declaration")
        plan["controlled_lesson_manifest"] = frozen_input(args.controlled_lesson_manifest)
        plan["experimental_arms"], plan["scientific_role"] = dict(LABELS), ROLE
        plan["memory_learning"] = "Controlled content transfer; preassigned source-only analyst lessons, no retrieval, Gate B promotion or L3 learning"
    if plan["supplemental_manifest"] is not None:
        plan["scope"] = "One supplemental task outside the original DEV manifests; role fixed by supplemental manifest"
    if plan["frozen_memory_bank"] is not None:
        cold_start = read(Path(plan["frozen_memory_bank"]["path"])).get("cold_start") is True
        plan["memory_learning"] = ("Frozen empty cold-start bank; no learned records or online Gate A/B updates"
            if cold_start else "Frozen learned bank from separate training tasks; no evaluation-time Gate A/B updates")
    env = environment(plan, run)
    if plan["paths"]["loader_preflight_path"] is None:
        plan["paths"]["loader_preflight_path"] = str(
            run / "environment/control/official-harness-loader-preflight.json")
    matches = [t for t in env.tasks if t.task_id == target_id]
    if len(matches) != 1 or target_id not in env.targets_by_id:
        raise ValueError("Target ID must identify exactly one known prepared dataset task")
    original = matches[0]
    task = replace(original, org_id=plan["experiment_id"], user_id=solver_user_id)
    plan["public_task"] = task.public_payload()
    if plan.get("controlled_lesson_manifest") is not None:
        plan["source_bank"] = {"kind": "CONTROLLED_CONTENT_TRANSFER_EMPTY_MEMORY_PROJECTION",
            "sha256": plan["controlled_lesson_manifest"]["sha256"], "verified_skill_count": 0}
    elif plan["frozen_memory_bank"] is None:
        plan["source_bank"] = dict(load_validated_source_bank().report)
    else:
        plan["source_bank"] = {"kind": "FROZEN_COLD_START_EMPTY_BANK" if cold_start else "FROZEN_LEARNED_BANK",
                               "sha256": plan["frozen_memory_bank"]["sha256"],
                               "validation": "Validated by memory bridge for each cell"}
    plan["target"] = dict(env.targets_by_id[target_id])
    planned_target_id(plan)
    declaration = procedure_declaration(plan)
    certificate = workflow_runtime_certificate(plan)
    controlled = controlled_lessons(plan)
    # Use the same scoped task in environment preparation and grader construction.
    env.tasks = tuple(task if t.task_id == target_id else t for t in env.tasks)
    for cell, arm in CELLS.items():
        root = cell_root(run, cell)
        root.mkdir(parents=True)
        prepared = env.prepare_cell(arm, task)
        workspace = prepared.workspace_factory(task)
        runner = workspace.command_runner
        if certificate is not None and runner.image != certificate["source_image"]:
            raise ValueError("Workflow certificate differs from the prepared image")
        if controlled is not None:
            from trimem_skhynix_codex_controlled_lessons import projection as controlled_projection
            projection = controlled_projection(plan, run, cell, controlled)
        else:
            projection = initialize_memory(root, task, arm, ROOT,
                **frozen_input_kwargs(plan, "frozen_memory_bank", "frozen_bank"))
        write(root / "bank-projection.json", projection)
        write(root / "workspace.json", {"plan_sha256": sha(canonical(plan)),
            "checkout_root": str(workspace.root), "image": runner.image,
            "masked_image_files": list(runner.masked_image_files),
            "masked_image_directories": list(runner.masked_image_directories),
            "command_runner_sha256": runner.content_hash})
        packet = {"cell": cell, "experiment_id": experiment_id, "target_id": target_id,
                  "solver_user_id": solver_user_id,
                  "task": task.public_payload(), "limits": plan["limits"],
                  "public_python": args.public_python, "tools": sorted(TOOLS),
                  "memory": "Query the provided recall operation for your current subgoal; use only returned records.",
                  "context": "Native Codex history; no special subgoal truncation is applied.",
                  "submission": "Submit once after relevant edits and public tests. Official grading happens after submission.",
                  "test_guidance": plan["public_test_guidance"]}
        if controlled is not None:
            packet["memory"] = "Begin with recall for your current subgoal before using repository tools. Use any returned lesson as unverified guidance and validate your changes."
        if declaration is not None:
            packet["training_procedure"] = declaration
            packet["procedure_guidance"] = (
                "After inspecting the source and public test module, call begin_procedure with "
                "source_path, test_path and canonical JSON test_argv bindings before any edits. "
                "Add an undecorated test_ function containing an assertion. Run the declared command "
                "while implementation is unchanged and observe its assertion failure. Then fix the "
                "implementation, keep the regression test unchanged and rerun the same command until "
                "it passes. The final passing command must verify the submitted patch. "
                "This records a regression verification workflow; it does not prove all issue cases.")
            if declaration.get("procedure_id") in ("python-public-named-regression-red-green-v2",
                    "python-public-multisource-named-regression-red-green-v3"):
                packet["procedure_guidance"] = declaration["public_instructions"]
        write(root / "public-task.json", packet)
        write(root / "state.json", {"status": "OPEN", "actions": 0, "started_at": None,
                                     "tail_sha256": "0" * 64})
    write(run / "plan.json", plan)
    (run / "plan.sha256").write_text(sha(canonical(plan)) + "\n", encoding="ascii")
    print(json.dumps({"status": "READY", "cells": 3, "target_id": target_id,
                      "experiment_id": experiment_id,
                      "plan_sha256": sha(canonical(plan)), "separate_model_api_calls": 0}))


def audit_events(root):
    tail, sequence, rows = "0" * 64, 0, []
    path = root / "tool-events.jsonl"
    for line in path.read_bytes().splitlines() if path.exists() else []:
        row = json.loads(line)
        digest = row.pop("sha256")
        if row["sequence"] != sequence + 1 or row["previous_sha256"] != tail or sha(canonical(row)) != digest:
            raise ValueError("Tool event chain mismatch")
        tail, sequence = digest, sequence + 1
        rows.append(row)
    state = read(root / "state.json")
    if state["tail_sha256"] != tail or state["actions"] != sequence or state.get("pending"):
        raise ValueError("State and tool receipts differ")
    return rows, tail


def grade(plan, run, cell):
    from enterprise_memory.trimem.agent_runtime import CANONICAL_FAILED_CELL_NOOP
    from enterprise_memory.trimem.grader import GradeRequest
    target_id = planned_target_id(plan)
    root = cell_root(run, cell)
    controlled = controlled_lessons(plan)
    with locked(root / "action.lock"):
        submission = read(root / "submission.json")
        state = read(root / "state.json")
        if (submission["plan_sha256"] != sha(canonical(plan)) or submission["cell"] != cell or
                submission["experiment_id"] != plan["experiment_id"] or
                submission["arm"] != CELLS[cell] or submission["target_id"] != target_id or
                submission["actions"] != state["actions"] or state["status"] != "SUBMITTED"):
            raise ValueError("Submission identity, state or action count differs")
        raw = (root / "submission.diff").read_bytes()
        if sha(raw) != submission["patch_sha256"]:
            raise ValueError("Submitted patch changed")
        events, tail = audit_events(root)
        if controlled is not None:
            from trimem_skhynix_codex_controlled_lessons import restore_delivery
            restore_delivery(plan, run, cell, events, controlled)
        if workspace_for(plan, run, cell).patch().encode() != raw:
            raise ValueError("Checkout changed after submission")
        if (root / "public-result.json").exists():
            cached = read(root / "public-result.json")
            validate_result(plan, cell, cached)
            if (cached["patch_sha256"] != sha(raw) or cached["tool_event_tail_sha256"] != tail or
                    cached["grader_private_sha256"] != sha((root / "grader-private.json").read_bytes())):
                raise ValueError("Existing grade receipt changed")
            return cached
        pending = root / "grader-pending.json"
        if pending.exists():
            raise ValueError("A grading invocation needs recovery; refusing duplicate execution")
        task = task_from_plan(plan)
        env = environment(plan, run)
        env.tasks = tuple(task if t.task_id == target_id else t for t in env.tasks)
        prepared = env.prepare_cell(CELLS[cell], task, resume=True)
        patch = raw.decode() if raw else CANONICAL_FAILED_CELL_NOOP
        write(pending, {"patch_sha256": sha(patch.encode()), "started_at": time.time()})
        result = prepared.grader.grade(GradeRequest(task.task_id, task.repository, task.commit,
            patch, prepared.workspace_factory(task).grader_context(base_commit=task.commit)))
        if result.official is not True or result.container_started is not True or result.status != "success":
            raise RuntimeError("Official grader did not complete successfully")
        write(root / "grader-private.json", {"report": result.report, "stdout": result.stdout,
                                             "stderr": result.stderr, "resolved": result.resolved})
        memory = [event["result"]["result"] for event in events
                  if event["request"]["op"] == "recall" and event["result"]["ok"]]
        injections = {item["memory_id"]: item for response in memory for item in response.get("injections", [])}
        commands = [event for event in events if event["request"].get("name") == "run_command"]
        row = {"schema": SCHEMA, "cell": cell, "arm": CELLS[cell], "target_id": target_id,
               "experiment_id": plan["experiment_id"],
               "plan_sha256": sha(canonical(plan)), "official": True, "resolved": bool(result.resolved),
               "grader_status": result.status, "grader_id": result.grader_id,
               "container_digest": result.container_digest, "grader_wall_time_ms": result.wall_time_ms,
               "agent_completed": submission["agent_completed"], "actions": len(events),
               "wall_seconds": submission["submitted_at"] - (submission["started_at"] or submission["submitted_at"]),
               "patch_sha256": sha(raw), "patch_utf8_bytes": len(raw),
               "grader_patch_sha256": sha(patch.encode()),
               "grader_patch_source": "NATIVE_CODEX_PATCH" if raw else "CANONICAL_FAILED_CELL_NOOP",
               "tool_event_tail_sha256": tail, "tool_errors": sum(not e["result"]["ok"] for e in events),
               "memory_queries": len(memory), "memory_injections": len(injections),
               "memory_bytes": sum(item["byte_count"] for item in injections.values()),
               "injected_memory_ids": sorted(injections), "command_count": len(commands),
               "successful_commands": sum(e["result"]["ok"] and e["result"]["result"].get("exit_code") == 0 for e in commands),
               "separate_model_api_calls": 0, "codex_tokens_and_cost": None,
               "requested_solver_model": plan["requested_solver_model"],
               "grader_private_sha256": sha((root / "grader-private.json").read_bytes())}
        if controlled is not None:
            row.update(scientific_role=plan["scientific_role"], experimental_arm=plan["experimental_arms"][cell],
                controlled_lesson_manifest_sha256=controlled.sha256)
        write(root / "public-result.json", row)
        return row


def validate_result(plan, cell, row):
    if (row.get("schema") != SCHEMA or row.get("plan_sha256") != sha(canonical(plan)) or
            row.get("experiment_id") != plan["experiment_id"] or
            row.get("cell") != cell or row.get("arm") != CELLS[cell] or
            row.get("target_id") != planned_target_id(plan) or
            row.get("official") is not True or type(row.get("resolved")) is not bool or
            row.get("grader_status") != "success"):
        raise ValueError("Official result identity or status differs")
    if plan.get("controlled_lesson_manifest") is not None and (
            row.get("scientific_role") != plan["scientific_role"] or
            row.get("experimental_arm") != plan["experimental_arms"][cell] or
            row.get("controlled_lesson_manifest_sha256") != plan["controlled_lesson_manifest"]["sha256"]):
        raise ValueError("Controlled result experimental binding differs")


def report(plan, run):
    controlled = controlled_lessons(plan)
    rows = []
    for cell in CELLS:
        path = cell_root(run, cell) / "public-result.json"
        if path.exists():
            row = read(path)
            validate_result(plan, cell, row)
            rows.append(row)
    complete = len(rows) == len(CELLS)
    value = {"schema": SCHEMA, "status": "COMPLETE" if complete else "INCOMPLETE",
             "experiment_id": plan["experiment_id"], "target_id": planned_target_id(plan),
             "plan_sha256": sha(canonical(plan)), "planned_targets": 1, "planned_cells": 3,
             "completed_cells": len(rows), "fully_paired_targets": int(complete), "cells": rows,
             "separate_model_api_calls": 0, "codex_tokens_and_cost": None,
             "comparison": {r["arm"]: {"resolved": int(r["resolved"]), "n": 1,
                 "solve_rate": float(r["resolved"])} for r in rows} if complete else None,
             "limitations": [plan["scope"], plan["l0_projection"], plan["host_isolation"], plan["memory_learning"],
                             "Different model and harness from live001/live002; no causal cross-run memory claim."]}
    if controlled is not None:
        value.update(scientific_role=plan["scientific_role"], experimental_arms=plan["experimental_arms"],
            controlled_lesson_manifest_sha256=controlled.sha256,
            controlled_comparison={r["experimental_arm"]: {"resolved": int(r["resolved"]), "n": 1,
                "solve_rate": float(r["resolved"])} for r in rows} if complete else None)
    write(run / "report.json", value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--run-root", type=Path, required=True)
    prep.add_argument("--workspace-root", type=Path, required=True)
    prep.add_argument("--dataset-cache-root", type=Path, required=True)
    prep.add_argument("--harness-root", type=Path, required=True)
    prep.add_argument("--loader-preflight-path", type=Path)
    prep.add_argument("--target-id", default=TARGET)
    prep.add_argument("--experiment-id", default=DEFAULT_EXPERIMENT_ID)
    prep.add_argument("--solver-user-id", default="native-codex-solver")
    prep.add_argument("--supplemental-manifest", type=Path)
    prep.add_argument("--frozen-memory-bank", type=Path)
    prep.add_argument("--procedure-declaration", type=Path)
    prep.add_argument("--controlled-lesson-manifest", type=Path)
    prep.add_argument("--public-python", required=True)
    for name in ("action", "seal", "grade", "report"):
        item = sub.add_parser(name)
        item.add_argument("--run-root", type=Path, required=True)
        if name != "report":
            item.add_argument("--cell", choices=tuple(CELLS), required=True)
        if name == "action":
            item.add_argument("--request-base64", required=True)
    args = parser.parse_args()
    block_model_client()
    if args.command == "prepare":
        prepare(args)
        return
    run = args.run_root.resolve()
    plan = load_plan(run)
    if args.command == "action":
        raw = base64.b64decode(args.request_base64, validate=True)
        if len(raw) > 262144:
            raise ValueError("Request too large")
        value = perform_action(plan, run, args.cell, json.loads(raw))
    elif args.command == "seal":
        root = cell_root(run, args.cell)
        with locked(root / "action.lock"):
            state = read(root / "state.json")
            audit_events(root)
            value = seal_submission(plan, run, args.cell, state, summary="Manager sealed available partial patch",
                                    agent_completed=False)
            write(root / "state.json", state)
    elif args.command == "grade":
        value = grade(plan, run, args.cell)
        report(plan, run)
    else:
        value = report(plan, run)
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
