# R5-A0 — SkillsBench v1.1 Oracle Reproduction Gate (gold-only)

Closes audit conditions **2/3/4/6** empirically. The official BenchFlow runner (pinned `benchflow==0.6.3`,
contemporaneous with v1.1) ran each SkillsBench task with `--agent oracle --sandbox docker` at the pinned commit
`b63b7b2`; the task's own `verifier/` scores the oracle's `oracle/solve.sh` output. **No paid model.** Runner
CI: `ci-r5-skillsbench-oracle.yml`; driver `scripts/r5_oracle_repro.py`; artifacts `oracle_repro.json` per run.

## Version pinning discovered (recorded)
v1.1 tasks (commit b63b7b2, 2026-06-16) use the `environment:` task.md key; the latest BenchFlow expects the
post-v1.1 `sandbox:` rename (skillsbench #1037, 2026-07-23) and rejects v1.1 tasks. **Pin `benchflow==0.6.3`**
(shipped with v1.1) — then the parser + Docker sandbox + oracle + verifier pipeline runs cleanly.

## Software-engineering subset — oracle reproduction (16 tasks)
| task | subtype | oracle reward |
|---|---|---|
| dialogue-parser | parser | **1.0** |
| python-scala-translation | code-translation | **1.0** |
| jax-computing-basics | library-api | **1.0** |
| react-performance-debugging | perf | **1.0** |
| spring-boot-jakarta-migration | JVM migration | **1.0** |
| azure-bgp-oscillation-route-leak | network | **1.0** |
| data-to-d3 | dataviz-frontend | **1.0** |
| fix-visual-stability | perf | **1.0** |
| flink-query | implementation | **1.0** |
| parallel-tfidf-search | perf | **1.0** |
| fix-build-google-auto | build-repair (BugSwarm) | **1.0** |
| debug-trl-grpo | debugging | **1.0** (log `[PASS]`) |
| llm-prefix-cache-replay | perf | **1.0** |
| simpo-code-reproduction | paper-to-code | **1.0** |
| tictoc-unnecessary-abort-detection | concurrency | **1.0** |
| fix-build-agentops | build-repair (BugSwarm) | 0.0 (see below) |

**Result: 15/16 SE oracles reproduce reward = 1.0** in clean gold-only CI, across every subtype and multiple
languages/frameworks (Python, JVM/Spring, JAX, React, Flink, network). This decisively demonstrates the
harness + verifier are reproducible (conditions 3/4).

## The one failure: fix-build-agentops
`fix-build-agentops` scored reward 0.0 (oracle ran, verifier ran, result FAIL) on **two independent runs** —
**NOT transient**. Its BugSwarm sibling `fix-build-google-auto` reproduced at 1.0, so the mechanism is not
uniformly broken; this specific task's shipped oracle does not satisfy its own verifier in clean CI. **A task
whose own gold cannot be reproduced deterministically must not enter the confirmatory arms**, so
`fix-build-agentops` is **excluded from the frozen reproducible pool** (recorded honestly, not patched — we do
not modify official tasks/tests, §hard-stops).

## Frozen reproducible pool (for a future R5 preregistration)
- **Reproducible SE tasks: 15** (all SE except any BugSwarm task that fails retry) — the core coding pool.
- **Extended coding tasks (15, from the frozen inclusion rule):** their oracles have **not yet been swept**; a
  gold-only sweep (same CI) is required before they join the pool. Recorded as a pre-main step.
- Any task whose oracle does not reproduce reward=1.0 in gold-only CI is **excluded** (a task we cannot grade
  deterministically must not enter the confirmatory arms).

## Audit conditions — now empirically closed
2 (env/oracle/verifier present+functional) **PASS**; 3 (oracle passes verifier) **PASS (15/16 SE = 1.0)**;
4 (Docker-reproducible) **PASS**; 6 (verifier isolatable) **PASS** (`Oracle mode: running oracle solve.sh` →
`Running verifier` are separate stages). With 1/5/8 already PASS and 7 addressed by the frozen 31-task inclusion
rule, **the SkillsBench v1.1 audit passes** for the reproducible coding subset. **No paid arms run; the R5
confirmatory main requires a separate preregistration + approval.**
