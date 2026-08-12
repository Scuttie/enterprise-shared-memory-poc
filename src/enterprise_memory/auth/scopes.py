"""Endpoint scope enforcement (P3 §13). Scopes are carried in the verified access token (`scope` string or
`scp` list) — NEVER in the request body. Each endpoint declares the minimum scope it requires; a request is
authorized only if the token carries that scope."""
from __future__ import annotations
from typing import Iterable, List

SOLVE_SUBMIT = "solve:submit"
SOLVE_READ = "solve:read"
PRIVATE_READ = "memory:private:read"
PRIVATE_WRITE = "memory:private:write"
SHARED_READ = "memory:shared:read"
CONTRACT_PROPOSE = "memory:contract:propose"
CONTRACT_REVIEW = "memory:contract:review"
CONTRACT_PROMOTE = "memory:contract:promote"
CONTRACT_DEPRECATE = "memory:contract:deprecate"
ADMIN = "memory:admin"

SCOPES = frozenset({SOLVE_SUBMIT, SOLVE_READ, PRIVATE_READ, PRIVATE_WRITE, SHARED_READ,
                    CONTRACT_PROPOSE, CONTRACT_REVIEW, CONTRACT_PROMOTE, CONTRACT_DEPRECATE, ADMIN})

# (METHOD, path-template) -> minimum required scope
ENDPOINT_SCOPES = {
    ("POST", "/solve"): SOLVE_SUBMIT,
    ("GET", "/solve/{job_id}"): SOLVE_READ,
    ("GET", "/memory/private"): PRIVATE_READ,
    ("POST", "/memory/private"): PRIVATE_WRITE,
    ("GET", "/memory/shared"): SHARED_READ,
    ("POST", "/memory/contracts"): CONTRACT_PROPOSE,
    ("POST", "/memory/contracts/{contract_id}/review"): CONTRACT_REVIEW,
    ("POST", "/memory/contracts/{contract_id}/promote"): CONTRACT_PROMOTE,
    ("POST", "/memory/contracts/{contract_id}/deprecate"): CONTRACT_DEPRECATE,
    ("POST", "/admin/reindex"): ADMIN,
}


class ScopeError(Exception):
    """Missing/insufficient scope. Fail-closed — deny."""


def token_scopes(claims: dict) -> List[str]:
    """Scopes from the verified token only: OAuth `scope` (space-delimited) or `scp` (list)."""
    raw = claims.get("scope")
    if isinstance(raw, str) and raw.strip():
        return raw.split()
    scp = claims.get("scp")
    if isinstance(scp, (list, tuple)):
        return [str(s) for s in scp]
    return []


def has_scope(claims: dict, required: str) -> bool:
    return required in set(token_scopes(claims))


def required_scope_for(method: str, path_template: str) -> str:
    try:
        return ENDPOINT_SCOPES[(method.upper(), path_template)]
    except KeyError:
        raise ScopeError("no_scope_mapping:%s %s" % (method, path_template))


def require_scope(claims: dict, required: str):
    if not has_scope(claims, required):
        raise ScopeError("missing_scope:%s" % required)


def authorize_endpoint(claims: dict, method: str, path_template: str):
    """Raise ScopeError unless the token carries the endpoint's minimum scope. ADMIN does NOT implicitly
    satisfy other scopes — least privilege is explicit."""
    require_scope(claims, required_scope_for(method, path_template))
