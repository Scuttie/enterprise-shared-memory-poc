# Independent public replication of Native008 exposed-C submissions

Both unchanged Native008 submissions that received public diagnostic memory pass all twelve frozen public checks in new isolated checkouts. This includes the original public issue reproducer for each task.

| Native008 submission | Clean base | Unchanged submitted patch | Original public issue checks after patch |
| --- | ---: | ---: | ---: |
| 20428 repeat 2 C | 1/12 | 12/12 | 5/5 |
| 20438 repeat 1 C | 2/12 | 12/12 | 5/5 |

For 20428, the probe embeds the exact long expression from the public issue. The script verified its literal equality with the expression in the frozen public instruction using AST extraction. After the unchanged submitted patch, the resulting polynomial has canonical `DMP([], EX, None)`, `is_zero=True`, expression zero, normal zero `terms_gcd`, and primitive content zero. All seven neighboring ground-arithmetic checks also pass.

For 20438, all five original ProductSet/FiniteSet checks pass. The four equal-set proper subset/superset checks and the three Range-product checks also pass.

These results confirm uptake and repair of the specific public behaviors described by the Native008 diagnostic bank. They do not identify the remaining official failures and do not change either task's official unresolved status. Public probe expectations are analyst-selected semantic checks, not a benchmark oracle or verified successful skill. This replication remains separate from Native010 solver memory; no lesson, patch hint, or new probe was added to its frozen bank.

Only four public probe commands ran: BASE and unchanged submitted C for each of two tasks. Both probes were reused byte-for-byte from the frozen Native008 public probe receipt, SHA-256 `41262bce2a86a70b255bc96c781fed4755045aa29133ce4b104acc8ff066155a`. No new semantic probe was introduced.

Execution used new local base-only clones under `/home/trimem-runner/native010-public-replication`, then the existing frozen Docker command runner and each task's pinned public image. Git history checks found one base commit, zero remotes, zero references, zero reflogs, no alternates, and no promisor markers. No original workspace was edited. Dataset-row loading and grader construction were bypassed; defensive process-local blockers prohibited dataset and grader access. No model, solver, official grader, network fetch, hidden fixture, gold patch, private grader payload, or hidden assertion access occurred.

All 1,006 protected original public artifact, helper, and frozen source input paths retained their pre-run SHA-256 values. The receipt includes the complete hash map, exact public command arguments, outputs, image identifiers, submitted patch hashes, public task/probe hashes, new checkout paths and Git isolation evidence.

Artifacts:

- Windows receipt: `C:/Users/jewon/AppData/Local/Temp/native010_public_replication_results.json`
- Receipt SHA-256: `f368f32cbd44bdfdef7e6c47c72a3b027a3bd41387905f3ddad4bb7faffb8c40`
- Script: `C:/Users/jewon/AppData/Local/Temp/native010_public_replication_run.py`
- Linux receipt: `/home/trimem-runner/native010-public-replication/public-replication-results.json`

Invocation from `C:/Users/jewon/esm-r23-d115-writer`:

```powershell
python -B artifacts/skhynix_v1/codex_008/operations/skhynix_codex_008_manage.py python --name recovery-20428-r2 --code-file C:/Users/jewon/AppData/Local/Temp/native010_public_replication_run.py
```

The script deliberately refuses an existing output root or receipt. Preserve these artifacts and use a newly named output root for any separately authorized rerun.
