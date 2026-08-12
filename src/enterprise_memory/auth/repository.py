"""Repository authorization (P3 §14). A generic RepositoryProvider / RepositoryAuthorizationProvider, plus a
GitHub App adapter tested against a MOCKED GitHub API. Every security-relevant value is derived server-side:

- installation approval + repository membership come from the installation, not the client;
- read/modify permission comes from the repository's GitHub permissions, not the client;
- the immutable target is a commit SHA resolved from the ref by the server, with the tree hash persisted;
- writable paths / allowed branches come from the caller's task policy (server-side), never from client input;
- short-lived installation credentials are minted separately and are NEVER placed in the access decision that
  reaches the model or sandbox;
- arbitrary host paths (absolute, `..`, `~`, drive-qualified) are rejected.
"""
from __future__ import annotations
import fnmatch
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Sequence


class RepositoryError(Exception):
    pass


class RepositoryAccessError(RepositoryError):
    pass


class AuthorizationDenied(RepositoryError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class RepositoryHandle:
    full_name: str
    default_branch: str
    can_read: bool
    can_write: bool
    installation_id: int


@dataclass(frozen=True)
class ResolvedRef:
    full_name: str
    requested_ref: str
    commit_sha: str        # immutable, server-resolved
    tree_sha: Optional[str]


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    action: str
    repo: str
    commit_sha: Optional[str] = None
    tree_sha: Optional[str] = None
    reasons: List[str] = field(default_factory=list)
    # NOTE: intentionally carries NO credential/token — see ephemeral_token().


def _unsafe_path(p: str) -> bool:
    if not p or p.startswith("/") or p.startswith("~") or p.startswith("\\"):
        return True
    if len(p) > 1 and p[1] == ":":                 # drive-qualified (C:\...)
        return True
    parts = p.replace("\\", "/").split("/")
    return ".." in parts


class RepositoryProvider(ABC):
    @abstractmethod
    def resolve_repository(self, installation_id, full_name) -> RepositoryHandle: ...

    @abstractmethod
    def resolve_ref(self, installation_id, full_name, ref) -> ResolvedRef: ...


class RepositoryAuthorizationProvider(ABC):
    @abstractmethod
    def authorize(self, installation_id, full_name, action, **kw) -> AccessDecision: ...


class GitHubAppRepositoryProvider(RepositoryProvider, RepositoryAuthorizationProvider):
    """`client` is any object with the GitHub App methods used below (mockable, no network in tests)."""

    def __init__(self, client):
        self._c = client

    def resolve_repository(self, installation_id, full_name) -> RepositoryHandle:
        inst = self._c.get_installation(installation_id)
        if inst is None or inst.get("suspended"):
            raise RepositoryAccessError("installation_unavailable")
        if full_name not in set(inst.get("repositories", [])):
            raise RepositoryAccessError("repo_outside_installation")
        repo = self._c.get_repo(installation_id, full_name)
        if repo is None:
            raise RepositoryAccessError("repo_not_found")
        perms = repo.get("permissions", {}) or {}
        return RepositoryHandle(full_name, repo.get("default_branch", "main"),
                                bool(perms.get("pull")), bool(perms.get("push")), installation_id)

    def resolve_ref(self, installation_id, full_name, ref) -> ResolvedRef:
        self.resolve_repository(installation_id, full_name)          # access gate first
        r = self._c.get_ref(full_name, ref)
        if not r or "sha" not in r:
            raise RepositoryError("ref_unresolved")
        tree = self._c.get_commit_tree(full_name, r["sha"]) or {}
        return ResolvedRef(full_name, ref, r["sha"], tree.get("tree_sha"))

    def ephemeral_token(self, installation_id) -> dict:
        """Short-lived installation token for the EXECUTOR only. Never embedded in an AccessDecision."""
        return self._c.create_installation_token(installation_id)

    def authorize(self, installation_id, full_name, action, *, ref=None, branch=None, path=None,
                  allowed_branch_globs: Optional[Sequence[str]] = None,
                  allowed_path_globs: Optional[Sequence[str]] = None) -> AccessDecision:
        if action not in ("read", "modify"):
            raise AuthorizationDenied("unknown_action")
        h = self.resolve_repository(installation_id, full_name)      # server-derived permissions
        if action == "read" and not h.can_read:
            raise AuthorizationDenied("no_read")
        if action == "modify" and not h.can_write:
            raise AuthorizationDenied("no_write")
        if branch is not None and allowed_branch_globs is not None:
            if not any(fnmatch.fnmatch(branch, g) for g in allowed_branch_globs):
                raise AuthorizationDenied("branch_not_allowed")
        if path is not None:
            if _unsafe_path(path):
                raise AuthorizationDenied("path_traversal")
            if allowed_path_globs is not None and not any(fnmatch.fnmatch(path, g) for g in allowed_path_globs):
                raise AuthorizationDenied("path_not_allowed")
        commit = tree = None
        if ref is not None:
            resolved = self.resolve_ref(installation_id, full_name, ref)   # immutable, server-resolved
            commit, tree = resolved.commit_sha, resolved.tree_sha
        return AccessDecision(True, action, full_name, commit, tree, reasons=["server_derived"])
