"""Negative / security E2E matrix (P5 §11). Every case fails closed and is tenant-safe."""
import time
import json
import uuid
import pytest
from conftest import ISSUER, AUDIENCE

jwt = pytest.importorskip("jwt")
from cryptography.hazmat.primitives.asymmetric import rsa                # noqa: E402
from cryptography.hazmat.primitives import serialization                 # noqa: E402

BODY = {"task_id": "fix-return", "instruction": "make f return 1", "desired_ref": "refs/heads/main"}


def _solve(client, token, **over):
    body = dict(BODY); body.update(over)
    return client.post("/v1/solve", headers={"authorization": "Bearer " + token}, json=body)


def test_no_token(seed, client):
    s = seed()
    assert client.post("/v1/solve", json={**BODY, "repository_id": s["repo"]}).status_code == 401


def test_bad_signature(seed, keyring, client):
    s = seed()
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = other.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption())
    now = int(time.time())
    tok = jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "sub": s["user"], "org_id": s["org"],
                      "scope": "solve:submit", "iat": now, "nbf": now - 5, "exp": now + 600}, pem,
                     algorithm="RS256", headers={"kid": "e2e-1"})       # unpublished key under a known kid
    assert _solve(client, tok, repository_id=s["repo"]).status_code == 401


def test_expired_token(seed, keyring, client):
    s = seed()
    tok = keyring(s["user"], s["org"], ["solve:submit"], exp=int(time.time()) - 1000)
    assert _solve(client, tok, repository_id=s["repo"]).status_code == 401


def test_wrong_issuer_and_audience(seed, keyring, client):
    s = seed()
    assert _solve(client, keyring(s["user"], s["org"], ["solve:submit"], iss="https://evil/"),
                  repository_id=s["repo"]).status_code == 401
    assert _solve(client, keyring(s["user"], s["org"], ["solve:submit"], aud="other"),
                  repository_id=s["repo"]).status_code == 401


def test_missing_scope(seed, keyring, client):
    s = seed()
    assert _solve(client, keyring(s["user"], s["org"], ["memory:shared:read"]),
                  repository_id=s["repo"]).status_code == 403


def test_body_identity_spoof_rejected(seed, keyring, client):
    s = seed()
    tok = keyring(s["user"], s["org"], ["solve:submit"])
    r = client.post("/v1/solve", headers={"authorization": "Bearer " + tok},
                    json={**BODY, "repository_id": s["repo"], "org_id": "spoof", "user_id": "spoof",
                          "patch": "x", "test_passed": True})
    assert r.status_code == 422                                          # extra fields forbidden


def test_no_modify_permission(seed, keyring, client):
    s = seed(with_modify=False)
    tok = keyring(s["user"], s["org"], ["solve:submit"])
    assert _solve(client, tok, repository_id=s["repo"]).status_code == 403


def test_ref_not_allowed(seed, keyring, client):
    s = seed()
    tok = keyring(s["user"], s["org"], ["solve:submit"])
    assert _solve(client, tok, repository_id=s["repo"], desired_ref="refs/heads/other").status_code == 400


def test_unknown_task_policy(seed, keyring, client):
    s = seed()
    tok = keyring(s["user"], s["org"], ["solve:submit"])
    assert _solve(client, tok, repository_id=s["repo"], task_id="nonexistent").status_code == 403


def test_cross_tenant_job_hidden(seed, keyring, client):
    a = seed(); b = seed()
    ta = keyring(a["user"], a["org"], ["solve:submit", "solve:read"])
    r = client.post("/v1/solve", headers={"authorization": "Bearer " + ta, "Idempotency-Key": "x-%s" % uuid.uuid4()},
                    json={**BODY, "repository_id": a["repo"]})
    job_id = r.json()["job_id"]
    tb = keyring(b["user"], b["org"], ["solve:read"])                    # different tenant guesses the id
    assert client.get("/v1/jobs/%s" % job_id, headers={"authorization": "Bearer " + tb}).status_code == 404


def test_foreign_private_memory_not_returned(seed, keyring, client):
    s = seed()
    # another user in the same org searching private returns nothing (owner-scoped)
    other_user = str(uuid.uuid4())
    tok = keyring(other_user, s["org"], ["memory:private:read"])
    r = client.post("/v1/memories/search", headers={"authorization": "Bearer " + tok},
                    json={"scope": "private", "query": "anything"})
    assert r.status_code == 200 and r.json()["hits"] == []


def test_search_missing_scope(seed, keyring, client):
    s = seed()
    tok = keyring(s["user"], s["org"], ["solve:submit"])                 # no memory:shared:read
    assert client.post("/v1/memories/search", headers={"authorization": "Bearer " + tok},
                       json={"scope": "shared", "query": "x"}).status_code == 403
