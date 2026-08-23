# Evidence & Limitations

Three claim axes, tracked separately. Machine-readable source of truth: [`STATUS.yaml`](STATUS.yaml).

## Service correctness — PASS in CI
Schema/RLS/immutability (`ci-experience-schema`), router reason codes + leakage sentinel (`ci-utility-router`),
metadata-only search + gated browse (`ci-agentic-search`), outcome credit + governance (`ci-outcome-governance`),
offline company demo `DEMO_PASS` (`ci-company-demo`), MCP + adapters (`ci-mcp`), docs truth (`ci-docs`),
literature provenance (`ci-literature-audit`).

## Research efficacy — NOT ESTABLISHED (null)
Injecting another engineer's solved experience did not reliably improve coding-task success. Five preregistered
levers (encoding R14, retrieval R15, reader R16, decoding R17, aggregation R18) are all null on SWE-bench Verified;
see [`../reports/MEMORY_TRANSFER_SYNTHESIS.md`](../reports/MEMORY_TRANSFER_SYNTHESIS.md). The utility-router held-out
product endpoint (`H1 = A5 − A0`) is reported honestly as `utility_router_result` in STATUS.

**R19 → R20 (important):** a small-sample R19 run showed A5 (router) > A0 (no memory), but that lift did **not**
survive its compute (A1) and shuffled (A2) controls, and it **did not replicate** in the powered R20 component
factorial (248 untouched tasks): every component effect — bundle, orchestration, relevance, router main, and the
router×relevance interaction — was NULL/INCONCLUSIVE, and even the apparent compute lift vanished (B1−B0 = 0.000).
So the R19 positive was small-sample noise. The router's confirmed property is **safety** (it abstains on 100% of
irrelevant cross-repo memory and adds no net loss), **not** a performance gain. (R20 component-factorial confirmation is tracked in PR #3.)

## Company staging certification — PENDING; production — NOT CLAIMED
No company-controlled staging environment or sign-off exists. `COMPANY-HANDOFF-READY` means a fresh clone builds,
tests pass, and the offline demo passes — **not** that the system is production-certified.

## Known limitations
- Memory efficacy null on the tested public regime; the value proposition is governance/attribution/safety plus
  utility-aware selection, and — only if the router endpoint passes — selective benefit.
- MemGovern upstream license unresolved → no upstream code/data vendored; clean-room only.
- Readers tested ≤ gpt-4o; single benchmark family (SWE-bench Verified); single-shot injection.

## Required company inputs
Model/harness manifest; staging env + sign-off; OIDC issuer/JWKS; PostgreSQL+Qdrant targets; repository access policy.
