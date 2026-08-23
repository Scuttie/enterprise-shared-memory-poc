"""Async test/local provider implementations (§2.1/§3). No external infrastructure, so the pipeline and
end-to-end tests run offline. Production adapters (Postgres/Mem0/S3/OIDC/GitHub App/Kubernetes) are
separate modules that must NOT be selectable under the production/staging dev-backend refusal."""
from __future__ import annotations
import asyncio
import hashlib
import os
import shutil
import tempfile

from ..serving import sandbox as _sandbox


class FakeSolarProvider:
    def __init__(self, responder=None):
        self._responder = responder or (lambda p: "```diff\n```")
        self.calls = []

    async def generate(self, logical_request_id: str, prompt: str) -> dict:
        text = self._responder(prompt)
        rec = {"logical_request_id": logical_request_id, "text": text,
               "prompt_sha256": "sha256:" + hashlib.sha256(prompt.encode()).hexdigest()[:16],
               "response_sha256": "sha256:" + hashlib.sha256((text or "").encode()).hexdigest()[:16],
               "model_requested": "fake", "model_returned": "fake",
               "usage": {"prompt": len(prompt) // 4, "completion": len(text or "") // 4},
               "latency_ms": 0, "retries": 0, "finish_reason": "stop", "parser_status": "ok"}
        self.calls.append(rec)
        return rec


class LocalArtifactStore:
    def __init__(self, root=None):
        self.root = root or tempfile.mkdtemp(prefix="esm_artifacts_")
        self._store = {}

    async def put(self, tenant_id, key, data: bytes, retention_class="default") -> str:
        self._store[(tenant_id, key)] = bytes(data)
        return "local://%s/%s" % (tenant_id, key)

    async def get(self, tenant_id, key) -> bytes:
        return self._store[(tenant_id, key)]


class LocalFixtureRepositoryProvider:
    def __init__(self, fixtures: dict):
        self._fixtures = fixtures

    async def resolve_commit(self, repo_id, ref) -> str:
        blob = repr(sorted(self._fixtures[repo_id]["files"].items()))
        return "sha_" + hashlib.sha256(blob.encode()).hexdigest()[:12]

    async def snapshot(self, repo_id, commit_sha, path_allowlist) -> dict:
        files = self._fixtures[repo_id]["files"]
        sel = {k: v for k, v in files.items() if (not path_allowlist or k in path_allowlist)}
        return {"repo_id": repo_id, "commit_sha": commit_sha, "files": sel,
                "tree_hash": "tree_" + hashlib.sha256(repr(sorted(sel.items())).encode()).hexdigest()[:12]}


class LocalEvaluationSandbox:
    """test/local ONLY subprocess sandbox. Production/staging MUST refuse it (settings gate)."""

    async def run(self, snapshot, patch_files, test_entry, timeout_s=20) -> dict:
        def _blocking():
            d = tempfile.mkdtemp(prefix="esm_sbx_")
            try:
                for name, content in snapshot["files"].items():
                    p = os.path.join(d, name)
                    os.makedirs(os.path.dirname(p) or d, exist_ok=True)
                    open(p, "w", encoding="utf-8").write(content)
                res = _sandbox.run_task(d, patch_files, test_entry, timeout=timeout_s)
                return {"passed": int(res["passed"]), "exec_ok": int(res["exec_ok"]), "escape": False}
            finally:
                shutil.rmtree(d, ignore_errors=True)
        return await asyncio.to_thread(_blocking)   # keep the blocking sandbox off the event loop


class ListAudit:
    def __init__(self):
        self.events = []

    async def emit(self, event_type, actor, subject, detail) -> str:
        self.events.append((event_type, actor, subject, detail))
        return "audit_%d" % len(self.events)


class InMemoryOutcomeStore:
    def __init__(self):
        self.records = []

    async def persist(self, record: dict) -> str:
        self.records.append(record)
        return "outcome_%d" % len(self.records)


class ListMetrics:
    def __init__(self):
        self.counters = {}
        self.observations = []

    def incr(self, name, value=1, tags=None):
        self.counters[name] = self.counters.get(name, 0) + value

    def observe(self, name, value, tags=None):
        self.observations.append((name, value))
