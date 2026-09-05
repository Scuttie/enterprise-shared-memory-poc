"""One protected real-provider native-action canary for approved DEV only."""
from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from enterprise_memory.providers.base import ModelRequest, ProviderError, SINGLE_FUNCTION_CALL
from enterprise_memory.providers.openai_responses import (
    OpenAIResponsesProvider,
    RestrictedProviderResponseStore,
)
from enterprise_memory.trimem.accounting import canonical_bytes, sha256_bytes
from enterprise_memory.trimem.function_tools import (
    FUNCTION_TOOLS_SHA256,
    detached_function_tools,
)
from enterprise_memory.trimem.gateway import GatewayResponse, parse_function_action
from enterprise_memory.trimem.workspace import InMemoryRepositoryWorkspace
from trimem_benchmark_run import validate_exec_approval
from trimem_development_phase_cap import (
    PROTOCOL_CANARY_INPUT_RESERVATION,
    PROTOCOL_CANARY_OUTPUT_RESERVATION,
    validate_development_phase_hard_cap,
)


MODEL = "gpt-5.4-mini-2026-03-17"
INPUT_CAP = PROTOCOL_CANARY_INPUT_RESERVATION
OUTPUT_CAP = PROTOCOL_CANARY_OUTPUT_RESERVATION
LOGICAL_ID = "TRIMEM_V1_D16_PROTOCOL_CANARY_0001"


