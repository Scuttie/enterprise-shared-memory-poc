"""Validate OPENAI_API_KEY bytes without performing network access."""
from __future__ import annotations

import argparse
import json
import os

from enterprise_memory.providers.openai_credential import (
    OpenAICredentialValidationError,
    validate_openai_api_key,
)


def validate_environment() -> dict[str, object]:
    present = "OPENAI_API_KEY" in os.environ
    try:
        raw = validate_openai_api_key(os.environ.get("OPENAI_API_KEY"))
    except OpenAICredentialValidationError as exc:
        return {
            "credential_present": present,
            "credential_format_valid": False,
            "failure_classification": exc.classification,
        }
    return {
        "credential_present": True,
        "credential_format_valid": True,
        "credential_bytes": len(raw),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = validate_environment()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    if result.get("credential_format_valid") is True:
        print("OPENAI_CREDENTIAL_FORMAT_PASS")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
