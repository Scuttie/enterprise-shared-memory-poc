# OSS v0.3 — License & Rights Audit (§2)

Target license: **Apache-2.0** (SPDX: `Apache-2.0`), as directed by the repository owner.

## Code-level provenance (agent-verifiable) — CLEAN
- `src/enterprise_memory/**`: clean-room; no `QuantaAlpha/MemGovern` or `moatless.experience` markers
  (enforced by `ci-literature-audit`). All product code is the project's own.
- No upstream MemGovern source/data or Chroma DB in this branch (R21 upstream work is isolated in PR #4).
- No benchmark **gold solution code** or **hidden tests** committed:
  - `artifacts/bigcode_r2/gold_bank.json` = a DERIVED facts manifest (apis/imports/operations/entry_point per
    task), 300 entries, `embeds canonical gold solution code: False` — abstracted metadata, not gold code.
  - `artifacts/actionable_memory_r3/gold_bank_manifest.json` = a manifest (bank_type/benchmark/facts/hashes).
- 80 `artifacts/openai_reader_r12/repo_d0/*.json.patch` = **model-generated** diffs (our R12 agent outputs vs
  public OSS repos), not benchmark gold. Retained as research artifacts; **excluded from the product wheel** (§3).
- Dependencies (`chromadb`, `fastapi`, `sqlalchemy`, `sentence-transformers`, …) retain their own licenses,
  recorded in `THIRD_PARTY_NOTICES.md`.

## Owner responsibility (NOT agent-verifiable)
The owner's legal right to relicense this repository to Apache-2.0 — including any institutional, grant, or
co-author obligations — is the **owner's decision and responsibility**. This audit covers only code-level
provenance. The owner directed Apache-2.0; the release PR is prepared as a DRAFT and is not merged/tagged.

## Verdict
Code-level provenance is CLEAN for an Apache-2.0 release of the project's own code, with benchmark-derived data
and research artifacts scoped out of the licensed product (see `docs/OSS_SCOPE_AND_DATA_POLICY.md`).
**Not `OSS_LICENSE_BLOCKED`.** Status: `OSS_RELEASE_PR_READY` pending the owner's merge decision.
