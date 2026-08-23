# R21 — Stage-B Configuration Recovery (no model calls)

Recovered from trajectory dir names / preds metadata:

| setting | value | class |
| --- | --- | --- |
| requested model (GPT-4o arms) | `openai/gpt-4o` (alias) | RECOVERED_PARTIAL (exact dated snapshot not in string) |
| requested model (mini arms) | `openai/gpt-4o-mini` (alias) | RECOVERED_PARTIAL |
| temperature | `1.0` | RECOVERED_EXACT |
| top_p | `None` | RECOVERED_EXACT |
| cost cap | `$20.00` | RECOVERED_EXACT |
| baseline config | `default__…` | RECOVERED_EXACT |
| memory config | `dsv31t_agenticMemSearch_1220_13w__…` | RECOVERED_EXACT |
| SWE-Agent | princeton-nlp/SWE-agent, config dir sweagent_0_7 (v0.7) | RECOVERED_PARTIAL (exact commit not pinned) |
| experience DB | experience_data.json 158MB oid c5bcc6e2; chroma.sqlite3 220MB oid 1450b7a0 | RECOVERED_EXACT (hash) |
| returned model string | inside `.traj` metadata (not extracted; would require deeper parse) | UNRECOVERED |

For Stage B: the exact **dated GPT-4o snapshot** and **returned_model** remain UNRECOVERED from dir names; they
sit inside per-instance `.traj` files. Any Stage-B live run without them risks MODEL_DRIFT_REPLICATION labeling.
