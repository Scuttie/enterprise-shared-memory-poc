# REALBENCH-R9 / R10 — Final Return (DevEval → ExecRepoBench ladder)

**Achieved endpoint: DevEval TECHNICAL STOP (endpoint A) + ExecRepoBench fallback NOT ELIGIBLE → static
public-benchmark efficacy ladder CLOSED on license grounds.** Both pre-declared instruments are reproducible and
execution-based, but both have unresolvable licenses for the intended research use. No memory effect was measured
on either; no third benchmark sought. R1–R8 frozen; P6 not started.

1. **Commits/HEAD/PR.** Branch `codex/production-service-v0.2`; R9/R10 work committed atop `5bdbb71`
   (start HEAD == live PR headRefOid, asserted). PR **#1 OPEN/DRAFT/unmerged**, base `main`; `main` `d56d178`
   unchanged; tag `v0.1.0-poc`; version `0.2.0.dev1`.
2. **R8 closure.** R8 = **NO_COMPANY_READER / PRECONDITION_UNAVAILABLE** (`reports/R8_NO_COMPANY_READER_CLOSURE.md`)
   — no company reader/endpoint/model/credential; fake CI harness not misrepresented; company replication
   UNAVAILABLE, not pending. PR body updated + read back.
3. **DevEval provenance + licenses.** Repo `seketeam/DevEval` @ `c1653455…` (static since 2024-09-04); data HF
   `LJ0815/DevEval` (Source_Code + Dependency_Data, CC-BY-4.0, public/ungated); execution-based Pass@k
   (`pass_k.py`); Local File (Infilling) setting present. **License: benchmark code = none (all-rights-reserved);
   data = CC-BY-4.0 (annotations only); 115 source repos = unmanifested → UNRESOLVABLE.**
   (`reports/R9_DEVEVAL_DEPENDENCY_AUDIT.md`, `artifacts/deveval_r9/official_manifest.json`.)
4. **Exact valid task count.** Not computed — stopped at the §2 license gate before validity filtering. Recorded
   provenance discrepancy: released **1,825/115** vs paper **1,874/117**.
5. **Repository/test hashes.** Not computed (no materialization of unlicensed repos).
6. **Grader reproduction (§3).** **NOT RUN** — license stop precedes it (we do not execute unlicensed benchmark
   code or materialize license-unmanifested source repos).
7. **Restoration/isolation audit.** **NOT RUN.**
8. **No-memory reader pilot by model/topic.** **NOT RUN** (no §4 reader audit — stopped at §2).
9. **Selected reader + gate decision.** **NOT REACHED.** (Reader remained unselected; DevEval endpoint A fired
   first.)
10–30. **Partition / source banks / canonical memory / relevance / representation discovery / retrieval /
    calibration / held-out main / Pass@1 by arm / H1–H4 effects / cluster CI + McNemar / transfer / mechanism /
    tokens-latency / preemption.** **ALL NOT RUN** — no valid instrument was reached, so no memory experiment
    was constructed or executed. No effect of any kind was measured.
31. **Workflows.** No new R9 CI added (they gate a running instrument, which does not exist); existing workflows
    unchanged/green. Paid stages never reached.
32. **Hard-stop decisions.** The §17 hard stop *"unresolved benchmark/data/source-repository license"* is the
    operative one and fired **twice**: DevEval (endpoint A) and ExecRepoBench (fallback ineligible). No other §17
    condition applicable (no memory/model context ever received target bodies/tests; nothing executed).
33. **ExecRepoBench status.** Audited (`reports/R10_EXECREPOBENCH_AUDIT.md`,
    `artifacts/execrepobench_r10/official_manifest.json`): reproducible execution-based FIM benchmark (code
    `QwenLM/Qwen2.5-Coder` @ `33bc6aab`, data HF `CSJianYang/ExecRepoBench` @ `fa61028…`, 1,164 rows vs advertised
    1.5K) but **license UNRESOLVABLE** — harness code unlicensed (LICENSE 404) + ~25 source repos neither
    enumerated nor license-attributed (`repos.zip` redistributes them). **NOT ELIGIBLE → static public-benchmark
    search closed; no third benchmark.**
34. **P6 recommendation.** **Do not begin P6.** Not started.
35. **Merge/release recommendation.** Keep **PR#1 draft**; do not merge; no RC/beta tag.

## Bottom line
The R9 ladder was executed exactly as pre-declared: primary DevEval, single fallback ExecRepoBench, no third
benchmark. Both are genuine, reproducible, execution-based repository-aligned instruments — and both are
**disqualified by unresolvable licensing for the intended research use**: the benchmark code is unlicensed and the
underlying real source repositories they redistribute are license-unmanifested (ExecRepoBench worse, not even
enumerating its repos). Per protocol the ladder **closes on a licensing/technical basis**, not because a memory
effect came out null — **no memory effect was ever measured**, since neither instrument cleared the license gate
that precedes any reader or memory work. This is the honest terminal state: the static positive-efficacy
public-benchmark search is closed. Company replication remains UNAVAILABLE (R8). **R1–R8 frozen; PR#1 draft; P6
not started.**
