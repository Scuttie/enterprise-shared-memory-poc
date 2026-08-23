"""P3 OIDC test harness — credential-free. A local RSA/EC key ring signs tokens and serves a JWKS document,
so no external IdP, company identity, or network egress is needed. A threaded localhost JWKS server exercises
the real HTTP fetch path."""
import os
import sys
import json
import threading
import pytest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

jwt = pytest.importorskip("jwt")
pytest.importorskip("cryptography")
from jwt.algorithms import RSAAlgorithm, ECAlgorithm                     # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa, ec           # noqa: E402
from cryptography.hazmat.primitives import serialization                # noqa: E402

ISSUER = "https://idp.test.local/"
AUDIENCE = "esm-api"


def _pem(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


class KeyRing:
    def __init__(self):
        self.keys = {}      # kid -> (private_pem, jwk, alg)

    def add_rsa(self, kid="rsa-1"):
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(RSAAlgorithm.to_jwk(k.public_key()))
        jwk.update(kid=kid, alg="RS256", use="sig")
        self.keys[kid] = (_pem(k), jwk, "RS256")
        return kid

    def add_ec(self, kid="ec-1"):
        k = ec.generate_private_key(ec.SECP256R1())
        jwk = json.loads(ECAlgorithm.to_jwk(k.public_key()))
        jwk.update(kid=kid, alg="ES256", use="sig")
        self.keys[kid] = (_pem(k), jwk, "ES256")
        return kid

    def jwks(self, kids=None):
        kids = kids or list(self.keys)
        return {"keys": [self.keys[k][1] for k in kids]}

    def sign(self, kid, claims, alg=None, headers=None):
        pem, _, default_alg = self.keys[kid]
        h = {"kid": kid}
        h.update(headers or {})
        return jwt.encode(dict(claims), pem, algorithm=(alg or default_alg), headers=h)


@pytest.fixture
def ring():
    return KeyRing()


def base_claims(**over):
    import time
    now = int(time.time())
    c = {"iss": ISSUER, "aud": AUDIENCE, "sub": "user-123", "org_id": "org-abc",
         "iat": now, "nbf": now - 5, "exp": now + 600}
    c.update(over)
    return c


class _JWKSHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.hits += 1
        body = json.dumps(self.server.jwks_provider()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def jwks_server(ring):
    """Serve ring.jwks() on localhost; the returned object exposes .url, .hits, and .set_kids()."""
    state = {"kids": None}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _JWKSHandler)
    srv.hits = 0
    srv.jwks_provider = lambda: ring.jwks(state["kids"])
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    class Handle:
        url = "http://127.0.0.1:%d/jwks.json" % srv.server_address[1]

        @property
        def hits(self):
            return srv.hits

        def set_kids(self, kids):
            state["kids"] = kids

    try:
        yield Handle()
    finally:
        srv.shutdown()
