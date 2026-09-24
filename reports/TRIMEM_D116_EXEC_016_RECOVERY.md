# TriMem V1 D1.16 — EXEC 016 approval-delay recovery

## Decision

`DEVELOPMENT_TUNING_EXEC_REQUEST_015` was never approved and is not a
scientific execution.  Its hosted and bounded credential-free preflights passed,
but its protected job waited for review long enough that the committed D1.15
loader rehearsal exceeded the one-hour live-freshness window.  The same
wall-clock check was embedded in immutable request replay, so approving the run
would have failed before approval materialization or credential access.

Run `34160843621` attempt 1 was therefore cancelled while waiting.  The
protected environment was not entered, no environment secret was installed,
and model calls, image pulls, grader containers, task-arm runs, tokens, and USD
were all zero.

## Root cause

D1.15 correctly required a fresh, complete loader rehearsal before writing and
triggering `_015`, but it reused that live age check whenever the immutable
sentinel was read.  Protected-environment review is intentionally unbounded, so
request validity became a function of the later wall clock even though the
protected job independently re-observes its runner and reruns the exact loader
preflight.

## D1.16 contract

D1.16 keeps the D1.15 full evidence validator unchanged and separates its use:

- immutable replay validates every field, identity, digest, binding, zero
  counter, timestamp syntax, and canonical byte;
- request write, branch trigger, and the unprotected bounded preflight apply the
  one-hour live-freshness window;
- delayed protected consumers do not re-age the preregistration; they must pass
  live protected-runner observation, cache-only service checks, pinned harness
  materialization, and the exact official-harness loader preflight.

The request writer launches that rehearsal in a separate POSIX process.  The
dedicated `trimem_d116_loader_rehearsal.py` entry point holds the complete
D1.16 inherited runtime context around the unchanged D1.15 collector.  This
prevents a D1.16 runner-readiness record from being interpreted under the
D1.15 schema merely because validation crossed a process boundary.  The
boundary was exercised locally before any `_016` sentinel, secret, image,
grader, or model call existed.

Malformed, future-dated, unbound, or noncanonical evidence remains fail-closed.

## Frozen scientific boundary

No result was observed and no scientific choice changed.  D1.16 preserves the
12 DEV targets, four M2 candidates, M0/M1 definitions, six-arm order, 72
task-arm runs, prompts/tools/parsers, runtime limits, grader and image locks,
selection rule, model `gpt-5.4-mini-2026-03-17`, 1,873 paid-call cap, and USD
50 hard cap.

`_016` remains a zero-authority request.  A fresh external approval must bind
its exact sentinel commit, source commit, freeze and request digests, workflow
run ID and attempt, caps, actor, timestamp, nonce, legal acceptance, and OpenAI
key commitment.  Until that approval is materialized in the protected job,
paid/model calls remain zero.
