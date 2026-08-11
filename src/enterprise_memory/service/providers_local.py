"""Test/local provider implementations (§3). These satisfy the interfaces without any external
infrastructure so the full pipeline and end-to-end tests run offline. Production adapters (Postgres,
Mem0/Qdrant, S3, OIDC, GitHub App, Kubernetes) are separate modules that must NOT be selectable under
ENVIRONMENT=production's dev-backend refusal — see settings.AppSettings.validate."""
from __future__ import annotations
import hashlib
import os
import shutil
import tempfile

from ..serving import sandbox as _sandbox


class FakeSolarProvider:
    """Deterministic coding-model stand-in for CI/e2e. `responder(prompt) -> diff text`."""

    def __init__(self, responder=None):
        self._responder = responder or (lambda p: "```diff\n```")
        self.calls = []

    def generate(self, logical_request_id: str, prompt: str) -> dict:
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

    def put(self, tenant_id: str, key: str, data: bytes, retention_class: str = "default") -> str:
        self._store[(tenant_id, key)] = bytes(data)
        return "local://%s/%s" % (tenant_id, key)

    def get(self, tenant_id: str, key: str) -> bytes:
        return self._store[(tenant_id, key)]


class LocalFixtureRepositoryProvider:
    """Serves in-memory fixture snapshots; never touches an arbitrary host path from client input."""

    def __init__(self, fixtures: dict):
        self._fixtures = fixtures      # repo_id -> {files: {name: content}}

    def resolve_commit(self, repo_id: str, ref: str) -> str:
        blob = repr(sorted(self._fixtures[repo_id]["files"].items()))
        return "sha_" + hashlib.sha256(blob.encode()).hexdigest()[:12]

    def snapshot(self, repo_id: str, commit_sha: str, path_allowlist: list) -> dict:
        files = self._fixtures[repo_id]["files"]
        sel = {k: v for k, v in files.items() if (not path_allowlist or k in path_allowlist)}
        return {"repo_id": repo_id, "commit_sha": commit_sha, "files": sel,
                "tree_hash": "tree_" + hashlib.sha256(repr(sorted(sel.items())).encode()).hexdigest()[:12]}


class LocalEvaluationSandbox:
    """test/local ONLY subprocess sandbox (reuses the hardened v0.1 sandbox). Production MUST refuse it."""

    def run(self, snapshot: dict, patch_files: dict, test_entry: str, timeout_s: int = 20) -> dict:
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


class ListMetrics:
    def __init__(self):
        self.counters = {}
        self.observations = []

    def incr(self, name, value=1, tags=None):
        self.counters[name] = self.counters.get(name, 0) + value

    def observe(self, name, value, tags=None):
        self.observations.append((name, value))
