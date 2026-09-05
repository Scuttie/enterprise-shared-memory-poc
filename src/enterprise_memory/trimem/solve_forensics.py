"""Sanitized structural classification for incomplete solve output.

The classifier never returns model text or argument values other than an
already-public repository path. It exists so the D1.4 decision rule is covered
by credential-free fixtures without embedding the restricted `_004` payload.
"""
from __future__ import annotations

import hashlib
import json
import posixpath
from typing import Any, Iterable


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _string(source: str, start: int) -> tuple[str, int, bool]:
    index = start + 1
    while index < len(source):
        if source[index] == '"':
            try:
                return json.loads(source[start:index + 1]), index + 1, True
            except json.JSONDecodeError:
                return "", index + 1, False
        if source[index] == "\\":
            index += 2
        else:
            index += 1
    # Decode only the completed prefix in memory. This value is used solely to
    # identify the open argument and is never included in the return object.
    prefix = source[start + 1:]
    while prefix.endswith("\\"):
        prefix = prefix[:-1]
    try:
        value = json.loads('"' + prefix + '"')
    except json.JSONDecodeError:
        value = ""
    return value, len(source), False


def _public_path(value: str | None) -> str | None:
    if not value or "\\" in value or "\x00" in value or value.startswith("/"):
        return None
    normalized = posixpath.normpath(value)
    if normalized in {".", ".."} or normalized.startswith("../"):
        return None
    return normalized


def classify_incomplete_action(
    visible_text: str,
    *,
    frozen_tools: Iterable[str],
) -> dict[str, Any]:
    """Return content-free lexical facts and the exact D1.4 class."""

    raw = visible_text.encode("utf-8", errors="strict")
    source = visible_text.lstrip()
    starts = source.startswith("{")
    stack: list[dict[str, Any]] = []
    top_keys: list[str] = []
    argument_keys: list[str] = []
    recovered: dict[tuple[str, ...], str] = {}
    open_argument = None
    inside_string = False
    maximum_depth = 0
    index = 0
    while starts and index < len(source):
        if source[index].isspace():
            index += 1
            continue
        char = source[index]
        if not stack:
            if char != "{":
                break
            stack.append({"path": (), "state": "key", "key": None})
            maximum_depth = 1
            index += 1
            continue
        frame = stack[-1]
        if frame["state"] == "key":
            if char == "}":
                stack.pop()
                index += 1
                continue
            if char != '"':
                break
            key, index, complete = _string(source, index)
            if not complete:
                inside_string = True
                break
            frame["key"] = key
            if frame["path"] == ():
                top_keys.append(key)
            elif frame["path"] == ("arguments",):
                argument_keys.append(key)
            frame["state"] = "colon"
            continue
        if frame["state"] == "colon":
            if char != ":":
                break
            frame["state"] = "value"
            index += 1
            continue
        if frame["state"] == "value":
            path = tuple(frame["path"]) + (frame["key"],)
            if char == '"':
                value, index, complete = _string(source, index)
                if path in {("tool",), ("arguments", "path")}:
                    recovered[path] = value
                if not complete:
                    inside_string = True
                    if frame["path"] == ("arguments",):
                        open_argument = frame["key"]
                    break
                frame.update(state="comma", key=None)
                continue
            if char == "{":
                frame.update(state="comma", key=None)
                stack.append({"path": path, "state": "key", "key": None})
                maximum_depth = max(maximum_depth, len(stack))
                index += 1
                continue
            end = index
            while end < len(source) and source[end] not in ",}":
                end += 1
            index = end
            frame.update(state="comma", key=None)
            continue
        if frame["state"] == "comma":
            if char == ",":
                frame["state"] = "key"
                index += 1
                continue
            if char == "}":
                stack.pop()
                index += 1
                continue
            break

    tool = recovered.get(("tool",))
    path = _public_path(recovered.get(("arguments", "path")))
    valid_prefix = starts and top_keys[:2] == ["tool", "arguments"] and tool in set(frozen_tools)
    if tool == "write_file" and open_argument == "content":
        classification = "SOLVE_TRUNCATED_WRITE_FILE_CONTENT"
        status = "CLASSIFIED_A"
    elif valid_prefix:
        classification = "SOLVE_TRUNCATED_OTHER_TOOL_ARGUMENT"
        status = "CLASSIFIED_B"
    else:
        classification = "SOLVE_TRUNCATED_NON_ACTION_TEXT"
        status = "CLASSIFIED_C"
    return {
        "classification": classification,
        "forensic_status": status,
        "visible_text_sha256": hashlib.sha256(raw).hexdigest(),
        "visible_text_bytes": len(raw),
        "utf8_valid": True,
        "starts_with_json_object": starts,
        "lexical_json_nesting_depth_at_truncation": len(stack),
        "maximum_lexical_json_nesting_depth": maximum_depth,
        "truncated_inside_json_string": inside_string,
        "top_level_key_names": top_keys,
        "tool_name": tool,
        "argument_key_names": argument_keys,
        "open_argument": open_argument,
        "path_value_sha256": _sha(path) if path else None,
        "public_benchmark_repository_path": path,
    }
