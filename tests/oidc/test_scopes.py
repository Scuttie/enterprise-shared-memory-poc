"""Endpoint scope matrix (P3 §13): every endpoint enforces exactly its minimum scope; scopes come from the
token only; admin does not implicitly grant other scopes."""
import pytest
from enterprise_memory.auth.scopes import (ENDPOINT_SCOPES, authorize_endpoint, ScopeError,
                                           token_scopes, has_scope)


def _claims(scopes):
    return {"scope": " ".join(scopes)}


def test_each_endpoint_requires_its_minimum_scope():
    for (method, path), req in ENDPOINT_SCOPES.items():
        authorize_endpoint(_claims([req]), method, path)              # exact scope authorizes
        with pytest.raises(ScopeError):
            authorize_endpoint(_claims([]), method, path)             # no scope denied
        other = next(s for s in ENDPOINT_SCOPES.values() if s != req)
        with pytest.raises(ScopeError):
            authorize_endpoint(_claims([other]), method, path)        # a different scope denied


def test_scope_forms():
    assert has_scope({"scp": ["solve:read"]}, "solve:read")
    assert token_scopes({"scope": "a b c"}) == ["a", "b", "c"]
    assert token_scopes({}) == []


def test_admin_does_not_imply_others():
    with pytest.raises(ScopeError):
        authorize_endpoint(_claims(["memory:admin"]), "POST", "/solve")


def test_unknown_endpoint_denied():
    with pytest.raises(ScopeError):
        authorize_endpoint(_claims(["solve:submit"]), "GET", "/nope")
