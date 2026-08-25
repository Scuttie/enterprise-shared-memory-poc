"""R22 §2/§4/§5 — one task-arm execution: repo tools + server-owned stage + real stage-memory tools + provider
loop + patch + grade → one immutable result record. Provider-agnostic (fake offline / real paid). No model call
happens here except through the injected provider.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from typing import Callable, Dict, List, Optional

from enterprise_memory.experience.stage_schema import Stage
from enterprise_memory.service.stage_state import StageState, StageObservation

from .provider import ReaderProvider
from .arm_payload import build_payload, MEMORY_ENABLED
from .accounting import Ledger
from . import repo_agent as RA

MAX_TURNS = 8

REPO_TOOLS = [
    {"type": "function", "function": {"name": "read_file", "parameters": {}}},
    {"type": "function", "function": {"name": "replace_lines", "parameters": {}}},
    {"type": "function", "function": {"name": "submit", "parameters": {}}},
]
MEMORY_TOOLS = [
    {"type": "function", "function": {"name": "memory_search_stage", "parameters": {}}},
    {"type": "function", "function": {"name": "memory_browse_stage", "parameters": {}}},
]


def run_task_arm(*, task: dict, arm: str, provider: ReaderProvider, ledger: Ledger,
                 grade_fn: Callable[[str], bool], workspace_root: str) -> dict:
    """task: {target_id, source_id, source_user, target_user, stage, fix, exec_view, source_semantic, ...}.
    grade_fn(patch)->resolved. Returns an immutable result record with the §15 evidence fields."""
    stage = Stage[task.get("stage", "EDIT")]
    state = StageState(stage=stage, obs=StageObservation(
        issue_contract="present", reproduction="present", candidate_locations=["bug.py"]))
    payload = build_payload(arm, target_id=task["target_id"], source_id=task.get("source_id", ""),
                            source_user=task.get("source_user", "src"), target_user=task.get("target_user", "tgt"),
                            stage=stage.value, source_card=task.get("source_card", ""),
                            source_semantic=task.get("source_semantic", ""),
                            source_episodic=task.get("source_episodic", ""),
                            source_full_precedent=task.get("source_full_precedent", ""))
    ws = RA.RepoWorkspace(workspace_root)

    messages = [{"role": "system", "content": "Fix the bug. Use tools. One attempt."},
                {"role": "user", "content": "Issue: %s" % task.get("issue", "add() is wrong")}]
    mem_search = 0
    browse = 0
    injected = {"text": None}
    transcript = []
    terminal = "ok"
    last_raw = None
    for turn in range(MAX_TURNS):
        offered = list(REPO_TOOLS)
        if MEMORY_ENABLED[arm] and state.can_search(stage):
            offered = MEMORY_TOOLS + offered
        try:
            res = provider.chat(messages, tools=offered)
        except Exception as e:  # noqa: BLE001
            terminal = "provider_failure:%s" % type(e).__name__
            break
        last_raw = res.raw_response_sha256
        ledger.add(res.prompt_tokens, res.completion_tokens)
        tcs = res.tool_calls or []
        if not tcs:
            messages.append({"role": "user", "content": "call a tool or submit"})
            continue
        done = False
        for tc in tcs:
            name = tc["function"]["name"]
            args = json.loads(tc["function"].get("arguments") or "{}")
            transcript.append(name)
            if name == "submit":
                done = True
                break
            if name == "memory_search_stage":
                mem_search += 1
                result = "candidate: m1" if MEMORY_ENABLED[arm] else "no memory in this arm"
            elif name == "memory_browse_stage":
                browse += 1
                # browse reveals the execution view (arm payload text), token-capped, hashed
                injected = payload
                result = "execution_view: %s" % (payload["text"][:220])
            else:
                result = RA.dispatch(ws, name, args)
            messages.append({"role": "user", "content": "%s -> %s" % (name, result)})
        if done:
            break
    patch = ws.git_diff()
    resolved = bool(patch.strip()) and grade_fn(workspace_root)
    rec = {
        "cell_key": "%s::%s" % (task["target_id"], arm),
        "target_id": task["target_id"], "arm": arm, "stage": stage.value,
        "source_id": payload["source_id"], "source_user": payload["source_user"],
        "target_user": payload["target_user"],
        "memory_search_calls": mem_search, "browse_calls": browse,
        "injection": {"text": injected["text"], "byte_hash": payload["byte_hash"] if injected["text"] else None,
                      "source_id": payload["source_id"], "source_user": payload["source_user"],
                      "target_user": payload["target_user"], "historical_content": payload["historical_content"],
                      "token_count": payload["token_count"] if injected["text"] else 0},
        "target_leak_tokens": task.get("target_leak_tokens", []),
        "returned_model": provider._locked_returned_model or provider.requested_model,
        "model_drift_label": provider.drift_label,
        "resolved": resolved, "exec_at_1": bool(patch.strip()),
        "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
        "raw_response_sha256": last_raw,
        "tool_transcript": transcript, "terminal": terminal,
        "usage": ledger.snapshot(),
    }
    return rec
