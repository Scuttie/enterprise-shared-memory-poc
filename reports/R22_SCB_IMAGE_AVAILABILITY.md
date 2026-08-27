# R22-P0.8 §4 — Official Docker image availability

Artifact: `artifacts/r22/scb_image_manifest.json`
Image repository: **`jiayuanz3/swecontextbench`** (Docker Hub). Tag derivation (upstream
`run_evaluation.py:2954`): `instance_id.replace("__", ".").lower()`.

## Method (no `docker` daemon required)
Docker CLI is unavailable in the credential-free environment, so tags were resolved via the **Docker Registry v2
API** (anonymous pull token): `GET /v2/jiayuanz3/swecontextbench/manifests/<tag>` with an OCI-index / manifest-list
`Accept`. The immutable digest is `sha256` of the returned manifest bytes (equal to `Docker-Content-Digest`);
`linux/amd64` is confirmed from the index `platforms`; size is summed from the amd64 sub-manifest layers+config.
The repository advertises **358 tags**, all in the `<owner>.<repo>-<num>` scheme.

## Result — 40/40
| check | result |
|---|---|
| official case JSON | 40/40 |
| Docker tag manifest (HTTP 200) | **40/40** |
| `linux/amd64` present | **40/40** |
| immutable digest recorded | **40/40** |
| missing tags | **0** |

Each index also carries an `unknown/unknown` entry — the standard buildkit attestation (provenance/SBOM) manifest,
not a platform.

### Sample immutable digests + amd64 image sizes
| instance | tag | digest (23) | size |
|---|---|---|---|
| apache__lucene-13388 | apache.lucene-13388 | `sha256:e0e7f0b130132e8c` | ~2393 MB |
| astropy__astropy-14500 | astropy.astropy-14500 | `sha256:420915045f16dd2c` | ~1218 MB |
| sympy__sympy-18196 | sympy.sympy-18196 | `sha256:b0d921c3245c2403` | ~1218 MB |

Full 40-target digest table: `artifacts/r22/scb_image_manifest.json`.

## Pull policy
Manifests were inspected only (no layer pull) in this credential-free audit. During an approved smoke, the 12 P1
images are pulled one at a time (sharded per target) and removed after each target
(`ci-r22-scb-grader-smoke.yml`). `R22_OFFICIAL_SCB_IMAGE_TECHNICAL_BLOCK` does **not** apply — 0 missing tags.
Absence was **not** inferred from the enriched `SWE-bench/*` datasets (P0.7's error).
