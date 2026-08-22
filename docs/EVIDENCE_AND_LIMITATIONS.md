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
