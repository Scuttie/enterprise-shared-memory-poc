# Research Reproduction

The research history is frozen and separate from the product. No credentials or private data are required or
included here.

## Memory-transfer study (R14–R18) — frozen
Five preregistered levers on SWE-bench Verified, all null:
[`../reports/MEMORY_TRANSFER_SYNTHESIS.md`](../reports/MEMORY_TRANSFER_SYNTHESIS.md) and the per-experiment reports
in [`../reports/`](../reports/). Arms, manifests, and analysis scripts are under `artifacts/swebench_r14/` and
`scripts/r1*_*.py`. These tasks are **DEVELOPMENT_OBSERVED** for R19 and are never reused for a new confirmatory
claim.

## Utility-router causal study (R19 / P6)
Preregistration and frozen manifests: [`P6_UTILITY_ROUTER_PREREG.md`](P6_UTILITY_ROUTER_PREREG.md) and
`../artifacts/p6/` (`router_policy.json`, `governance_thresholds.json`, task/source manifests). Fixed reader,
harness, and tool budget across arms **A0–A5**:
- A0 no memory · A1 compute-matched planning · A2 shuffled agentic memory · A3 static relevant · A4 agentic
  reference (no router) · A5 utility-gated.
- Endpoints: `L1=A4−A0`, `L2=A4−A1`, `L3=A4−A2`, `H1=A5−A0`, `H2=A5−A1`, `H3=A5−A2`, `H4=A5−A4`. ITT; exact
  McNemar; repository-cluster bootstrap; Holm for secondary superiority.

## Literature
MemGovern (arXiv 2601.06789) exact reproduction is license-blocked (see
[`../reports/MEMGOVERN_REPRODUCIBILITY_AUDIT.md`](../reports/MEMGOVERN_REPRODUCIBILITY_AUDIT.md)); the product
carries a clean-room behavioral reference (A4), never presented as MemGovern's numbers. SWE-Exp (Apache-2.0) is a
conceptual comparator (no files reused). Official grader only; gold/hidden tests never enter agent context.

## Result label
The router held-out result is one of `UTILITY_ROUTER_POSITIVE | NULL | NEGATIVE | NOT_RUN`
(`utility_router_result` in [`STATUS.yaml`](STATUS.yaml)).
