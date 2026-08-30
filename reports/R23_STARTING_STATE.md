# R23-F0 — Starting state (live-verified)

New experiment **`REALBENCH_R23_SEMANTIC_SUBTASK_GRAPH_V1`** (R23-SSGM), on a **new worktree/branch off the verified
live R22 head**. R22 is referenced as a coarse stage-level baseline + provenance only; it is **not continued or
mutated**.

| item | value |
|---|---|
| R22 branch live head | `289413dcf737d85213eb15233e80a4daf5bf952b` (descendant of `50ddb46` ✓) |
| new branch | `codex/r23-semantic-subtask-graph-memory` (branch point = R22 live head) |
| new worktree | `C:/Users/jewon/esm-r23` (clean checkout) |
| PR #16 | OPEN / DRAFT, head `codex/r22-stage-aligned-memory`, base `main` — **unchanged** |
| main | `ce10ab49586db7a859fbe5cca93051b93f9f5b55` — **unchanged** |
| v0.3.0-rc1 tag object | `c1741c6d635bc97e470ea553753c143888a0c0be` — **unchanged** |
| R22 seals | main `dd79f3d2` · oracle `100d7caa` · paid-v2 `d0d98e51` — frozen |
| R1–R21 | frozen |

Lock: `artifacts/r23/parent_state_lock.json`.

## New PR (to be created)
Draft; **base = `codex/r22-stage-aligned-memory`** (NOT main), so only R23 changes are shown. No PR to main; no
merge/tag/release.

## Git safety (honored)
No `reset --hard` / `clean` / `restore .` / `checkout -- .` / force-push / results-rewriting rebase / R22-manifest
replacement / R22-results renaming. (A timed-out `git worktree add` left a stale index.lock + partial checkout; it
was cleared and the checkout completed to `289413d` — no committed R22 artifact was touched.) The R22
gradeability/campaign work is **not** silently continued.

paid/model API calls = 0.
