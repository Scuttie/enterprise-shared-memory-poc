#!/usr/bin/env python
"""Optional live Solar smoke (one fictional-data request). Runs only when UPSTAGE_API_KEY is set. Never
prints the key; never runs research benchmarks. Fictional inputs only."""
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from enterprise_memory.providers.solar import SolarProvider          # noqa: E402
from enterprise_memory.providers.secrets import EnvSecretProvider    # noqa: E402
from enterprise_memory.providers.base import ModelRequest            # noqa: E402


async def main():
    if not os.environ.get("UPSTAGE_API_KEY"):
        print("no UPSTAGE_API_KEY -> skip"); return 0
    provider = SolarProvider(os.environ.get("SOLAR_BASE_URL", "https://api.upstage.ai/v1"),
                             os.environ.get("SOLAR_MODEL", "solar-pro2-251215"),
                             EnvSecretProvider(environment="test"), key_name="UPSTAGE_API_KEY",
                             max_output_tokens=64, max_attempts=2)
    req = ModelRequest(messages=[{"role": "user", "content":
                                  "Return the single word OK for this fictional connectivity check."}],
                       max_output_tokens=16)
    try:
        resp, rec = await provider.generate(req, logical_request_id="live-smoke", org_id="smoke")
        out = {"ok": True, "returned_model": rec.returned_model, "attempts": rec.attempts,
               "total_tokens": rec.total_tokens, "redaction_status": rec.redaction_status,
               "finish_reason": rec.finish_reason}
    finally:
        await provider.aclose()
    print(json.dumps(out))            # no key, no raw prompt/response
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
