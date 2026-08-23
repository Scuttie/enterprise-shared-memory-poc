# Company Handoff — Fresh-Clone Acceptance (§4)

A brand-new clone of the remote repository was checked out at the exact sealed commit and run with a clean
environment (no reused venv/cache/DB/Qdrant).

- Clone → `git checkout ea4bd4a1998831540d6acf9f50c171608cec82bd`
- `bash scripts/company_acceptance_check.sh` (== `make company-acceptance`)

## Result (`reports/company_acceptance_result.json`, from the fresh clone)
| Field | Value |
| --- | --- |
| commit_sha | `ea4bd4a1998831540d6acf9f50c171608cec82bd` |
| package_version | `0.3.0.dev1` |
| test_passed / test_count | true / 60 |
| demo_passed | **DEMO_PASS: true** |
| docs_check_passed | true |
| package_passed | true |
| release_check (manifest_current) | true |
| secret_scan_clean | true |
| wheel | `enterprise_shared_memory_poc-0.3.0.dev1-py3-none-any.whl` · sha256 `3d29daee291cec7732c5fc512f710fbda3fddb395e261ff43cb2e403b7e3e60b` |
| sdist | `enterprise_shared_memory_poc-0.3.0.dev1.tar.gz` · sha256 `85cba1f7a5d6f080e3a9af82ae89a247882b0d2be27928263ab618905197f23b` |
| overall_pass | **true** |

Git status clean (tracked); all handoff package files present; README → Korean guide link resolves.

`COMPANY_ACCEPTANCE_PASS: true` · `DEMO_PASS: true`. (Wheel/sdist hashes are per-build; the acceptance records the
hashes produced by this fresh clone.)
