# Enterprise Shared Memory

Governed **private/shared memory for coding agents**: an auditable control plane that stores verified coding
experience, retrieves candidates, and applies a **utility-aware router** deciding `USE` / `ABSTAIN` before any
memory reaches a model — so redundant, out-of-scope, stale, or harmful experience is rejected and never leaks
across tenants.

<!-- STATUS:BEGIN -->
| Dimension | Status |
| --- | --- |
| Version | `0.3.0.dev1` |
| Service plumbing | `IMPLEMENTED` |
| Research efficacy | `MEMORY_TRANSFER_EFFICACY_NULL` |
| Utility router (held-out) | `NOT_RUN` |
| Company handoff | `IN_PROGRESS` |
| Production certification | `NOT_CLAIMED` |
| Migration head | `0014` |

> **COMPANY HANDOFF IN PROGRESS — not yet COMPANY-HANDOFF-READY, not COMPANY-STAGING-CERTIFIED.** Service correctness, research efficacy, and staging certification are tracked separately; see [`docs/STATUS.yaml`](docs/STATUS.yaml) (single source of truth) and [`docs/EVIDENCE_AND_LIMITATIONS.md`](docs/EVIDENCE_AND_LIMITATIONS.md).
<!-- STATUS:END -->

> **Efficacy honesty (read this first).** Injecting another engineer's solved experience did **not** reliably
> improve coding-task success in our controlled study (REALBENCH R14–R18: five levers — encoding, retrieval,
> reader strength, decoding, aggregation — all null on SWE-bench Verified;
> [`reports/MEMORY_TRANSFER_SYNTHESIS.md`](reports/MEMORY_TRANSFER_SYNTHESIS.md)). This project therefore ships as
> a **governance and attribution platform** whose value is safety, auditability, and *utility-aware selection*,
> not an assumed performance boost. Any performance claim is gated on the held-out utility-router result
> (`utility_router_result` in [`docs/STATUS.yaml`](docs/STATUS.yaml)).

> **Design principle:** *Store canonical experience for governance; compile neutral projections for retrieval and
> literal execution views for coding; gate every injection with an auditable router.*

## What problem this solves
Naive shared memory propagates stale/out-of-scope/wrong fixes and leaks private context. The system keeps an
**authoritative canonical experience record in PostgreSQL** (Qdrant/Mem0 are replaceable retrieval indices, never
the source of truth) governed by permission/scope/version/expiry/supersession gates, and hands the coding model a
**compact literal execution view** compiled deterministically only after every gate — and the utility router —
approves it.

## What is implemented
Canonical **PostgreSQL** experience/contract registry (authoritative; RLS-isolated) · Mem0/Qdrant private/shared retrieval adapters (governed `infer=False` path +
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
