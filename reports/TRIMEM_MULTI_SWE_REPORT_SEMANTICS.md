# TriMem Multi-SWE two-stage report semantics

## Decision

The pinned Multi-SWE evaluator does not define `Report.valid` and
`FinalReport.resolved` as the same signal. The frozen interpretation is:

```text
REPORT_VALID = LOCAL_TRANSITION_PREDICATE

FINAL_RESOLVED =
    REPORT_VALID
    AND ALL_FROZEN_EXPECTED_TRANSITION_KEYS_COVERED
```

Consequently, `Report.valid=true` with a final unresolved classification is
legal when at least one frozen expected transition key is absent from its
corresponding generated-report category. This is the Vue NOOP regression shape
that exposed the previous adapter conflation. A NOOP baseline is defined by the
final unresolved classification, not by `Report.valid=false`.

## Pinned source

Repository: `https://github.com/multi-swe-bench/multi-swe-bench`

Revision: `24f493f8a103e72312ded4f6b9c89f081d69cb09`

Commit tree: `741ce10a4ec220fec713112502850b381a6226b9`

The contract uses Git object bytes, not working-tree bytes.

| Git blob | OID | Bytes | Lines | SHA-256 |
| --- | --- | ---: | ---: | --- |
| `multi_swe_bench/harness/report.py` | `a0b23ab1bf3c2407e15338fd0e644c0138fd3d90` | 12,942 | 347 | `5a025fd496d42c4b7377fc0702d64c6d0e356b117eaf2face47e73a52c29902f` |
| `multi_swe_bench/harness/gen_report.py` | `251e8b01059a18a9af5ae176c696eb4be8950ae4` | 21,331 | 589 | `02ebc8a5414898d12f4f5a9ba0c11a8f57c9f34a0bdc02c2311afac9f654847d` |
| `multi_swe_bench/harness/dataset.py` | `19aeb4370fcfdaeccef99b3a47d06c5a572d468c` | 2,833 | 79 | `dd49f55baf63b60fff309b6a5b2a1826697e2b85ad1a9bccff18321dcdc200fc` |
| `multi_swe_bench/harness/test_result.py` | `bbdd5dc729582a1d06c79f416058bbc4d7db9c91` | 5,164 | 157 | `5411af794920cf4b170fe9dbe8c21c12cc63e2bbe2280d6d82acb850f4808be3` |
| `multi_swe_bench/harness/pull_request.py` | `0c2c99a4602bc6dc127cc0bb3ecaff56a6550d17` | 6,015 | 211 | `32b49f48b39124f67727f408898bd96cce91c0a362faa716ac858dcb0b0b47c7` |

`report.py` lines 50–70 reconstruct the union of test IDs and use `NONE` for
an unobserved stage. Lines 90–142 implement the four ordered Stage-A checks.
`gen_report.py` lines 430–487 first reject an invalid report and then perform
the p2p/f2p/s2p/n2p expected-key containment checks. `report.py` lines 309–347
map accepted reports to `resolved_ids` and rejected reports to
`unresolved_ids`. `dataset.py` lines 24–42 define the frozen transition and
TestResult inputs. `test_result.py` lines 43–101 enforce count/set agreement
and disjoint pass/fail/skip classifications. `pull_request.py` lines 77–100
bind the `PullRequestBase.id` value stored by `FinalReport` to the exact
`{org}/{repo}:pr-{number}` format.

## Stage A: local report validity

The dependency-free implementation reconstructs missing stage observations as
`NONE` and evaluates the same predicate invoked upstream as `Report.check()` in
pinned order:

1. The fix-patch result contains at least one classified test.
2. No test transitions from test-patch `PASS` to fix-patch `FAIL`.
3. At least one test transitions from a non-`PASS` test-patch state to
   fix-patch `PASS`.
4. No test has test-patch state `NONE` or `SKIP`, fix-patch state `FAIL`, and
   unpatched-run state `PASS`.

