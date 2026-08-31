#!/usr/bin/env python3
"""Verify the frozen Mini-SWE-Agent R0 scaffold from an existing checkout.

This verifier is credential-free and performs no clone, model, environment, or
Docker operation. Point it at a checkout already detached at the locked commit.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "artifacts" / "r23" / "agent_scaffold_lock.json"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def yaml_literal_block(text: str, section: str, key: str) -> str:
    """Extract a two-space-key YAML ``|`` scalar without adding a YAML dependency."""

    lines = text.splitlines()
    try:
        section_start = lines.index(section + ":") + 1
    except ValueError as error:
        raise ValueError("missing YAML section %s" % section) from error
    section_end = len(lines)
    for index in range(section_start, len(lines)):
        if lines[index] and not lines[index].startswith((" ", "\t")):
            section_end = index
            break
    marker = "  %s: |" % key
    try:
        block_start = lines.index(marker, section_start, section_end) + 1
    except ValueError as error:
        raise ValueError("missing literal block %s.%s" % (section, key)) from error
    values = []
    for line in lines[block_start:section_end]:
        if line and len(line) - len(line.lstrip(" ")) <= 2:
            break
        values.append(line[4:] if line.startswith("    ") else "")
    # YAML's default clip chomping preserves exactly one final newline.
    return "\n".join(values).rstrip("\n") + "\n"


def ast_assignment_and_function_hashes(path: Path) -> dict:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "BASH_TOOL" for target in node.targets)
    )
    parser = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "parse_toolcall_actions"
    )
    tool = ast.literal_eval(assignment.value)
    return {
        "tool_schema_canonical_sha256": canonical_sha256(tool),
        "tool_schema_source_sha256": sha256_bytes(ast.get_source_segment(source, assignment).encode("utf-8")),
        "tool_call_parser_source_sha256": sha256_bytes(ast.get_source_segment(source, parser).encode("utf-8")),
    }


def function_hash(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    return sha256_bytes(ast.get_source_segment(source, function).encode("utf-8"))


def git_value(checkout: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(checkout), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def verify(checkout: Path) -> dict:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if not (checkout / ".git").exists():
        raise ValueError("--checkout must point to a Mini-SWE-Agent git checkout")

    config_path = checkout / lock["config_path"]
    tool_path = checkout / lock["tool_source_path"]
    patch_parser_path = checkout / lock["patch_parser_source_path"]
    agent_loop_path = checkout / lock["agent_loop_source_path"]
    batch_path = checkout / lock["mount_and_image_route"]["batch_source_path"]
    config_text = config_path.read_text(encoding="utf-8")

    observed = {
        "commit": git_value(checkout, "rev-parse", "HEAD"),
        "config_git_blob": git_value(checkout, "rev-parse", "HEAD:" + lock["config_path"]),
        "config_sha256": sha256_bytes(config_path.read_bytes()),
        "system_prompt_sha256": sha256_bytes(yaml_literal_block(config_text, "agent", "system_template").encode()),
        "instance_prompt_sha256": sha256_bytes(yaml_literal_block(config_text, "agent", "instance_template").encode()),
        "observation_prompt_sha256": sha256_bytes(
            yaml_literal_block(config_text, "model", "observation_template").encode()
        ),
        "format_error_prompt_sha256": sha256_bytes(
            yaml_literal_block(config_text, "model", "format_error_template").encode()
        ),
        "tool_source_git_blob": git_value(checkout, "rev-parse", "HEAD:" + lock["tool_source_path"]),
        "tool_source_file_sha256": sha256_bytes(tool_path.read_bytes()),
        "patch_parser_source_git_blob": git_value(
            checkout, "rev-parse", "HEAD:" + lock["patch_parser_source_path"]
        ),
        "patch_parser_source_file_sha256": sha256_bytes(patch_parser_path.read_bytes()),
        "patch_parser_source_sha256": function_hash(patch_parser_path, "_check_finished"),
        "agent_loop_source_git_blob": git_value(checkout, "rev-parse", "HEAD:" + lock["agent_loop_source_path"]),
        "agent_loop_source_file_sha256": sha256_bytes(agent_loop_path.read_bytes()),
        "batch_source_git_blob": git_value(
            checkout, "rev-parse", "HEAD:" + lock["mount_and_image_route"]["batch_source_path"]
        ),
        "batch_source_file_sha256": sha256_bytes(batch_path.read_bytes()),
        "image_name_function_source_sha256": function_hash(batch_path, "get_swebench_docker_image_name"),
    }
    observed.update(ast_assignment_and_function_hashes(tool_path))

    step_line = next(line for line in config_text.splitlines() if line.strip().startswith("step_limit:"))
    observed["default_step_cap"] = int(step_line.split(":", 1)[1].strip())
    expected = {
        **{key: lock[key] for key in observed if key in lock},
        **{
            key: lock["mount_and_image_route"][key]
            for key in ("batch_source_git_blob", "batch_source_file_sha256", "image_name_function_source_sha256")
        },
    }
    mismatches = {
        key: {"expected": expected[key], "observed": value}
        for key, value in observed.items()
        if expected.get(key) != value
    }
    return {
        "status": "PASS" if not mismatches else "FAIL",
        "checkout": "USER_SUPPLIED_CHECKOUT",
        "observed": observed,
        "mismatches": mismatches,
        "model_calls": 0,
        "docker_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", required=True, type=Path)
    args = parser.parse_args()
    result = verify(args.checkout.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"status": "ERROR", "error_type": type(error).__name__, "error": str(error)}))
        raise SystemExit(2)
