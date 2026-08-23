# R9 §2 — DevEval Provenance + License Audit → DEVEVAL TECHNICAL STOP (endpoint A)

Live, date-anchored audit (2026-08-18) of the **official** DevEval (Li et al., ACL 2024 Findings,
arXiv:2405.19856; repo `seketeam/DevEval`). All facts from live HTTP (GitHub REST + raw, HuggingFace API, arXiv),
not cached memory. Authoritative record: `artifacts/deveval_r9/official_manifest.json`,
`configs/deveval_r9/benchmark_lock.json`.

## What DevEval is (validated)
- **Repo** `github.com/seketeam/DevEval` @ `c1653455e0a18480a29aa07ba51636070f113316` (static since 2024-09-04),
  default branch `main`. Namesake `open-compass/DevEval` is a **different** benchmark — not conflated.
- **Execution-based, real-repository** function-generation benchmark. `data.tar.gz` (metadata → `data.jsonl`) is
  in the repo; `Source_Code.tar.gz` + `Dependency_Data.tar.gz` at HF `LJ0815/DevEval` (public, ungated, ~2.59 GB).
- **Task structure** confirmed: `namespace`, `project_path`, `completion_path`, `requirement`
  (`Functionality`/`Arguments`), `tests`, `dependency` (`intra_class`/`intra_file`/`cross_file`), signature/body
  positions. The **Local File (Infilling)** setting I need exists verbatim (signature + requirement + local
  context above+below, no target body).
- **Grader** is genuine execution-based Pass@k: `pass_k.py`, `run_pass_k.sh`, `parser/recall_k.py`,
  `check_source_code.py`; per-repository environment setup required (gpt-4-turbo Pass@1 = 53.04%).
- **Provenance wrinkle (recorded):** released README+data say **1,825 samples / 115 repos / 10 topics**; the
  paper says **1,874 / 117**. Not a stop by itself — the released artifact count (1,825/115) would govern.

## License — UNRESOLVABLE for the intended research use 🚩 (the deciding finding)
| component | status |
|---|---|
| Benchmark **code** (`seketeam/DevEval`) | **NO LICENSE** — GitHub API `license: null`; no LICENSE/COPYING/NOTICE in repo root → all-rights-reserved by default → **UNRESOLVED** |
| **Data** (HF `LJ0815/DevEval`) | **CC-BY-4.0** (HF card) — resolved for the *annotations/metadata only* |
| **115 underlying source repositories** | **NOT documented per-repo** — no SPDX manifest, no redistribution terms; the bundled `Source_Code.tar.gz` carries undocumented mixed upstream terms (possibly GPL/AGPL). CC-BY-4.0 on the HF bundle **cannot override** each upstream repo's own license → **UNRESOLVED** |

The intended research use is **executing generated code against the real repositories' unit tests**, which
requires running the (unlicensed) benchmark code and materializing the bundled source of 115 repositories whose
individual licenses are unmanifested. Under default copyright, unlicensed code grants no reuse rights, and the
source-repo terms cannot be verified from released artifacts. Per §2 — *"If the benchmark or the source-repository
license status cannot be resolved: DEVEVAL TECHNICAL STOP"* — this condition is met.

## Decision
**DEVEVAL TECHNICAL STOP (endpoint A).** The stop is on **license resolvability**, reached in §2 **before** grader
reproduction (§3) — we do not execute against or materialize unlicensed/unmanifested material. Reproducibility
and instrument structure are otherwise fine; the blocker is licensing, exactly the pre-declared criterion.

Per the milestone ("In A or B only: open the predeclared ExecRepoBench fallback audit"), R9 now opens the
**ExecRepoBench fallback audit** (R10-A0). ExecRepoBench's *data* is declared MIT (HF `CSJianYang/ExecRepoBench`)
— a cleaner license baseline to audit — with a documented sample-count inconsistency (advertised ~1.5K vs released
~1.16K) to resolve there.

## Constraints honored
No official test modified; no synthetic replacement; no benchmark selected by observed memory lift; DevEval was
**not** stopped to flee a null (no memory run occurred — the stop is purely licensing/technical). No third
benchmark will be sought (ExecRepoBench is the single pre-declared fallback). **R1–R8 frozen; `main` d56d178;
PR#1 draft/OPEN; version 0.2.0.dev1; P6 not started.**
