"""Frozen provider-native structured-output contracts for TriMem roles."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


MAX_DECOMPOSITION_SUBTASKS = 24

DECOMPOSITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["subtasks"],
    "properties": {
        "subtasks": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_DECOMPOSITION_SUBTASKS,
            "items": {
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
                    "id": {"type": "string"},
                    "objective": {"type": "string"},
                    "predicted_operation": {"type": "string"},
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "preconditions": {"$ref": "#/$defs/string_list"},
                    "invariants": {"$ref": "#/$defs/string_list"},
                    "files": {"$ref": "#/$defs/string_list"},
                    "symbols": {"$ref": "#/$defs/string_list"},
                    "apis": {"$ref": "#/$defs/string_list"},
                    "errors": {"$ref": "#/$defs/string_list"},
                    "tests": {
                        "type": "array",
                        "description": "Public tests or other concrete completion-evidence descriptions.",
                        "items": {"type": "string"},
                    },
                    "required_memory_facets": {"$ref": "#/$defs/string_list"},
                },
            },
        }
    },
    "$defs": {
        "string_list": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
}

EXPERIENCE_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["episode", "semantic_candidate"],
    "properties": {
        "episode": {
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "action", "outcome"],
            "properties": {
                "summary": {"type": "string"},
                "action": {"type": "string"},
                "outcome": {"type": "string", "enum": ["passed", "failed"]},
            },
        },
        "semantic_candidate": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "preconditions",
                        "operation",
                        "invariant",
                        "non_applicability",
                        "verification",
                        "applicability_scope",
                    ],
                    "properties": {
                        "preconditions": {"type": "string"},
                        "operation": {"type": "string"},
                        "invariant": {"type": "string"},
                        "non_applicability": {"type": "string"},
                        "verification": {"type": "string"},
                        "applicability_scope": {
                            "type": "string",
                            "enum": ["EXACT_REPOSITORY", "CROSS_REPOSITORY"],
                        },
                    },
                },
            ]
        },
    },
}

SCHEMAS: dict[str, dict[str, Any]] = {
    "trimem_decomposition_v1": DECOMPOSITION_SCHEMA,
    "trimem_experience_extraction_v1": EXPERIENCE_EXTRACTION_SCHEMA,
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def schema_sha256(schema: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(schema)).hexdigest()


def output_contract(name: str) -> dict[str, Any]:
    try:
        schema = SCHEMAS[name]
    except KeyError as exc:
        raise ValueError("unknown TriMem provider output schema") from exc
    # JSON round-trip produces a detached value so callers cannot mutate the
    # module's source-of-truth object through a request instance.
    detached = json.loads(canonical_bytes(schema))
    return {
        "output_schema_name": name,
        "output_json_schema": detached,
        "output_schema_sha256": schema_sha256(schema),
        "strict_structured_output": True,
    }


def validate_structured_value(value: Any, schema: Mapping[str, Any]) -> None:
    """Validate the deliberately small JSON-Schema subset used above.

    This keeps the production parser dependency-free while making the exact
    schema sent to Responses the same schema enforced by the local adapter.
    """

    def resolve(node: Mapping[str, Any]) -> Mapping[str, Any]:
        reference = node.get("$ref")
        if reference is None:
            return node
        if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
            raise ValueError("unsupported schema reference")
        name = reference.rsplit("/", 1)[-1]
        resolved = schema.get("$defs", {}).get(name)
        if not isinstance(resolved, Mapping):
            raise ValueError("unresolved schema reference")
        return resolved

    def visit(item: Any, node: Mapping[str, Any], path: str) -> None:
        node = resolve(node)
        alternatives = node.get("anyOf")
        if isinstance(alternatives, list):
            failures = []
            for alternative in alternatives:
                try:
                    visit(item, alternative, path)
                    return
                except ValueError as exc:
                    failures.append(str(exc))
            raise ValueError(f"{path} does not match any allowed schema")
        kind = node.get("type")
        if kind == "null":
            if item is not None:
                raise ValueError(f"{path} must be null")
            return
        if kind == "object":
            if not isinstance(item, dict):
                raise ValueError(f"{path} must be an object")
            properties = node.get("properties", {})
            required = set(node.get("required", ()))
            missing = sorted(required - set(item))
            if missing:
                raise ValueError(f"{path} missing required fields: {missing}")
            if node.get("additionalProperties") is False:
                extra = sorted(set(item) - set(properties))
                if extra:
                    raise ValueError(f"{path} has additional fields: {extra}")
            for key, child in item.items():
                if key in properties:
                    visit(child, properties[key], f"{path}.{key}")
            return
        if kind == "array":
            if not isinstance(item, list):
                raise ValueError(f"{path} must be an array")
            if len(item) < int(node.get("minItems", 0)):
                raise ValueError(f"{path} has too few items")
            maximum = node.get("maxItems")
            if maximum is not None and len(item) > int(maximum):
                raise ValueError(f"{path} has too many items")
            if node.get("uniqueItems") and len({canonical_bytes(x) for x in item}) != len(item):
                raise ValueError(f"{path} contains duplicate items")
            child_schema = node.get("items")
            if isinstance(child_schema, Mapping):
                for index, child in enumerate(item):
                    visit(child, child_schema, f"{path}[{index}]")
            return
        if kind == "string":
            if not isinstance(item, str):
                raise ValueError(f"{path} must be a string")
            if len(item) < int(node.get("minLength", 0)):
                raise ValueError(f"{path} is too short")
            if "enum" in node and item not in node["enum"]:
                raise ValueError(f"{path} is outside the enum")
            return
        raise ValueError(f"{path} uses an unsupported schema type")

    visit(value, schema, "$")
    if schema is DECOMPOSITION_SCHEMA or schema == DECOMPOSITION_SCHEMA:
        subtasks = value["subtasks"]
        list_fields = (
            "depends_on",
            "preconditions",
            "invariants",
            "files",
            "symbols",
            "apis",
            "errors",
            "tests",
            "required_memory_facets",
        )
        for row_index, row in enumerate(subtasks):
            for field in ("id", "objective", "predicted_operation"):
                if not row[field]:
                    raise ValueError(f"$.subtasks[{row_index}].{field} must not be empty")
            for field in list_fields:
                values = row[field]
                if any(not entry for entry in values):
                    raise ValueError(
                        f"$.subtasks[{row_index}].{field} contains an empty value"
                    )
                if len(set(values)) != len(values):
                    raise ValueError(
                        f"$.subtasks[{row_index}].{field} contains duplicate values"
                    )
        identifiers = [row["id"] for row in subtasks]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("$.subtasks contains duplicate node IDs")
        seen: set[str] = set()
        for row in subtasks:
            if any(dependency not in seen for dependency in row["depends_on"]):
                raise ValueError("subtask dependencies must precede dependents")
            seen.add(row["id"])
    elif schema is EXPERIENCE_EXTRACTION_SCHEMA or schema == EXPERIENCE_EXTRACTION_SCHEMA:
        episode = value["episode"]
        for field in ("summary", "action"):
            if not episode[field]:
                raise ValueError(f"$.episode.{field} must not be empty")
        semantic_candidate = value["semantic_candidate"]
        if semantic_candidate is not None:
            for field in (
                "preconditions",
                "operation",
                "invariant",
                "non_applicability",
                "verification",
            ):
                if not semantic_candidate[field]:
                    raise ValueError(f"$.semantic_candidate.{field} must not be empty")
