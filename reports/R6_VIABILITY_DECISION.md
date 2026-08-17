# R6 §3 — Reader-Skill Viability Decision → Endpoint B (available readers out of reach)

Per the §3 rule, a reader is **skill-viable** on SkillsBench only if ALL hold: terminal exec ≥ 29/30,
harness/verifier errors = 0, **official-skill exact success ≥ 3/30**, **≥ 3 net gains over no-skill**, no
leakage, pinned identity. Selection (had any been viable) is by **highest exact success — never by p-value.**

## Verdict per reader
| reader | exec ran | harness/verifier err | official-skill exact | net gain vs A0 | **viable?** |
|---|---|---|---|---|---|
| P2 `solar-pro2-251215` | 27/30 | 0 (3 task-intrinsic env-err) | **0/30** | **0** | **NO** |
| P3 `solar-pro3-260323` | 27/30 | 0 (3 task-intrinsic env-err) | **0/30** | **0** | **NO** |

Both readers fail the two capability gates outright: official-skill exact success 0 < 3, and net gain 0 < 3.
The result does not hinge on the exec-count gate — even restricting to the 27 tasks whose verifier ran cleanly,
exact success is 0/27 with the official skill genuinely injected (24/30 behavior change confirmed). No selection
is made; **neither Solar reader is skill-viable on SkillsBench.**

## Why this is the honest call (not a benchmark-switch to flee a null)
- R6 tested the *exact* condition R5 omitted (A1 official skill) on the *same* frozen tasks, with the skill
  verified to have changed agent behavior. The zero survived. This **retires the "we never gave it the skill"
  alternative**, rather than reinterpreting R5.
- It is **not** evidence that official skills cannot help in general — only that these two Solar readers are out
  of reach on SkillsBench's hard tasks even with the skill. The paper's own reader (Claude Code) is in-band; a
  sufficiently strong reader remains the revive path (a future preregistration), unchanged from R5.
- No task/verifier was modified; the verifier was never exposed; no synthetic tasks; no reader was
  weakened/strengthened within R6; no task reselection.

## Decision
**Endpoint B — available readers out of reach.** Per §6, the SkillsBench follow-up (§5 S0–S3 on unseen official
tasks) is **NOT opened** (it requires a viable reader, and there is none). Instead R6 **opens
`REALBENCH_SWE_POLYBENCH_R7`**: an instrument audit of SWE-PolyBench Verified plus a no-memory calibration pilot
gated on a resolved rate in **[0.10, 0.70]** (a genuine measurable band — neither R3's ceiling nor R5/R6's
floor), with the M0–M4 memory design preregistered (§7). No paid SWE-PolyBench runs begin under R6 beyond what
the audit/pilot gate authorizes.

**Standing constraints preserved:** R1–R5 frozen and immutable; R6 diagnostic frozen
(`configs/skills_reader_r6/diagnostic_2x2_lock.json`); `main` `d56d178`; PR#1 draft/OPEN/unmerged; version
`0.2.0.dev1`; **P6 not started.**
