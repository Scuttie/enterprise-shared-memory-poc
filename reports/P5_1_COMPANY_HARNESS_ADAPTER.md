# P5.1 — Company Claude-Code / GLM harness adapter

**Scope:** §10 (company harness boundary) + §21 (live canary). We do **not** assume the company model is
literally "GLM-5.3"; the exact identity comes from a required `CompanyManifest`.

## Boundary
`service/company_harness.py` — `CompanyHarnessClient.run(payload) -> result`, usable as the `harness` for
`ExternalHarnessExecutionBackend`.

**Request may contain only** logical_request_id, immutable repository reference, task instruction, server-owned
edit policy, governed memory views, allowed public tool interface, output-format requirements.
**Request must not contain** an OIDC/Git/DB/MinIO/Qdrant credential, hidden tests, another user's raw private
trace, or the server-side final verdict. `CompanyHarnessRequest.as_dict()` walks the whole request and raises
`ForbiddenHarnessField` if any forbidden key appears (checked BEFORE dispatch). The transport reads any API key
from an env var named by config — never from the request payload.

**Result** carries patch, harness/model identity, sanitized tool-call transcript, usage, latency, optional
public-test evidence, and a raw-response reference. The service remains responsible for repository
authorization, private/shared memory validation, final patch validation, hidden tests, sandbox verdict, and
outcome persistence.

## Manifest (required, validated)
`CompanyManifest` requires harness_name/version, model_id/revision, serving_protocol, endpoint,
context_window, max_output_tokens, tool_schema_hash, repository_mount_mode, sandbox_test_ownership (**must be
`service`** — the service owns the sandbox/hidden tests), streaming, timeout_seconds, build_id. `validate()`
fails closed on any missing field, an unknown protocol, harness-owned sandbox, or non-positive limits.

## Serving protocols (config adapters)
Three pluggable transports, selected by the manifest — Anthropic-compatible HTTP (`/v1/messages`),
OpenAI-compatible HTTP (`/chat/completions`, which also fits an OpenAI-style GLM or Solar gateway), and a
generic internal JSON-RPC. We do not guess which the company uses.

## Live canary (§21)
`canary_status(manifest, endpoint, secret_env)` returns `READY` only when an exact valid manifest, an approved
endpoint, and an approved secret mechanism (env var present) are all supplied; otherwise
`PENDING_CONFIGURATION`. No result is ever fabricated and the model is never guessed to be GLM-5.3.

**Current status: `COMPANY_CANARY = PENDING_CONFIGURATION`** — no company manifest/endpoint/secret supplied.

## CI (credential-free)
`ci-company-harness` runs `tests/company_harness` against a **local fake harness HTTP server** only — no
company endpoint, no credentials. Tests: all three protocols return a patch through the same governed
contract; forbidden fields rejected; manifest validation (incompleteness + harness-owned sandbox + unknown
protocol); canary PENDING→READY only when fully configured; and the adapter drives
`ExternalHarnessExecutionBackend` end to end. **7/7 pass.**

## Reproducibility pinning (§17)
The `ci-e2e` MinIO image is now pinned by immutable digest
(`minio/minio@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e`), alongside the
already digest-pinned PostgreSQL and Qdrant images.
