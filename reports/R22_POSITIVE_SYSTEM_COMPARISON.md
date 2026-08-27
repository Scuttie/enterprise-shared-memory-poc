# R22 — positive-system comparison (§3.5)

The SWE-Exp row is verified from the pinned code (`artifacts/r22/upstream/swe_exp_lock.json`). ExpeRepair (MIT) and
the subtask-memory paper (arXiv:2602.21611) rows are from their publications; a full structural audit of those two
is the next **credential-free** step and does not change R22's current terminus (paid gate — see
`reports/R22_BLOCKER.md`). Per §3.5, unlicensed upstream code is not copied/vendored; only paper-level clean-room
design is used for those.

| System | memory unit | retrieval timing | selector | agent architecture | claimed lift |
|---|---|---|---|---|---|
| SWE-Exp (verified from code) | success/failure "perspective" + "modify" experience | at MCTS decision, `--experience` | e5-large-instruct cosine + LLM `select_perspective(k)` | MCTS SWE-Search + Instructor/ExpAgent dual agent | published 35.4% → 41.6% (author report) |
| ExpeRepair (published) | episodic + semantic | test/patch stages | dynamic prompt composition | test agent + patch agent | published |
| Subtask memory (published) | functional subtask | stage-aligned | stage-specific | repository agent | published |
| v0.3 current (this repo) | whole issue / canonical card | mostly pre-solve | RuleRouter (USE/ABSTAIN) | single solve worker | **R14–R20 null** |
| R22 (to test) | stage transition (COMPREHEND/REPRODUCE/LOCALIZE/EDIT/VERIFY) | after observation, per stage | deterministic hard gate + utility rerank (RANK-D / RANK-L) | same reader | **to test (paid-gated)** |

## Reading
SWE-Exp is the positive reference whose information structure R22 reproduces (dual encode/select experience over a
search agent). R22's hypothesis is that aligning that memory to the *current subtask stage* and retrieving *after
observation* (vs v0.3's whole-issue pre-solve injection, which was null in R14–R20) is what could move the needle —
but this is stated as a hypothesis to be tested behind controls (shuffled + compute), not a claim.
