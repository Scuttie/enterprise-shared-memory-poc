"""Verify the protected OpenAI key against its restricted run-bound HMAC."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from trimem_openai_model_access_check import (
    strict_json_object,
    verify_approval_credential_binding,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approval-file", type=Path, required=True)
    args = parser.parse_args()
    document = strict_json_object(args.approval_file.read_bytes())
    if not verify_approval_credential_binding(
        os.environ.get("OPENAI_API_KEY"), document
    ):
        print(json.dumps({"credential_binding": "FAIL"}, separators=(",", ":")))
        return 1
    print(json.dumps({"credential_binding": "PASS"}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
