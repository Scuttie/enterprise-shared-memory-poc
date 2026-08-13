"""A local fake company-harness HTTP server speaking one of the three supported protocols. Credential-free;
returns a canned unified diff. Used only in tests (§10)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CANNED_PATCH = ("--- a/src/app.py\n+++ b/src/app.py\n@@ -1,2 +1,3 @@\n def f():\n-    return 0\n"
                "+    # governed fix applied by fake company harness\n+    return 1\n")


def _make_handler(protocol):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(n) if n else b"{}"
            req = json.loads(raw or b"{}")
            content = "Here is the fix:\n```diff\n%s```\n" % CANNED_PATCH
            if protocol == "openai":
                body = {"model": req.get("model", "fake-glm"), "usage": {"total_tokens": 42},
                        "choices": [{"message": {"role": "assistant", "content": content}}]}
            elif protocol == "anthropic":
                body = {"model": req.get("model", "fake-glm"), "usage": {"input_tokens": 20, "output_tokens": 22},
                        "content": [{"type": "text", "text": content}]}
            else:  # jsonrpc
                body = {"jsonrpc": "2.0", "id": req.get("id"),
                        "result": {"text": content, "model": req.get("params", {}).get("model", "fake-glm"),
                                   "usage": {"total_tokens": 42}}}
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    return H


class FakeHarnessServer:
    def __init__(self, protocol="openai"):
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(protocol))
        self.port = self._srv.server_address[1]
        self.endpoint = "http://127.0.0.1:%d" % self.port
        self._t = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._srv.shutdown()
        self._srv.server_close()
