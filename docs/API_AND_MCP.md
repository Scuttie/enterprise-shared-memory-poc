# API & MCP

## HTTP `/v1` (bearer + scope + tenant; append-only audit; idempotency where writable)
| Endpoint | Scope |
| --- | --- |
| `POST /v1/experience-cards/search` | `memory:search` |
| `GET  /v1/experience-cards/{card_id}` | `memory:browse` |
| `POST /v1/memory-browse` | `memory:browse` |
| `POST /v1/memory-decisions` | `memory:search` |
| `POST /v1/memory-outcomes` | `memory:feedback` |
| `POST /v1/experience-cards/{id}/promote` · `/quarantine` · `/deprecate` | `memory:review` |
| `GET  /v1/memory-policies` | `memory:review` |
| `GET  /v1/memory-audit/{request_id}` | `memory:admin` |

`search` returns metadata only; the execution view comes only from `browse`, and only after gates + router approve.

## MCP tools (stdio or streamable-HTTP)
`memory_search`, `memory_browse`, `memory_report_outcome`, `memory_explain_decision`. Contract:
[`../examples/company_harness/tool_schema.json`](../examples/company_harness/tool_schema.json). Identity is
server-side; no credentials in payloads; verifier/hidden tests never exposed. Client-set `org_id` / `token` /
`policy_mode` / `experiment_arm` / `gold_patch` / `hidden_tests` are rejected.

## Error codes (JSON-RPC)
`-32601` method not found · `-32602` invalid params (incl. forbidden client fields) · `-32603` internal
(fail-closed) · `-32700` parse error.
