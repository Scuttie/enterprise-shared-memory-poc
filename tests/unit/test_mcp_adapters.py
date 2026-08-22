"""P6/R19 §11 — MCP dispatcher + company adapters."""
import pytest

from enterprise_memory.mcp import MemoryMCPServer
from enterprise_memory.adapters import validate_manifest, tool_specs, ManifestError, SUPPORTED_PROTOCOLS
from enterprise_memory.experience import SourceEvidence, Bank, SourceOutcome, GovernanceState, compile_card
from enterprise_memory.agentic.store import InMemoryExperienceStore


def _srv(mode="utility_gated"):
    store = InMemoryExperienceStore()
    ev = SourceEvidence(bank=Bank.HISTORICAL_VERIFIED, source_type="issue_fix", source_repository="acme/widgets",
                        source_outcome=SourceOutcome.PASSED, symptom_signature="loader crash missing config key",
                        root_cause="missing key", fault_localization="acme/widgets/loader.py",
                        affected_symbols=["WidgetLoader.load"], affected_apis=["configparser"],
                        repair_strategy="guard missing key", ordered_actions=["guard missing key"],
                        version_scope="2.x", language="python", framework="acme")
    card = compile_card(ev); card.governance_state = GovernanceState.PROMOTED
    store.add("org-demo", "v1", card)
    return MemoryMCPServer("org-demo", "user-hash", store=store, mode=mode)


def _call(srv, name, args, rid=1):
    return srv.handle({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                       "params": {"name": name, "arguments": args}})


def test_tools_list_has_four():
    r = _srv().handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = [t["name"] for t in r["result"]["tools"]]
    assert names == ["memory_search", "memory_browse", "memory_report_outcome", "memory_explain_decision"]


def test_search_metadata_then_browse_gated():
    srv = _srv()
    s = _call(srv, "memory_search", {"query": "loader missing config key", "repository": "acme/widgets",
                                     "subtask": "modification", "request_id": "r1"})
    cands = s["result"]["content"]
    assert cands and "execution_view" not in cands[0]
    b = _call(srv, "memory_browse", {"version_id": cands[0]["version_id"], "repository": "acme/widgets",
                                     "target_symbols": ["WidgetLoader.load"], "target_apis": ["configparser"],
                                     "subtask": "modification", "version": "2.x", "request_id": "r1"}, rid=2)
    assert b["result"]["content"]["fault_localization"] == "acme/widgets/loader.py"


def test_client_cannot_set_server_fields():
    srv = _srv()
    r = _call(srv, "memory_search", {"query": "x", "org_id": "other-org"})
    assert "error" in r and "server-controlled" in r["error"]["message"]
    r2 = _call(srv, "memory_search", {"query": "x", "policy_mode": "off"})
    assert "error" in r2


def test_unknown_method_and_tool():
    srv = _srv()
    assert "error" in srv.handle({"jsonrpc": "2.0", "id": 1, "method": "nope"})
    assert "error" in _call(srv, "no_such_tool", {})


def test_manifest_validation():
    ok = validate_manifest({"protocol": "openai", "model": "company-model", "endpoint": "https://x"})
    assert ok["protocol"] == "openai"
    with pytest.raises(ManifestError):
        validate_manifest({"protocol": "openai", "endpoint": "https://x"})       # missing model
    with pytest.raises(ManifestError):
        validate_manifest({"protocol": "bogus", "model": "m", "endpoint": "e"})  # bad protocol
    with pytest.raises(ManifestError):
        validate_manifest({"protocol": "openai", "model": "m", "endpoint": "e", "api_key": "sk-.."})  # secret


def test_tool_specs_all_protocols():
    for p in SUPPORTED_PROTOCOLS:
        specs = tool_specs(p)
        assert len(specs) == 4
