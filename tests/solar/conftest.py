"""Fake OpenAI-compatible server harness for the Solar provider (P4 §13). In-process, credential-free — no
real UPSTAGE_API_KEY, no network egress. Never runs research benchmarks."""
import os
import sys
import json
import time
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from enterprise_memory.providers.secrets import SecretProvider   # noqa: E402


class StubSecret(SecretProvider):
    def get_secret(self, name):
        return "sk-test-solar-key"


def ok_body(content="PATCH-OK", model="solar-pro2-251215"):
    return {"id": "req-abc", "model": model,
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        srv = self.server
        with srv.lock:
            srv.count += 1
            srv.concurrent += 1
            srv.max_concurrent = max(srv.max_concurrent, srv.concurrent)
        try:
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            resp = srv.responses.popleft() if srv.responses else dict(srv.default)
            if resp.get("delay"):
                time.sleep(resp["delay"])
            status = resp.get("status", 200)
            body = json.dumps(resp.get("body", ok_body())).encode()
            self.send_response(status)
            for k, v in (resp.get("headers") or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        finally:
            with srv.lock:
                srv.concurrent -= 1

    def log_message(self, *a):
        pass


class FakeSolar:
    def __init__(self):
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._srv.responses = deque()
        self._srv.default = {"status": 200, "body": ok_body()}
        self._srv.lock = threading.Lock()
        self._srv.count = 0
        self._srv.concurrent = 0
        self._srv.max_concurrent = 0
        self._t = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._t.start()

    @property
    def base_url(self):
        return "http://127.0.0.1:%d/v1" % self._srv.server_address[1]

    def program(self, responses):
        self._srv.responses = deque(responses)

    def set_default(self, resp):
        self._srv.default = resp

    @property
    def count(self):
        return self._srv.count

    @property
    def max_concurrent(self):
        return self._srv.max_concurrent

    def shutdown(self):
        self._srv.shutdown()


@pytest.fixture
def fake_solar():
    s = FakeSolar()
    try:
        yield s
    finally:
        s.shutdown()


@pytest.fixture
def secret():
    return StubSecret()
