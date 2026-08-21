# Literature Memory-System Audit (P6/R19 §3)

Three external references frame the milestone. This is the overview; per-reference detail is in
`MEMGOVERN_REPRODUCIBILITY_AUDIT.md`, `SWE_EXP_REUSE_AUDIT.md`, and machine-readable pins/labels in
`THIRD_PARTY_RESEARCH_REFERENCES.json`. `ci-literature-audit` enforces the vendoring rules.

| Reference | arXiv | Repo | License | Label | Reused in product? |
| --- | --- | --- | --- | --- | --- |
| **MemGovern** | 2601.06789 | QuantaAlpha/MemGovern | **Unresolved** (MIT badge, no LICENSE file) | `REPRODUCTION_BLOCKED` | **No** — clean-room behavioral only |
| **SWE-Exp** | 2507.23361 | YerbaPage/SWE-Exp | Apache-2.0 | `BEHAVIORAL_REIMPLEMENTATION` | **No files yet** — conceptual comparator |
| Structural subtask memory | (unverified) | (unverified) | (unverified) | `CONCEPTUAL_COMPARATOR` | Concept only (subtask taxonomy) |

## RQ1 framing
MemGovern is the published **positive** system (+4.65% on SWE-bench Verified, 135K governed cards). Because its
license is unresolved and it bundles a non-redistributable experience DB + trajectories, **exact reproduction is
externally BLOCKED** for anything shippable (Endpoint A). We therefore:
- run exact external reproduction, if at all, only in an **isolated secret-gated job** never part of the package;
- carry the literature comparison inside the product via a **clean-room** ungated agentic-memory arm
  (`A4`, §10.3), honestly labeled a reimplementation — never presented as MemGovern's numbers.

## Clean-room reproduction specification (native, distributable)
`NATIVE_CLEAN_ROOM` reproduces the *behavior*, not the code, on our existing enterprise service:

1. **Experience cards** — `ExperienceCardVersion` (§5) with symptom/root-cause/fault-localization/repair-strategy/
   scope/validation fields, compiled from verified public issue+PR+patch evidence (§6). Canonical in PostgreSQL.
2. **Neutral retrieval projection** — metadata-only vectors in Qdrant/Mem0 (§6.3); no patch, identity, or verdict.
3. **Experience-server-equivalent tools** — `search_experiences` (metadata) → `browse_experience` (gated execution
   view) → `report_memory_outcome`, over HTTP and MCP (§7, §11).
4. **Agentic search policy** — subtask → query → candidates → (router) → gated browse → injection (§7).
5. **A4 = ungated reference** (matches the literature selection policy); **A5 = utility-gated** (our method).

No MemGovern/SWE-Exp source or data is copied. Compatibility with their *interfaces* (card fields, search/read
tool shapes) is documented as behavioral tests, not code reuse.

## License-ambiguity does not block the product
Per §0/§3, external-code license ambiguity blocks only the external exact-reproduction path. The clean-room native
build, company handoff, docs, demo, and packaging proceed regardless.

## Provenance enforcement (`ci-literature-audit`)
`scripts/check_literature_provenance.py` fails CI if: the references JSON is missing/mislabeled; MemGovern is not
`REPRODUCTION_BLOCKED`; any bundled upstream data artifact is committed (`chroma_db_experience`,
`experience_data.json`, `trajectories/*.tar.gz`); or any `src/` file carries an upstream provenance marker without
a recorded, license-cleared reuse entry.
