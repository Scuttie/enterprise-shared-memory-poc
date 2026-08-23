#!/usr/bin/env python3
"""Example: wire a company coding harness to the memory service over HTTP /v1 (or MCP).
No credentials are embedded; the bearer token is read from the environment at runtime. Shows the search->browse->
outcome loop a harness performs per subtask. Offline-safe: if EM_ENDPOINT is unset it runs against the in-process
MCP dispatcher so the example is runnable with zero infra.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
from enterprise_memory.adapters import validate_manifest, tool_specs
from enterprise_memory.mcp import MemoryMCPServer
from enterprise_memory.experience import SourceEvidence, Bank, SourceOutcome, GovernanceState, compile_card
from enterprise_memory.agentic.store import InMemoryExperienceStore

MANIFEST = {"protocol": os.environ.get("EM_PROTOCOL", "openai"),
            "model": os.environ.get("EM_MODEL", "company-local-model"),
            "endpoint": os.environ.get("EM_ENDPOINT", "http://in-process")}


def run():
    validate_manifest(MANIFEST)                      # fail closed on a bad manifest
    specs = tool_specs(MANIFEST["protocol"])         # declare the 4 memory tools to the company model
    print("declared %d memory tools for protocol=%s" % (len(specs), MANIFEST["protocol"]))

    # offline path: in-process MCP dispatcher with a seeded card
    store = InMemoryExperienceStore()
    ev = SourceEvidence(bank=Bank.HISTORICAL_VERIFIED, source_type="issue_fix", source_repository="acme/widgets",
                        source_outcome=SourceOutcome.PASSED, symptom_signature="loader crash missing config key",
                        root_cause="missing key", fault_localization="acme/widgets/loader.py",
                        affected_symbols=["WidgetLoader.load"], affected_apis=["configparser"],
                        repair_strategy="guard missing key", ordered_actions=["guard missing key"],
                        version_scope="2.x", language="python", framework="acme")
    card = compile_card(ev); card.governance_state = GovernanceState.PROMOTED
    store.add("org-demo", "v1", card)
    srv = MemoryMCPServer("org-demo", "harness-user", store=store, mode="utility_gated")

    search = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "memory_search",
                        "arguments": {"query": "loader missing config key", "repository": "acme/widgets",
                                      "subtask": "modification", "request_id": "r1"}}})
    cands = search["result"]["content"]
    print("search ->", json.dumps(cands)[:200])
    if cands:
        browse = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "memory_browse",
                            "arguments": {"version_id": cands[0]["version_id"], "repository": "acme/widgets",
                                          "target_symbols": ["WidgetLoader.load"], "target_apis": ["configparser"],
                                          "subtask": "modification", "version": "2.x", "request_id": "r1"}}})
        print("browse ->", json.dumps(browse["result"]["content"])[:200])


if __name__ == "__main__":
    run()
