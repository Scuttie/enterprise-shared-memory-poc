"""OIDC network / JWK / claim hardening (P3.1 §5)."""
import threading
import time
import pytest
from conftest import base_claims, ISSUER, AUDIENCE
from enterprise_memory.auth.oidc import (OIDCConfig, JWKSCache, verify_access_token, OIDCError,
                                         validate_jwks_uri)


def cfg(jwks_uri="https://idp.test.local/jwks.json", **over):
    kw = dict(issuer=ISSUER, audience=AUDIENCE, jwks_uri=jwks_uri, allowed_algs=("RS256",),
              environment="production")
    kw.update(over)
    return OIDCConfig(**kw)


# ---- JWKS URI policy -----------------------------------------------------------------------------
def test_prod_requires_https():
    with pytest.raises(OIDCError):
        validate_jwks_uri("http://idp/jwks", cfg())


def test_prod_rejects_userinfo():
    with pytest.raises(OIDCError):
        validate_jwks_uri("https://user:pw@idp/jwks", cfg())


def test_prod_rejects_unallowlisted_port():
    with pytest.raises(OIDCError):
        validate_jwks_uri("https://idp:8443/jwks", cfg())
    validate_jwks_uri("https://idp:8443/jwks", cfg(allowed_jwks_ports=(443, 8443)))   # allowlisted ok


def test_dev_allows_http():
    validate_jwks_uri("http://127.0.0.1:9999/jwks", cfg(environment="dev"))


# ---- JWKS document validation --------------------------------------------------------------------
def test_empty_jwks_rejected(ring):
    ring.add_rsa("k1"); c = cfg()
    cache = JWKSCache(c, fetcher=lambda: {"keys": []})
    with pytest.raises(OIDCError):
        verify_access_token(ring.sign("k1", base_claims()), c, cache)


def test_duplicate_kid_rejected(ring):
    ring.add_rsa("k1"); ring.add_rsa("k2"); c = cfg()
    j1 = dict(ring.keys["k1"][1]); j2 = dict(ring.keys["k2"][1]); j2["kid"] = "k1"
    cache = JWKSCache(c, fetcher=lambda: {"keys": [j1, j2]})
    with pytest.raises(OIDCError) as e:
        verify_access_token(ring.sign("k1", base_claims()), c, cache)
    assert "duplicate_kid" in str(e.value)


def test_too_many_keys_rejected(ring):
    ring.add_rsa("k1"); c = cfg(max_jwks_keys=1)
    j = dict(ring.keys["k1"][1]); j2 = dict(j); j2["kid"] = "k2"
    cache = JWKSCache(c, fetcher=lambda: {"keys": [j, j2]})
    with pytest.raises(OIDCError):
        verify_access_token(ring.sign("k1", base_claims()), c, cache)


# ---- per-JWK validation --------------------------------------------------------------------------
def test_jwk_kty_mismatch(ring):
    ring.add_rsa("k1"); ring.add_ec("e1"); c = cfg()
    ec = dict(ring.keys["e1"][1]); ec["kid"] = "k1"          # EC key published under the RS256 kid
    cache = JWKSCache(c, fetcher=lambda: {"keys": [ec]})
    with pytest.raises(OIDCError) as e:
        verify_access_token(ring.sign("k1", base_claims()), c, cache)
    assert str(e.value) == "jwk_kty_mismatch"


def test_jwk_use_not_sig(ring):
    ring.add_rsa("k1"); c = cfg()
    j = dict(ring.keys["k1"][1]); j["use"] = "enc"
    cache = JWKSCache(c, fetcher=lambda: {"keys": [j]})
    with pytest.raises(OIDCError) as e:
        verify_access_token(ring.sign("k1", base_claims()), c, cache)
    assert str(e.value) == "jwk_use_not_sig"


def test_jwk_key_ops_no_verify(ring):
    ring.add_rsa("k1"); c = cfg()
    j = dict(ring.keys["k1"][1]); j["key_ops"] = ["encrypt"]
    cache = JWKSCache(c, fetcher=lambda: {"keys": [j]})
    with pytest.raises(OIDCError) as e:
        verify_access_token(ring.sign("k1", base_claims()), c, cache)
    assert str(e.value) == "jwk_key_ops_no_verify"


# ---- claim type validation -----------------------------------------------------------------------
def test_org_id_must_be_string(ring):
    ring.add_rsa("k1"); c = cfg()
    with pytest.raises(OIDCError) as e:
        verify_access_token(ring.sign("k1", base_claims(org_id=123)), c,
                            JWKSCache(c, fetcher=lambda: ring.jwks()))
    assert str(e.value) == "claim_org_id_invalid"


def test_scope_must_be_string(ring):
    ring.add_rsa("k1"); c = cfg()
    with pytest.raises(OIDCError) as e:
        verify_access_token(ring.sign("k1", base_claims(scope=["a", "b"])), c,
                            JWKSCache(c, fetcher=lambda: ring.jwks()))
    assert str(e.value) == "claim_scope_invalid"


# ---- single-flight refresh -----------------------------------------------------------------------
def test_single_flight_refresh(ring):
    ring.add_rsa("k1"); c = cfg()
    calls = {"n": 0}

    def slow():
        calls["n"] += 1
        time.sleep(0.2)
        return ring.jwks()

    cache = JWKSCache(c, fetcher=slow)
    tok = ring.sign("k1", base_claims())
    errs = []

    def worker():
        try:
            verify_access_token(tok, c, cache)
        except Exception as ex:  # noqa: BLE001
            errs.append(ex)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errs and calls["n"] == 1      # concurrent unknown-kid requests -> one refresh, no storm
