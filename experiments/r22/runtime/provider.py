"""R22 §3 — reader provider interface. FakeReaderProvider is fully offline (no network, no credential); the
OpenAI-compatible provider (OpenAI + DeepSeek) is structured for the paid path but never called in credential-free
work. Provider is chosen explicitly, never inferred from model text. Every call persists usage + returned model.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


class ProviderError(Exception):
    pass


class ModelDriftError(ProviderError):
    pass


@dataclass
class ChatResult:
    content: str
    tool_calls: List[dict]
    prompt_tokens: int
    completion_tokens: int
    returned_model: str
    request_id: str
    latency_s: float
    retry_count: int
    raw_response_sha256: str
    terminal_failure: Optional[str] = None


class ReaderProvider:
    """Abstract reader. Subclasses must not print secret values and must return a usage record."""

    def __init__(self, requested_provider: str, requested_model: str):
        self.requested_provider = requested_provider
        self.requested_model = requested_model
        self._locked_returned_model: Optional[str] = None

    def _check_model_stable(self, returned_model: str):
        if self._locked_returned_model is None:
            self._locked_returned_model = returned_model
        elif returned_model != self._locked_returned_model:
            raise ModelDriftError("returned model changed mid-campaign: %s -> %s"
                                  % (self._locked_returned_model, returned_model))

    def chat(self, messages: List[dict], tools: Optional[List[dict]] = None) -> ChatResult:
        raise NotImplementedError

    @property
    def drift_label(self) -> Optional[str]:
        # deepseek-chat alias is not snapshot-pinned
        return "MODEL_DRIFT_REPLICATION" if self.requested_model == "deepseek-chat" else None


class FakeReaderProvider(ReaderProvider):
    """Deterministic, offline. Drives the harness E2E: given a fixture that declares the fix, it emits scripted
    tool calls (read -> replace_lines -> submit) and deterministic usage. No network, no credential."""

    def __init__(self, script: Optional[Dict[str, dict]] = None, model: str = "fake-reader"):
        super().__init__("fake", model)
        self.script = script or {}
        self._turn = 0
        self._searched = False
        self._browsed = False
        self._read = False
        self._edited = False

    @staticmethod
    def _call(name, args):
        return [{"id": "c", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]

    def chat(self, messages, tools=None):
        self._turn += 1
        fix = self.script.get("fix", {})
        offered = {t["function"]["name"] for t in (tools or [])}
        # deterministic state machine: search -> browse (if memory offered) -> read -> replace -> submit
        if "memory_search_stage" in offered and not self._searched:
            self._searched = True
            tcs = self._call("memory_search_stage", {"stage": self.script.get("stage", "EDIT")})
        elif self._searched and not self._browsed and "memory_browse_stage" in offered:
            self._browsed = True
            tcs = self._call("memory_browse_stage", {"candidate_id": "m1"})
        elif not self._read:
            self._read = True
            tcs = self._call("read_file", {"path": fix.get("path", "bug.py")})
        elif not self._edited and fix:
            self._edited = True
            tcs = self._call("replace_lines", {"path": fix["path"], "start_line": fix["start_line"],
                                               "end_line": fix["end_line"], "new_content": fix["new_content"]})
        else:
            tcs = self._call("submit", {})
        raw = json.dumps({"turn": self._turn, "tool_calls": tcs}, sort_keys=True)
        returned = self.requested_model
        self._check_model_stable(returned)
        return ChatResult(content="", tool_calls=tcs, prompt_tokens=1000, completion_tokens=100,
                          returned_model=returned, request_id="fake-%d" % self._turn, latency_s=0.0,
                          retry_count=0, raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest())


class OpenAICompatibleReaderProvider(ReaderProvider):
    """OpenAI + DeepSeek chat/completions over HTTPS (urllib), reusing the R14 request shape. NEVER called in
    credential-free work. Requires the named secret; refuses if missing; never logs the secret value."""

    ENDPOINTS = {"openai": "https://api.openai.com/v1", "deepseek": "https://api.deepseek.com/v1"}

    def __init__(self, provider: str, model: str, secret_name: str, temperature: float = 0.0,
                 max_retries: int = 3):
        if provider not in self.ENDPOINTS:
            raise ProviderError("unsupported provider %r (only openai|deepseek)" % provider)
        super().__init__(provider, model)
        self.secret_name = secret_name
        self.temperature = temperature
        self.max_retries = max_retries
        self._key = os.environ.get(secret_name)
        if not self._key:
            raise ProviderError("secret env %s is not present (name only; never printed)" % secret_name)
        self.base = os.environ.get("R22_%s_BASE_URL" % provider.upper(), self.ENDPOINTS[provider])

    def chat(self, messages, tools=None):
        import urllib.request
        body = json.dumps({"model": self.requested_model, "messages": messages, "tools": tools or [],
                           "tool_choice": "auto" if tools else "none",
                           "temperature": self.temperature}).encode()
        last = None
        t0 = time.time()
        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(self.base + "/chat/completions", data=body,
                                             headers={"Authorization": "Bearer %s" % self._key,
                                                      "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=180) as r:
                    data = json.loads(r.read().decode())
                usage = data.get("usage")
                if not usage:
                    raise ProviderError("provider response has no usage record")
                returned = data.get("model", "")
                self._check_model_stable(returned)
                msg = data["choices"][0]["message"]
                raw = json.dumps(data, sort_keys=True)
                return ChatResult(
                    content=msg.get("content") or "", tool_calls=msg.get("tool_calls") or [],
                    prompt_tokens=usage["prompt_tokens"], completion_tokens=usage["completion_tokens"],
                    returned_model=returned, request_id=data.get("id", ""), latency_s=time.time() - t0,
                    retry_count=attempt, raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest())
            except ModelDriftError:
                raise
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise ProviderError("provider terminal failure after %d retries: %s" % (self.max_retries, last))


def make_provider(spec: dict) -> ReaderProvider:
    """spec = {mode: 'fake'|'real', provider, model, secret_name, script?}. Explicit; never infers from model."""
    if spec.get("mode") == "fake":
        return FakeReaderProvider(script=spec.get("script"), model=spec.get("model", "fake-reader"))
    return OpenAICompatibleReaderProvider(spec["provider"], spec["model"], spec["secret_name"],
                                          temperature=spec.get("temperature", 0.0))
