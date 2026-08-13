"""OIDC verifier matrix (P3 §12): signatures, issuer/audience, exp/nbf/iat, alg allowlist, alg=none,
symmetric rejection, unknown kid, JWKS rotation, cache TTL, and fail-closed fetch."""
import time
import pytest
from conftest import base_claims, ISSUER, AUDIENCE
from enterprise_memory.auth.oidc import OIDCConfig, JWKSCache, verify_access_token, OIDCError


def cfg(jwks_uri="https://idp.test.local/jwks.json", **over):
    kw = dict(issuer=ISSUER, audience=AUDIENCE, jwks_uri=jwks_uri, allowed_algs=("RS256",),
              environment="production")
    kw.update(over)
    return OIDCConfig(**kw)


def cache_for(ring, c, **kw):
    return JWKSCache(c, fetcher=lambda: ring.jwks(), **kw)


def test_valid_rs256(ring):
    ring.add_rsa("k1")
    c = cfg()
    claims = verify_access_token(ring.sign("k1", base_claims()), c, cache_for(ring, c))
    assert claims["sub"] == "user-123" and claims["org_id"] == "org-abc"


def test_bad_signature_unknown_key(ring):
    ring.add_rsa("k1")
    ring.add_rsa("k2")                                    # k2 not published in jwks (only k1)
    c = cfg()
    cache = JWKSCache(c, fetcher=lambda: ring.jwks(["k1"]))
    with pytest.raises(OIDCError):
        verify_access_token(ring.sign("k2", base_claims()), c, cache)


def test_wrong_issuer(ring):
    ring.add_rsa("k1"); c = cfg()
    with pytest.raises(OIDCError) as e:
        verify_access_token(ring.sign("k1", base_claims(iss="https://evil/")), c, cache_for(ring, c))
    assert "issuer" in str(e.value)


def test_wrong_audience(ring):
    ring.add_rsa("k1"); c = cfg()
    with pytest.raises(OIDCError) as e:
        verify_access_token(ring.sign("k1", base_claims(aud="other")), c, cache_for(ring, c))
    assert "audience" in str(e.value)


def test_missing_exp(ring):
    ring.add_rsa("k1"); c = cfg()
    claims = base_claims(); claims.pop("exp")
    with pytest.raises(OIDCError):
        verify_access_token(ring.sign("k1", claims), c, cache_for(ring, c))


def test_expired(ring):
    ring.add_rsa("k1"); c = cfg()
    with pytest.raises(OIDCError) as e:                   # beyond the 60s bounded leeway
        verify_access_token(ring.sign("k1", base_claims(exp=int(time.time()) - 1000)), c, cache_for(ring, c))
    assert str(e.value) == "expired"


def test_not_yet_valid_nbf(ring):
    ring.add_rsa("k1"); c = cfg()
    with pytest.raises(OIDCError) as e:
        verify_access_token(ring.sign("k1", base_claims(nbf=int(time.time()) + 600)), c, cache_for(ring, c))
    assert str(e.value) == "not_yet_valid"


def test_missing_org_id(ring):
    ring.add_rsa("k1"); c = cfg()
    claims = base_claims(); claims.pop("org_id")
    with pytest.raises(OIDCError) as e:
        verify_access_token(ring.sign("k1", claims), c, cache_for(ring, c))
    assert "org_id" in str(e.value)


def test_iat_in_future(ring):
    ring.add_rsa("k1"); c = cfg()
    with pytest.raises(OIDCError) as e:                   # PyJWT rejects a future iat as immature; our
        verify_access_token(ring.sign("k1", base_claims(iat=int(time.time()) + 10_000)), c, cache_for(ring, c))
    assert str(e.value) in ("iat_in_future", "not_yet_valid")   # manual iat guard is defence-in-depth


def test_alg_none_rejected(ring):
    ring.add_rsa("k1"); c = cfg()
    tok = __import__("jwt").encode(base_claims(), None, algorithm="none", headers={"kid": "k1"})
    with pytest.raises(OIDCError) as e:
        verify_access_token(tok, c, cache_for(ring, c))
    assert str(e.value) == "alg_none"


