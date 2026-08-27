# R22-P0.9 §2 — Ruff forensic freeze (3 targets)

Manifest: `artifacts/r22_p09/ruff_forensic_manifest.json`. Pinned evaluator commit
`31bb04155f52b184bf31b220e3cff0607ac9c953`. Source campaign run `32863011986` @ `6f55b83`. **No diagnostic execution
has run** — this is a static freeze of the existing campaign evidence + the pinned official case/image.

| role | instance | subset | case sha256 | gold patch sha256 | test patch sha256 | image digest | campaign gold |
|---|---|---|---|---|---|---|---|
| F1 | astral-sh__ruff-15725 | Multilingual | `724af16e168b0b0e…` | `a80ddbb0c6d2bb7b…` | `513b8a07629e0e53…` | `sha256:6045d9611a478df9…` | UNRESOLVED |
| F2 | astral-sh__ruff-16445 | Multilingual | `b159f1a2fd336861…` | `7d9a01ce0b0aa6a0…` | `5a897c51f8b2d6e5…` | `sha256:f05058578e9bbd8a…` | UNRESOLVED |
| POS | astral-sh__ruff-15997 | Multilingual | `29eb0637bfe0cc77…` | `6e8d1e901dd849b2…` | `f223d1e15ff954ff…` | `sha256:4ff6fbb327893411…` | RESOLVED |

Test configuration (from the frozen run logs):
- F1: FAIL_TO_PASS **1**, PASS_TO_PASS 35 → "Collected 0 test results".
- F2: FAIL_TO_PASS **98**, PASS_TO_PASS 2 → "Collected 0 test results".
- POS: FAIL_TO_PASS **1**, PASS_TO_PASS 8 → "Collected 9 test results" → resolved.

(Note: F1 has only 1 FAIL_TO_PASS selector yet still collects 0 — so the failure is **not** a function of selector
count.) Frozen per target: case JSON path/hash, repo, base_commit, issue hash, gold/test patch hashes, ordered
FAIL_TO_PASS/PASS_TO_PASS canonical hashes, image tag+digest, evaluator commit + file/tree hashes, original shard
summary hash, and the gold+noop evidence hashes (eval.sh, test_output.txt, run_instance.log, report.json,
patch.diff). No diagnostic execution precedes this manifest.
