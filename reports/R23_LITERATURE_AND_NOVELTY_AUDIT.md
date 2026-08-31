# R23-F0 — Literature & novelty audit

Primary sources pinned in `artifacts/r23/literature_lock.json` (fetched 2026-08-31; PDF byte-hashes pinned in
R23-B0).

## A — arXiv:2602.21611v1 — the direct predecessor
"Structurally Aligned Subtask-Level Memory for Software Engineering Agents" (Shen, Zhang, Sun, Zeng, Yue).
SWE-bench Verified; 4 backbones; **mean +4.7 pp** (Gemini 2.5 Flash +5.6, Pro +6.8, Claude 3.7 +3.9, Claude 4.0
+2.3); 3 shuffled-order runs. **Method fingerprint:**
- Memory = triple **`m=(z,d,e)`**: category `z ∈ {Analyze,Reproduce,Edit,Verify}`, description `d` = objective +
  keywords, abstracted experience `e`.
- Retrieval = **category hard-filter → semantic Top-1, forced** (no threshold, **no abstention**).
- Ablations: Vanilla · Instance-level (ReasoningBank) · Structured-prompt-only (+1.0) · No-category-filter (+1.6) ·
  Raw-trajectory (+1.2).
- **Code NOT released** ("upon acceptance") → R23-R is a **clean-room reimplementation**.

## B — arXiv:2507.23361 SWE-Exp
Experience bank (success+failure), SWE-bench Verified, Claude 4 Sonnet, multi-agent+MCTS, 73.0% Pass@1. **Code
released:** `github.com/YerbaPage/SWE-Exp`. (Comparison/provenance, not the primary method.)

## C — arXiv:2510.04851 LEGOMem
Modular procedural memory, multi-agent workflow, **OfficeBench** (different domain). Comparison only.

Comparison set also logged: ReasoningBank, ExperRepair, Agent Workflow Memory, Reflexion, ExpeL, CodePlan, TRAD,
StructuThink, repository-memory/commit-history retrieval, step-wise thought retrieval.

## Novelty judgment
| candidate contribution | in A? |
|---|---|
| category-level subtask memory `m=(z,d,e)` | **YES — NOT NOVEL** (R23 reproduces it as `AR3`, uses it as the `STAGE` baseline) |
| semantic **operation/precondition/dependency-graph** atoms | **NO** |
| source-atomization × target-query **2×2 factorial** | **NO** |
| **overlap-conditioned** causal analysis (whole-task sim vs subtask overlap) | **NO** (A stratifies by trajectory length only) |
| conditional-efficacy vs natural-stream + **abstention** | **NO** (forced Top-1) |
| **known-wrong-atom** safety | **NO** |

**Result: no collision → PROCEED** (not `R23_NOVELTY_COLLISION_REVIEW`). The category-level subtask memory is
treated as prior work (reproduction/baseline); R23's candidate contributions are the semantic graph atoms, the
source×query factorial, the overlap-conditioned causal analysis, the conditional-efficacy/abstention separation, and
the wrong-atom safety — none tested by A. Per §0 no efficacy is claimed pre-result; all are hypotheses until the
gates run.

## B0 §1 correction — claim boundary
**`NOVELTY SCREEN = PROCEED` ; `NOVELTY CLAIM = NOT YET ESTABLISHED`.** One screening pass does not establish
publication-level novelty; it only found the audited literature does not reveal the complete R23 combination. The
category-level subtask memory of A remains NOT NOVEL (reproduced/baseline); R23's candidate distinctions stay
hypotheses until the gates run.

## B0 §1.1 — third-party non-author implementation
`taeilkim2465/agentic_memory_distillation` @ `2895d10c` (created 2026-06-18, pushed 2026-08-10) —
**`THIRD_PARTY_NONAUTHOR_IMPLEMENTATION`, license NONE**. SASM for AppWorld/BFCL/ToolSandbox; **not** the SWE-bench
reproduction artifact; belongs to another 2026 program; **not** author code for arXiv:2602.21611. Inspect for
interface/omitted-baseline comparison only; no vendoring without a compatible license. Official author-code
availability re-checked before any paid run. (`artifacts/r23/third_party_implementation_audit.json`)
