# P5.1 — Frozen executable coding-bank audit

**Scope:** §5 (server-owned task policy + RepositoryTaskAdapter) and §6 (frozen executable coding bank).
This is a synthetic engineering/research instrument, **not** a claim of broad real-world coding generality.

## Instrument design
Four domains — `internal_api`, `cache`, `config`, `schema`. Each **family** binds a single reusable local
convention (a domain-specific integer constant `C` that differs from the common prior default `D`) across
three disjoint tasks:
- `own_source` — solved on behalf of the eventual target user (feeds the M1 private arm);
- `cross_source` — owned by a different source user (feeds M2/M3/M4);
- `target` — assigned to the target user.

All three share the technique but use different function names, bases, files, and tests. Each task is a
bounded edit of a frozen-signature function. The **public test is incomplete** (it pins only a case that does
not reveal `C`); the **hidden test enforces the convention** and never ships to the model. Target output
values differ from source output values (three distinct bases per family). The memory fact carries `C` (the
reusable convention), never the target's answer.

Generator: `benchmarks/p5_1_static/` (`schema.py`, `families.py`, `fixtures.py`, `solver.py`, `audit.py`).
Fully deterministic (SHA-256-derived constants/names; no RNG, no clock) so regeneration is bit-identical.
Generator version `p5.1-static/1.0.0`.

## Audit result (all green)
| Check | calibration (16 fam / 48 tasks) | main (32 fam / 96 tasks) |
|-------|--------------------------------|--------------------------|
| source/target task overlap | 0 | 0 |
| source/target repository overlap | 0 | 0 |
| target-answer leakage | 0 | 0 |
| hidden-test leakage | 0 | 0 |
| gold-solver hidden pass rate | 100% | 100% |
| wrong-world hidden fail (public pass) | 100% | 100% |
| exact-signature coverage | 100% | 100% |
| distinct output bases per family | 16/16 | 32/32 |
| deterministic regeneration | stable hash | stable hash |
| calibration ∩ main (families, tasks) | 0, 0 | — |

The gold solver passes every hidden test; a plausible un-memorised "wrong-world" solution (using the common
prior default `D`) passes the incomplete public test but fails every hidden test — establishing that the tasks
genuinely require the convention and that memory (which carries `C`) is the lever.

## Server-owned task policy (§5, migration 0011)
`task_execution_policies` gains `family_id`, `domain`, `repository_fixture_id`, `target_path`,
`public_test_entry`, `hidden_test_manifest_id`, `runtime`, `timeout_seconds`, `allowed_import_changes`,
`allowed_new_files`, `source_world_id`, `target_world_id`, `policy_version`. The client may still specify only
`task_id` + desired ref; all edit/test information stays server-owned. `/v1/solve` now uses the policy's
`target_path`.

## RepositoryTaskAdapter (§5)
`service/task_adapter.py`:
- `RepositoryTaskAdapter` (ABC): `resolve_commit`/`resolve_tree`/`installation_for`, `snapshot` (model-visible,
  no hidden test), `hidden_test` (server-only grading), `snapshot_hash`.
- `FrozenExecutableBenchmarkAdapter` — resolves a `repository_fixture_id` to a frozen task; the snapshot ships
  only stub + incomplete public test (asserts the hidden test is absent); the hidden test is served separately.
- `CompanyRepositoryAdapter` — complete contract, **fails closed** (`CompanyAdapterNotConfigured`) until an
  approved company configuration is provided, so it can never silently reach a live company repository.

## Tests
`tests/unit/test_benchmark_bank.py` (runs in `ci`): generator audit ok; counts; deterministic regeneration;
adapter snapshot excludes the hidden test; company adapter fails closed. **5/5 pass.**
