"""P5 request dependencies: OIDC identity, DB-backed repository authorization + task policy, and an offline
deterministic repository provider (the credential-free "mocked GitHub App" used in ci-e2e). All authoritative
data comes from the verified token and PostgreSQL — never from the request body."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from typing import List, Optional
from sqlalchemy import text

from ..persistence.tenant_context import tenant_tx
from ..auth.oidc import verify_access_token, OIDCError
from ..auth.scopes import token_scopes

DEFAULT_SRC = "def f():\n    return 0\n"
DEFAULT_TEST = "from src.app import f\n\n\ndef test_f():\n    assert f() == 1\n"


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class Unauthenticated(Exception):
    pass


@dataclass
class IdentityContext:
    subject_id: str
    org_id: str
    scopes: List[str]
    request_id: Optional[str] = None

    def as_claims(self):
        return {"scope": " ".join(self.scopes)}


class OIDCIdentityProvider:
    def __init__(self, config, cache):
        self._config = config
        self._cache = cache

    def authenticate(self, authorization_header, request_id=None) -> IdentityContext:
        if not authorization_header or not authorization_header.lower().startswith("bearer "):
            raise Unauthenticated("missing_bearer")
        token = authorization_header.split(" ", 1)[1].strip()
        try:
            claims = verify_access_token(token, self._config, self._cache)
        except OIDCError as e:
            raise Unauthenticated(str(e))
        return IdentityContext(subject_id=claims["sub"], org_id=claims["org_id"],
                               scopes=token_scopes(claims), request_id=request_id)


class DbRepositoryAuthz:
    async def can_modify(self, engine, org_id, user_id, repo_id) -> bool:
        async with tenant_tx(engine, org_id, user_id) as c:
            n = (await c.execute(text(
                "SELECT count(*) FROM repository_permissions p WHERE p.repository_id=:r AND p.can_modify"
                " AND ((p.subject_type='user' AND p.subject_id=:u)"
                "   OR (p.subject_type='team' AND p.subject_id IN"
                "        (SELECT tm.team_id FROM team_memberships tm WHERE tm.user_id=:u)))"),
                {"r": repo_id, "u": user_id})).scalar()
        return int(n or 0) > 0


class DbTaskPolicyRepository:
    async def get(self, engine, org_id, repo_id, task_key):
        async with tenant_tx(engine, org_id) as c:
            r = (await c.execute(text(
                "SELECT id, editable_paths, target_symbol, exact_signature, test_bundle_ref,"
                " maximum_changed_lines, allowed_refs, version, target_path, family_id, domain,"
                " repository_fixture_id, public_test_entry, hidden_test_manifest_id, runtime, timeout_seconds,"
                " allowed_import_changes, allowed_new_files, source_world_id, target_world_id, policy_version,"
                " retrieval_policy, experiment_id, experiment_arm"
                " FROM task_execution_policies WHERE repository_id=:r AND task_key=:tk AND active"),
                {"r": repo_id, "tk": task_key})).first()
        if r is None:
            return None
        rp = r[21]
        return {"task_policy_id": str(r[0]), "editable_paths": list(r[1]), "target_symbol": r[2],
                "exact_signature": r[3], "test_bundle_ref": r[4], "maximum_changed_lines": int(r[5]),
                "allowed_refs": list(r[6]), "version": int(r[7]),
                "target_path": r[8], "family_id": r[9], "domain": r[10], "repository_fixture_id": r[11],
                "public_test_entry": r[12], "hidden_test_manifest_id": r[13], "runtime": r[14],
                "timeout_seconds": (int(r[15]) if r[15] is not None else None),
                "allowed_import_changes": (list(r[16]) if r[16] is not None else []),
                "allowed_new_files": (list(r[17]) if r[17] is not None else []),
                "source_world_id": r[18], "target_world_id": r[19],
                "policy_version": (int(r[20]) if r[20] is not None else None),
                "retrieval_policy": (rp if isinstance(rp, dict) else (json.loads(rp) if rp else None)),
                "experiment_id": r[22], "experiment_arm": r[23]}


class OfflineRepositoryProvider:
    """Deterministic, credential-free repository resolution + sanitized snapshot. Immutable commit/tree are
    server-derived; the harness/worker only ever sees a read-only snapshot."""
    def installation_for(self, org_id) -> int:
        return int(_sha(str(org_id))[:8], 16) % 1_000_000 + 1

    def resolve_commit(self, repo_id, ref) -> str:
        return _sha("%s|%s" % (repo_id, ref))[:40]

    def resolve_tree(self, commit_sha) -> str:
        return _sha("tree|%s" % commit_sha)[:40]

    def snapshot(self, repo_id, commit_sha, target_path) -> dict:
        return {target_path: DEFAULT_SRC, "tests/test_app.py": DEFAULT_TEST}

    def hidden_test(self, repo_id):
        return None                     # demo task grades on the public test in the snapshot


def ref_allowed(ref: str, allowed_refs) -> bool:
    import fnmatch
    return any(fnmatch.fnmatch(ref, g) or ref == g for g in allowed_refs)
