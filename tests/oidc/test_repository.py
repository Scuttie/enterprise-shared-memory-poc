"""Repository authorization against a MOCKED GitHub App (P3 §14): installation approval, repo membership,
read vs modify, branch/path restrictions, ref->immutable commit + tree, short-lived creds never in the
decision, and server-derived permissions the client cannot override."""
import pytest
from enterprise_memory.auth.repository import (GitHubAppRepositoryProvider, RepositoryAccessError,
                                               AuthorizationDenied)


class MockGitHub:
    def __init__(self, push=False, suspended=False, repos=("orgA/repoX",)):
        self.installations = {1: {"account": "orgA", "suspended": suspended, "repositories": list(repos)}}
        self.repos = {(1, "orgA/repoX"): {"full_name": "orgA/repoX", "default_branch": "main",
                                          "permissions": {"pull": True, "push": push}}}
        self.refs = {("orgA/repoX", "main"): {"sha": "c0ffee1234"}}
        self.trees = {("orgA/repoX", "c0ffee1234"): {"tree_sha": "tree-abc"}}
        self.token_calls = 0

    def get_installation(self, i):
        return self.installations.get(i)

    def get_repo(self, i, f):
        return self.repos.get((i, f))

    def get_ref(self, f, r):
        return self.refs.get((f, r))

    def get_commit_tree(self, f, s):
        return self.trees.get((f, s))

    def create_installation_token(self, i):
        self.token_calls += 1
        return {"token": "ghs_ephemeral_SECRET", "expires_at": "2026-01-01T00:00:00Z"}


def prov(**kw):
    return GitHubAppRepositoryProvider(MockGitHub(**kw))


def test_read_allowed_and_ref_resolves_immutable():
    d = prov(push=False).authorize(1, "orgA/repoX", "read", ref="main", branch="main",
                                   allowed_branch_globs=["main"], path="src/a.py",
                                   allowed_path_globs=["src/**"])
    assert d.allowed and d.commit_sha == "c0ffee1234" and d.tree_sha == "tree-abc"


def test_modify_denied_without_push():
    with pytest.raises(AuthorizationDenied) as e:
        prov(push=False).authorize(1, "orgA/repoX", "modify")
    assert e.value.reason == "no_write"


def test_modify_allowed_with_push():
    d = prov(push=True).authorize(1, "orgA/repoX", "modify", ref="main")
    assert d.allowed and d.action == "modify" and d.commit_sha == "c0ffee1234"


def test_repo_outside_installation():
    with pytest.raises(RepositoryAccessError):
        prov(repos=()).authorize(1, "orgA/repoX", "read")


def test_suspended_installation():
    with pytest.raises(RepositoryAccessError):
        prov(suspended=True).authorize(1, "orgA/repoX", "read")


def test_branch_restriction():
    with pytest.raises(AuthorizationDenied) as e:
        prov().authorize(1, "orgA/repoX", "read", branch="feature/x", allowed_branch_globs=["main"])
    assert e.value.reason == "branch_not_allowed"


@pytest.mark.parametrize("bad", ["../etc/passwd", "/etc/passwd", "~/secrets", "C:\\Windows", "a/../../b"])
def test_path_traversal_rejected(bad):
    with pytest.raises(AuthorizationDenied) as e:
        prov().authorize(1, "orgA/repoX", "read", path=bad, allowed_path_globs=["**"])
    assert e.value.reason == "path_traversal"


def test_path_not_allowed():
    with pytest.raises(AuthorizationDenied) as e:
        prov().authorize(1, "orgA/repoX", "read", path="docs/readme.md", allowed_path_globs=["src/**"])
    assert e.value.reason == "path_not_allowed"


def test_decision_never_contains_credentials():
    gh = MockGitHub(push=True)
    p = GitHubAppRepositoryProvider(gh)
    d = p.authorize(1, "orgA/repoX", "modify", ref="main")
    blob = str(d) + repr(d)
    assert "ghs_ephemeral_SECRET" not in blob and not hasattr(d, "token")
    tok = p.ephemeral_token(1)                          # minted only via the executor-only method
    assert tok["token"] == "ghs_ephemeral_SECRET" and gh.token_calls == 1


def test_client_cannot_override_permission_or_commit():
    # caller "wants" modify + supplies permissive path globs, but server push=False wins
    with pytest.raises(AuthorizationDenied):
        prov(push=False).authorize(1, "orgA/repoX", "modify", path="src/x.py", allowed_path_globs=["**"])
    # the immutable commit always comes from the server ref resolution, never from client input
    d = prov(push=True).authorize(1, "orgA/repoX", "modify", ref="main")
    assert d.commit_sha == "c0ffee1234"
