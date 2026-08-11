"""§4 identity & authorization. Identity is NEVER trusted from the request body — it is derived from a
validated token. `StaticIdentityProvider` is for test/local. `JwtIdentityProvider` validates issuer/
audience/expiry/not-before/signature/scopes and fails closed; it ships with a stdlib HS256 verifier for
deterministic tests. Production uses RS256 + rotating JWKS (the `_verify_signature` hook is the extension
point) — do not use HS256 in production."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field

SCOPES = ("memory:private:read", "memory:private:write", "memory:shared:read", "memory:contract:propose",
          "memory:contract:review", "memory:contract:promote", "memory:contract:deprecate",
          "memory:admin", "solve:submit", "solve:read")


@dataclass
class IdentityContext:
    subject_id: str
    org_id: str
    team_ids: list = field(default_factory=list)
    roles: list = field(default_factory=list)
    scopes: list = field(default_factory=list)
    token_id: str = ""
    request_id: str = ""

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


class AuthError(Exception):
    pass


class StaticIdentityProvider:
    """Test/local only. Maps a fixed bearer value to a preconfigured identity."""

    def __init__(self, table: dict):
        self._table = table

    async def authenticate(self, authorization_header: str | None) -> IdentityContext:
        if not authorization_header or not authorization_header.startswith("Bearer "):
            raise AuthError("missing_bearer")
        tok = authorization_header[7:]
        ic = self._table.get(tok)
        if ic is None:
            raise AuthError("unknown_token")
        return ic


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_hs256(payload: dict, secret: str) -> str:
    """Test helper: mint an HS256 JWT (NEVER used in production)."""
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url(json.dumps(payload).encode())
    sig = _b64url(hmac.new(secret.encode(), ("%s.%s" % (header, body)).encode(), hashlib.sha256).digest())
    return "%s.%s.%s" % (header, body, sig)


class JwtIdentityProvider:
    def __init__(self, issuer: str, audience: str, hs256_secret: str | None = None, leeway_s: int = 30,
                 required_alg: str = "HS256", now_fn=time.time):
        self.issuer = issuer
        self.audience = audience
        self._secret = hs256_secret
        self.leeway = leeway_s
        self.required_alg = required_alg
        self._now = now_fn

    def _verify_signature(self, header: dict, signing_input: bytes, signature: bytes) -> bool:
        if header.get("alg") != self.required_alg:
            return False
        if self.required_alg == "HS256":
            if not self._secret:
                return False
            expected = hmac.new(self._secret.encode(), signing_input, hashlib.sha256).digest()
            return hmac.compare_digest(expected, signature)
        # PRODUCTION: RS256 via rotating JWKS goes here (resolve kid -> public key, verify). Fail closed.
        raise AuthError("alg_not_supported_here_use_jwks:%s" % self.required_alg)

    async def authenticate(self, authorization_header: str | None) -> IdentityContext:
        if not authorization_header or not authorization_header.startswith("Bearer "):
            raise AuthError("missing_bearer")
        parts = authorization_header[7:].split(".")
        if len(parts) != 3:
            raise AuthError("malformed_jwt")
        h_b64, p_b64, s_b64 = parts
        try:
            header = json.loads(_b64url_decode(h_b64))
            payload = json.loads(_b64url_decode(p_b64))
            signature = _b64url_decode(s_b64)
        except Exception:
            raise AuthError("undecodable_jwt")
        if not self._verify_signature(header, ("%s.%s" % (h_b64, p_b64)).encode(), signature):
            raise AuthError("bad_signature")
        now = self._now()
        if payload.get("iss") != self.issuer:
            raise AuthError("bad_issuer")
        aud = payload.get("aud")
        if aud != self.audience and (not isinstance(aud, list) or self.audience not in aud):
            raise AuthError("bad_audience")
        if "exp" in payload and now > float(payload["exp"]) + self.leeway:
            raise AuthError("expired")
        if "nbf" in payload and now < float(payload["nbf"]) - self.leeway:
            raise AuthError("not_yet_valid")
        scopes = payload.get("scope", "").split() if isinstance(payload.get("scope"), str) else payload.get("scopes", [])
        return IdentityContext(subject_id=payload["sub"], org_id=payload["org_id"],
                               team_ids=payload.get("team_ids", []), roles=payload.get("roles", []),
                               scopes=list(scopes), token_id=payload.get("jti", ""))


class StaticRepoAuthz:
    """Test/local repository authorization derived from identity, NOT client input."""

    def __init__(self, read_map: dict, write_map: dict | None = None):
        self._read = read_map
        self._write = write_map or {}

    async def can_read(self, ident: IdentityContext, repo_id: str) -> bool:
        return repo_id in self._read.get(ident.org_id, set())

    async def can_modify(self, ident: IdentityContext, repo_id: str) -> bool:
        return repo_id in self._write.get(ident.org_id, set())

    async def readable_repos(self, ident: IdentityContext) -> list:
        return sorted(self._read.get(ident.org_id, set()))
