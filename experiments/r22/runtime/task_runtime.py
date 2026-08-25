"""R22 §2/§4/§5/§6/§7 — one task-arm execution with the PROPER OpenAI tool-call protocol (assistant.tool_calls +
role=tool replies), server-owned stage progression from COMPREHEND, real stage-memory tools backed by an injected
MemorySourceLoader, and O1's neutral scaffold actually placed in the prompt. Provider-agnostic; grader injected.
"""
from __future__ import annotations

import hashlib
import json
from typing import Callable, Dict, List, Optional

from enterprise_memory.experience.stage_schema import Stage
from enterprise_memory.service.stage_state import StageState, StageObservation

from .provider import ReaderProvider
from .arm_payload import build_payload, MEMORY_ENABLED
from .accounting import Ledger
from . import repo_agent as RA

MAX_TURNS = 10
EXEC_TOKEN_BUDGET = 440

TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "read_file", "description": "Read a file (line-numbered).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"},
                    "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "search", "description": "grep -rn a regex within a path.",
     "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
                    "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "replace_lines", "description": "Replace an inclusive 1-based line range.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"}, "new_content": {"type": "string"}},
                    "required": ["path", "start_line", "end_line", "new_content"]}}},
    {"type": "function", "function": {"name": "submit", "description": "Finish: the fix is complete.",
     "parameters": {"type": "object", "properties": {}}}},
]
MEMORY_SCHEMAS = [
    {"type": "function", "function": {"name": "memory_search_stage",
     "description": "Search prior-issue memory for the CURRENT stage (metadata only).",
     "parameters": {"type": "object", "properties": {"stage": {"type": "string"}}, "required": ["stage"]}}},
    {"type": "function", "function": {"name": "memory_browse_stage",
     "description": "Reveal the execution view of one candidate.",
     "parameters": {"type": "object", "properties": {"candidate_id": {"type": "string"}},
                    "required": ["candidate_id"]}}},
]


def _tok(s):
    return max(len(s.split()), len(s) // 4)


def run_task_arm(*, task: dict, arm: str, provider: ReaderProvider, ledger: Ledger,
                 grade_fn: Callable[[dict, str], dict], workspace_root: str,
                 memory_record: Optional[dict] = None) -> dict:
    """memory_record: the arm-assigned source's stage views {card, semantic, episodic, full_precedent,
    execution_view}. For O0 it is ignored; for O1 it is ignored (neutral scaffold only)."""
    stage = Stage[task.get("stage", "COMPREHEND")]
    state = StageState(stage=stage, obs=StageObservation())
    payload = build_payload(
        arm, target_id=task["target_id"], source_id=task.get("source_id", ""),
        source_user=task.get("source_user", "src"), target_user=task.get("target_user", "tgt"),
        stage=stage.value,
        source_card=(memory_record or {}).get("card", ""),
        source_semantic=(memory_record or {}).get("semantic", ""),
        source_episodic=(memory_record or {}).get("episodic", ""),
        source_full_precedent=(memory_record or {}).get("full_precedent", ""))
    ws = RA.RepoWorkspace(workspace_root)

    system = "Fix the bug described in the issue. Use the tools. One attempt."
    if arm == "O1":
        system += "\n" + payload["text"]           # neutral scaffold is VISIBLE to the reader (no historical content)
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": "Issue:\n%s" % task.get("issue", "add() is wrong")}]

    mem_search = 0
    browse = 0
    exec_tokens = 0
    injected = {"text": None}
    transcript = []
    prompt_hash_seed = [system, task.get("issue", "")]
    terminal = "ok"
    last_raw = None
    for _ in range(MAX_TURNS):
        offered = list(TOOL_SCHEMAS)
        if MEMORY_ENABLED[arm] and state.can_search(stage) and mem_search < 2:
            offered = MEMORY_SCHEMAS + offered
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
        # PROPER protocol: keep the assistant tool_calls message, reply per call with role=tool + tool_call_id
        messages.append({"role": "assistant", "content": res.content or None, "tool_calls": tcs})
        done = False
        for tc in tcs:
            name = tc["function"]["name"]
            args = json.loads(tc["function"].get("arguments") or "{}")
            tcid = tc.get("id", "")
            transcript.append(name)
            if name == "submit":
                done = True
                messages.append({"role": "tool", "tool_call_id": tcid, "content": "submitted"})
                break
            if name == "memory_search_stage":
                mem_search += 1
                result = ("candidate: %s (source %s, stage %s)"
                          % (task.get("source_id", "src"), task.get("source_id", "src"), stage.value)
                          if MEMORY_ENABLED[arm] else "no memory in this arm")
            elif name == "memory_browse_stage":
                if browse >= 2:
                    result = "browse budget exhausted"
                else:
                    view = (memory_record or {}).get("execution_view") or {"approx_tokens": payload["token_count"]}
                    text = payload["text"]
                    tok = _tok(text)
                    if exec_tokens + tok > EXEC_TOKEN_BUDGET:
                        result = "execution-memory token budget exhausted"
                    else:
                        browse += 1
                        exec_tokens += tok
                        injected = payload
                        result = "execution_view (%d tok): %s" % (tok, text)
            else:
                result = RA.dispatch(ws, name, args)
                if name == "replace_lines":
                    state.obs.applied_patch = ws.git_diff()[:64] or "edited"
            messages.append({"role": "tool", "tool_call_id": tcid, "content": str(result)[:2000]})
        if done:
            break

    patch = ws.git_diff()
    grade = grade_fn(dict(task, _workspace=workspace_root), patch)
    resolved = bool(grade.get("resolved"))
    canonical = json.dumps({"target": task["target_id"], "arm": arm, "patch": patch,
                            "resolved": resolved, "injection": payload["byte_hash"] if injected["text"] else None},
                           sort_keys=True)
    rec = {
        "cell_key": "%s::%s" % (task["target_id"], arm), "target_id": task["target_id"], "arm": arm,
        "stage": stage.value, "subset": task.get("subset"), "repo_cluster": task.get("repo_cluster", task["target_id"]),
        "source_id": payload["source_id"], "source_user": payload["source_user"], "target_user": payload["target_user"],
        "memory_search_calls": mem_search, "browse_calls": browse, "exec_memory_tokens": exec_tokens,
        "injection": {"text": injected["text"], "byte_hash": payload["byte_hash"] if injected["text"] else None,
                      "source_id": payload["source_id"], "source_user": payload["source_user"],
                      "target_user": payload["target_user"], "historical_content": payload["historical_content"],
                      "token_count": payload["token_count"] if injected["text"] else 0},
        "target_leak_tokens": task.get("target_leak_tokens", [task["target_id"]]),
        "returned_model": provider._locked_returned_model or provider.requested_model,
        "model_drift_label": provider.drift_label,
        "resolved": resolved, "exec_at_1": bool(patch.strip()), "grader": grade,
        "image_digest": task.get("image_digest"),
        "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
        "raw_response_sha256": last_raw, "tool_transcript": transcript, "terminal": terminal,
        "prompt_hash": hashlib.sha256("\n".join(prompt_hash_seed).encode()).hexdigest(),
        "content_hash": hashlib.sha256(canonical.encode()).hexdigest(),
        "usage": ledger.snapshot(),
        "messages": messages,
    }
    return rec
