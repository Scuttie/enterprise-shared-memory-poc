"""§8 raw-artifact ledger (HARD requirement). Persists the COMPLETE solve record so every raw response
and applied patch can be reloaded EXACTLY (response hash alone is insufficient). Never stores the API
key, env secrets, host .env, or unrelated private files."""
from __future__ import annotations
import json
import hashlib

_SECRET_KEYS = ("api_key", "authorization", "upstage_api_key", "token", "secret")


def _sanitize(req: dict) -> dict:
    return {k: v for k, v in req.items() if k.lower() not in _SECRET_KEYS}


class RawLedger:
    def __init__(self, path):
        self.path = path
        open(self.path, "a", encoding="utf-8").close()

    def record(self, rec: dict):
        rec = dict(rec)
        rec["request"] = _sanitize(rec.get("request", {}))
        for bad in _SECRET_KEYS:
            rec.pop(bad, None)
        rec["raw_response_sha256"] = "sha256:" + hashlib.sha256((rec.get("raw_response") or "").encode()).hexdigest()
        rec["applied_patch_sha256"] = "sha256:" + hashlib.sha256((rec.get("applied_patch") or "").encode()).hexdigest()
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def reload(self):
        return [json.loads(l) for l in open(self.path, encoding="utf-8") if l.strip()]


REQUIRED_FIELDS = ("request", "raw_response", "parsed_diff", "applied_patch", "patch_sha256", "files_changed",
                   "changed_lines", "patch_scope_ok", "public_stdout", "hidden_outcome", "first_failing_test",
                   "diagnostic_behavior", "model_requested", "model_returned", "request_id", "response_id",
                   "token_usage", "latency_ms", "retries", "finish_reason", "parser_status")


def validate_mock(path):
    """Prove with a MOCK record (no Solar) that every required field persists and the raw response +
    applied patch reload EXACTLY (byte-identical). Returns (ok, detail)."""
    led = RawLedger(path)
    raw = "```diff\n-    raise NotImplementedError\n+    return base_delay * 2\n```"
    applied = "def backoff_interval(base_delay, client_tier, protocol_rev):\n    return base_delay * 2\n"
    rec = {"request": {"model": "solar-pro2-251215", "messages": "<prompt>", "api_key": "SHOULD_NOT_PERSIST"},
           "raw_response": raw, "parsed_diff": raw, "applied_patch": applied, "patch_sha256": "sha256:x",
           "files_changed": ["mod.py"], "changed_lines": 2, "patch_scope_ok": True, "public_stdout": "",
           "hidden_outcome": "pass", "first_failing_test": None, "diagnostic_behavior": "CORRECT_WORLD",
           "model_requested": "solar-pro2-251215", "model_returned": "solar-pro2-251215",
           "request_id": "req_mock", "response_id": "resp_mock", "token_usage": {"prompt": 10, "completion": 5},
           "latency_ms": 123, "retries": 0, "finish_reason": "stop", "parser_status": "ok"}
    stored = led.record(rec)
    back = led.reload()[-1]
    missing = [f for f in REQUIRED_FIELDS if f not in back]
    exact = (back["raw_response"] == raw and back["applied_patch"] == applied)
    no_secret = ("api_key" not in json.dumps(back)) and ("SHOULD_NOT_PERSIST" not in json.dumps(back))
    ok = (not missing) and exact and no_secret
    return ok, {"missing_fields": missing, "raw_reload_exact": exact, "no_secret_persisted": no_secret}
