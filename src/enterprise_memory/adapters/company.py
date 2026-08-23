"""P6/R19 §11 — company harness adapters. Translate a company's model/tool protocol to the memory tools.

Four protocols supported: openai (OpenAI-compatible function calling), anthropic (Anthropic tool-use),
jsonrpc (plain JSON-RPC), mcp (MCP tools/list+tools/call). We do NOT assume the company's model name or endpoint;
a manifest supplies them and is validated. Credentials are read from the environment/secret store, never embedded.
"""
from __future__ import annotations

from ..agentic import tools as toolmod

SUPPORTED_PROTOCOLS = ("openai", "anthropic", "jsonrpc", "mcp")


class ManifestError(ValueError):
    pass


def validate_manifest(manifest: dict) -> dict:
    """Fail closed on an incomplete/unsafe company manifest."""
    if not isinstance(manifest, dict):
        raise ManifestError("manifest must be a mapping")
    proto = manifest.get("protocol")
    if proto not in SUPPORTED_PROTOCOLS:
        raise ManifestError("protocol must be one of %s" % (SUPPORTED_PROTOCOLS,))
    if not manifest.get("model"):
        raise ManifestError("manifest.model is required (do not guess the company model identity)")
    if not manifest.get("endpoint") and proto != "mcp":
        raise ManifestError("manifest.endpoint is required for %s" % proto)
    for forbidden in ("api_key", "token", "password", "secret"):
        if forbidden in manifest:
            raise ManifestError("manifest must not contain %r; use env/secret store" % forbidden)
    return manifest


def tool_specs(protocol: str) -> list:
    """Emit the 4 memory tools in the requested protocol's tool-declaration shape."""
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ManifestError("unsupported protocol: %s" % protocol)
    specs = []
    for t in toolmod.ALL_TOOLS:
        if protocol == "openai":
            specs.append({"type": "function", "function": {
                "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}})
        elif protocol == "anthropic":
            specs.append({"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]})
        elif protocol == "mcp":
            specs.append({"name": t["name"], "description": t["description"], "inputSchema": t["input_schema"]})
        else:  # jsonrpc
            specs.append({"method": "tools/call", "tool": t["name"], "params_schema": t["input_schema"]})
    return specs
