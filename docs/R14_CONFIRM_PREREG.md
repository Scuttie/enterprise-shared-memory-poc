# R14-CONFIRM — powered confirmation of the RAW worked-example positive (same reader, N up)

R14 (n=60) gave the program's first positive: M1(relevant raw prior fix)=0.150 vs M0=M2=0.083, relevance-specific,
but underpowered (McNemar p=0.22; only 5-vs-1 discordant at ~8% base). Per the decision to raise power on the
SAME reader, this preregisters a confirmation on **120 NEW targets** (sha256 `284ee88f…`), disjoint from the
original 60, pooled to **N=180** for the confirmatory analysis. Reader gpt-4o-mini, identical harness/memory/
controls; the original 60 arm results are reused unchanged (no re-run, no selection).

## Frozen before running
- Targets: 120 deterministic (hash key 'confirm'+id), each with an earlier same-repo source; disjoint from main-60;
  sources are not any target; `created_at(source) < created_at(target)`; `source_user ≠ target_user`.
- Memory M1 = relevant same-repo prior resolved issue (problem + real gold diff, RAW). M2 = cross-repo control.
- **Primary (confirmatory) H1 = M1 − M2 on pooled N=180.** Secondary H2 = M1 − M0. Exact McNemar +
  repository-cluster bootstrap 95% CI. ITT. Decision rule fixed in advance: **confirmed** iff pooled M1−M2 > 0 with
  McNemar p < 0.05 AND cluster-boot CI excludes 0; otherwise reported as **promising-but-not-confirmed** (still a
  valid final result). No third try, no reader change, no target reshuffle after seeing the numbers.

A null on this confirmation does not erase the R14 direction; it bounds the effect as smaller/noisier than n=60 hinted.
