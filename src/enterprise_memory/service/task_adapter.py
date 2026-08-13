"""RepositoryTaskAdapter (P5.1 §5). The worker never trusts the client for repository content or edit/test
policy. An adapter loads an IMMUTABLE task fixture / repository snapshot, resolves the server-owned target path
and policy, returns a snapshot hash, and NEVER exposes hidden tests to the coding backend. Two adapters share
the contract:

  FrozenExecutableBenchmarkAdapter  — the frozen static instrument (deterministic, credential-free).
  CompanyRepositoryAdapter          — the boundary for a real company repository; contract complete, remains
                                      unconnected until an endpoint/configuration is provided.
"""
from __future__ import annotations
import hashlib
import json
from abc import ABC, abstractmethod


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class RepositoryTaskAdapter(ABC):
    @abstractmethod
    def installation_for(self, org_id) -> int: ...

    @abstractmethod
    def resolve_commit(self, repo_id, ref) -> str: ...

    @abstractmethod
    def resolve_tree(self, commit_sha) -> str: ...

    @abstractmethod
    def snapshot(self, repo_id, commit_sha, target_path) -> dict:
        """Read-only, model-visible snapshot. MUST NOT contain any hidden test."""

    @abstractmethod
    def hidden_test(self, repo_id) -> str | None:
        """Server-only grading test. NEVER returned to the coding backend; only the sandbox uses it."""

    def snapshot_hash(self, repo_id, commit_sha, target_path) -> str:
        return _sha(json.dumps(self.snapshot(repo_id, commit_sha, target_path), sort_keys=True))


class FrozenExecutableBenchmarkAdapter(RepositoryTaskAdapter):
    """Resolves a repository_fixture_id to a frozen benchmark task. The snapshot is the task's stub + the
    INCOMPLETE public test only; the hidden test is served separately for grading and never shipped."""

    def __init__(self, splits=(("calibration", 4), ("main", 8))):
        from benchmarks.p5_1_static import generate
        self._by_repo = {}
        self._by_task = {}
        for name, n in splits:
            for fam in generate(name, n):
                for t in fam.tasks.values():
                    self._by_repo[t.repo_fixture_id] = t
                    self._by_task[t.task_id] = t

    def task_for_repo(self, repo_id):
        t = self._by_repo.get(str(repo_id))
        if t is None:
            raise KeyError("no frozen task for repository fixture %r" % (repo_id,))
        return t

    def installation_for(self, org_id) -> int:
        return int(_sha(str(org_id))[:8], 16) % 1_000_000 + 1

    def resolve_commit(self, repo_id, ref) -> str:
        return _sha("%s|%s" % (repo_id, ref))[:40]

    def resolve_tree(self, commit_sha) -> str:
        return _sha("tree|%s" % commit_sha)[:40]

    def snapshot(self, repo_id, commit_sha, target_path) -> dict:
        t = self.task_for_repo(repo_id)
        snap = t.snapshot()                      # stub + incomplete public test ONLY
        assert t.hidden_test not in "\n".join(snap.values()), "hidden test must never ship in the snapshot"
        return snap

    def hidden_test(self, repo_id) -> str | None:
        return self.task_for_repo(repo_id).hidden_test


class CompanyAdapterNotConfigured(RuntimeError):
    pass


class CompanyRepositoryAdapter(RepositoryTaskAdapter):
    """Boundary for a real company repository. The contract is complete; it stays unconnected until an
    approved endpoint/configuration is supplied. Every method fails closed until configured so it can never
    silently reach a live company repository without explicit configuration."""

    def __init__(self, config=None):
        self._config = config

    def _require(self):
        if not self._config:
            raise CompanyAdapterNotConfigured(
                "CompanyRepositoryAdapter requires an approved company repository configuration")

    def installation_for(self, org_id) -> int:
        self._require(); return self._config.installation_for(org_id)

    def resolve_commit(self, repo_id, ref) -> str:
        self._require(); return self._config.resolve_commit(repo_id, ref)

    def resolve_tree(self, commit_sha) -> str:
        self._require(); return self._config.resolve_tree(commit_sha)

    def snapshot(self, repo_id, commit_sha, target_path) -> dict:
        self._require(); return self._config.snapshot(repo_id, commit_sha, target_path)

    def hidden_test(self, repo_id) -> str | None:
        self._require(); return self._config.hidden_test(repo_id)
