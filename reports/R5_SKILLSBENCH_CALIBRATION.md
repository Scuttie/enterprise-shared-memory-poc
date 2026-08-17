# R5 — A0 NO_SKILL Calibration (dynamic-range gate)

A0 no-skill calibration on the frozen reproducible pool (30 tasks: 15 SE + 15 extended coding; oracle-verified
30/31). **Reader = Solar-pro2 repository-agent** via BenchFlow `deepagents` + the `vllm/` user-endpoint route to
Upstage (`--model vllm/solar-pro2-251215` + `BENCHFLOW_PROVIDER_BASE_URL/API_KEY/MODEL`), `--skill-mode
no-skill`, official SkillsBench verifiers, Docker sandbox. Runs 31987193673 / 31988435791 / 31988446098.
Result: `artifacts/swe_skills_r5/A0_calibration_results.json`.

## Reader is validated and genuinely working
The routing fix (a `vllm/` user-endpoint provider so BenchFlow honors the Upstage base URL — its `openai`
provider is hardcoded to api.openai.com) made Solar drive the agent correctly: on dialogue-parser it produced
**13 tool calls, errors=0**, and the verifier scored it. Across the 30-task calibration, **25/30 tasks show
genuine multi-tool attempts** (median 9 tool calls, up to 29; the agent explores + edits the repo); 3 tasks hit
an agent error (reward=None). So the failures below are *real attempt-and-fail*, not an infrastructure artifact.

## Result — FLOOR
**No-skill Pass@1 = 0.0000 (0/30).** Solar-pro2, as a repository agent, solved **none** of the 30 reproducible
SkillsBench tasks without a skill, despite genuine multi-tool attempts. This is consistent with the benchmark
being deliberately hard (skill-requiring) and with a mid-tier reader: the tasks are out of reach for Solar-pro2
unaided.

## §5 / §10-G3 in-band gate — FAIL (floor)
The in-band definition requires the no-skill baseline to sit in a measurable band — §5: no-skill pass 1/3 or 2/3
per skill; §10 G3: no-skill Pass@1 ∈ [0.10, 0.90] with ≥8 in-band skills over ≥4 subdomains. At **0/30**, **zero
tasks are in-band** — the instrument has no dynamic range in which a skill effect (A1–A3 vs A0) could be
measured. If the reader fails ~all tasks no-skill (and, per the SkillsBench paper, most tasks don't improve even
*with* skills), there is no signal to detect.

→ **§0-B INSTRUMENT STOP.** The skill-condition main (A1 official / A2 governed-executable / A3 shuffled-matched)
and the version-mismatch safety subset are **NOT run**. Decision + rationale: `R5_SKILLSBENCH_CALIBRATION_DECISION.md`.

## Not a reader-weakening or task-swapping situation
The §5 rule forbids weakening the reader; here the reader is already at the floor. It also forbids swapping
tasks after seeing outcomes. Neither is done. The pool, reader, and inclusion rule stay frozen; the honest
result is that this reader/benchmark pairing lacks dynamic range at the **floor** — exactly the mirror of R3
(DS-1000 + Solar) at the **ceiling** (0.98).
