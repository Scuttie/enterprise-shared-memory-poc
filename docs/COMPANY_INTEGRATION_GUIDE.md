# Company Integration Guide

## 1. Provide a model/harness manifest
```yaml
# configs/company.example.yaml (placeholders only)
protocol: openai        # openai | anthropic | jsonrpc | mcp
model: <your-model-id>  # required — do NOT let the system guess your model identity
endpoint: <url>         # required for openai/anthropic/jsonrpc; omit for mcp
```
The adapter validates this manifest and **fails closed** if `model` is missing or a secret is embedded. Credentials
come from the environment / secret store at runtime, never the manifest.

## 2. Choose a transport
- **OpenAI-compatible** function calling — `adapters.tool_specs("openai")`.
- **Anthropic** tool-use — `adapters.tool_specs("anthropic")`.
- **JSON-RPC** — `adapters.tool_specs("jsonrpc")`.
- **MCP** — stdio (`python -m enterprise_memory.mcp.server`) or streamable-HTTP; configs in
  [`../examples/company_harness/`](../examples/company_harness/).

## 3. The per-subtask loop
`memory_search` (metadata) → `memory_browse` (execution view, gated) → apply → `memory_report_outcome`. Identity,
tenant, repository authorization, and policy mode are all server-side.

## 4. Repository mounting & sandbox ownership
The coding agent and its sandbox remain **owned by the company harness**; this service supplies governed memory
only. The verifier and hidden tests are never exposed to the model.

## 5. Try it offline first
```bash
python examples/company_harness/http_adapter.py         # zero-infra, in-process
python examples/company_harness/mock_local_model_server.py
```
