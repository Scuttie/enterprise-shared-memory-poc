# Enterprise Shared Memory PoC

**Status: DEMO-COMPLETE — NOT PRODUCTION-READY**

Governed private/shared memory for coding agents. One developer's *verified* coding experience can help
another developer's executable task succeed — **without** leaking private information or spreading stale,
out-of-scope, or incorrect fixes.

> **Design principle:** *Store contracts for governance; compile literal execution views for coding.*

## What problem this solves
Naive shared memory propagates stale/out-of-scope/wrong fixes and leaks private context. This PoC keeps an
**authoritative canonical Memory Contract** (SQLite) governed by permission/scope/version/expiry/
supersession gates, and hands the coding model a **compact literal execution view** compiled
deterministically only after every gate passes.

## What is implemented
Canonical SQLite contract registry · Mem0 private/shared retrieval adapters (governed `infer=False` path +
`infer=True` baseline) · permission & tenant isolation · scope/version/expiry/supersession gates ·
security scanner · promotion state machine · append-only audit ledger · FastAPI serving layer + OpenAPI ·
controlled execution sandbox · compact-literal execution-view compiler with invalid-contract **refusal** ·
deterministic Alice/Bob demo.

## Five-minute offline demo (no credentials)
```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv/Scripts/activate
python -m pip install -e ".[dev]"
python scripts/demo_alice_bob.py --offline
python -m pytest -q tests/unit tests/security tests/integration/test_api.py
```
PowerShell:
```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python scripts/demo_alice_bob.py --offline
.venv/Scripts/python -m pytest -q tests/unit tests/security tests/integration/test_api.py
```

## Live setup (Solar + Mem0)
1. `cp .env.example .env` and set `UPSTAGE_API_KEY` (never commit it).
2. Configure `ENTERPRISE_MEMORY_RUNTIME_ROOT` and `configs/mem0.example.yaml`.
3. `python scripts/mem0_validate.py` (opt-in: `RUN_MEM0_INTEGRATION=1`).
4. Start FastAPI: `uvicorn enterprise_memory.serving.api:create_app --factory`.

## Architecture (control plane vs execution plane)
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The **canonical contract** governs selection/validity;
a **compact literal execution view** is compiled for the coding model; Mem0 is a replaceable retrieval
index; the audit trail is immutable.

## Current status & limitations
Demo-complete, not production-ready. Evidence and honest limitations:
[docs/EVIDENCE_AND_LIMITATIONS.md](docs/EVIDENCE_AND_LIMITATIONS.md),
[docs/PRODUCTIONIZATION_CHECKLIST.md](docs/PRODUCTIONIZATION_CHECKLIST.md). No general coding-efficacy
claim; the preregistered acceptance suite was **not fully passed** (3/5 gates).
