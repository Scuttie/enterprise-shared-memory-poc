#!/usr/bin/env python3
"""Offline mock 'local model server' for company integration testing — no real model, no network egress.
Echoes a tool-call plan so a company harness can exercise search->browse->outcome without any provider credential.
Run: python examples/company_harness/mock_local_model_server.py
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
from enterprise_memory.mcp import MemoryMCPServer
from enterprise_memory.experience import SourceEvidence, Bank, SourceOutcome, GovernanceState, compile_card
from enterprise_memory.agentic.store import InMemoryExperienceStore


def _seed():
    store = InMemoryExperienceStore()
    ev = SourceEvidence(bank=Bank.HISTORICAL_VERIFIED, source_type="issue_fix", source_repository="acme/widgets",
                        source_outcome=SourceOutcome.PASSED, symptom_signature="loader crash missing config key",
                        root_cause="missing key", fault_localization="acme/widgets/loader.py",
                        affected_symbols=["WidgetLoader.load"], affected_apis=["configparser"],
                        repair_strategy="guard missing key", ordered_actions=["guard missing key"],
                        version_scope="2.x", language="python", framework="acme")
    card = compile_card(ev); card.governance_state = GovernanceState.PROMOTED
    store.add("org-demo", "v1", card)
    return store


def main():
    srv = MemoryMCPServer(org_id="org-demo", actor_id_hash="mock-harness", store=_seed(), mode="utility_gated")
    # simulate a harness plan
    print(json.dumps(srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))[:200], "...")
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "memory_search",
                       "arguments": {"query": "loader missing config key", "repository": "acme/widgets",
                                     "subtask": "modification", "request_id": "demo"}}}
    print("SEARCH:", json.dumps(srv.handle(call)["result"]["content"])[:300])


if __name__ == "__main__":
    main()
