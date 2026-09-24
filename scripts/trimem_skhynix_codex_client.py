"""Windows transport for the native Codex pilot's public action broker.

Send JSON as UTF-8 base64 to avoid PowerShell/native-argument quoting loss.
This program invokes only local WSL Python; it creates no model API client.
"""
import argparse
import base64
import json
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", choices=("A", "B", "C"), required=True)
    parser.add_argument("--request-base64", required=True)
    parser.add_argument("--base", default="/home/trimem-runner/skhynix-codex-001")
    args = parser.parse_args()
    raw = base64.b64decode(args.request_base64, validate=True)
    if len(raw) > 262144 or not isinstance(json.loads(raw), dict):
        raise ValueError("Expected a bounded JSON request object")
    if not args.base.startswith("/home/trimem-runner/") or any(x in args.base for x in ("..", "\\", "\x00")):
        raise ValueError("Unexpected pilot base")
    command = ["wsl.exe", "-d", "TriMemRunner2404", "--user", "trimem-runner", "--exec", "env",
               "LD_LIBRARY_PATH=/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib",
               "HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1",
               "/opt/trimem-rehearsals/e932-preflight/venv/bin/python",
               args.base + "/source/scripts/trimem_skhynix_codex.py", "action",
               "--run-root", args.base + "/execution", "--cell", args.cell,
               "--request-base64", args.request_base64]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    sys.stdout.buffer.write(result.stdout)
    if result.returncode:
        sys.stderr.buffer.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
