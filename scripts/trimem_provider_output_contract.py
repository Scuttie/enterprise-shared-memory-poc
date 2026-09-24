"""Build or verify the frozen TriMem provider-native output schemas."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from enterprise_memory.trimem.provider_output_contracts import (  # noqa: E402
    SCHEMAS,
    canonical_bytes,
    schema_sha256,
)


CONFIG = ROOT / "configs/trimem_v1/provider_output_schemas.json"
LOCK = ROOT / "artifacts/trimem_v1/provider_output_schema_lock.json"
SOURCE = ROOT / "src/enterprise_memory/trimem/provider_output_contracts.py"


def pretty(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def config_document() -> dict[str, Any]:
    return {
        "schema": "trimem/provider-output-schemas/1.0",
        "status": "FROZEN_PRE_RESULT_AMENDMENT",
        "schemas": {
            name: {
                "strict": True,
                "json_schema": json.loads(canonical_bytes(schema)),
                "json_schema_sha256": schema_sha256(schema),
            }
            for name, schema in sorted(SCHEMAS.items())
        },
        "role_bindings": {
            "decompose": "trimem_decomposition_v1",
            "extract": "trimem_experience_extraction_v1",
            "solve": None,
        },
    }


def lock_document(config_raw: bytes) -> dict[str, Any]:
    return {
        "schema": "trimem/provider-output-schema-lock/1.0",
        "status": "FROZEN_PRE_RESULT_AMENDMENT",
        "classification": "PRE_RESULT_PROVIDER_OUTPUT_CONTRACT_AMENDMENT",
        "config_path": CONFIG.relative_to(ROOT).as_posix(),
        "config_sha256": hashlib.sha256(config_raw).hexdigest(),
        "source_path": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "schema_sha256": {
            name: schema_sha256(schema) for name, schema in sorted(SCHEMAS.items())
        },
        "arm_contract": {
            "arms": ["M0", "M1", "M2"],
            "identical_role_bindings": True,
            "source_of_truth": "enterprise_memory.trimem.provider_output_contracts.SCHEMAS",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    config_raw = pretty(config_document())
    lock_raw = pretty(lock_document(config_raw))
    if args.write:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_bytes(config_raw)
        LOCK.write_bytes(lock_raw)
        return 0
    if not CONFIG.is_file() or CONFIG.read_bytes() != config_raw:
        raise SystemExit("provider output schema config drift")
    if not LOCK.is_file() or LOCK.read_bytes() != lock_raw:
        raise SystemExit("provider output schema lock drift")
    print("provider output schema lock: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
