# Recorded memory delivery and submission chronology

This read-only audit includes **all 24 VALID tasks in both arms**. It makes no
model, grader, or retrieval calls and never emits problem, candidate, lesson,
test, or model-reasoning text. Original files are checked before and after.

From the repository root, with a new output filename:

```powershell
python artifacts/skhynix_v1/lcb_002/mechanism-001/timeline-source-001.py --pilot data/skhynix_lcb_002/pilot-001 --exposure-audit artifacts/skhynix_v1/lcb_002/pilot-exposure-audit-001.json --output artifacts/skhynix_v1/lcb_002/mechanism-001/timeline-002.json
python -m pytest artifacts/skhynix_v1/lcb_002/mechanism-001/test_timeline_source_001.py
```

`timeline-002.json` is the final metadata output. `timeline-001.json` preserves
the initial audit before provenance labels and limitations were clarified.

Each native session's receipt equals its solve-receipt entry; original
`events_sha256` and `stderr_sha256` are verified. Tool requests are paired by
their STARTED/COMPLETED IDs and must match. A memory-bearing response is prior
delivery only if it completed **before the finish request started**. A finish's
own response cannot establish prior delivery. Every delivered memory entry,
including its exact text, must equal the final hash-bound injection ledger.

The original receipts did **not** record prompt hashes. Prompt-only evidence is
therefore explicitly labelled as a retained prompt hashed at audit time, not an
independent execution-time prompt pin. The frozen native source writes this
prompt and sends the same string to the session process. All original pinned
implementation files are rechecked; no runtime code is changed.

For each finish, output contains only allowlisted field names, value types,
integer trace-step values, successful target-history IDs available before that
step, status, and memory IDs delivered before the request. It separates memory
seen in that same session from earlier sessions. `ledger_entry_sha256` hashes
the whole canonical entry; `exact_text_sha256` hashes the injected text and
corresponds to the previous exposure audit's `injection_sha256`.

Observed counts:

| Measure | OFF | ON |
|---|---:|---:|
| Independent tasks | 24 | 24 |
| Native sessions | 36 | 32 |
| Finish requests | 184 | 40 |
| Accepted / rejected finish requests | 13 / 171 | 22 / 18 |
| Delivered injections / targets | 0 / 0 | 36 / 23 |

The 40 ON finish requests are repeated actions within 24 tasks, not independent
problems. Of 36 ON injection entries, 27 occur in an original-hash-bound event
response; nine are found only in retained prompts. All 22 accepted ON finishes
have prior same-session structured memory delivery: 20 also have an original
event-pinned prior response, while `3653` and `abc379_b` have prompt-only prior
delivery. `abc386_c` is the one ON target without any injection.

All 18 rejected ON finishes have no recorded structured `context.memory` entry
in that session's prompt or prior response. This does **not** prove absence of
information derived from earlier memory: L0 working context or handoff evidence
could paraphrase it, and this audit performs no semantic analysis of that prose.

For `abc380_d`, four rejected finishes occur in session 2 with empty structured
memory. Session 1 had received the `abc311_b` episode. Session 3 receives the
`abc347_a` episode in its prompt and public-test response, then submits valid
target step `[10]`. Session, public-test evidence, and memory all change; this
sequence does not isolate a cause. For regression `3636`, the `abc327_a` episode
appears only in the session-1 prompt; its eight rejected finishes occur in
session 2 with no structured memory delivery. None attempts integer `[11]`.

The 11 OFF-fail/ON-pass pairs comprise ten OFF submission failures and one OFF
submitted wrong answer. Each has a first-attempt accepted ON finish and prior
event-pinned memory delivery. They are not 11 within-session corrections;
`abc380_d` is the separate observed ON reject-then-accept case.

These are recorded delivery and protocol-shape observations. They do not show
whether the model read or used an example, reveal its internal reasoning, or
establish that memory caused the outcome. Private grader artifacts are not
opened; correctness comparisons remain the separately published primary report.