class EnvironmentSecret:
    def get(self, name: str) -> str | None:
        return os.environ.get(name)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(value) + b"\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def _run_strict(output: Path, approval_path: Path) -> dict[str, Any]:
    if output.exists():
        raise RuntimeError("protocol canary output already exists")
    validated = validate_exec_approval("development", approval_path)
    if validated["phase"] != "DEVELOPMENT_TUNING":
        raise RuntimeError("protocol canary phase differs")
    hard = validate_development_phase_hard_cap(
        validated["hard_cap"],
        protocol_canary_input_reservation=INPUT_CAP,
        protocol_canary_output_reservation=OUTPUT_CAP,
    )
    approval_binding = validated["approval"]
    approval_sha256 = validated["approval_artifact_sha256"]
    if not isinstance(approval_binding, dict):
        raise RuntimeError("protocol canary approval binding is missing")
    restricted = output.parent / "restricted" / "protocol-canary"
    prompt = (
        "Protocol canary only. Call list_files exactly once for the tiny local "
        "synthetic workspace. Do not emit a message."
    )
    request = ModelRequest(
        messages=[{"role": "user", "content": prompt}],
        max_output_tokens=OUTPUT_CAP,
        response_mode=SINGLE_FUNCTION_CALL,
        function_tools=detached_function_tools(),
        function_tools_sha256=FUNCTION_TOOLS_SHA256,
        tool_choice={"type": "function", "name": "list_files"},
        parallel_tool_calls=False,
    )
    async def generate():
        async with httpx.AsyncClient() as client:
            provider = OpenAIResponsesProvider(
                "https://api.openai.com/v1",
                MODEL,
                EnvironmentSecret(),
                family="gpt5.4",
                reasoning_effort="medium",
                max_retries=1,
                http_client=client,
                raw_response_recorder=RestrictedProviderResponseStore(restricted),
            )
            return await provider.generate(
                request,
                logical_request_id=LOGICAL_ID,
                org_id="protocol-canary",
            )

    try:
        response, record = asyncio.run(generate())
    except ProviderError as failure:
        record = failure.record
        envelope = getattr(record, "response_envelope", None)
        write_json(output, {
            "schema": "trimem/protocol-action-canary/1.0",
            "status": "FAIL",
            "scientific_result": False,
            "global_integrity_failure": True,
            "generation_calls": 1,
            "failure_class": getattr(record, "final_status", "PROVIDER_FAILURE"),
            "provider_response_envelope": (
                envelope.to_public_dict() if envelope is not None else None
            ),
        })
        raise RuntimeError("protocol canary failed closed") from failure
    envelope = response.envelope
    if envelope is None or not envelope.provider_reported_usage_available:
        raise RuntimeError("protocol canary lacks exact provider usage")
    if response.returned_model != MODEL:
        raise RuntimeError("protocol canary returned-model mismatch")
    if (
        int(envelope.input_tokens or 0) > INPUT_CAP
        or int(envelope.output_tokens or 0) > OUTPUT_CAP
        or int(envelope.cached_input_tokens or 0) > int(envelope.input_tokens or 0)
    ):
        raise RuntimeError("protocol canary usage exceeded its reservation")
    gateway_response = GatewayResponse(
        text=response.text,
        provider="openai-responses",
        model=MODEL,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cached_input_tokens=envelope.cached_input_tokens,
        reasoning_tokens=envelope.reasoning_tokens,
        wall_time_ms=max(0, int(round(float(record.total_latency or 0) * 1000))),
        paid=True,
        response_mode=response.response_mode,
        output_items=tuple(item.to_public_dict() for item in response.output_items),
        function_call_id=response.function_call_id,
        function_name=response.function_name,
        function_arguments=response.function_arguments,
        function_arguments_sha256=response.function_arguments_sha256,
    )
    name, arguments = parse_function_action(
        gateway_response,
        {str(tool["name"]) for tool in detached_function_tools()},
    )
    if name != "list_files" or arguments != {}:
        raise RuntimeError("protocol canary did not produce list_files({})")
    workspace = InMemoryRepositoryWorkspace(
        {"README.md": "synthetic protocol canary\n"},
        editable_paths=("README.md",),
    )
    tool_result = workspace.execute(name, arguments)
    if tool_result != {"files": ["README.md"]}:
        raise RuntimeError("protocol canary function execution failed")
    input_tokens = int(envelope.input_tokens)
    cached_tokens = int(envelope.cached_input_tokens)
    output_tokens = int(envelope.output_tokens)
    usd = (
        Decimal(input_tokens - cached_tokens) * Decimal("0.75")
        + Decimal(cached_tokens) * Decimal("0.075")
        + Decimal(output_tokens) * Decimal("4.50")
    ) / Decimal(1_000_000)
    result = {
        "schema": "trimem/protocol-action-canary/1.0",
        "status": "PASS",
        "scientific_result": False,
        "logical_call_id": LOGICAL_ID,
        "approval_sha256": approval_sha256,
        "model": MODEL,
        "reasoning_effort": "medium",
        "generation_calls": 1,
        "input_token_cap": INPUT_CAP,
        "output_token_cap": OUTPUT_CAP,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": int(envelope.reasoning_tokens),
        "actual_usd": format(usd, ".12f"),
        "function_tools_sha256": FUNCTION_TOOLS_SHA256,
        "tool_choice": {"type": "function", "name": "list_files"},
        "parallel_tool_calls": False,
        "function_name": name,
        "argument_bytes": len((response.function_arguments or "").encode("utf-8")),
        "argument_sha256": response.function_arguments_sha256,
        "tool_result_sha256": sha256_bytes(canonical_bytes(tool_result)),
        "provider_response_envelope": envelope.to_public_dict(),
        "raw_evidence_root": restricted.relative_to(output.parents[4]).as_posix(),
    }
    write_json(output, result)
    return result


def run(output: Path, approval_path: Path) -> dict[str, Any]:
    try:
        return _run_strict(output, approval_path)
    except Exception as exc:
        if not output.exists():
            write_json(output, {
                "schema": "trimem/protocol-action-canary/1.0",
                "status": "FAIL",
                "scientific_result": False,
                "global_integrity_failure": True,
                "generation_calls": 0,
                "failure_class": type(exc).__name__,
            })
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approval-file", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output.resolve(), args.approval_file.resolve())
    print(json.dumps({
        "status": result["status"],
        "generation_calls": 1,
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "actual_usd": result["actual_usd"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
