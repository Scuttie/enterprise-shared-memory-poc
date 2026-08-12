"""Production OIDC access-token verification (P3 §12). Fail-closed by construction:

- algorithm allowlist (default RS256; ES256 only if explicitly enabled); alg=none and any non-allowlisted
  algorithm are rejected; symmetric algorithms (HS*) are rejected outright in staging/production;
- signature verified against a JWKS key selected by `kid`; unknown kid forces one refresh; key rotation is
  picked up automatically; a JWKS fetch failure with no usable cached key is rejected (never fail-open);
- issuer + audience are verified; exp is required; nbf/iat are checked with a bounded leeway; an iat in the
  future is rejected; sub and org_id are required;
- a JWKS cache TTL bounds refreshes; oversized tokens are rejected before any parsing.

Identity/authorization is taken ONLY from the returned verified claims — never from request-body input.
The JWKS fetcher is injectable so unit tests need no network; a local fixture server exercises the HTTP
path in CI."""
from __future__ import annotations
import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

import jwt
from jwt.algorithms import RSAAlgorithm, ECAlgorithm

_ALG_TO_JWK = {"RS256": RSAAlgorithm, "ES256": ECAlgorithm}
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

    def bounded_leeway(self) -> int:
        return max(0, min(int(self.leeway_seconds), _MAX_LEEWAY))


def _default_fetcher(uri: str, timeout: float = 5.0) -> dict:
    with urllib.request.urlopen(uri, timeout=timeout) as r:   # noqa: S310 - fixed https jwks_uri
        return json.loads(r.read().decode("utf-8"))


class JWKSCache:
    """kid -> JWK cache with TTL, forced refresh on unknown kid, and fail-closed fetch."""

    def __init__(self, config: OIDCConfig, fetcher: Optional[Callable[[], dict]] = None,
                 clock: Callable[[], float] = time.time):
        self._c = config
        self._fetch = fetcher or (lambda: _default_fetcher(config.jwks_uri))
        self._clock = clock
        self._by_kid: Dict[str, dict] = {}
        self._fetched_at = 0.0

    def _refresh(self):
        data = self._fetch()                                  # may raise -> handled fail-closed by caller
        keys = {}
        for jwk in (data or {}).get("keys", []):
            kid = jwk.get("kid")
            if kid:
                keys[kid] = jwk
        self._by_kid = keys
        self._fetched_at = self._clock()

    def get_jwk(self, kid: str) -> dict:
        stale = (self._clock() - self._fetched_at) > self._c.cache_ttl_seconds
        if (kid not in self._by_kid) or stale:
            try:
                self._refresh()
            except Exception:
                if (kid in self._by_kid) and not stale:       # transient blip, key still fresh in cache
                    return self._by_kid[kid]
                raise OIDCError("jwks_unavailable")           # fail-closed
        jwk = self._by_kid.get(kid)
        if jwk is None:
            raise OIDCError("unknown_kid")
        return jwk


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
    if config.environment in ("staging", "production") and alg.upper().startswith("HS"):
        raise OIDCError("symmetric_alg_forbidden")
    alg_cls = _ALG_TO_JWK.get(alg)
    if alg_cls is None:
        raise OIDCError("unsupported_alg:%s" % alg)

    kid = header.get("kid")
    if not kid:
        raise OIDCError("missing_kid")
    key = alg_cls.from_jwk(json.dumps(cache.get_jwk(kid)))

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

    for claim in config.require_claims:
        if claim not in claims:
            raise OIDCError("missing_claim:%s" % claim)
    iat = claims.get("iat")
    if iat is not None and float(iat) > clock() + leeway:
        raise OIDCError("iat_in_future")
    return claims
