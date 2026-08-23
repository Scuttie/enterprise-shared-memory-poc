"""Production OIDC access-token verification (P3 §12 + P3.1 §5). Fail-closed by construction:

- algorithm allowlist (default RS256; ES256 only if explicitly enabled); alg=none and any non-allowlisted
  algorithm are rejected; symmetric algorithms (HS*) are rejected outright in staging/production;
- the JWKS URI is validated in staging/production: HTTPS only, no userinfo, port allowlist, and redirects
  may not change scheme or host; the fetch applies a timeout, bounds the response size and the number of
  keys, rejects an empty JWKS and duplicate `kid`s;
- each selected JWK is validated (kty matches the algorithm; optional alg/use/key_ops are consistent) before
  the key material is trusted; signature verified against the JWKS key selected by `kid`; unknown kid forces
  one single-flight refresh; key rotation is picked up; a JWKS fetch failure with no usable cached key is
  rejected (never fail-open);
- issuer + audience are verified; exp is required; nbf/iat are checked with a bounded leeway; an iat in the
  future is rejected; sub/org_id are required and type-checked; oversized tokens are rejected before parsing.

Every parser/type failure is normalized to OIDCError — no raw ValueError/TypeError escapes as an HTTP 500.
Identity/authorization is taken ONLY from the returned verified claims — never from request-body input."""
from __future__ import annotations
import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urlsplit

import jwt
from jwt.algorithms import RSAAlgorithm, ECAlgorithm

_ALG_TO_JWK = {"RS256": RSAAlgorithm, "ES256": ECAlgorithm}
_ALG_TO_KTY = {"RS256": "RSA", "ES256": "EC"}
_MAX_LEEWAY = 300


class OIDCError(Exception):
    """Any verification failure. Always fail-closed — the caller must treat this as 'deny'."""


@dataclass
class OIDCConfig:
    issuer: str
    audience: str
    jwks_uri: str
    allowed_algs: Tuple[str, ...] = ("RS256",)
    environment: str = "production"           # dev | staging | production
    leeway_seconds: int = 60
    cache_ttl_seconds: int = 300
    max_token_bytes: int = 8192
    require_claims: Tuple[str, ...] = ("exp", "sub", "org_id")
    allowed_jwks_ports: Tuple[int, ...] = (443,)
    http_timeout: float = 5.0
    max_jwks_bytes: int = 1_048_576
    max_jwks_keys: int = 32

    def bounded_leeway(self) -> int:
        return max(0, min(int(self.leeway_seconds), _MAX_LEEWAY))

    def is_prod_like(self) -> bool:
        return self.environment in ("staging", "production")


def validate_jwks_uri(uri: str, config: OIDCConfig):
    """Fail-closed JWKS URI policy (enforced in staging/production)."""
    try:
        parts = urlsplit(uri)
    except Exception:
        raise OIDCError("bad_jwks_uri")
    if not config.is_prod_like():
        if parts.scheme not in ("http", "https"):
            raise OIDCError("bad_jwks_scheme")
        return
    if parts.scheme != "https":
        raise OIDCError("jwks_requires_https")
    if parts.username or parts.password or "@" in (parts.netloc or ""):
        raise OIDCError("jwks_uri_userinfo_forbidden")
    port = parts.port if parts.port is not None else 443
    if port not in config.allowed_jwks_ports:
        raise OIDCError("jwks_port_not_allowlisted:%s" % port)
    if not parts.hostname:
        raise OIDCError("jwks_uri_no_host")


