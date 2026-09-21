"""Persistent native architecture broker; no model or grader client is reachable.

Managers prepare/admit/seal; workers use authenticated ``action`` only. Host
tool restrictions remain a launcher protocol, not a new OS security boundary.
The same planner, graph transitions and whole-task budgets apply to both arms.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from dataclasses import asdict, fields
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from enterprise_memory.trimem.accounting import canonical_bytes, strict_json_loads
from enterprise_memory.trimem.native_architecture_context import (
    HandoffBinding, HandoffLimits, HandoffMemory, NativeHandoffPacket,
    TaskHandoffContext, validate_handoff,
)
from enterprise_memory.trimem.working_graph import Evidence, ShortTermWorkingGraph, SubtaskSpec
import trimem_skhynix_host_profile as host_profile


SCHEMA = "skhynix/native-architecture-broker/1.0"
TOOLS = frozenset({"list_files", "read_file", "search", "write_file", "replace_text", "run_command"})
ARMS = frozenset({"BASELINE", "PDF_MEMORY"})
ZERO = "0" * 64


class BrokerError(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value: bytes):
    return hashlib.sha256(value).hexdigest()


def read(path):
    return strict_json_loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def write_once(path, value):
    path = Path(path)
    raw = canonical(value) + b"\n"
    if path.exists():
        if path.read_bytes() != raw:
            raise BrokerError("immutable broker artifact already exists with different bytes")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def identity(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}", value):
        raise BrokerError(f"invalid {label}")
    return value


def digest(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise BrokerError(f"invalid {label}")
    return value


@contextmanager
def locked(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class ArchitectureBroker:
    def __init__(self, root, *, workspace, configuration_sha256, bank_sha256,
                 memory_callback: Callable | None = None, clock=time.time):
        self.root = Path(root).resolve()
        self.workspace = workspace
        self.clock = clock
        self.memory_callback = memory_callback
        self.configuration_sha256 = digest(configuration_sha256, "configuration SHA")
        self.bank_sha256 = digest(bank_sha256, "bank SHA")
        self.manifest = read(self.root / "manifest.json")
        expected = (self.root / "manifest.sha256").read_text(encoding="ascii").strip()
        if sha(canonical(self.manifest)) != expected or self.manifest.get("schema") != SCHEMA:
            raise BrokerError("broker manifest changed")
        if (self.manifest["configuration_sha256"] != configuration_sha256
                or self.manifest["bank_sha256"] != bank_sha256):
            raise BrokerError("broker frozen configuration or bank changed")
        self.limits = HandoffLimits(**self.manifest["limits"])
        self.arm = self.manifest["arm"]
        self.task = self.manifest["task"]

    @classmethod
    def create(cls, root, *, task_public, arm, workspace, configuration_sha256,
               bank_sha256, tool_schema, limits=HandoffLimits(), memory_callback=None,
               clock=time.time, workspace_configuration=None):
        root = Path(root).resolve()
        if root.exists():
            raise BrokerError("refusing to overwrite a broker run")
        if arm not in ARMS or not isinstance(limits, HandoffLimits):
            raise BrokerError("invalid arm or task limits")
        digest(configuration_sha256, "configuration SHA")
        digest(bank_sha256, "bank SHA")
        graph = ShortTermWorkingGraph(task_public["task_id"], task_public["instruction"], task_public["repository"])
        TaskHandoffContext(task=task_public, graph=graph, history=[], tool_schema=tool_schema)
        manifest = {"schema": SCHEMA, "task": task_public, "arm": arm,
            "configuration_sha256": configuration_sha256, "bank_sha256": bank_sha256,
            "tool_schema": tool_schema, "limits": asdict(limits),
            "workspace_configuration": workspace_configuration,
            "policy": "COMMON_SEMANTIC_SUBGOAL_TRANSITIONS_FRESH_WORKER",
            "host_isolation": "LAUNCHER_PROTOCOL_NOT_OS_BOUNDARY", "separate_model_api_calls": 0}
        canonical(manifest)
        root.mkdir(parents=True)
        write(root / "manifest.json", manifest)
        (root / "manifest.sha256").write_text(sha(canonical(manifest)) + "\n", encoding="ascii")
        initial = {"status": "WAITING_HANDOFF", "actions": 0, "started_at": None,
            "graph": graph.snapshot(), "history": [], "workers": {}, "current_worker": None,
            "last_packet": None, "memory_checkpoint": {}, "memory_queries": {},
            "memory_ledger": [], "tool_errors": 0, "unfinished_actions": 0,
            "submission": None}
        write(root / "initial-state.json", initial)
        manifest["initial_state_sha256"] = sha(canonical(initial))
        write(root / "manifest.json", manifest)
        (root / "manifest.sha256").write_text(sha(canonical(manifest)) + "\n", encoding="ascii")
        write(root / "state.json", initial)
        (root / "events.jsonl").write_bytes(b"")
        broker = cls(root, workspace=workspace, configuration_sha256=configuration_sha256,
                     bank_sha256=bank_sha256, memory_callback=memory_callback, clock=clock)
        return broker

    def _events(self):
        events, previous = [], ZERO
        for line in (self.root / "events.jsonl").read_bytes().splitlines():
            row = strict_json_loads(line)
            value = {key: item for key, item in row.items() if key != "sha256"}
            if (row.get("sequence") != len(events) + 1 or row.get("previous_sha256") != previous
                    or row.get("sha256") != sha(canonical(value))):
                raise BrokerError("broker event chain changed")
            previous = row["sha256"]
            events.append(row)
        return events

    def _append(self, event):
        with (self.root / "events.jsonl").open("ab") as stream:
            stream.write(canonical(event) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _recover_finished(self):
        path = self.root / "pending.json"
        if not path.exists():
            return
        pending = read(path)
        if pending.get("phase") != "FINISHED":
            raise BrokerError("unfinished broker action; manager must seal the partial patch")
        event, state = pending["event"], pending["state"]
        if event["state_after_sha256"] != sha(canonical(state)):
            raise BrokerError("pending committed state changed")
        events = self._events()
        if len(events) == event["sequence"] - 1:
            previous = events[-1]["sha256"] if events else ZERO
            if event["previous_sha256"] != previous:
                raise BrokerError("pending commit predecessor differs")
            if sha(canonical({k: v for k, v in event.items() if k != "sha256"})) != event["sha256"]:
                raise BrokerError("pending event hash changed")
            self._append(event)
        elif not events or events[-1] != event:
            raise BrokerError("pending event differs from committed journal")
        write(self.root / "state.json", state)
        path.unlink()

    def _load(self):
        self._recover_finished()
        state, events = read(self.root / "state.json"), self._events()
        if sha(canonical(read(self.root / "initial-state.json"))) != self.manifest["initial_state_sha256"]:
            raise BrokerError("initial checkpoint differs from frozen manifest")
        expected = events[-1]["state_after_sha256"] if events else sha(canonical(read(self.root / "initial-state.json")))
        if sha(canonical(state)) != expected:
            raise BrokerError("broker checkpoint differs from event chain")
        observed = [event["history_row"] for event in events if event.get("history_row") is not None]
        if observed != state["history"] or any(row.get("arm") != self.arm for row in state["history"]):
            raise BrokerError("exact public history differs from canonical arm event rows")
        if state["actions"] != sum(event["kind"] == "WORKER_ACTION" for event in events) + state["unfinished_actions"]:
            raise BrokerError("whole-task request count differs from journal")
        if state["submission"] is not None:
            if (read(self.root / "submission.json") != state["submission"]
                    or sha((self.root / "submission.diff").read_bytes()) != state["submission"]["patch_sha256"]):
                raise BrokerError("sealed submission artifact changed")
        return state, events

    def _commit(self, state, events, *, kind, request, response, history_row=None):
        event = {"sequence": len(events) + 1, "at": self.clock(), "kind": kind,
            "request": request, "response": response, "history_row": history_row,
            "previous_sha256": events[-1]["sha256"] if events else ZERO,
            "state_after_sha256": sha(canonical(state))}
        event["sha256"] = sha(canonical(event))
        write(self.root / "pending.json", {"phase": "FINISHED", "event": event, "state": state})
        self._append(event)
        write(self.root / "state.json", state)
        (self.root / "pending.json").unlink()

    def _remaining(self, state):
        elapsed = 0.0 if state["started_at"] is None else self.clock() - state["started_at"]
        if elapsed < 0:
            raise BrokerError("clock moved behind the whole-task start")
        return {"requests_remaining": max(0, self.limits.task_requests - state["actions"]),
            "seconds_remaining": max(0, int(self.limits.task_seconds - elapsed)),
            "requests_used": state["actions"], "elapsed_seconds": elapsed}

    def _owner(self, state):
        return TaskHandoffContext(task=self.task, graph=ShortTermWorkingGraph.from_snapshot(state["graph"]),
            history=state["history"], tool_schema=self.manifest["tool_schema"])

    def _packet(self, name):
        value = read(self.root / "packets" / name)
        binding = HandoffBinding(**value["body"]["binding"])
        return NativeHandoffPacket(binding, value["sha256"], value["body"])

    def _recall(self, state):
        graph = ShortTermWorkingGraph.from_snapshot(state["graph"])
        node = graph.active_node
        if node is None:
            return {"injections": [], "decisions": [], "repeat": False}
        if node.node_id in state["memory_queries"]:
            return {**state["memory_queries"][node.node_id], "repeat": True}
        query = {"node_id": node.node_id, "objective": node.objective, "operation": node.operation,
            "symbols": list(node.symbols), "apis": list(node.apis), "errors": list(node.errors)}
        if self.arm == "BASELINE":
            result = {"injections": [], "checkpoint": state["memory_checkpoint"], "decisions": []}
        else:
            if self.memory_callback is None:
                raise BrokerError("PDF_MEMORY requires the frozen architecture memory callback")
            result = self.memory_callback(self.task, graph, query, state["memory_checkpoint"])
        if not isinstance(result, dict) or set(result) != {"injections", "checkpoint", "decisions"}:
            raise BrokerError("memory callback response schema differs")
        if not isinstance(result["checkpoint"], dict) or not isinstance(result["decisions"], list):
            raise BrokerError("memory checkpoint and decisions must be object and list")
        items = result["injections"]
        if not isinstance(items, (list, tuple)) or any(not isinstance(item, HandoffMemory) for item in items):
            raise BrokerError("memory callback must return typed handoff memories")
        if any(item.bank_sha256 != self.bank_sha256 or item.active_node_id != node.node_id for item in items):
            raise BrokerError("memory callback bank or active subgoal differs")
        prior_ids = {item["memory_id"] for item in state["memory_ledger"]}
        if len({item.memory_id for item in items}) != len(items) or any(item.memory_id in prior_ids for item in items):
            raise BrokerError("memory callback repeated an already delivered record")
        ledger = state["memory_ledger"] + [asdict(item) for item in items]
        if (len(ledger) > self.limits.max_memory_injections or
                sum(len(item["exact_text"].encode()) for item in ledger) > self.limits.max_memory_bytes):
            raise BrokerError("whole-task memory budget exceeded")
        canonical(result["checkpoint"])
        canonical(result["decisions"])
        state["memory_checkpoint"] = result["checkpoint"]
        state["memory_ledger"] = ledger
        receipt = {"query": query, "injections": [asdict(item) for item in items],
            "decisions": result["decisions"], "repeat": False}
        state["memory_queries"][node.node_id] = receipt
        return receipt

    def issue_handoff(self, worker_id):
        identity(worker_id, "worker ID")
        with locked(self.root / "broker.lock"):
            state, events = self._load()
            if state["status"] != "WAITING_HANDOFF" or worker_id in state["workers"]:
                raise BrokerError("task is not waiting for a new unique worker")
            remaining = self._remaining(state)
            if remaining["seconds_remaining"] <= 0 or remaining["requests_remaining"] <= 0:
                raise BrokerError("whole-task request or wall budget exhausted")
            recall = self._recall(state)
            previous = self._packet(state["last_packet"]) if state["last_packet"] else None
            packet = self._owner(state).build_handoff(arm=self.arm, worker_id=worker_id,
                configuration_sha256=self.configuration_sha256, bank_sha256=self.bank_sha256,
                limits=self.limits, memory_injections=[HandoffMemory(**item) for item in recall["injections"]],
                previous_packet=previous)
            name = f"{len(state['workers']) + 1:04d}.json"
            write_once(self.root / "packets" / name, packet.public_dict())
            write_once(self.root / "packet-owners" / name, {"graph": state["graph"], "history": state["history"]})
            state["workers"][worker_id] = {"status": "ISSUED", "packet_file": name,
                "packet_sha256": packet.sha256, "issued_at": self.clock()}
            state["last_packet"], state["current_worker"] = name, worker_id
            state["status"] = "WAITING_ADMISSION"
            response = {"worker_id": worker_id, "packet": packet.public_dict(),
                "packet_sha256": packet.sha256, "budget": self._remaining(state)}
            self._commit(state, events, kind="ISSUE_HANDOFF", request={"worker_id": worker_id}, response=response)
            return response

    def admit_worker(self, worker_id, packet_sha256, launch_receipt):
        required = {"thread_id", "fork_turns", "fresh_session", "requested_model", "launch_evidence_sha256"}
        if not isinstance(launch_receipt, dict) or set(launch_receipt) != required:
            raise BrokerError("actual native launch receipt fields differ")
        identity(launch_receipt["thread_id"], "actual thread ID")
        digest(launch_receipt["launch_evidence_sha256"], "launch evidence SHA")
        if launch_receipt["requested_model"] != host_profile.solver()["model"]:
            raise BrokerError("native requested model differs")
        with locked(self.root / "broker.lock"):
            state, events = self._load()
            worker = state["workers"].get(worker_id)
            if state["status"] != "WAITING_ADMISSION" or state["current_worker"] != worker_id or worker is None:
                raise BrokerError("worker was not issued the current handoff")
            if any(row.get("thread_id") == launch_receipt["thread_id"] for row in state["workers"].values()):
                raise BrokerError("actual native thread was already used")
            packet = self._packet(worker["packet_file"])
            if packet_sha256 != worker["packet_sha256"]:
                raise BrokerError("admission packet hash differs")
            validate_handoff(packet.public_dict(), expected_binding=packet.binding,
                expected_sha256=packet_sha256, fork_turns=launch_receipt["fork_turns"],
                new_worker=launch_receipt["fresh_session"])
            token = secrets.token_hex(32)
            worker.update(status="ADMITTED", thread_id=launch_receipt["thread_id"],
                launch_receipt=launch_receipt, admission_token_sha256=sha(token.encode()), admitted_at=self.clock(),
                delivered_memory_ids=[item["memory_id"] for item in packet.public_dict()["body"]["memory_injections"]])
            state["status"] = "RUNNING"
            response = {"worker_id": worker_id, "thread_id": worker["thread_id"],
                "packet_sha256": packet_sha256, "admitted": True}
            self._commit(state, events, kind="ADMIT_WORKER", request=launch_receipt, response=response)
            return {**response, "admission_token": token}

    def _revoke(self, state, worker_id, reason):
        state["workers"][worker_id].update(status="REVOKED", revoked_at=self.clock(), revocation_reason=reason)
        state["current_worker"] = None

    def revoke_worker(self, worker_id, *, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise BrokerError("revocation reason is required")
        with locked(self.root / "broker.lock"):
            state, events = self._load()
            if state["current_worker"] != worker_id or state["status"] not in {"RUNNING", "WAITING_ADMISSION"}:
                raise BrokerError("worker is not current")
            self._revoke(state, worker_id, reason)
            state["status"] = "TERMINATED"
            self._commit(state, events, kind="REVOKE_WORKER", request={"worker_id": worker_id, "reason": reason},
                         response={"status": "TERMINATED"})

    def _history_row(self, state, node_id, tool, arguments, result, *, status="success"):
        request = {"tool": tool, "arguments": arguments}
        return {"task_id": self.task["task_id"], "arm": self.arm, "step_no": state["actions"],
            "active_node_id": node_id, "tool": tool, "status": status,
            "request_payload": request, "result_payload": result,
            "request": {"sha256": sha(canonical(request)), "bytes": len(canonical(request))},
            "result": {"sha256": sha(canonical(result)), "bytes": len(canonical(result))}}

    def _seal(self, state, *, summary, completed, reason):
        if state["submission"] is not None:
            raise BrokerError("a patch has already been sealed")
        patch = self.workspace.patch()
        if not isinstance(patch, str):
            raise BrokerError("workspace patch must be UTF-8 text")
        raw = patch.encode()
        path = self.root / "submission.diff"
        if path.exists() and path.read_bytes() != raw:
            raise BrokerError("partial submission artifact already differs")
        path.write_bytes(raw)
        submission = {"schema": "skhynix/native-architecture-submission/1.0", "task_id": self.task["task_id"],
            "arm": self.arm, "configuration_sha256": self.configuration_sha256, "bank_sha256": self.bank_sha256,
            "patch_sha256": sha(raw), "patch_utf8_bytes": len(raw), "summary": summary,
            "agent_completed": completed, "reason": reason, "submitted_at": self.clock(),
            "actions": state["actions"], "started_at": state["started_at"], "separate_model_api_calls": 0}
        state["submission"], state["status"] = submission, "SUBMITTED"
        if state["current_worker"] is not None:
            self._revoke(state, state["current_worker"], "PATCH_SEALED")
        write(self.root / "submission.json", submission)
        return submission

    def _dispatch(self, state, worker_id, request):
        op = request["op"]
        allowed = {
            "info": {"op"}, "plan_subgoals": {"op", "subgoals"},
            "activate_subgoal": {"op", "node_id"}, "tool": {"op", "name", "arguments"},
            "complete_subgoal": {"op", "summary", "evidence_steps"}, "recall": {"op"},
            "trace": {"op", "subgoal_id", "max_bytes", "start_after_step"},
            "trace_chunk": {"op", "subgoal_id", "step_no", "offset_bytes", "max_bytes"},
            "diff": {"op"}, "submit": {"op", "summary"},
        }
        if op not in allowed or set(request) != allowed[op]:
            raise BrokerError("unknown operation or request fields")
        graph = ShortTermWorkingGraph.from_snapshot(state["graph"])
        node_id, history_row = graph.active_node_id, None
        if op == "info":
            return {"task": strict_json_loads(canonical(self.task)), "arm": self.arm, "graph": self._owner(state)._common_graph(),
                    "status": state["status"], "budget": self._remaining(state)}, None
        if op == "plan_subgoals":
            specs = request["subgoals"]
            if not isinstance(specs, list) or not specs or len(specs) > 32:
                raise BrokerError("declare one to 32 semantic subgoals per planning request")
            for spec in specs:
                if not isinstance(spec, dict) or set(spec) - {item.name for item in fields(SubtaskSpec)}:
                    raise BrokerError("semantic subgoal fields differ")
                identity(spec.get("node_id"), "subgoal ID")
                graph.add_subtask(SubtaskSpec(**spec))
            result = {"dag_revised": True, "added_node_ids": [spec["node_id"] for spec in specs]}
            if node_id is not None:
                history_row = self._history_row(state, node_id, "revise_subtask_dag", {"subgoals": specs}, result)
        elif op == "activate_subgoal":
            if graph.active_node_id is not None:
                raise BrokerError("complete the active subgoal before a transition")
            graph.activate(request["node_id"])
            self._revoke(state, worker_id, "SEMANTIC_SUBGOAL_TRANSITION")
            state["status"] = "WAITING_HANDOFF"
            result = {"handoff_required": True, "active_node_id": graph.active_node_id, "worker_must_stop": True}
        elif op == "tool":
            if node_id is None:
                raise BrokerError("repository tools require an active semantic subgoal")
            name, arguments = request["name"], request["arguments"]
            if name not in TOOLS or not isinstance(arguments, dict):
                raise BrokerError("only bounded public repository tools are available")
            arguments = strict_json_loads(canonical(arguments))
            if name == "run_command":
                timeout = arguments.get("timeout_seconds", 60)
                if type(timeout) is not int or not 1 <= timeout <= 120:
                    raise BrokerError("command timeout must be an integer in 1..120")
                arguments["timeout_seconds"] = min(timeout, self._remaining(state)["seconds_remaining"])
                if arguments["timeout_seconds"] <= 0:
                    raise BrokerError("whole-task wall budget exhausted")
            try:
                result = self.workspace.execute(name, arguments)
            except Exception as exc:
                result = {"error": type(exc).__name__, "message": str(exc)[:2000]}
                state["tool_errors"] += 1
            if not isinstance(result, dict):
                raise BrokerError("public workspace result must be a JSON object")
            history_row = self._history_row(state, node_id, name, arguments, result,
                                           status="error" if "error" in result else "success")
        elif op == "complete_subgoal":
            if node_id is None:
                raise BrokerError("there is no active semantic subgoal")
            summary, steps = request["summary"], request["evidence_steps"]
            if not isinstance(summary, str) or not summary.strip() or len(summary.encode()) > 4000:
                raise BrokerError("completion summary must be nonempty bounded public text")
            if not isinstance(steps, list) or not steps or any(type(step) is not int for step in steps) or len(set(steps)) != len(steps):
                raise BrokerError("completion requires distinct actual public evidence steps")
            rows = {row["step_no"]: row for row in state["history"] if row["active_node_id"] == node_id}
            if any(step not in rows for step in steps):
                raise BrokerError("completion evidence does not belong to this active subgoal")
            support = [{"step_no": step, "result_sha256": rows[step]["result"]["sha256"]} for step in steps]
            graph.complete_active(Evidence.capture("PUBLIC_TOOL_REFERENCES", summary, support,
                supports_completion=True, source="native broker completion; not a CI success label"))
            result = {"completed": True, "evidence": summary}
            history_row = self._history_row(state, node_id, "complete_subtask", {"evidence": summary}, result)
            ready = graph.ready_nodes()
            if ready:
                graph.activate(ready[0].node_id)
                self._revoke(state, worker_id, "SEMANTIC_SUBGOAL_TRANSITION")
                state["status"] = "WAITING_HANDOFF"
                result = {**result, "handoff_required": True, "active_node_id": graph.active_node_id,
                          "worker_must_stop": True}
            else:
                result = {**result, "handoff_required": False, "task_subgoals_complete": graph.complete}
        elif op == "recall":
            if node_id is None:
                raise BrokerError("memory recall requires an active semantic subgoal")
            result = self._recall(state)
        elif op in {"trace", "trace_chunk"}:
            worker = state["workers"][worker_id]
            packet = self._packet(worker["packet_file"])
            # Trace references are to the exact owner snapshot at handoff, not
            # to a later mutated graph/history from this worker's live actions.
            issue = next(event for event in self._events() if event["kind"] == "ISSUE_HANDOFF"
                         and event["response"]["packet_sha256"] == worker["packet_sha256"])
            snapshot = read(self.root / "packet-owners" / worker["packet_file"])
            owner = TaskHandoffContext(task=self.task, graph=ShortTermWorkingGraph.from_snapshot(snapshot["graph"]),
                                      history=snapshot["history"], tool_schema=self.manifest["tool_schema"])
            args = {key: value for key, value in request.items() if key != "op"}
            function = owner.retrieve_trace if op == "trace" else owner.retrieve_trace_chunk
            result = function(issue["response"]["packet"], expected_binding=packet.binding,
                expected_sha256=worker["packet_sha256"], worker_id=worker_id, task_id=self.task["task_id"], **args)
        elif op == "diff":
            patch = self.workspace.patch()
            result = {"patch": patch[:32_000], "truncated": len(patch) > 32_000,
                      "patch_sha256": sha(patch.encode()), "patch_utf8_bytes": len(patch.encode())}
        else:
            summary = request["summary"]
            if not isinstance(summary, str) or not summary.strip() or len(summary.encode()) > 8000:
                raise BrokerError("submission summary must be nonempty bounded text")
            result = self._seal(state, summary=summary, completed=True, reason="WORKER_SUBMITTED")
        state["graph"] = graph.snapshot()
        return result, history_row

    def action(self, worker_id, admission_token, request):
        if not isinstance(request, dict) or not isinstance(request.get("op"), str):
            raise BrokerError("worker request must contain an operation")
        request_id = identity(request.get("request_id"), "request ID")
        canonical(request)
        with locked(self.root / "broker.lock"):
            state, events = self._load()
            worker = state["workers"].get(worker_id)
            if not isinstance(admission_token, str) or worker is None or worker.get("admission_token_sha256") != sha(admission_token.encode()):
                raise BrokerError("worker admission token differs")
            for event in events:
                prior = event["request"]
                if event["kind"] == "WORKER_ACTION" and prior["worker_id"] == worker_id and prior["request"]["request_id"] == request_id:
                    if prior["request"] != request:
                        raise BrokerError("request ID was already bound to different bytes")
                    return event["response"]
            if state["status"] != "RUNNING" or state["current_worker"] != worker_id or worker["status"] != "ADMITTED":
                raise BrokerError("worker is revoked or the task is sealed")
            budget = self._remaining(state)
            if budget["requests_remaining"] <= 0 or budget["seconds_remaining"] <= 0:
                raise BrokerError("whole-task request or time budget exhausted")
            if state["started_at"] is None:
                state["started_at"] = self.clock()
            state["actions"] += 1
            public_request = {"worker_id": worker_id, "request": request}
            write(self.root / "pending.json", {"phase": "STARTED", "reserved_state": state,
                "request": public_request, "previous_sha256": events[-1]["sha256"] if events else ZERO})
            try:
                result, history_row = self._dispatch(state, worker_id, {k: v for k, v in request.items() if k != "request_id"})
                response = {"ok": True, "result": result}
            except Exception as exc:
                history_row = None
                state["tool_errors"] += 1
                response = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:2000]}
            if history_row is not None:
                state["history"].append(history_row)
            response["step_no"] = state["actions"]
            response["budget"] = self._remaining(state)
            self._commit(state, events, kind="WORKER_ACTION", request=public_request, response=response, history_row=history_row)
            return response

    def seal_partial(self, *, reason, summary="Manager sealed the current partial patch"):
        if not isinstance(reason, str) or not reason.strip():
            raise BrokerError("partial seal reason is required")
        with locked(self.root / "broker.lock"):
            pending_path = self.root / "pending.json"
            if pending_path.exists() and read(pending_path).get("phase") == "STARTED":
                pending, events = read(pending_path), self._events()
                if pending["previous_sha256"] != (events[-1]["sha256"] if events else ZERO):
                    raise BrokerError("unfinished action predecessor differs")
                before = read(self.root / "state.json")
                expected_before = events[-1]["state_after_sha256"] if events else sha(canonical(read(self.root / "initial-state.json")))
                if sha(canonical(before)) != expected_before:
                    raise BrokerError("unfinished action base checkpoint changed")
                expected_reserved = {**before, "actions": before["actions"] + 1,
                    "started_at": pending["reserved_state"]["started_at"] if before["started_at"] is None else before["started_at"]}
                if pending["reserved_state"] != expected_reserved:
                    raise BrokerError("unfinished action reservation changed")
                state = pending["reserved_state"]
                state["unfinished_actions"] += 1
            else:
                state, events = self._load()
            response = self._seal(state, summary=summary, completed=False, reason=reason)
            self._commit(state, events, kind="SEAL_PARTIAL", request={"reason": reason}, response=response)
            return response

    def status(self):
        with locked(self.root / "broker.lock"):
            state, events = self._load()
            delivered_ids = {identity for worker in state["workers"].values()
                             for identity in worker.get("delivered_memory_ids", [])}
            return {"schema": SCHEMA, "task_id": self.task["task_id"], "arm": self.arm,
                "status": state["status"], "active_node_id": state["graph"]["active_node_id"],
                "current_worker": state["current_worker"], "budget": self._remaining(state),
                "workers_issued": len(state["workers"]),
                "workers_admitted": sum("thread_id" in row for row in state["workers"].values()),
                "event_count": len(events), "event_tail_sha256": events[-1]["sha256"] if events else ZERO,
                "tool_errors": state["tool_errors"], "unfinished_actions": state["unfinished_actions"],
                "memory_records_reserved": len(state["memory_ledger"]),
                "memory_injections": len(delivered_ids),
                "memory_bytes": sum(len(row["exact_text"].encode()) for row in state["memory_ledger"]
                                    if row["memory_id"] in delivered_ids),
                "submission": state["submission"], "separate_model_api_calls": 0}


def open_from_frozen_workspace(root, *, memory_callback=None):
    """Manager-frozen workspace factory; workers cannot choose import callbacks."""
    root = Path(root)
    manifest = read(root / "manifest.json")
    config = manifest["workspace_configuration"]
    if not isinstance(config, dict) or set(config) != {
        "checkout_root", "image", "masked_image_files", "masked_image_directories", "command_runner_sha256",
    }:
        raise BrokerError("frozen workspace configuration fields differ")
    from enterprise_memory.trimem.git_workspace import DockerSandboxCommandRunner, GitCheckoutWorkspace
    runner = DockerSandboxCommandRunner(config["image"], masked_image_files=tuple(config["masked_image_files"]),
                                       masked_image_directories=tuple(config["masked_image_directories"]))
    if runner.content_hash != config["command_runner_sha256"]:
        raise BrokerError("frozen command sandbox differs")
    workspace = GitCheckoutWorkspace(config["checkout_root"], base_commit=manifest["task"]["commit"], command_runner=runner)
    return ArchitectureBroker(root, workspace=workspace, configuration_sha256=manifest["configuration_sha256"],
                              bank_sha256=manifest["bank_sha256"], memory_callback=memory_callback)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    action = commands.add_parser("action")
    action.add_argument("--worker-id", required=True)
    action.add_argument("--token-file", required=True, type=Path)
    action.add_argument("--request-base64", required=True)
    args = parser.parse_args()
    broker = open_from_frozen_workspace(args.root)
    if args.command == "status":
        result = broker.status()
    else:
        request = strict_json_loads(base64.b64decode(args.request_base64, validate=True))
        token = args.token_file.read_text(encoding="utf-8").strip()
        result = broker.action(args.worker_id, token, request)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
