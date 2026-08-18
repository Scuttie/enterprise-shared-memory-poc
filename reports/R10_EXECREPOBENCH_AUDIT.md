# R10-A0 §15 — ExecRepoBench Fallback Audit → NOT ELIGIBLE (license unresolvable) → LADDER CLOSED

The pre-declared fallback, opened only because DevEval reached endpoint A (license technical stop). Live audit
2026-08-18 (GitHub REST+raw, HuggingFace API/datasets-server, arXiv). Record:
`artifacts/execrepobench_r10/official_manifest.json`, `configs/execrepobench_r10/benchmark_lock.json`.

## Instrument (works) vs license (disqualifies)
ExecRepoBench **is** a genuine, reproducible, execution-based repository-level fill-in-the-middle benchmark:
- Code `github.com/QwenLM/Qwen2.5-Coder` (→Qwen3-Coder) `qwencoder-eval/base/benchmarks/ExecRepoBench` @
  `33bc6aab`; data HF `CSJianYang/ExecRepoBench` @ `fa61028…` (`exec_repo_bench.jsonl` + `repos.zip`), public/ungated.
- Grader executes `prefix + generated_middle + suffix` in the real repo's conda env; **pass iff `returncode==0`**
  (Pass@1, 240 s timeout); test files excluded from masking; answer not in the prompt.
- **Count:** released **1,164 rows** vs advertised 1.5K (site) / 1.0K (abstract) / 1.2K (paper) — a real headline
  discrepancy (~22% below 1.5K), recorded.

## License — UNRESOLVABLE (the same DevEval defect, worse) 🚩
| component | status |
|---|---|
| Benchmark **harness code** | **NO LICENSE** — GitHub `license: null`, raw `LICENSE` → **404**, no LICENSE/NOTICE anywhere in repo root. Genuinely absent (not the API-null-but-file-present case). Qwen *model* Apache-2.0 does **not** license this eval repo. **UNRESOLVED** |
| **Data** (HF) | **MIT** — but the tag covers only the packaging; it cannot relicense third-party code redistributed inside `repos.zip` |
| **~25 underlying source repos** | **Neither enumerated nor license-attributed.** Extracted from the-stack-v2, filtered by GitHub stars + file length with **no stated license filter**; `repos.zip` redistributes the full repos with no per-repo license map. **UNRESOLVED — arguably worse than DevEval**, which at least manifested its 115 repo names |

For the intended research use (executing generated code against these redistributed real repos' tests), both the
harness code and the source-repo terms are unresolved. §15 requires a resolved license; this fails it.

## Decision — close the static public-benchmark ladder
Per §15: *"If not [eligible]: close the static public-benchmark search. Do not select a third benchmark."* The
two pre-declared instruments in the ladder — **DevEval (primary) and ExecRepoBench (fallback)** — are both
reproducible, execution-based, and **both fail the license gate for the intended research use** (unlicensed
benchmark code + unmanifested/redistributed upstream source repositories). No frozen no-memory pilot was run on
ExecRepoBench (the license gate precedes it, exactly as the DevEval stop preceded its grader step); no memory
arm was run on either. **The static positive-efficacy public-benchmark ladder is CLOSED on license grounds.**

**No third benchmark is sought** (protocol). This is a licensing/technical closure, **not** a flight from a null
memory effect — no memory effect was ever measured on either instrument.

## Constraints honored
No official test modified; no synthetic tasks; no benchmark chosen by observed memory lift; no target
reference/tests placed in any model/memory context; **P6 not started.** Preserved: R1–R8 frozen; `main` d56d178;
PR#1 draft/OPEN; version 0.2.0.dev1; tag v0.1.0-poc.
