"""Server-owned repository task policy (P3.1 §6): ref/branch binding, immutable commit + tree, installation
mapping the client cannot choose, policy versioning, and POSIX path normalization."""
import pytest
from enterprise_memory.auth.repository import (GitHubAppRepositoryProvider, InMemoryTaskPolicyRepository,
                                               InstallationDirectory, RepositoryTaskPolicy, AuthorizationDenied,
                                               authorize_task, normalize_git_path, is_full_commit_sha)

SHA = "a" * 40


class MockGitHub:
    def __init__(self, push=True, tree="tree-1", sha=SHA):
        self.installations = {1: {"account": "orgA", "suspended": False, "repositories": ["orgA/repoX"]}}
        self.repos = {(1, "orgA/repoX"): {"full_name": "orgA/repoX", "default_branch": "main",
                                          "permissions": {"pull": True, "push": push}}}
        self.refs = {("orgA/repoX", "refs/heads/main"): {"sha": sha}}
        self.trees = {("orgA/repoX", sha): {"tree_sha": tree}}

    def get_installation(self, i):
        return self.installations.get(i)

    def get_repo(self, i, f):
        return self.repos.get((i, f))

    def get_ref(self, f, r):
        return self.refs.get((f, r))

    def get_commit_tree(self, f, s):
        return self.trees.get((f, s))

    def create_installation_token(self, i):
        return {"token": "ghs_x", "expires_at": "z"}


def _policy(**over):
    kw = dict(org_id="orgA", installation_id=1, repository_full_name="orgA/repoX",
              allowed_ref_globs=("refs/heads/main",), allowed_branch_globs=("main",),
              allowed_path_globs=("src/**",), required_action="modify", task_policy_id="tp1", policy_version=3)
    kw.update(over)
    return RepositoryTaskPolicy(**kw)


def _ctx(gh=None, policy=None, mapping=None):
    return (GitHubAppRepositoryProvider(gh or MockGitHub()),
            InMemoryTaskPolicyRepository([policy or _policy()]),
            InstallationDirectory(mapping or {"orgA": 1}))


def _auth(ctx, **over):
    prov, repo, d = ctx
    kw = dict(org_id="orgA", task_policy_id="tp1", expected_policy_version=3, ref="refs/heads/main")
    kw.update(over)
    return authorize_task(prov, repo, d, **kw)


def test_happy_path_immutable_commit():
    dec = _auth(_ctx(), path="src/a.py")
    assert dec.allowed and dec.commit_sha == SHA and dec.tree_sha == "tree-1"
    assert is_full_commit_sha(dec.commit_sha) and "policy:tp1@3" in dec.reasons


def test_disallowed_ref():
    with pytest.raises(AuthorizationDenied) as e:
        _auth(_ctx(), ref="refs/heads/other")
    assert e.value.reason == "ref_not_allowed"


def test_branch_ref_mismatch():
    with pytest.raises(AuthorizationDenied) as e:
        _auth(_ctx(), branch="feature")            # caller-supplied branch != branch derived from ref
    assert e.value.reason == "branch_ref_mismatch"


def test_client_cannot_select_installation():
    with pytest.raises(AuthorizationDenied) as e:  # directory says 2, policy pinned to 1
        _auth(_ctx(mapping={"orgA": 2}))
    assert e.value.reason == "installation_policy_mismatch"


def test_policy_version_mismatch():
    with pytest.raises(AuthorizationDenied) as e:
        _auth(_ctx(), expected_policy_version=99)
    assert e.value.reason == "policy_version_mismatch"


def test_missing_tree_sha():
    with pytest.raises(AuthorizationDenied) as e:
        _auth((GitHubAppRepositoryProvider(MockGitHub(tree="")),
               InMemoryTaskPolicyRepository([_policy()]), InstallationDirectory({"orgA": 1})))
    assert e.value.reason == "missing_tree_sha"


def test_malformed_commit_sha():
    with pytest.raises(AuthorizationDenied) as e:
        _auth((GitHubAppRepositoryProvider(MockGitHub(sha="notasha")),
               InMemoryTaskPolicyRepository([_policy()]), InstallationDirectory({"orgA": 1})))
    assert e.value.reason == "bad_commit_sha"


def test_no_write_permission():
    with pytest.raises(AuthorizationDenied) as e:
        _auth((GitHubAppRepositoryProvider(MockGitHub(push=False)),
               InMemoryTaskPolicyRepository([_policy()]), InstallationDirectory({"orgA": 1})))
    assert e.value.reason == "no_write"


def test_path_outside_policy():
    with pytest.raises(AuthorizationDenied) as e:
        _auth(_ctx(), path="docs/x.md")
    assert e.value.reason == "path_not_allowed"


@pytest.mark.parametrize("bad,reason", [
    ("%2e%2e/etc", "path_encoded_traversal"), ("a\\b", "path_bad_chars"),
    ("../x", "path_traversal"), ("/etc/passwd", "path_absolute")])
def test_path_normalization_rejects(bad, reason):
    with pytest.raises(AuthorizationDenied) as e:
        normalize_git_path(bad)
    assert e.value.reason == reason
    assert normalize_git_path("src/pkg/a.py") == "src/pkg/a.py"
