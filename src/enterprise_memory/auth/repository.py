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
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


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


# ================================================================ P3.1 §6: server-owned task policy
@dataclass(frozen=True)
class RepositoryTaskPolicy:
    org_id: str
    installation_id: int
    repository_full_name: str
    allowed_ref_globs: Tuple[str, ...]
    allowed_branch_globs: Tuple[str, ...]
    allowed_path_globs: Tuple[str, ...]
    required_action: str
    task_policy_id: str
    policy_version: int


class TaskPolicyRepository(ABC):
    @abstractmethod
    def get_policy(self, org_id, task_policy_id) -> RepositoryTaskPolicy: ...


class InMemoryTaskPolicyRepository(TaskPolicyRepository):
    def __init__(self, policies):
        self._p = {(p.org_id, p.task_policy_id): p for p in policies}

    def get_policy(self, org_id, task_policy_id) -> RepositoryTaskPolicy:
        p = self._p.get((str(org_id), str(task_policy_id)))
        if p is None:
            raise AuthorizationDenied("unknown_task_policy")
        return p


class InstallationDirectory:
    """Server-side org_id -> approved GitHub App installation_id mapping. The client cannot choose it."""
    def __init__(self, mapping):
        self._m = dict(mapping)

    def installation_for(self, org_id) -> int:
        i = self._m.get(str(org_id))
        if i is None:
            raise AuthorizationDenied("no_installation_for_org")
        return i


def is_full_commit_sha(s) -> bool:
    return bool(isinstance(s, str) and _FULL_SHA.match(s))


def normalize_git_path(p: str) -> str:
    """Normalized POSIX Git path or AuthorizationDenied. Rejects backslashes, NUL, encoded traversal,
    absolute paths, and `..`/`.` segments."""
    if not isinstance(p, str) or not p:
        raise AuthorizationDenied("empty_path")
    if "\\" in p or "\x00" in p:
        raise AuthorizationDenied("path_bad_chars")
    low = p.lower()
    if "%2e" in low or "%2f" in low or "%5c" in low or "%00" in low:
        raise AuthorizationDenied("path_encoded_traversal")
    if p.startswith("/") or (len(p) > 1 and p[1] == ":"):
        raise AuthorizationDenied("path_absolute")
    parts = p.split("/")
    if ".." in parts or "." in parts or "" in parts:
        raise AuthorizationDenied("path_traversal")
    return "/".join(parts)


def _branch_from_ref(ref: str):
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/"):]
    if ref.startswith("refs/tags/"):
        return None
    if "/" not in ref and not is_full_commit_sha(ref):
        return ref                                   # bare branch name
    return None


def authorize_task(provider: GitHubAppRepositoryProvider, policy_repo: TaskPolicyRepository,
                   installation_dir: InstallationDirectory, *, org_id, task_policy_id,
                   expected_policy_version, ref, branch=None, path=None) -> AccessDecision:
    """Authorize a solve against a SERVER-OWNED policy. The caller supplies no allowlist, no installation,
    no permissions, no immutable commit — those are all derived server-side and bound to the policy."""
    policy = policy_repo.get_policy(org_id, task_policy_id)
    if int(policy.policy_version) != int(expected_policy_version):
        raise AuthorizationDenied("policy_version_mismatch")
    installation_id = installation_dir.installation_for(org_id)      # server-derived; client cannot pick
    if int(installation_id) != int(policy.installation_id):
        raise AuthorizationDenied("installation_policy_mismatch")
    full = policy.repository_full_name

    if not any(fnmatch.fnmatch(ref, g) for g in policy.allowed_ref_globs):
        raise AuthorizationDenied("ref_not_allowed")
    derived_branch = _branch_from_ref(ref)
    if branch is not None and derived_branch is not None and branch != derived_branch:
        raise AuthorizationDenied("branch_ref_mismatch")
    eff_branch = derived_branch if derived_branch is not None else branch
    if eff_branch is not None and not any(fnmatch.fnmatch(eff_branch, g) for g in policy.allowed_branch_globs):
        raise AuthorizationDenied("branch_not_allowed")
    if path is not None:
        np = normalize_git_path(path)
        if not any(fnmatch.fnmatch(np, g) for g in policy.allowed_path_globs):
            raise AuthorizationDenied("path_not_allowed")

    handle = provider.resolve_repository(installation_id, full)
    if policy.required_action == "read" and not handle.can_read:
        raise AuthorizationDenied("no_read")
    if policy.required_action == "modify" and not handle.can_write:
        raise AuthorizationDenied("no_write")
    resolved = provider.resolve_ref(installation_id, full, ref)
    if not is_full_commit_sha(resolved.commit_sha):
        raise AuthorizationDenied("bad_commit_sha")
    if not resolved.tree_sha:
        raise AuthorizationDenied("missing_tree_sha")
    return AccessDecision(True, policy.required_action, full, resolved.commit_sha, resolved.tree_sha,
                          reasons=["policy:%s@%d" % (policy.task_policy_id, policy.policy_version)])
