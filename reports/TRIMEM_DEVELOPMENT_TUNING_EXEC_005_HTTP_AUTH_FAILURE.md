# TriMem-Coder V1 D1.4 DEV `_005` execution closure

## Endpoint

`TRIMEM_V1_DEV_INCOMPLETE`

The fresh `_005` attempt reached the protected environment, all exact-head gates,
and all 13 digest-locked benchmark images. It then failed closed on the first
decomposition request with `HTTP_AUTH_ERROR`. Zero of 72 task-arm cells completed,
so performance is `NOT_MEASURED` and no M2 candidate was selected.

## Exact terminal failure

- Run: [33859839836](https://github.com/Scuttie/enterprise-shared-memory-poc/actions/runs/33859839836), attempt 1
- Execution HEAD: `57db1a21fca3b036a64629c439ca196fb1606638`
- Frozen source HEAD: `5e80da790db0aa5b7cf1a8ce29020fedad7f6254`
- Stream/target: `M2-baseline` / `swebench_verified--django__django-16100`
- Logical call: `swebench_verified--django__django-16100:M2:decompose:0001`
- Classification: `HTTP_AUTH_ERROR` (HTTP 401/403 family)
- Exact model request: `gpt-5.4-mini-2026-03-17`

The credential supplied to the protected run did not authenticate. Public
evidence cannot distinguish malformed, revoked, unauthorized, or otherwise
invalid credential material, so the label is intentionally no narrower than
`HTTP_AUTH_ERROR`. This is not a model-capability, memory-controller, retrieval,
solve-tool, or official-grader result.

## `_005` accounting

| measure | result |
|---|---:|
| completed task-arm cells | 0 / 72 |
| external provider requests | 1 |
| fail-closed ledger model calls | 1 |
| decomposition / solve / extraction | 1 / 0 / 0 |
| provider-reported input/output/reasoning tokens | unavailable |
| conservative ledger reservation | 5,069 input + 8,192 output |
| conservative ledger USD | $0.04066575 |
| actual provider billing | unknown; no provider usage object |
| target/support image pulls | 12 / 1 |
| grader containers / official grader runs | 0 / 0 |

`paid_model_calls=1` is the repository's fail-closed ledger terminology: it
means one request may have reached the provider and consumes the local cap. It
is not evidence that OpenAI billed the request. The `$0.04066575` value is the
full uncached reservation, not a claimed invoice amount.

The wrapper's one bounded process-level resume replayed the terminal journal's
same `HTTP_AUTH_ERROR`; it issued zero additional provider requests. Therefore
the two identical error lines in the workflow log are one external request,
not two.

## Evidence and cleanup

- Encrypted restricted artifact ID: `9931958997`
- GitHub artifact digest: `sha256:a7bdb0a02d3725b3d15d43048a03320ec4ecaff4e3deadcc9eb7f74e3476b1c2`
- Ciphertext SHA-256: `2858db3dd128ce136a316d7622ef4039b39cc89d58ccca03f4a6513c7da74c83`
- Workflow-log ZIP SHA-256: `247add01b369c567674af3f63a5cc9a0ff09ed092ab9755681e74059aa190cbd`
- Exact API-key and approval-B64 matches in 35 log members: 0 / 0
- Environment secrets after cleanup: 0
- Repository runners after cleanup: 0
- Pending deployments after completion: 0

The encrypted artifact is preserved and hash-bound. The one-time evidence
passphrase was not retained before the GitHub environment secret was deleted,
so this closure does not claim that the restricted tar was decrypted or that a
post-run plaintext inventory was reconstructed. This evidence-custody limitation
is recorded explicitly rather than silently overstating audit coverage.

## Authority boundary

Run `33859839836` was not rerun. No Actions attempt 2, `_006`, HELDOUT,
grader-smoke rerun, ablation, merge, tag, or release was created. The one-time
`_005` authority is consumed, and no further execution is authorized.

The machine-readable receipt is
`artifacts/trimem_v1/development_tuning_exec/exec-005/http-auth-error-receipt.json`.
