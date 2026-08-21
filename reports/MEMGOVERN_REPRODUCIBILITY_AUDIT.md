# MemGovern Reproducibility & License Audit (P6/R19 §3.1)

**Reference:** MemGovern — *Enhancing Code Agents through Learning from Governed Human Experiences.*
arXiv `2601.06789` (v2 seen) · repo `github.com/QuantaAlpha/MemGovern` · default branch `main`.
**Reported headline:** +4.65% resolution on SWE-bench Verified using 135K governed experience cards.
This is the "published positive SWE-memory system" that RQ1 asks whether we can reproduce.

## License status — UNRESOLVED → `REPRODUCTION_BLOCKED` (for vendoring)
- The README displays an **MIT badge**, but the repository has **no LICENSE file**.
- Per §3.1, an MIT badge is **not** a legal conclusion. Absent an actual license grant, the default is
  all-rights-reserved. We therefore treat MemGovern source and data as **not redistributable**.
- The repo **bundles data via Git LFS**: `data/agentic_exp_data_*/experience_data.json`,
  `data/*/chroma_db_experience/`, and per-model `trajectories/*.tar.gz`. None of this may enter the company
  package or `src/enterprise_memory`.

## Labels (used precisely)
| Path | Label | Rationale |
| --- | --- | --- |
| Vendoring MemGovern code/data into the product | **REPRODUCTION_BLOCKED** | license unresolved + LFS data non-redistributable |
| Exact end-to-end reproduction of their numbers | **REPRODUCTION_BLOCKED (external, isolated)** | may run only in a secret-gated, throwaway checkout that is never packaged |
| Our native search/browse/router system | **BEHAVIORAL_REIMPLEMENTATION** | clean-room; auditable; distributable under this repo's license |

## What we may and may not do
**Allowed:** read the paper/README; audit behavior; document the experience-card schema and experience-server
tool contract as an *interface* to be matched; build a clean-room behavioral reimplementation on our existing
PostgreSQL/Qdrant service; run documented API/schema compatibility tests.
**Not allowed:** copy any implementation file into `src/enterprise_memory`; bundle their experience DB or chroma
store; distribute their trajectories; call our clean-room build an *exact* reproduction; restate the MIT badge as
a license.

## Architecture we will match behaviorally (not copy)
Two-process design: an **Experience Server** (vector search + experience lookup exposing search/read tools) and
**SWE-agent** driven by a config that calls those tools. Our native equivalent: candidate generation from the
Qdrant/Mem0 index over neutral projections, `search_experiences` / `browse_experience` tools (metadata-first, then
gated execution view), canonical reload from PostgreSQL before any use.

## Interface compatibility to document (clean-room)
- Experience-card fields (symptom/root-cause/repair-strategy/scope/validation) → our `ExperienceCardVersion` (§5).
- Search-tool contract (query → candidate summaries) → `search_experiences` metadata-only response (§7).
- Read/browse-tool contract (id → full card) → `browse_experience` gated execution view (§7).

## Reproduction endpoint status
`REFERENCE_EXTERNAL` exact reproduction of MemGovern's +4.65% is **externally blocked** by license (Endpoint A,
§0). This does **not** stop the native clean-room company build. The literature *comparison* is carried by our
`A4 AGENTIC_REFERENCE_MEMORY` arm (§10.3), which behaviorally matches the ungated agentic-memory system on our own
frozen manifest, honestly labeled as a reimplementation — never as MemGovern's exact numbers.

## Pins to finalize in the secret-gated repro job (not in the package)
Paper revision, repo commit, SWE-agent commit, experience-card schema hash, server protocol, embedding model/index
format, and task manifest are recorded as `UNVERIFIED_PIN_IN_SECRET_GATED_REPRO_JOB` in
`THIRD_PARTY_RESEARCH_REFERENCES.json` and pinned only inside the isolated reproduction environment.