The observed boolean must equal this recomputation. A valid report must carry
the upstream empty error value. An invalid report must carry an error whose
structure corresponds to the first failed ordered rule.

## Stage B: frozen expected-key coverage

For each category in `p2p_tests`, `f2p_tests`, `s2p_tests`, and `n2p_tests`,
every key in the frozen Dataset row must occur in the corresponding observed
Report category. This is containment, matching the pinned reporter; it is not
exact set equality. The local validator separately reconstructs the entire
observed category map from the three TestResults, so injected or misclassified
observed categories are rejected before coverage is summarized.

Only `Stage A AND Stage B` is compared with the one-target official
`FinalReport` classification.

## Truth table

`accept` means the official final classification exactly matches the computed
two-stage result.

| Report valid | Expected coverage complete | Final resolved | Computed resolved | Accept |
| --- | --- | --- | --- | --- |
| false | false | false | false | yes |
| false | false | true | false | no |
| false | true | false | false | yes |
| false | true | true | false | no |
| true | false | false | false | yes |
| true | false | true | false | no |
| true | true | false | true | no |
| true | true | true | true | yes |

With a valid frozen source Dataset, an invalid generated Report normally has
empty transition categories, so the `false / true` coverage rows are logical
formula rows rather than the expected campaign shape.

## Production API and public evidence

The one shared implementation is
`scripts/trimem_multi_swe_report_semantics.py`:

```python
validate_multi_swe_report_semantics(
    instance_id=frozen_instance_id,
    source_row=frozen_dataset_row,
    status=per_instance_report,
    final_report=one_target_final_report,
)
```

It returns an immutable `MultiSWEReportSemantics`. `to_public_dict()` emits
only booleans, counts, canonical category-domain SHA-256 values, and a
structural invalidity reason code. `PUBLIC_SUMMARY_FIELDS` is the shared exact
field-set contract. Raw test names remain restricted evidence and do not occur
in the public summary or validation error text.

`validate_public_summary()` independently checks that public shape, primitive
types, category counts, digests, validity match, coverage derivation, and final
boolean relationships without requiring restricted names.

The pinned `TestResult.__post_init__` receives sets and enforces count-to-set
size agreement plus disjoint pass/fail/skip sets. It does not itself prove that
the pre-materialization raw JSON arrays contained no duplicate entries. TriMem
therefore applies the required stricter boundary before set construction: it
rejects duplicate raw IDs even when the supplied count would match the
deduplicated set. The validator also rejects malformed, overlapping, or
count-mismatched classifications; a non-boolean `valid`; status field drift;
identity drift; observed/recomputed validity disagreement; malformed, unknown,
or duplicate FinalReport target IDs; and any final/computed result mismatch.

## Regression matrix

Production-helper tests establish:

- A: valid + complete + final resolved is accepted.
- B: valid + one missing f2p + final unresolved is accepted.
- C: valid + one missing p2p + final unresolved is accepted.
- D: recomputed invalid + final unresolved is accepted.
- E: valid + complete + final unresolved is rejected.
- F: invalid + final resolved is rejected.
- G: valid + incomplete + final resolved is rejected.
- H: observed valid/recomputed valid disagreement is rejected.
- I: duplicate, overlapping, malformed, missing, and extra status material is
  rejected.
- O: GOLD and NOOP may both have `Report.valid=true` while their final outcomes
  differ.

The direct Stage-A production function also verifies all four ordered
`Report.check` failure reasons. The current focused suite has 32 passing tests.

The production adapter/runner/aggregate regression group separately closes
the non-semantic cases required by the same correction:

- J: a failed adapter envelope retains every captured private-input, submitted
  patch, invocation, harness/report stream, raw report, test-status, and
  container-status reference under the sole versioned `_trimem` root.
- K: a malformed secondary private-input identity never replaces the original
  Multi-SWE identity/result mismatch; the process-visible error begins with
  the primary reason and secondary validation errors stay in their own list.
