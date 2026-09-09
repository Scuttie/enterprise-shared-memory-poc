"""Trusted credential-free D1.15 full loader rehearsal collector.

Run only under the exact self-hosted POSIX surface.  The collector validates
the frozen compiled-prefix alias, creates fresh pinned harness checkouts, runs
the complete official-loader preflight, then invokes the production benchmark
evidence validator.  It never reads credentials or starts images, graders,
containers, task arms, or models.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_benchmark_run as benchmark_run  # noqa: E402
import trimem_compiled_prefix_alias as alias_contract  # noqa: E402
import trimem_development_trigger_d115 as d115  # noqa: E402
from trimem_harness_lock import prepare_harnesses  # noqa: E402
from trimem_official_harness_loader_preflight import (  # noqa: E402
    run_official_harness_loader_preflight,
)


class D115LoaderRehearsalError(RuntimeError):
    """The trusted full rehearsal could not be completed exactly."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _strict_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise D115LoaderRehearsalError(f"{label} has duplicate fields")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D115LoaderRehearsalError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise D115LoaderRehearsalError(f"{label} is not an object")
    return value


def _read_exact_repository_head(repository: Path) -> str:
    """Read HEAD while trusting only this exact cross-OS checkout path.

    Windows-owned DrvFS checkouts are intentionally not present in the WSL
    user's global ``safe.directory`` list.  Supply the one exact repository as
    protected command-scope configuration while disabling every ambient Git
    configuration and replacement-object input.
    """

    git_metadata = repository / ".git"
    if not git_metadata.is_dir() or git_metadata.is_symlink():
        raise D115LoaderRehearsalError(
            "exact loader rehearsal requires a standalone Git checkout"
        )
    environment = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": d115.WSL_COLLECTOR_HOME,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "LD_LIBRARY_PATH": d115.EXACT_PYTHON_LIBRARY_PATH,
        "PATH": d115.WSL_COLLECTOR_PATH,
    }
    try:
        completed = subprocess.run(
            [
                "/usr/bin/git",
                "--no-replace-objects",
                "-c",
                f"safe.directory={repository}",
                "-c",
                "core.fsmonitor=false",
                "-c",
                f"core.hooksPath={os.devnull}",
                "-C",
                str(repository),
                "rev-parse",
                "--verify",
                "HEAD^{commit}",
            ],
            cwd=repository,
            check=False,
            capture_output=True,
            text=False,
            timeout=30,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise D115LoaderRehearsalError(
            "rehearsal repository HEAD could not be read"
        ) from exc
    if completed.returncode != 0 or completed.stderr != b"":
        raise D115LoaderRehearsalError(
            "rehearsal repository HEAD could not be read"
        )
    try:
        observed = completed.stdout.decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise D115LoaderRehearsalError(
            "rehearsal repository HEAD is not canonical ASCII"
        ) from exc
    if not observed.endswith("\n") or observed.count("\n") != 1:
        raise D115LoaderRehearsalError(
            "rehearsal repository HEAD is not canonical ASCII"
        )
    head = observed[:-1]
    if d115.HEX40.fullmatch(head) is None:
        raise D115LoaderRehearsalError(
            "rehearsal repository HEAD is not canonical ASCII"
        )
    return head


def collect_exact_loader_rehearsal(
    *,
    repository: Path,
    source_head: str,
    runner_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    if os.name != "posix":
        raise D115LoaderRehearsalError("exact loader rehearsal requires POSIX")
    repository = repository.resolve(strict=True)
    observed_head = _read_exact_repository_head(repository)
    if observed_head != source_head:
        raise D115LoaderRehearsalError("rehearsal repository HEAD differs")
    validated_readiness = d115._validate_runner_readiness(
        runner_readiness, source_head=source_head
    )
    alias_evidence = alias_contract.validate_compiled_prefix_alias()
    exact_python = Path(str(alias_evidence["python_binary_realpath"]))
    with tempfile.TemporaryDirectory(prefix="trimem-d115-loader-") as directory:
        harnesses = prepare_harnesses(Path(directory) / "harnesses")
        preflight = run_official_harness_loader_preflight(
            python_binary=exact_python,
            swe_harness_root=harnesses["swebench_verified"],
            multi_harness_root=harnesses["multi_swe_bench_mini"],
        )
        benchmark_run.validate_official_harness_loader_preflight_evidence(
            preflight,
            python_binary=exact_python,
        )
        preflight_sha256 = hashlib.sha256(_canonical_bytes(preflight)).hexdigest()
        result = {
            "activation_actuals": dict(d115.ACTIVATION_ZERO_COUNTERS),
            "alias_evidence": alias_evidence,
            "benchmark_validation": {
                "preflight_sha256": preflight_sha256,
                "status": "PASS",
                "validator": (
                    "trimem_benchmark_run."
                    "validate_official_harness_loader_preflight_evidence"
                ),
            },
            "full_loader_preflight": preflight,
            "observed_at_utc": datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"
            ).replace("+00:00", "Z"),
            "repository": d115.EXPECTED_REPOSITORY,
            "runner_names": list(d115.RUNNER_NAMES),
            "runner_readiness_sha256": hashlib.sha256(
                _canonical_bytes(validated_readiness)
            ).hexdigest(),
            "schema": d115.LOADER_REHEARSAL_SCHEMA,
            "source_head": source_head,
            "status": "PASS",
        }
        # The same strict reader used by the request writer must accept the
        # collector output before it can leave this trusted POSIX process.
        d115.validate_loader_rehearsal(
            result,
            source_head=source_head,
            runner_readiness=validated_readiness,
        )
        return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--runner-readiness", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw_readiness = args.runner_readiness.read_bytes()
        readiness = _strict_object(raw_readiness, label="runner readiness")
        if raw_readiness != _canonical_bytes(readiness) + b"\n":
            raise D115LoaderRehearsalError(
                "runner readiness is not canonical UTF-8 plus one LF"
            )
        result = collect_exact_loader_rehearsal(
            repository=args.repository,
            source_head=args.source_head,
            runner_readiness=readiness,
        )
    except Exception as exc:
        failure = {
            "error": str(exc),
            "error_type": type(exc).__name__,
            "schema": d115.LOADER_REHEARSAL_SCHEMA,
            "status": "NOT_READY",
        }
        sys.stderr.buffer.write(_canonical_bytes(failure) + b"\n")
        return 1
    sys.stdout.buffer.write(_canonical_bytes(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
