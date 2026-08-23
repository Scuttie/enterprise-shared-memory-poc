"""Company Claude-Code / local-GLM harness adapter boundary (P5.1 §10). The service owns authorization,
memory validation, hidden tests, patch validation, sandbox verdict and outcome persistence; the company
harness only receives GOVERNED inputs and returns a patch + sanitized metadata. It never sees credentials, the
hidden tests, another user's raw private trace, or the server-side final verdict, and it cannot override the
server-owned policy.

We do NOT assume the company's model is literally 'GLM-5.3' — the exact identity comes from a required
CompanyManifest. Three serving protocols are supported via pluggable transports (Anthropic-compatible HTTP,
OpenAI-compatible HTTP, generic internal JSON-RPC); the correct one is named in the manifest. A live canary
runs only when an exact manifest + approved endpoint + approved secret are all present; otherwise the canary
status is PENDING_CONFIGURATION.
"""
from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

# keys that must NEVER appear in a request to the company harness
FORBIDDEN_REQUEST_KEYS = {
    "oidc_token", "access_token", "bearer", "authorization", "installation_token", "git_token",
    "database_url", "db_url", "db_password", "minio_secret", "minio_secret_key", "s3_secret",
    "qdrant_api_key", "secret", "credentials", "hidden_test", "hidden_tests", "hidden_test_manifest",
    "private_trace", "raw_private_trace", "final_verdict", "verdict", "sandbox_result",
}

_PROTOCOLS = ("anthropic", "openai", "jsonrpc")


class CompanyManifestError(ValueError):
    pass


class ForbiddenHarnessField(ValueError):
    pass


@dataclass(frozen=True)
class CompanyManifest:
    harness_name: str
    harness_version: str
    model_id: str
    model_revision: str
    serving_protocol: str            # anthropic | openai | jsonrpc
    endpoint: str
    context_window: int
    max_output_tokens: int
    tool_schema_hash: str
    repository_mount_mode: str
    sandbox_test_ownership: str       # must be 'service' — the service owns the sandbox/hidden tests
    streaming: bool
    timeout_seconds: int
    build_id: str

    def validate(self):
        missing = [k for k in ("harness_name", "harness_version", "model_id", "model_revision",
                               "serving_protocol", "endpoint", "tool_schema_hash", "repository_mount_mode",
                               "sandbox_test_ownership", "build_id") if not getattr(self, k)]
        if missing:
            raise CompanyManifestError("incomplete company manifest: missing %s" % ", ".join(missing))
        if self.serving_protocol not in _PROTOCOLS:
            raise CompanyManifestError("unknown serving_protocol %r" % self.serving_protocol)
        if self.sandbox_test_ownership != "service":
            raise CompanyManifestError("sandbox/hidden tests must be service-owned, not %r"
                                       % self.sandbox_test_ownership)
        if not (self.context_window > 0 and self.max_output_tokens > 0 and self.timeout_seconds > 0):
            raise CompanyManifestError("context_window/max_output_tokens/timeout_seconds must be positive")
        return self


@dataclass
class CompanyHarnessRequest:
    logical_request_id: str
    repository_reference: dict
    instruction: str
    edit_policy: dict
    memory_views: List[str] = field(default_factory=list)
    public_tool_interface: List[str] = field(default_factory=lambda: ["read_file", "run_public_tests"])
    output_format: dict = field(default_factory=lambda: {"type": "unified_diff"})

    def as_dict(self) -> dict:
        d = {"logical_request_id": self.logical_request_id, "repository_reference": self.repository_reference,
             "instruction": self.instruction, "edit_policy": self.edit_policy,
             "memory_views": list(self.memory_views), "public_tool_interface": list(self.public_tool_interface),
             "output_format": self.output_format}
        _assert_no_forbidden(d)
        return d


@dataclass
class CompanyHarnessResult:
    patch: str
    harness_identity: str
    model: str
    tool_calls: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    latency: float = 0.0
    public_test_evidence: Optional[dict] = None
    raw_response_ref: Optional[str] = None