- L: if the official final report was already parsed as resolved before a
  later adapter failure, `official_final_report_resolved=true` is retained,
  `adapter_normalized=false`, `scientific_resolved=null`, and aggregation
  rejects the cell instead of converting it to unresolved.
- M: the production smoke gateway boundary creates exactly one terminal JSON
  record for each invocation, including typed and unexpected failures.
- N: the immutable six-attempt/five-normalized fixture accounts six attempted,
  six complete-execution-evidence, five normalized, zero authoritative, and
  six unattempted cells.

Success and failure share
`trimem/official-grader-adapter-evidence/2.0`. The `_trimem` root is restricted
adapter evidence, not the separately generated public artifact. Public rows
use an exact allowlist and publish only counts, booleans, and canonical
digests; raw test names and private failure reasons remain restricted. The
seven failure counters are produced from one ordered stage rule table with an
adapter-contract fallback. A pre-cell environment or harness-preparation
failure has a sealed zero-execution record. Cell-level scientific authority is
revoked atomically when aggregate/public/image-cleanup validation fails; final
campaign eligibility additionally requires the exact successful signed
workflow attempt. A content-bound campaign-finalization journal records the
scientific rejection or the start/commit of authority promotion. Interrupted
promotion/rollback transactions are recovered fail closed to a canonical
non-authoritative tree. Evidence inventory and encryption still run after
approval materialization even if authority recovery fails. Failure closure
waits for recovery success or skip; plaintext cleanup requires a successful
encrypted-evidence upload and otherwise preserves plaintext and ciphertext.

## Locks and execution scope

- Semantics module bytes: 31,877
- Semantics module SHA-256:
  `4132f7580edbabd2492ca65129575713ef3e74bb1929de4f8626552dfffda62d`
- Semantics projection SHA-256:
  `9671d6da70ad59c2ea9f47f3fac75b702c84fc43cda2e8d3defe825d90d529e0`
- Semantics self-lock SHA-256:
  `407fc0e383f5a2270bd586a61d5789c6a4f29619da15016f027eb086ea4850f6`
- Semantics lock raw-file SHA-256:
  `620618f967ef5e33037fccc123fcf004f63bbe656efeb61c46e85f764ef9c80e`
- Extended evaluation-contract projection SHA-256:
  `75b5a2179789dd3fd2ba05def343fb535c42c9a555ac07948ad2d8c338560368`
- Extended evaluation-contract self-lock SHA-256:
  `4bc48ea3bbe31b0e6bd8b99946e351d89d4a92f6ab2a4c7c2f6cb151a66230ce`
- Extended evaluation-contract raw-file SHA-256:
  `79e2b399c56269eff1cd23f815156ba4ace259c81e12690d63377a32c107c1ae`
- Adapter failure-envelope contract raw-file SHA-256:
  `77b6b215538da9f809428fb5eb3a2c860b1c1d8f2d443b0291379cd46df9990b`

The local `validate_report_semantics_lock()` path validates the strict JSON
self-seal, projection, truth table, module bytes, privacy boundary, and exact
five-blob semantic projection without network access. Contract CI additionally
reads the five exact semantic blobs from the pinned Git object database and
checks the Stage-A, Stage-B, and final-report identity AST structure.

This semantics correction performed zero local Docker operations, zero
official target/support grader-image pulls, and zero official grader runs.
Digest-pinned PostgreSQL/Qdrant service containers used by credential-free CI
are a separate infrastructure boundary and are not grader-image lifecycle
operations. Model/API calls, input/output tokens, and USD spend remain zero. It
did not run DEV, HELDOUT, or ablations and did not repeat the image probe.

## Official exec-005 closure

The one authorized recovery campaign ran as GitHub Actions workflow run
`33674784590`, attempt `1`, on sentinel-only execution HEAD
`cc001245b8c26373b5467a0dbdcbbbda0a9542be`. The branch trigger preflight,
protected approval materialization, EXEC gate, serial grader campaign,
fail-closed aggregate, public projection, image cleanup, evidence inventory,
encryption/upload, plaintext cleanup, and attestation/upload all succeeded.
The authority-rollback and namespaced failure-closure paths were correctly
skipped. No attempt was rerun and no second dispatch was created.

