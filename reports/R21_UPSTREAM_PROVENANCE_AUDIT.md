# R21 — MemGovern Upstream Provenance Audit (Stage 0 / R21-A)

Isolated research checkout (sibling workspace, **not** committed to this repo; `GIT_LFS_SKIP_SMUDGE=1` so no
upstream data was pulled). No live model call. This is the permitted audit ceiling while
`UPSTREAM_RESEARCH_USE_APPROVED` is unset (§3).

## Repository
- Repo: `github.com/QuantaAlpha/MemGovern`, commit **`a8456580a4a6ea8de04755e958875cd549f43845`** (matches spec pin).
- **License: NONE** — no `LICENSE`/`COPYING` file in the tree; README shows an MIT *badge* only. GitHub API
  `license.spdx_id = NONE`. → **REPRODUCTION_BLOCKED** for vendoring/redistribution (§3, §15).
- SWE-Agent: `sweagent @ git+princeton-nlp/SWE-agent` (upstream); repo ships `config/sweagent_0_7/*` (v0.7).
- Deps: `chromadb>=0.5.0`, `openai>=1.0.0`, `sentence-transformers>=2.2.0`.

## Experience bank (LFS — real objects, NOT pulled)
| artifact | size | oid |
| --- | --- | --- |
| `experience_data.json` (135K cards) | 158.2 MB | `sha256:c5bcc6e2…` |
| `chroma_db_experience/chroma.sqlite3` | 220.4 MB | `sha256:1450b7a0…` |
Bank dir `agentic_exp_data_1220_13w_DSnewPrompt` (built with a DeepSeek prompt). LFS pointers are valid → the
objects exist on GitHub LFS (not empty pointers). Not downloaded (respecting the approval gate).

## Agentic search machinery (genuine, not static injection)
`tools/experience_server.py` + `tools/agentic_rag_server.py`; tools `exp_search`, `exp_read`, `exp_read_filtered`.
The main config instructs the agent to form a query, **decompose**, **rewrite**, run **follow-up** searches, then
selectively `exp_read` and map to the current repo — i.e. real in-trajectory agentic retrieval (distinct from
R19/R20's start-of-run static top-k injection).

## Published result table (README)
| Model | SWE-Agent | MemGovern | Δ |
| --- | --- | --- | --- |
| GPT-4o | 23.2% | 32.6% | +9.4 |
| GPT-4o-Mini | 14.0% | 17.2% | +3.2 |

## Author trajectory artifacts (LFS — enable Stage A regrade)
`gpt4o_default` 119.6 MB · `gpt4o_agentic` 138.9 MB · `gpt4o_mini_default` 37.0 MB · `gpt4o_mini_agentic` 487.6 MB
(+ `gemini3_pro`, a `gpt-5 dsv31t` `.rar`). These make **author-artifact recomputation (Stage A)** possible with
the official grader and **no model calls**.

## Model-snapshot provenance gap
The exact **GPT-4o config/snapshot/temperature** behind the +9.4 row is **not committed** as a config — only
Claude/DeepSeek configs are shipped; GPT-4o was run via CLI model override. Snapshot/temperature are recoverable
only from *inside* the trajectory tarball metadata. → any live GPT-4o rerun risks `MODEL_SNAPSHOT_UNAVAILABLE` /
`MODEL_DRIFT_REPLICATION` labeling (§6).

## Endpoint determination (honest)
- **Provenance/artifact/license audit: COMPLETE.**
- **Stage A (author artifact recompute): PERMITTED + FEASIBLE** — public-grader audit of committed trajectories;
  no approval var needed; next actionable step.
- **Stage B/C/D (independent live reproduction / component swap / company bridge): BLOCKED** —
  `UPSTREAM_RESEARCH_USE_APPROVED` unset (§3), `MAX_LIVE_REPRO_BUDGET_USD` unset (§6.2), license NONE (no
  vendoring), and the primary GPT-4o snapshot is not pinned.

## Verdict lines
```
AUTHOR_ARTIFACT               = PENDING_STAGE_A (artifacts available; regrade not yet run)
INDEPENDENT_EXACT_REPRODUCTION = BLOCKED (approval + budget + GPT-4o snapshot pin required)
COMPANY_NATIVE_BRIDGE          = NOT_RUN (gated on an established exact reproduction)
```
