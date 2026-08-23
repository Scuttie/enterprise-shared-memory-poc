# SWE-Exp Reuse Audit (P6/R19 §3.2)

**Reference:** SWE-Exp — *Experience-Driven Software Issue Resolution.* arXiv `2507.23361` ·
repo `github.com/YerbaPage/SWE-Exp` · default branch `main` · **License: Apache-2.0** (repo metadata).

## License — Apache-2.0 (reuse conditionally allowed)
Apache-2.0 permits reuse **only after** the §3.2 conditions are met. Until then, SWE-Exp is used as a **conceptual
comparator**, and **no files are copied**.

### Reuse preconditions (all must hold before any file-level copy)
1. **File-level attribution audit** — list every reused file with its upstream path + commit.
2. **NOTICE preservation** — carry the upstream `NOTICE`/`LICENSE` and add attributions to our `NOTICE`.
3. **No incompatible transitive code** — SWE-Exp builds on the **moatless** framework; the moatless license and
   all transitive dependency licenses must be verified Apache-compatible before copying anything that pulls them
   in. (Blocker until audited.)
4. **Document exact reused files** — record in `THIRD_PARTY_RESEARCH_REFERENCES.json`.

## Current decision — `NO_FILES_REUSED_YET`
We adopt SWE-Exp's **concepts** (an experience bank of verified resolutions; trajectory-derived experience;
retrieval-then-reuse), reimplemented natively (`BEHAVIORAL_REIMPLEMENTATION`) on our PostgreSQL/Qdrant service.
Relevant upstream modules observed for behavior only: `moatless/experience/exp_agent/exp_agent.py` (experience
generation), `select_agent.py` (retrieval), `extract_verified_issue_types_batch.py` (issue typing),
`search_tree.py` (trajectory extraction/reuse). None are vendored.

## Data
SWE-Exp does **not** appear to bundle benchmark gold patches or third-party datasets (it generates trajectories
from open-source repos). Even so, we never ingest target gold/tests into memory (§5 hard constraint), independent
of upstream.

## If reuse is later chosen
Open a dedicated commit that (a) adds the file(s) verbatim under `third_party/swe_exp/` with the Apache-2.0 header
intact, (b) updates `NOTICE`, (c) records exact files+commit in the references JSON, (d) confirms no GPL/AGPL
transitive pull-in. Until that commit exists, `ci-literature-audit` asserts zero SWE-Exp/moatless files under
`src/`.
