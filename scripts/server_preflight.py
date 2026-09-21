"""Check that this host can run the SK hynix memory experiment.

Every check is read-only. Nothing is downloaded, started, solved or graded.
Run it after unpacking the repository and again after the port work:

    python3.11 scripts/server_preflight.py
    python3.11 scripts/server_preflight.py --vllm-url http://localhost:8000/v1
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parent.parent
BANK_ROOT = REPO / "artifacts" / "skhynix_v1" / "architecture_scale_001" / "frozen-bank-240"
REQUIRED_PATHS = (
    "scripts/trimem_skhynix_architecture_native.py",
    "scripts/trimem_skhynix_architecture_broker.py",
    "scripts/trimem_skhynix_architecture_run.py",
    "scripts/trimem_skhynix_architecture_memory.py",
    "scripts/trimem_skhynix_verify_portable_bank.py",
    "configs/skhynix_v1/architecture_scale_001/protocol.json",
    "artifacts/skhynix_v1/architecture_scale_001/frozen-bank-240/pipeline-v15/bank-240/bank.json",
)
# Weights alone, before runtime and KV-cache overhead.
MODEL_WEIGHT_GIB = {"GLM-5.3-Flash (FP8)": 306, "GLM-5.3 (FP8)": 860}


def result(name, ok, detail, *, advice=None):
    return {"check": name, "status": "PASS" if ok else "FAIL", "detail": detail,
            **({"advice": advice} if advice and not ok else {})}


def check_python():
    version = "%d.%d.%d" % sys.version_info[:3]
    ok = sys.version_info[:2] == (3, 11)
    return result("Python 3.11", ok, "running " + version,
                  advice="The pinned runtime is 3.11; other versions are untested here.")


def check_files():
    missing = [name for name in REQUIRED_PATHS if not (REPO / name).is_file()]
    return result("Required files", not missing,
                  "all %d present" % len(REQUIRED_PATHS) if not missing
                  else "missing: " + ", ".join(missing),
                  advice="The archive is incomplete. Download the repository again.")


def check_bank():
    verifier = REPO / "scripts" / "trimem_skhynix_verify_portable_bank.py"
    if not verifier.is_file():
        return result("Frozen memory bank", False, "verifier script is missing")
    process = subprocess.run([sys.executable, str(verifier)], capture_output=True, text=True)
    try:
        report = json.loads(process.stdout)
    except ValueError:
        return result("Frozen memory bank", False, "verifier produced no readable report",
                      advice="Run the verifier directly to see its error.")
    ok = report.get("status") == "PASS"
    return result("Frozen memory bank", ok,
                  "%s, %s references checked, %s failures" % (
                      report.get("status"), report.get("references_checked"),
                      report.get("failure_count")),
                  advice="Without an intact bank the ON arm cannot run at all.")


def check_docker():
    if shutil.which("docker") is None:
        return result("Docker", False, "docker not on PATH",
                      advice="Official SWE-bench grading needs per-instance images.")
    process = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                             capture_output=True, text=True)
    ok = process.returncode == 0
    return result("Docker", ok,
                  "daemon reachable, server " + process.stdout.strip() if ok
                  else "docker is installed but the daemon did not answer",
                  advice="Start the daemon, or add this user to the docker group.")


def check_gpu():
    if shutil.which("nvidia-smi") is None:
        return result("GPU", False, "nvidia-smi not on PATH",
                      advice="Serving GLM locally needs NVIDIA GPUs visible to this host.")
    process = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
        capture_output=True, text=True)
    if process.returncode != 0 or not process.stdout.strip():
        return result("GPU", False, "nvidia-smi did not report any device")
    rows = [line.split(",") for line in process.stdout.strip().splitlines()]
    total_gib = sum(int(row[1]) for row in rows) / 1024
    names = ", ".join(sorted({row[0].strip() for row in rows}))
    fits = [name for name, need in MODEL_WEIGHT_GIB.items() if total_gib >= need]
    detail = "%d device(s) (%s), %.0f GiB total" % (len(rows), names, total_gib)
    if fits:
        return result("GPU", True, detail + " — weights fit: " + ", ".join(fits))
    smallest = min(MODEL_WEIGHT_GIB.items(), key=lambda item: item[1])
    return result("GPU", False, detail,
                  advice="%s alone needs about %d GiB; add GPUs, use larger cards, or quantise "
                         "(quantising changes the model under evaluation and must be reported)."
                         % (smallest[0], smallest[1]))


def check_vllm(url):
    if not url:
        return {"check": "vLLM endpoint", "status": "SKIP",
                "detail": "not requested; pass --vllm-url once the server is up"}
    import urllib.request
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/models", timeout=10) as response:
            payload = json.loads(response.read())
    except Exception as exc:
        return result("vLLM endpoint", False, "%s: %s" % (type(exc).__name__, exc),
                      advice="Start vllm serve with --tool-call-parser glm47 "
                             "--enable-auto-tool-choice, then re-run.")
    served = [row.get("id") for row in payload.get("data", [])]
    return result("vLLM endpoint", bool(served), "serving: " + ", ".join(map(str, served))
                  if served else "endpoint answered but serves no model")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vllm-url", default=None,
                        help="OpenAI-compatible base URL, e.g. http://localhost:8000/v1")
    arguments = parser.parse_args()

    checks = [check_python(), check_files(), check_bank(),
              check_docker(), check_gpu(), check_vllm(arguments.vllm_url)]
    failed = [row for row in checks if row["status"] == "FAIL"]

    width = max(len(row["check"]) for row in checks)
    print()
    for row in checks:
        print("  [%-4s] %-*s  %s" % (row["status"], width, row["check"], row["detail"]))
        if "advice" in row:
            print("  %s   -> %s" % (" " * width, row["advice"]))
    print()
    print("  %d passed, %d failed, %d skipped" % (
        sum(row["status"] == "PASS" for row in checks), len(failed),
        sum(row["status"] == "SKIP" for row in checks)))
    print()
    print("  This checks the environment only. It does not verify that the model can")
    print("  actually drive the MCP tool - that needs the one-task smoke run in")
    print("  docs/port/AGENT_BRIEF.md before any full arm is started.")
    print()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
