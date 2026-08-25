# R22-P0.8 §2 — Official SWE-ContextBench evaluator audit

Upstream: **`jiayuanz3/SWEContextBench`** @ pinned commit **`31bb04155f52b184bf31b220e3cff0607ac9c953`**
Lock artifact: `artifacts/r22/scb_official_evaluator_lock.json`

## The benchmark ships its own evaluator (this is what P0.7 missed)
At the pinned commit the repo root contains: `README.md`, `evaluation.sh`, `environment.yml`, `cases/`,
`swebench_memory/`, `predictions/`, `assets/`. Evaluation is driven by `evaluation.sh` →
`swebench_memory.harness.combine_instances` (builds the combined dataset from `cases/<subset>/` + predictions) →
`swebench_memory.harness.run_evaluation`, pulling `jiayuanz3/swecontextbench:base` and the per-instance images.

## Pinned file hashes (sha256 / git blob / bytes)
| path | sha256 (16) | git blob (12) | bytes |
|---|---|---|---|
| README.md | `6bd3efdd5b7407f2` | `351e0cc71f37` | 2191 |
| evaluation.sh | `4382682a3a387c93` | `0c443d983ac9` | 2744 |
| environment.yml | `d052a2c1bc14cded` | `9375f421ca59` | 224174 |
| swebench_memory/harness/run_evaluation.py | `e6b29452302df417` | `f97c4dc737c8` | 207603 |
| swebench_memory/harness/combine_instances.py | `93f6c83c54979bfa` | `6dfb2b95bfdf` | 4301 |
| swebench_memory/harness/build_instance.py | `e45c2a7e8b5cfd3c` | `7a38572eac15` | 57232 |
| swebench_memory/harness/build_base.py | `088ee24d1e53b286` | `0346a249c4eb` | 3119 |
| swebench_memory/__init__.py | `d70645eb15bd110b` | `a0b8641c21d5` | 305 |

Tree SHAs: `cases/` = `b4a06fef2a00ba8852b84df6c8a12e7d42ff8ecd`,
`swebench_memory/` = `d9d3910b9d52b2511fe8a975f31b047b7d6e9bd9`.

## Image-tag derivation (verified in code, not assumed)
`swebench_memory/harness/run_evaluation.py:2954` (also `:3345`):
```python
HARDENED_IMAGE_REPOSITORY = "jiayuanz3/swecontextbench"          # :35
image_tag = f"{HARDENED_IMAGE_REPOSITORY}:{instance_id.replace('__', '.').lower()}"
```
e.g. `astropy__astropy-14500` → `jiayuanz3/swecontextbench:astropy.astropy-14500`. (The `_safe_docker_component`
`__`→`_` mapping at `:41` is for container/temporary-image names, not the pull tag.)

## Official grade command
```
python -m swebench_memory.harness.run_evaluation \
    --dataset_name <combined-or-case.json> --predictions_path <preds.json> --run_id <id>
```
Report → `<run_id>.json` (`resolved_ids` / `unresolved_ids` + per-instance results); logs →
`logs/run_evaluation/<run_id>/`.

## License (recorded separately — no legal conclusion claimed)
- **Dataset license:** MIT, per the released dataset metadata.
- **Evaluation-code license:** **NO EXPLICIT LICENSE FILE DETECTED.** `LICENSE`, `LICENSE.md`, `LICENSE.txt` all
  return 404 at the pinned commit, and `README.md` contains no license statement. Redistribution rights unresolved.

Handling rules (followed): upstream evaluator source is **not** copied into this repo, wheel, sdist, Docker image,
or release; it is **not** modified/redistributed; it is used only via an **ephemeral pinned checkout** at runtime
(`experiments/r22/runtime/scb_official_grader.py`), gated on explicit execution approval. See
`reports/R22_UPSTREAM_RIGHTS_STATUS.md`.
