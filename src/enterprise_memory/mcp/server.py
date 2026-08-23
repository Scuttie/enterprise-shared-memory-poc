"""P6/R19 §11 — MCP-style server for Claude-Code-like harnesses (transport-agnostic dispatcher).

Exposes memory_search / memory_browse / memory_report_outcome / memory_explain_decision over JSON-RPC 2.0.
Identity is derived SERVER-SIDE from the session context, never from the tool payload; credentials never appear
in payloads; the verifier and hidden tests are never exposed. The dispatcher is pure (dict->dict) so it can be
driven by a stdio loop (local dev) or a streamable-HTTP transport (internal deployment) and unit-tested directly.
No external MCP SDK dependency (keeps CI light); the wire shape matches MCP tools/list + tools/call.
"""
from __future__ import annotations

import json
import sys
from typing import Optional

from ..agentic import MemorySearchService, SearchSession, tools as toolmod
from ..agentic.store import InMemoryExperienceStore
from ..router import TaskContext, TrajectoryState

_MCP_TOOLS = [
    {"name": "memory_search", "description": toolmod.SEARCH_EXPERIENCES["description"],
     "inputSchema": toolmod.SEARCH_EXPERIENCES["input_schema"]},
    {"name": "memory_browse", "description": toolmod.BROWSE_EXPERIENCE["description"],
     "inputSchema": toolmod.BROWSE_EXPERIENCE["input_schema"]},
    {"name": "memory_report_outcome", "description": toolmod.REPORT_MEMORY_OUTCOME["description"],
     "inputSchema": toolmod.REPORT_MEMORY_OUTCOME["input_schema"]},
    {"name": "memory_explain_decision", "description": toolmod.MEMORY_EXPLAIN_DECISION["description"],
     "inputSchema": toolmod.MEMORY_EXPLAIN_DECISION["input_schema"]},
]

# keys a client must never be able to set (identity/policy are server-side; §11/§22)
_CLIENT_FORBIDDEN = frozenset({"org_id", "actor_id", "token", "authorization", "api_key",
                               "policy_mode", "experiment_arm", "gold_patch", "hidden_tests"})


class MemoryMCPServer:
    """One server bound to a server-side session identity. The client supplies only tool args."""

    def __init__(self, org_id: str, actor_id_hash: str, store: Optional[InMemoryExperienceStore] = None,
                 mode: str = "utility_gated"):
        self._org = org_id
        self._actor = actor_id_hash
        self._mode = mode
        self.svc = MemorySearchService(store or InMemoryExperienceStore())
        self._sessions = {}

    def _session(self, request_id: str, target_task_id: str, repository: str) -> SearchSession:
        s = self._sessions.get(request_id)
        if s is None:
            s = SearchSession(session_id="mcp-" + request_id, org_id=self._org, request_id=request_id,
                              actor_id_hash=self._actor, target_task_id=target_task_id, mode=self._mode)
            s._repository = repository  # type: ignore[attr-defined]
            self._sessions[request_id] = s
        return s

    def handle(self, req: dict) -> dict:
        rid = req.get("id")
        method = req.get("method")
        try:
            if method == "tools/list":
                return _ok(rid, {"tools": _MCP_TOOLS})
            if method == "tools/call":
                params = req.get("params") or {}
                name = params.get("name")
                args = params.get("arguments") or {}
                _reject_forbidden(args)
                return _ok(rid, self._call(name, args))
            return _err(rid, -32601, "method not found: %s" % method)
        except _ToolError as e:
            return _err(rid, -32602, str(e))
        except Exception as e:  # fail closed
            return _err(rid, -32603, "internal error: %s" % type(e).__name__)

    def _call(self, name: str, args: dict) -> dict:
        req_id = args.get("request_id", "req-1")
        repo = args.get("repository", "")
        task = TaskContext(org_id=self._org, repository=repo, subtask=args.get("subtask", "localization"),
                           target_apis=args.get("target_apis", []), target_symbols=args.get("target_symbols", []),
                           error_signature=args.get("error_signature", ""), version=args.get("version", ""))
        sess = self._session(req_id, args.get("target_task_id", "t"), repo)
        if name == "memory_search":
            res = self.svc.search_experiences(sess, task, args.get("query", ""),
                                              subtask=args.get("subtask"), top_k=int(args.get("top_k", 10)))
            return {"content": res, "isError": False}
        if name == "memory_browse":
            cands = self.svc.store.search(self._org, repo, args.get("query", args.get("version_id", "")))
            match = [c for c in cands if c.version_id == args.get("version_id")]
            if not match:
                return {"content": None, "isError": False, "note": "candidate not visible"}
            view = self.svc.browse_experience(sess, task, TrajectoryState(), match[0])
            return {"content": view, "isError": False}
        if name == "memory_report_outcome":
            sess._log("outcome_reported", target_outcome=args.get("target_outcome"))
            return {"content": {"accepted": True}, "isError": False}
        if name == "memory_explain_decision":
            return {"content": self.svc.explain_decision(sess), "isError": False}
        raise _ToolError("unknown tool: %s" % name)

    def serve_stdio(self):  # pragma: no cover - I/O loop
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except Exception:
                sys.stdout.write(json.dumps(_err(None, -32700, "parse error")) + "\n"); sys.stdout.flush(); continue
            sys.stdout.write(json.dumps(self.handle(req)) + "\n"); sys.stdout.flush()


class _ToolError(Exception):
    pass


def _reject_forbidden(args: dict) -> None:
    bad = {k for k in args if k.lower() in _CLIENT_FORBIDDEN}
    if bad:
        raise _ToolError("client may not set server-controlled fields: %s" % sorted(bad))


def _ok(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


if __name__ == "__main__":  # pragma: no cover
    MemoryMCPServer(org_id="org-demo", actor_id_hash="local-dev").serve_stdio()
