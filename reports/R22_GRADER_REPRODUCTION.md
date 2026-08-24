# R22 §3 (G0) — mixed official-grader reproduction (executed)

Goal: the official SWE-bench grader must **discriminate** on the frozen 12-task mixed smoke — gold patch → resolved,
no patch → unresolved — with no model calls and no test modification. Per-instance subset routing
(`reports/R22_MIXED_GRADER_ROUTING.md`): 1 Verified, 2 Lite, 9 Multilingual.

## Execution (ci-r22-grader-smoke.yml, run 32754432915)
Sharded matrix (1 instance/job × {gold, no-patch} = 24 evals), Docker-capable ubuntu-24.04 runner, ~25GB disk freed
(110GB free confirmed), official `swebench==5.0.2` `run_evaluation --dataset_name <subset> --instance_ids <iid>`.

## Result — completeness 24/24, no-patch 0/12 resolved (correct), gold 9/12
| Instance | Subset | gold | no-patch | note |
| --- | --- | --- | --- | --- |
| caddyserver__caddy-5761 | Multilingual (go) | ✅ resolved | unresolved | correct |
| prometheus__prometheus-9248 | Multilingual (go) | ✅ resolved | unresolved | correct |
| apache__lucene-11760 | Multilingual (java) | ✅ resolved | unresolved | correct |
| google__gson-2311 | Multilingual (java) | ✅ resolved | unresolved | correct |
| rubocop__rubocop-13396 | Multilingual (ruby) | ✅ resolved | unresolved | correct |
| tokio-rs__tokio-6724 | Multilingual (rust) | ✅ resolved | unresolved | correct |
| tokio-rs__axum-1119 | Multilingual (rust) | ✅ resolved | unresolved | correct |
| astral-sh__ruff-15543 | Multilingual (rust) | ✅ resolved | unresolved | correct |
| php-cs-fixer__php-cs-fixer-7875 | Multilingual (php) | ✅ resolved | unresolved | correct |
| astropy__astropy-8707 | Lite (py) | ❌ infra | unresolved | swebench KeyError:'image' |
| sympy__sympy-14774 | Verified/Lite (py) | ❌ infra | unresolved | swebench KeyError:'image' |
| mwaskom__seaborn-3190 | Lite (py) | ❌ infra | unresolved | swebench KeyError:'image' |

## Precise blocker (exact task-level)
- **All 9 SWE-bench Multilingual instances grade correctly** — per-subset routing + official images + harness work.
- **The 3 SWE-bench Lite/Verified (python) instances fail** the gold condition with a **swebench 5.0.2 internal
  `KeyError: 'image'`** at `image=instance["image"]` in the python x86 image-spec path. This is **not disk**
  (110GB free after cleanup) and **not routing** — it is a harness-version defect/incompatibility in the python
  build path for these instances under 5.0.2.
- Therefore the mixed **12/12 gold** gate is **not met** (gold 9/12). The frozen mixed smoke is **not** narrowed to
  Verified-only (that would not satisfy the gate).

## Verdict: `R22_MIXED_GRADER_TECHNICAL_BLOCK`
Documented with exact per-task failures. Materially more than the prior total block: routing is proven and the
official harness discriminates **9/12** (all multilingual). To clear it: a swebench version/patch that fixes the
python `KeyError:'image'` build path (or a self-hosted runner with prebuilt python instance images). No model calls
were made.
