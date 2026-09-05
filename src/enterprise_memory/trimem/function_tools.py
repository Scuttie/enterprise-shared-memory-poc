"""Canonical native function-tool contract for every TriMem solve call."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .provider_output_contracts import validate_structured_value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _nullable(schema: Mapping[str, Any]) -> dict[str, Any]:
    return {"anyOf": [dict(schema), {"type": "null"}]}


STRING_LIST: dict[str, Any] = {
    "type": "array",
    "maxItems": 64,
    "items": {"type": "string", "minLength": 1},
}

SEMANTIC_SUBTASK: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "id",
        "objective",
        "predicted_operation",
        "depends_on",
        "preconditions",
        "invariants",
        "files",
        "symbols",
        "apis",
        "errors",
        "tests",
        "required_memory_facets",
    ],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "objective": {"type": "string", "minLength": 1},
        "predicted_operation": {"type": "string", "minLength": 1},
        "depends_on": STRING_LIST,
        "preconditions": _nullable(STRING_LIST),
        "invariants": _nullable(STRING_LIST),
        "files": _nullable(STRING_LIST),
        "symbols": _nullable(STRING_LIST),
        "apis": _nullable(STRING_LIST),
        "errors": _nullable(STRING_LIST),
        "tests": _nullable(STRING_LIST),
        "required_memory_facets": _nullable(STRING_LIST),
    },
}

DEPENDENCY_ADDITION: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["node_id", "depends_on"],
    "properties": {
        "node_id": {"type": "string", "minLength": 1},
        "depends_on": {"type": "string", "minLength": 1},
    },
}


def _tool(name: str, description: str, properties: Mapping[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": dict(properties),
            "required": list(required),
            "additionalProperties": False,
        },
        "strict": True,
    }


FUNCTION_TOOLS: tuple[dict[str, Any], ...] = (
    _tool(
        "list_files",
        "List repository files in deterministic path order.",
        {},
        [],
    ),
    _tool(
        "read_file",
        "Read a bounded UTF-8 line window from one repository file.",
        {
            "path": {"type": "string", "minLength": 1},
            "start_line": _nullable({"type": "integer", "minimum": 1}),
            "max_lines": _nullable({"type": "integer", "minimum": 1, "maximum": 2000}),
        },
        ["path", "start_line", "max_lines"],
    ),
    _tool(
        "search",
        "Search repository text for a non-empty literal query, optionally under one path.",
        {
            "query": {"type": "string", "minLength": 1},
            "path": _nullable({"type": "string", "minLength": 1}),
        },
        ["query", "path"],
    ),
    _tool(
        "write_file",
        "Create a new UTF-8 file or intentionally replace one complete small file.",
        {
            "path": {"type": "string", "minLength": 1},
            "content": {"type": "string"},
        },
        ["path", "content"],
    ),
    _tool(
        "replace_text",
        "Atomically replace one exact text span in an existing UTF-8 file bound to its SHA-256.",
        {
            "path": {"type": "string", "minLength": 1},
            "expected_file_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "old_text": {"type": "string", "minLength": 1},
            "new_text": {"type": "string"},
        },
        ["path", "expected_file_sha256", "old_text", "new_text"],
    ),
    _tool(
        "run_public_tests",
        "Run the task's frozen public test command in its isolated environment.",
        {},
        [],
    ),
    _tool(
        "run_command",
        "Run one bounded argv command in the digest-pinned network-disabled task image.",
        {
            "argv": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "items": {"type": "string", "minLength": 1},
            },
            "cwd": _nullable({"type": "string", "minLength": 1}),
            "timeout_seconds": _nullable({
                "type": "integer",
                "minimum": 1,
                "maximum": 120,
            }),
        },
        ["argv", "cwd", "timeout_seconds"],
    ),
    _tool(
        "revise_subtask_dag",
        "Revise the task-local semantic DAG when new repository evidence reveals additional work.",
        {
            "reason": {"type": "string", "minLength": 1, "maxLength": 4096},
            "new_subtasks": {
                "type": "array",
                "maxItems": 16,
                "items": SEMANTIC_SUBTASK,
            },
            "dependency_additions": {
                "type": "array",
                "maxItems": 32,
                "items": DEPENDENCY_ADDITION,
            },
        },
        ["reason", "new_subtasks", "dependency_additions"],
    ),
    _tool(
        "complete_subtask",
        "Complete the active semantic subtask with non-empty observed evidence.",
        {"evidence": {"type": "string", "minLength": 1}},
        ["evidence"],
    ),
)

FUNCTION_TOOL_BY_NAME: dict[str, dict[str, Any]] = {
    item["name"]: item for item in FUNCTION_TOOLS
}
FUNCTION_TOOLS_SHA256 = hashlib.sha256(canonical_bytes(FUNCTION_TOOLS)).hexdigest()


def detached_function_tools() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(canonical_bytes(item)) for item in FUNCTION_TOOLS)


def validate_function_arguments(name: str, arguments: Any) -> dict[str, Any]:
    try:
        tool = FUNCTION_TOOL_BY_NAME[name]
    except KeyError as exc:
        raise ValueError("SOLVE_UNKNOWN_FUNCTION") from exc
    if not isinstance(arguments, dict):
        raise ValueError("SOLVE_FUNCTION_ARGUMENT_SCHEMA_FAILURE")
    try:
        validate_structured_value(arguments, tool["parameters"])
    except ValueError as exc:
        raise ValueError("SOLVE_FUNCTION_ARGUMENT_SCHEMA_FAILURE") from exc
    return arguments


def function_tool_manifest() -> dict[str, Any]:
    return {
        "schema": "trimem/native-function-tools/1.0",
        "function_tools": list(detached_function_tools()),
        "function_tools_sha256": FUNCTION_TOOLS_SHA256,
        "tool_choice": "required",
        "parallel_tool_calls": False,
    }