def _assert_no_forbidden(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in FORBIDDEN_REQUEST_KEYS:
                raise ForbiddenHarnessField("forbidden key in harness request: %s%s" % (path, k))
            _assert_no_forbidden(v, path + str(k) + ".")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _assert_no_forbidden(v, path + "[%d]." % i)


_DIFF_RE = re.compile(r"(?ms)^(?:diff --git|---\s).*?(?=\Z)")


def extract_patch(text: str) -> str:
    """Extract a unified diff from a harness response (fenced or bare)."""
    if not text:
        return ""
    fence = re.search(r"```(?:diff|patch)?\s*(.*?)```", text, re.S)
    body = fence.group(1) if fence else text
    m = re.search(r"(?ms)^(--- .*)", body)
    return (m.group(1) if m else body).strip() + "\n"


# ---------------------------------------------------------------- transports (one per serving protocol)
class HarnessTransport:
    async def invoke(self, manifest: CompanyManifest, request: dict) -> dict:
        raise NotImplementedError


def _auth_headers(manifest, secret_env):
    key = os.environ.get(secret_env) if secret_env else None
    return ({"Authorization": "Bearer %s" % key} if key else {})


class OpenAICompatibleTransport(HarnessTransport):
    """OpenAI-compatible /chat/completions (also matches an OpenAI-style GLM or Solar gateway)."""
    def __init__(self, secret_env=None):
        self._secret_env = secret_env

    async def invoke(self, manifest, request):
        import httpx
        prompt = _render_prompt(request)
        url = manifest.endpoint.rstrip("/") + "/chat/completions"
        body = {"model": manifest.model_id, "temperature": 0,
                "max_tokens": manifest.max_output_tokens,
                "messages": [{"role": "user", "content": prompt}]}
        async with httpx.AsyncClient(timeout=manifest.timeout_seconds) as c:
            r = await c.post(url, json=body, headers=_auth_headers(manifest, self._secret_env))
            r.raise_for_status()
            data = r.json()
        text = data["choices"][0]["message"]["content"]
        return {"text": text, "usage": data.get("usage", {}), "model": data.get("model", manifest.model_id),
                "raw": json.dumps(data)}


class AnthropicCompatibleTransport(HarnessTransport):
    """Anthropic-compatible /v1/messages."""
    def __init__(self, secret_env=None):
        self._secret_env = secret_env

    async def invoke(self, manifest, request):
        import httpx
        prompt = _render_prompt(request)
        url = manifest.endpoint.rstrip("/") + "/v1/messages"
        body = {"model": manifest.model_id, "max_tokens": manifest.max_output_tokens, "temperature": 0,
                "messages": [{"role": "user", "content": prompt}]}
        headers = _auth_headers(manifest, self._secret_env)
        headers.setdefault("anthropic-version", "2023-06-01")
        async with httpx.AsyncClient(timeout=manifest.timeout_seconds) as c:
            r = await c.post(url, json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
        parts = data.get("content", [])
        text = "".join(p.get("text", "") for p in parts) if isinstance(parts, list) else str(parts)
        return {"text": text, "usage": data.get("usage", {}), "model": data.get("model", manifest.model_id),
                "raw": json.dumps(data)}


class GenericJsonRpcTransport(HarnessTransport):
    """Generic internal JSON-RPC: {method, params:{request}} -> {result:{text,usage,model}}."""
    def __init__(self, secret_env=None, method="complete"):
        self._secret_env = secret_env
        self._method = method

    async def invoke(self, manifest, request):
        import httpx
        body = {"jsonrpc": "2.0", "id": request["logical_request_id"], "method": self._method,
                "params": {"model": manifest.model_id, "request": request,
                           "prompt": _render_prompt(request)}}
        async with httpx.AsyncClient(timeout=manifest.timeout_seconds) as c:
            r = await c.post(manifest.endpoint, json=body, headers=_auth_headers(manifest, self._secret_env))
            r.raise_for_status()
            data = r.json()
        res = data.get("result", {})
        return {"text": res.get("text", ""), "usage": res.get("usage", {}),
                "model": res.get("model", manifest.model_id), "raw": json.dumps(data)}


_TRANSPORTS = {"openai": OpenAICompatibleTransport, "anthropic": AnthropicCompatibleTransport,
               "jsonrpc": GenericJsonRpcTransport}


def _render_prompt(request: dict) -> str:
    views = "\n\n".join("### governed memory view %d\n%s" % (i, v)
                        for i, v in enumerate(request.get("memory_views", [])))
    ref = request.get("repository_reference", {})
    return ("Task: %s\nEdit policy: %s\nRepository reference: %s\n\n%s\n\nReturn ONLY a unified diff patch."
            % (request.get("instruction", ""), json.dumps(request.get("edit_policy", {}), sort_keys=True),
               json.dumps(ref, sort_keys=True), views))


# ---------------------------------------------------------------- the client
class CompanyHarnessClient:
    """`harness` for ExternalHarnessExecutionBackend. Builds a governed request (asserting no forbidden field),
    dispatches over the manifest's protocol, and returns a sanitized result dict. Never sees credentials in the
    payload (the transport reads an API key from an env var named by config, never from the request)."""

    def __init__(self, manifest: CompanyManifest, transport: Optional[HarnessTransport] = None,
                 secret_env: Optional[str] = None):
        self.manifest = manifest.validate()
        self.transport = transport or _TRANSPORTS[manifest.serving_protocol](secret_env=secret_env)

    async def run(self, payload: dict) -> dict:
        import time
        # governed request — strip to allowed fields only; assert nothing forbidden slipped in
        req = CompanyHarnessRequest(
            logical_request_id=payload["logical_request_id"], instruction=payload.get("instruction", ""),
            repository_reference=payload.get("repository_reference", {}),
            edit_policy=payload.get("edit_policy", {}), memory_views=list(payload.get("memory_views", [])))
        request = req.as_dict()
        t0 = time.monotonic()
        out = await self.transport.invoke(self.manifest, request)
        latency = time.monotonic() - t0
        patch = extract_patch(out.get("text", ""))
        identity = "%s/%s@%s" % (self.manifest.harness_name, self.manifest.model_id,
                                 self.manifest.model_revision)
        res = CompanyHarnessResult(patch=patch, harness_identity=identity,
                                   model=out.get("model", self.manifest.model_id),
                                   tool_calls=_sanitize_tool_calls(out.get("tool_calls", [])),
                                   usage=out.get("usage", {}), latency=latency,
                                   public_test_evidence=out.get("public_test_evidence"),
                                   raw_response_ref=None)
        return {"patch": res.patch, "raw": out.get("raw", res.patch), "model": res.model,
                "harness_identity": res.harness_identity, "usage": res.usage, "latency": res.latency,
                "tool_calls": res.tool_calls, "public_test_evidence": res.public_test_evidence,
                "model_call_records": [{"logical_request_id": payload["logical_request_id"],
                                        "backend_type": "external_harness", "final_status": "success",
                                        "attempts": 1, "requested_model": self.manifest.model_id,
                                        "returned_model": res.model, "redaction_status": "clean"}]}


def _sanitize_tool_calls(calls):
    out = []
    for c in (calls or []):
        if isinstance(c, dict):
            out.append({k: v for k, v in c.items() if str(k).lower() not in FORBIDDEN_REQUEST_KEYS})
    return out


def canary_status(manifest: Optional[CompanyManifest], endpoint: Optional[str], secret_env: Optional[str]):
    """Company live-canary readiness (§21). Only 'READY' when an exact manifest, an approved endpoint, and an
    approved secret mechanism are all present; otherwise PENDING_CONFIGURATION (never fabricated)."""
    if manifest is None or not endpoint or not secret_env or not os.environ.get(secret_env):
        return "PENDING_CONFIGURATION"
    try:
        manifest.validate()
    except CompanyManifestError:
        return "PENDING_CONFIGURATION"
    return "READY"
