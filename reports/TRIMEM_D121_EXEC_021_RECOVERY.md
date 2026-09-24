# TriMem-Coder V1 D1.21 `_021` SWE outcome-normalization recovery

## Current endpoint

This credential-free source may end only at
`TRIMEM_V1_READY_FOR_EXEC_021_REQUEST`. It is not a benchmark score and does
not authorize protected execution. Run `34240675412`, attempt `1`, and
`DEVELOPMENT_TUNING_EXEC_REQUEST_020.json` are spent. They must not be rerun,
resumed, or reused as approval for another attempt.
The freeze retains both the immutable `_019` request and the spent exact
`_020` request as history; only the not-yet-created `_021` request is excluded.

## Immutable `_020` execution boundary

- source HEAD: `138619d5d5e83009c3c22a4d9619a9394b0b59a1`;
- execution HEAD: `f15371a612d6c35acabe56e7d3196429b95ca3bb`;
- `_020` raw bytes/SHA-256: `49618` /
  `c177d9664972eaa128c3d7efe6666c192c2666912fd52b258364944fa3ad2665`;
- `_020` Git blob: `c37ed850c34bb8d398e7670eaf242e4e6020f14d`;
- `_020` payload SHA-256:
  `041f09b92e2f8b42224c560a95dac82fd76cbede7aa726042135d54fdab53d7c`;
- source freeze SHA-256:
  `3b91b43f7b299bdcca90f604e78975308543b5680b37be0a19ebb370686b5e71`;
- workflow run/attempt: `34240675412` / `1`;
- run created/updated: `2026-09-08T14:48:42Z` /
  `2026-09-08T15:05:06Z`.

The branch-trigger and bounded-context preflights passed. In the protected
job, approval materialization, protected environment, EXEC gate, exact-model
metadata, protocol canary, all 13 frozen image pulls, and grader-factory
rehearsal also passed. The first official grader container started and its
upstream harness exited zero.

## What the grader actually found

The first cell was index `000`, target
`swebench_verified--django__django-16100`, stream `M2-baseline`. The complete
official SWE-bench report had zero FAIL_TO_PASS failures and exactly one
PASS_TO_PASS regression. Therefore its authoritative scientific outcome was
`UNRESOLVED`:

```text
resolved = (len(FAIL_TO_PASS.failure) == 0)
           and (len(PASS_TO_PASS.failure) == 0)
```

The old adapter instead rejected the non-empty PASS_TO_PASS failure set as
`adapter_contract_failed`, and the driver surfaced
`GLOBAL_GRADER_INFRA_FAILURE`. That classification was wrong. A P2P
regression is a valid negative scientific outcome; it is not evidence that
the adapter, container, or harness failed. Since no terminal-cell record was
committed and aggregation was never entered, this run still has zero terminal
cells out of 72, no public aggregate, `Pass@1 = null`, and
`PERFORMANCE = NOT_MEASURED`.

## Exact consumed accounting

Scientific work consumed 17 paid generation calls: one decomposition, 16
solve calls, and zero extraction calls. It used 142,200 input tokens, zero
cached input tokens, 6,416 output tokens, and exactly `$0.135522000000`.

The protocol canary separately consumed one paid generation call, 950 input
tokens, 28 output tokens, and `$0.000838500000`.

The whole attempt therefore consumed 18 paid/model generation calls, 143,150
input tokens, zero cached input tokens, 6,444 output tokens, and
`$0.136360500000`. It also consumed 13 image pulls and, conservatively, one
grader attempt, one grader container, and one official grader run. Reasoning
tokens are unavailable in the recovered ledger and are recorded as `null /
UNAVAILABLE_NOT_INFERRED`; they are not inferred from output-token or price
fields.

## Evidence custody

No public campaign result exists. Failure custody passed and preserved:

- restricted encrypted artifact `10062528991`, digest
  `311d83fd954d01f84622f45647eda55457653d2454abdf0c21e51d51b33a91fd`;
- inventory artifact `10062530700`, digest
  `2f6ea4abaa2b26213db5c21bb73bd490e54d2cd72a058bdd29920cde197a9a32`;
- custody artifact `10062533559`, digest
  `d4fd4cad7f8995276b2506dd774c2c1a9ff0689ed72b40f9f8dfa7935833db4b`.

The restricted inventory covers 239 files and 10,562,762 bytes with inventory
SHA-256
`2eb8ab41af1211632134ecfe92348a44537ea346e479dd15211f8099e7e4f14a`.
The frozen receipt contains hashes, accounting, and sanitized semantics only;
it contains no credential or model content.

## Fail-closed D1.21 correction

For SWE reports, D1.21 first retains the strict source-domain equality,
failure-set disjointness, completeness, patch/application, container,
subprocess, and report-integrity checks. Only after those checks pass does it
derive `resolved` from both failure sets. A non-empty P2P failure set now
produces an authoritative unresolved result and an exact
`pass_to_pass_regressions` count. The benchmark matrix independently
recomputes both the predicate and count before accepting the cell. Malformed,
missing, contradictory, or infrastructure evidence still fails closed.

## Preserved science and `_021` authority boundary

D1.21 does not change model `gpt-5.4-mini-2026-03-17`, reasoning effort
`medium`, pricing, all 12 targets and their order, six streams, prompts, tools,
parsers, memory policies, per-arm budgets, grader/image locks, the `$10.80`
expected budget, or the `$50.00` hard cap. No result-dependent scientific
choice was made.

Only a sentinel-only `_021` child may be created after the exact-source
credential-free CI, fresh runner/readiness evidence, checkout rehearsal,
loader rehearsal, and grader-factory rehearsal pass. Protected execution then
requires a new external approval bound to that exact sentinel commit, run ID,
attempt `1`, freeze, request bytes, actor, timestamp, nonce, legal acceptance,
caps, and key commitment. The exact required authorization is
`TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_021_APPROVED_ONCE`. Until that separate
approval exists, the new
attempt has zero model/API calls, zero containers, zero task-arm runs, and zero
USD. DEV/HELDOUT, grader-smoke reruns, component ablation, merge, tag, and
release remain outside this recovery.