def test_hs256_not_allowed(ring):
    ring.add_rsa("k1"); c = cfg()
    tok = __import__("jwt").encode(base_claims(), "shared-secret", algorithm="HS256", headers={"kid": "k1"})
    with pytest.raises(OIDCError) as e:
        verify_access_token(tok, c, cache_for(ring, c))
    assert "alg_not_allowed" in str(e.value)


def test_symmetric_forbidden_even_if_allowlisted(ring):
    ring.add_rsa("k1")
    c = cfg(allowed_algs=("RS256", "HS256"), environment="production")
    tok = __import__("jwt").encode(base_claims(), "shared-secret", algorithm="HS256", headers={"kid": "k1"})
    with pytest.raises(OIDCError) as e:
        verify_access_token(tok, c, cache_for(ring, c))
    assert str(e.value) == "symmetric_alg_forbidden"


def test_token_too_large(ring):
    ring.add_rsa("k1"); c = cfg(max_token_bytes=64)
    with pytest.raises(OIDCError) as e:
        verify_access_token(ring.sign("k1", base_claims()), c, cache_for(ring, c))
    assert str(e.value) == "token_too_large"


def test_es256_when_enabled(ring):
    ring.add_ec("e1")
    c = cfg(allowed_algs=("RS256", "ES256"))
    claims = verify_access_token(ring.sign("e1", base_claims()), c, cache_for(ring, c))
    assert claims["sub"] == "user-123"


def test_es256_rejected_when_not_allowlisted(ring):
    ring.add_ec("e1"); c = cfg(allowed_algs=("RS256",))
    with pytest.raises(OIDCError) as e:
        verify_access_token(ring.sign("e1", base_claims()), c, cache_for(ring, c))
    assert "alg_not_allowed" in str(e.value)


def test_fail_closed_when_jwks_unavailable(ring):
    ring.add_rsa("k1"); c = cfg()

    def boom():
        raise RuntimeError("network down")

    cache = JWKSCache(c, fetcher=boom)
    with pytest.raises(OIDCError) as e:
        verify_access_token(ring.sign("k1", base_claims()), c, cache)
    assert str(e.value) == "jwks_unavailable"


# ---- HTTP path (local JWKS server) --------------------------------------------------------------
def test_http_fetch_and_valid(ring, jwks_server):
    ring.add_rsa("k1")
    c = cfg(jwks_uri=jwks_server.url, environment="dev")
    cache = JWKSCache(c)                                  # default fetcher hits the local server
    claims = verify_access_token(ring.sign("k1", base_claims()), c, cache)
    assert claims["sub"] == "user-123" and jwks_server.hits >= 1


def test_key_rotation(ring, jwks_server):
    ring.add_rsa("k1")
    c = cfg(jwks_uri=jwks_server.url, environment="dev")
    cache = JWKSCache(c)
    assert verify_access_token(ring.sign("k1", base_claims()), c, cache)["sub"] == "user-123"
    ring.add_rsa("k2"); jwks_server.set_kids(["k2"])     # rotate: only k2 published now
    assert verify_access_token(ring.sign("k2", base_claims()), c, cache)["sub"] == "user-123"  # refresh picks it up
    with pytest.raises(OIDCError):                        # retired k1 no longer verifiable
        verify_access_token(ring.sign("k1", base_claims()), c, cache)


def test_cache_ttl_bounds_refresh(ring, jwks_server):
    ring.add_rsa("k1")
    base = time.time()
    clk = {"t": base}
    c = cfg(jwks_uri=jwks_server.url, cache_ttl_seconds=100, environment="dev")
    cache = JWKSCache(c, clock=lambda: clk["t"])
    tok = ring.sign("k1", base_claims())
    verify_access_token(tok, c, cache, clock=lambda: clk["t"])
    h1 = jwks_server.hits
    verify_access_token(tok, c, cache, clock=lambda: clk["t"])     # within TTL -> cached, no new fetch
    assert jwks_server.hits == h1
    clk["t"] = base + 200                                          # beyond TTL -> refetch
    verify_access_token(tok, c, cache, clock=lambda: clk["t"])
    assert jwks_server.hits > h1
