# R22 — SWE-Exp license audit

- Repository: `cslsolow/SWE-Exp`
- Pinned commit: `6b5c92ed0a6fc14de972c5d499673e2c4f03ce33` (remote HEAD at audit == pinned commit)
- Root `LICENSE`: **Apache License 2.0** (sha256 `c6bc7016…1bdecc`).
- Paper: arXiv:2507.23361.

## Verdict
**SWE-Exp code is Apache-2.0** — usable as a positive-reference for reproduction under its terms (attribution +
NOTICE). It was cloned into the sibling `third_party_r22/swe-exp` workspace and is **not** copied into
`src/enterprise_memory` (per §1). No SWE-Exp file is vendored into this repository.

## Transitive dependencies (from `requirements.txt`) — licenses to respect at reproduction time
- `moatless-tree-search==0.0.4`, `moatless-testbeds` (git pin `91938b8…`) — the SWE-Search engine + grader.
- `instructor==1.9.0`, `litellm==1.72.9`, `sentencepiece==0.2.0`, and the HF model
  `intfloat/multilingual-e5-large-instruct`.
These are pulled only into the isolated reproduction environment, never vendored here.

## Note
This audit covers redistribution/reuse rights only. It is **not** a claim of reproduction; running SWE-Exp requires
paid model credentials + Docker grading (see `reports/R22_BLOCKER.md`).