class _StrictRedirect(urllib.request.HTTPRedirectHandler):
    """Reject redirects that change scheme or host (SSRF hardening)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urlsplit(req.full_url)
        new = urlsplit(newurl)
        if new.scheme != old.scheme or (new.hostname or "").lower() != (old.hostname or "").lower():
            raise OIDCError("jwks_cross_host_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _bounded_fetch(uri: str, config: OIDCConfig) -> dict:
    opener = urllib.request.build_opener(_StrictRedirect())
    try:
        with opener.open(uri, timeout=config.http_timeout) as r:  # noqa: S310 - validated https uri
            raw = r.read(config.max_jwks_bytes + 1)
    except OIDCError:
        raise
    except Exception:
        raise OIDCError("jwks_fetch_failed")
    if len(raw) > config.max_jwks_bytes:
        raise OIDCError("jwks_too_large")
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        raise OIDCError("jwks_not_json")


def _normalise_jwks(data: dict, config: OIDCConfig) -> Dict[str, dict]:
    if not isinstance(data, dict):
        raise OIDCError("jwks_malformed")
    keys = data.get("keys")
    if not isinstance(keys, list) or not keys:
        raise OIDCError("jwks_empty")
    if len(keys) > config.max_jwks_keys:
        raise OIDCError("jwks_too_many_keys")
    by_kid: Dict[str, dict] = {}
    for jwk in keys:
        if not isinstance(jwk, dict):
            raise OIDCError("jwks_bad_key")
        kid = jwk.get("kid")
        if not kid:
            continue
        if kid in by_kid:
            raise OIDCError("jwks_duplicate_kid")
        by_kid[kid] = jwk
    if not by_kid:
        raise OIDCError("jwks_no_usable_keys")
    return by_kid


class JWKSCache:
    """kid -> JWK cache with TTL, single-flight refresh (one per issuer at a time), fail-closed fetch."""

    def __init__(self, config: OIDCConfig, fetcher: Optional[Callable[[], dict]] = None,
                 clock: Callable[[], float] = time.time):
        validate_jwks_uri(config.jwks_uri, config)
        self._c = config
        self._fetch = fetcher or (lambda: _bounded_fetch(config.jwks_uri, config))
        self._clock = clock
        self._by_kid: Dict[str, dict] = {}
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def _refresh_locked(self):
        by_kid = _normalise_jwks(self._fetch(), self._c)   # validate before touching the cache
        self._by_kid = by_kid                              # atomic replacement
        self._fetched_at = self._clock()

    def get_jwk(self, kid: str) -> dict:
        stale = (self._clock() - self._fetched_at) > self._c.cache_ttl_seconds
        if (kid in self._by_kid) and not stale:
            return self._by_kid[kid]
        with self._lock:                                   # single-flight: no refresh storm
            stale = (self._clock() - self._fetched_at) > self._c.cache_ttl_seconds
            if (kid not in self._by_kid) or stale:
                try:
                    self._refresh_locked()
                except OIDCError:
                    if (kid in self._by_kid) and not stale:
                        return self._by_kid[kid]
                    raise
                except Exception:
                    if (kid in self._by_kid) and not stale:
                        return self._by_kid[kid]
                    raise OIDCError("jwks_unavailable")
            jwk = self._by_kid.get(kid)
        if jwk is None:
            raise OIDCError("unknown_kid")
        return jwk


def _select_key(jwk: dict, alg: str):
    want_kty = _ALG_TO_KTY[alg]
    if jwk.get("kty") != want_kty:
        raise OIDCError("jwk_kty_mismatch")
    if jwk.get("alg") not in (None, alg):
        raise OIDCError("jwk_alg_mismatch")
    if jwk.get("use") not in (None, "sig"):
        raise OIDCError("jwk_use_not_sig")
    ops = jwk.get("key_ops")
    if ops is not None and "verify" not in ops:
        raise OIDCError("jwk_key_ops_no_verify")
    try:
        return _ALG_TO_JWK[alg].from_jwk(json.dumps(jwk))
    except OIDCError:
        raise
    except Exception:
        raise OIDCError("jwk_material_invalid")


def _check_claim_types(claims: dict):
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise OIDCError("claim_sub_invalid")
    org = claims.get("org_id")
    if not isinstance(org, str) or not org:
        raise OIDCError("claim_org_id_invalid")
    for t in ("exp", "nbf", "iat"):
        if t in claims and not isinstance(claims[t], (int, float)):
            raise OIDCError("claim_%s_not_numeric" % t)
    if "scope" in claims and not isinstance(claims["scope"], str):
        raise OIDCError("claim_scope_invalid")
    if "scp" in claims and not (isinstance(claims["scp"], list)
                                and all(isinstance(s, str) for s in claims["scp"])):
        raise OIDCError("claim_scp_invalid")
    aud = claims.get("aud")
    if aud is not None and not isinstance(aud, (str, list)):
        raise OIDCError("claim_aud_invalid")


def verify_access_token(token: str, config: OIDCConfig, cache: JWKSCache,
                        clock: Callable[[], float] = time.time) -> dict:
    if not isinstance(token, str) or not token:
        raise OIDCError("empty_token")
    if len(token.encode("utf-8")) > config.max_token_bytes:
        raise OIDCError("token_too_large")
    try:
        header = jwt.get_unverified_header(token)
    except Exception:
        raise OIDCError("malformed_header")

    alg = header.get("alg")
    if alg is None or alg == "none":
        raise OIDCError("alg_none")
    if alg not in config.allowed_algs:
        raise OIDCError("alg_not_allowed:%s" % alg)
    if config.is_prod_like() and alg.upper().startswith("HS"):
        raise OIDCError("symmetric_alg_forbidden")
    if alg not in _ALG_TO_JWK:
        raise OIDCError("unsupported_alg:%s" % alg)

    kid = header.get("kid")
    if not kid:
        raise OIDCError("missing_kid")
    key = _select_key(cache.get_jwk(kid), alg)

    leeway = config.bounded_leeway()
    try:
        claims = jwt.decode(token, key, algorithms=[alg], audience=config.audience, issuer=config.issuer,
                            leeway=leeway,
                            options={"require": ["exp"], "verify_aud": True, "verify_iss": True,
                                     "verify_signature": True})
    except jwt.ExpiredSignatureError:
        raise OIDCError("expired")
    except jwt.ImmatureSignatureError:
        raise OIDCError("not_yet_valid")
    except jwt.InvalidAudienceError:
        raise OIDCError("bad_audience")
    except jwt.InvalidIssuerError:
        raise OIDCError("bad_issuer")
    except jwt.MissingRequiredClaimError as e:
        raise OIDCError("missing_claim:%s" % e)
    except jwt.InvalidSignatureError:
        raise OIDCError("bad_signature")
    except jwt.PyJWTError as e:
        raise OIDCError("invalid_token:%s" % type(e).__name__)
    except (ValueError, TypeError):                        # normalize any parser failure
        raise OIDCError("invalid_token")

    if not isinstance(claims, dict):
        raise OIDCError("invalid_claims")
    for claim in config.require_claims:
        if claim not in claims:
            raise OIDCError("missing_claim:%s" % claim)
    _check_claim_types(claims)
    iat = claims.get("iat")
    if iat is not None and float(iat) > clock() + leeway:
        raise OIDCError("iat_in_future")
    return claims
