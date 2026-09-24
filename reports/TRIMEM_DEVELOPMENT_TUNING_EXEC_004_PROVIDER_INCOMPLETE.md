# TriMem V1 D1.3 DEV execution closure

## Endpoint

`TRIMEM_V1_DEV_INCOMPLETE`

The fresh `_004` workflow run reached the protected environment and provider, but failed closed during the first M2-baseline task. Zero of 72 task-arm cells completed, so performance remains `NOT_MEASURED` and no M2 candidate was selected.

## Exact terminal failure

- Run: [33840007588](https://github.com/Scuttie/enterprise-shared-memory-poc/actions/runs/33840007588), attempt 1
- Execution HEAD: `795c589c7da0b815bbe4f6188191fd0165f85649`
- Frozen source HEAD: `ded36427f03b60256305a32266fd0537f3602798`
- Stream/target: `M2-baseline` / `swebench_verified--django__django-16100`
- Logical call: `swebench_verified--django__django-16100:M2:solve:0005`
- Classification: `RESPONSE_INCOMPLETE_MAX_OUTPUT_TOKENS`
- Provider result: HTTP 200, `response.status=incomplete`, `incomplete_details.reason=max_output_tokens`
- Exact model: `gpt-5.4-mini-2026-03-17`

D1.3 observability worked: the response envelope, raw restricted response, exact provider status, incomplete reason, item/content types, hashes, and provider-reported usage were persisted before interpretation. The decomposition call succeeded and produced three semantic subtasks. The failure occurred later at the unchanged 2,048-token solve ceiling; it was not a decomposition-schema failure, refusal, grader failure, or model-identity mismatch.

## Actual accounting for `_004`

| measure | actual |
|---|---:|
| completed task-arm cells | 0 / 72 |
| provider/API/model calls | 6 |
| decomposition calls | 1 |
| solve calls | 5 |
| extraction calls | 0 |
| input tokens | 54,620 |
| cached input tokens | 17,664 |
| output tokens | 4,203 |
| reasoning tokens | 1,485 |
| model cost | $0.0479553 |
| target image pulls | 12 |
| support image pulls | 1 |
| grader containers / official grader runs | 0 / 0 |

Provider status distribution was five `SUCCESS` responses and one `RESPONSE_INCOMPLETE_MAX_OUTPUT_TOKENS`. All usage above is provider-reported; it is not a conservative reservation mislabeled as actual usage.

One bounded process-level resume ran inside the same workflow attempt. It reused the existing terminal journal, made zero additional provider calls, emitted no duplicate request/failure accounting events, and failed closed because the evidence suffix was outside the solve crash window. No GitHub Actions rerun or attempt 2 was created.

## Evidence and cleanup

- Encrypted restricted artifact ID: `9924796142`
- GitHub artifact digest: `sha256:337116f8200d9008f8ee99df9380bb1af7875ecca1508c01f06dd95adbfa5580`
- Ciphertext SHA-256: `8d567e84863b08e4b262829569cf1ae38f6e020ed0fcd81b4d4d0cfc5a9f184e`
- Restricted stream audit: 134 files, 9,671,681 bytes, inventory SHA-256 `96b1b00f90a5d28fedbb547b31458e8f4ecbf86f8d28d4ecfc180f30c9e74793`
- Workflow-log ZIP SHA-256: `09876ba5ab16a30f73dd3161a187fa3244f3194a1acb59f99a4d049049a2df9a`
- Exact secret matches in all 35 log members: API key 0, approval B64 0, evidence passphrase 0
- Environment secrets after cleanup: 0
- Repository runners after cleanup: 0
- Pending deployments after completion: 0

The encrypted evidence was audited as a stream; plaintext evidence was not extracted to disk. The API key was scoped only to this authorized benchmark execution and was neither printed nor committed.

## Authority boundary

Runs `33788493773` and `33840007588` were not rerun. `_005`, HELDOUT, ablations, model/target changes, merge, tag, and release were not performed. This terminal failure closes the one-time `_004` authority; another execution requires new explicit authorization.

The machine-readable evidence receipt is `artifacts/trimem_v1/development_tuning_exec/exec-004/provider-incomplete-max-output-tokens-receipt.json`.
