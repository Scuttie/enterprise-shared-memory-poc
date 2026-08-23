"""P5.1 §10 — company harness adapter boundary, credential-free against a local fake harness server. Proves:
the three serving protocols each return a patch through the same governed contract; forbidden fields
(credentials/hidden tests/verdict) are rejected before dispatch; the manifest must be complete and
service-owned; the live canary is PENDING_CONFIGURATION until fully configured; and the adapter plugs into
ExternalHarnessExecutionBackend."""
import asyncio
import pytest
from fake_harness import FakeHarnessServer
from enterprise_memory.service.company_harness import (
    CompanyManifest, CompanyHarnessClient, CompanyHarnessRequest, ForbiddenHarnessField,
    CompanyManifestError, canary_status)
from enterprise_memory.service.execution import ExternalHarnessExecutionBackend


def _manifest(protocol, endpoint):
    return CompanyManifest(harness_name="acme-code", harness_version="1.2.3", model_id="company-glm",
                           model_revision="2026-01-01", serving_protocol=protocol, endpoint=endpoint,
                           context_window=32000, max_output_tokens=1024, tool_schema_hash="deadbeef",
                           repository_mount_mode="read_only_snapshot", sandbox_test_ownership="service",
                           streaming=False, timeout_seconds=15, build_id="build-42")


def _payload():
    return {"logical_request_id": "lrq-1", "instruction": "make f return 1",
            "target_path": "src/app.py", "repository_reference": {"repo": "r", "commit": "c"},
            "edit_policy": {"editable_paths": ["src/**"], "max_changed_lines": 12},
            "memory_views": ["governed view: use return 1"]}


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("protocol", ["openai", "anthropic", "jsonrpc"])
def test_protocol_returns_patch(protocol):
    with FakeHarnessServer(protocol) as srv:
        client = CompanyHarnessClient(_manifest(protocol, srv.endpoint))
        out = run(client.run(_payload()))
    assert "return 1" in out["patch"] and out["patch"].startswith("--- a/src/app.py")
    assert out["harness_identity"] == "acme-code/company-glm@2026-01-01"
    assert out["model"] and out["latency"] >= 0 and out["usage"]
    assert out["model_call_records"][0]["backend_type"] == "external_harness"


def test_forbidden_field_rejected():
    # a forbidden key anywhere in the governed request must raise BEFORE any dispatch
    req = CompanyHarnessRequest(logical_request_id="x", repository_reference={"repo": "r"},
                                instruction="i", edit_policy={"hidden_test": "assert secret"})
    with pytest.raises(ForbiddenHarnessField):
        req.as_dict()
    req2 = CompanyHarnessRequest(logical_request_id="x", repository_reference={"authorization": "Bearer z"},
                                 instruction="i", edit_policy={})
    with pytest.raises(ForbiddenHarnessField):
        req2.as_dict()


def test_manifest_validation():
    with pytest.raises(CompanyManifestError):
        _manifest("openai", "http://x").__class__(**{**_manifest("openai", "http://x").__dict__,
                                                     "model_id": ""}).validate()
    # sandbox/hidden tests must remain service-owned
    bad = _manifest("openai", "http://x").__dict__ | {"sandbox_test_ownership": "harness"}
    with pytest.raises(CompanyManifestError):
        CompanyManifest(**bad).validate()
    with pytest.raises(CompanyManifestError):
        (_manifest("weird", "http://x")).validate()


def test_canary_pending_until_configured(monkeypatch):
    m = _manifest("openai", "http://x")
    assert canary_status(None, None, None) == "PENDING_CONFIGURATION"
    assert canary_status(m, m.endpoint, "COMPANY_KEY") == "PENDING_CONFIGURATION"   # secret env not set
    monkeypatch.setenv("COMPANY_KEY", "up_xxx")
    assert canary_status(m, m.endpoint, "COMPANY_KEY") == "READY"


def test_external_harness_backend_end_to_end():
    with FakeHarnessServer("openai") as srv:
        client = CompanyHarnessClient(_manifest("openai", srv.endpoint))
        backend = ExternalHarnessExecutionBackend(client)
        res = run(backend.execute({"instruction": "make f return 1", "target_path": "src/app.py",
                                   "repository_reference": {"repo": "r", "commit": "c"},
                                   "edit_policy": {"editable_paths": ["src/**"], "max_changed_lines": 12}},
                                  {"src/app.py": "def f():\n    return 0\n"},
                                  ["governed view"], logical_request_id="lrq-2", org_id="o"))
    assert res.backend_type == "external_harness" and "return 1" in res.patch_text
    assert res.returned_model
