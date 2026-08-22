# Company harness integration example

Wire your coding agent to the governed memory service in one of four protocols — **openai**, **anthropic**,
**jsonrpc**, or **mcp** — without reading the research history or contacting the author.

## Zero-infra offline check
```bash
python examples/company_harness/http_adapter.py          # runs against the in-process MCP dispatcher
python examples/company_harness/mock_local_model_server.py
```

## Files
| File | Purpose |
| --- | --- |
| `tool_schema.json` | The 4 memory tools (`search_experiences`, `browse_experience`, `report_memory_outcome`, `memory_explain_decision`). |
| `http_adapter.py` | Declare tools to your model + run the search→browse→outcome loop (offline-safe). |
| `mcp_stdio_config.json` | Local stdio MCP server config (Claude-Code-like harness). |
| `mcp_http_config.json` | Streamable-HTTP MCP config for internal deployment. |
| `mock_local_model_server.py` | Offline mock model server — exercise the loop with no provider credential. |

## Rules
- **Identity is server-side.** Never pass `org_id`, tokens, or `policy_mode` as tool arguments — the server
  rejects them. Configure identity via OIDC + `EM_*` env / secret store.
- **`search` returns metadata only.** The execution view arrives only from `browse`, and only after the server's
  gates + utility router approve.
- **Do not guess the model identity.** Supply `manifest.model`; the adapter validates it.
- The verifier and hidden tests are never exposed to the model.

See `docs/API_AND_MCP.md` and `docs/COMPANY_INTEGRATION_GUIDE.md` for full endpoint/scopes detail.