The independently reconstructed aggregate is byte-identical to the workflow
aggregate: 26,286 bytes with SHA-256
`5fd116bb8266209588255e58c6dd7806ba24e2072b65fc399fb1f47b831b9f6a`;
its canonical aggregate seal is
`52c9863955b9d1b6ab5084f4671df44425406292391ff840a33e0126d73b3e0a`.
All 12 frozen rows were attempted, received one terminal record, retained
complete official-execution evidence, normalized under the adapter contract,
and became authoritative. GOLD resolved 6/6 and NOOP_BASELINE was unresolved
6/6. Patch application, actual-test execution, image-digest verification, and
submitted-patch identity each passed 12/12. Host `prepare.sh` reads and source
image builds were both zero. The seven independent environment,
infrastructure, image-lifecycle, official-harness, official-report,
adapter-contract, and aggregate failure counters were all zero.

The eight Multi-SWE rows reproduced the exact two-stage contract. All four
GOLD rows were locally valid, coverage-complete, and finally resolved. All four
NOOP rows were finally unresolved. The Vue NOOP row preserved the critical
legal shape: `report_valid=true`, incomplete f2p coverage with one missing
expected transition, and `final_resolved=false`. The other three Multi-SWE
NOOP rows were locally invalid and coverage-incomplete; no NOOP pass criterion
depended on local validity.

Committed sanitized evidence is bound as follows:

- public result: 26,472 bytes, SHA-256
  `4a1253e69a95b3058b9433fbfe51ef3f8bee538c90b5faf29c996a841224faa4`;
- restricted-evidence inventory: 113,557 bytes, SHA-256
  `b1c3ba191c4d037f4f8ee70cf8a4821592b5b25a65700d7ce3faa2d0024add8e`;
- attestation subject: 1,548 bytes, SHA-256
  `647d9d3eaddaf2917bfaaa8fc47c0c54f814a50ddf5e900c3176d3c895513846`;
- attestation bundle: 11,910 bytes, SHA-256
  `c1cc04284b8f1be1cde006fa2309f6af918e8478485002b4556df7fcb165335e`;
- encrypted restricted member: 12,636,192 bytes, SHA-256
  `6b22e66e8b22b6a30420903eac5ce6699fd8047ff5d71d925cc68320a1b3179c`.

The encrypted archive was safely audited with zero unsafe members. Its exact
503 inventoried evidence files (11,706,964 bytes) matched path, size, and
SHA-256 bidirectionally, and its additional inventory member was byte-identical
to the uploaded inventory. The restricted aggregate was independently replayed
with the exact run ID and attempt and reproduced the uploaded aggregate bytes.
The pinned `gh 2.97.0` verification, certificate bindings, Rekor material, and
live completed-successful workflow-attempt check all passed.

The first offline closure check exposed one fail-closed verifier omission: the
production execution summary correctly contained `terminal_record_count=12`,
but the readiness reconstruction and its synthetic fixture omitted that field.
The closure fix adds the field and independently locks the actual production
summary at 1,409 bytes and SHA-256
`40a86b900af452d04484c9d63ebe75002d643935e159a118a6489d87ec2ec4a5`.
This strengthens post-execution verification only; it does not alter or rerun
the frozen campaign.

The campaign used 12 grader calls, 12 grader containers, six target-image
pulls, one support-image pull, and seven exact image removals. Task-arm,
solve, extraction, decomposition, model, API, paid-model, model-gateway, and
all token counters are zero; total USD is zero. The exact endpoint is
`TRIMEM_V1_GRADER_SMOKE_PASS_READY_FOR_DEVELOPMENT_APPROVAL`.
`DEV_APPROVAL_ALLOWED=YES` means only that a separate development approval may
now be considered. DEV execution remains unauthorized and was not started;
HELDOUT, ablation, merge, tag, and release were also not performed.
