"""One-shot, credential-free contract probe for the frozen Vue smoke image.

This is deliberately not an evaluator.  It never loads a dataset payload,
applies a patch, or runs a test command.  Its only container invocation checks
the paths baked into the immutable image and the repository HEAD prepared by
the official image recipe.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "configs/trimem_v1/grader_smoke_manifest.json"
IMAGE_LOCK_PATH = ROOT / "artifacts/trimem_v1/grader_image_lock.json"

INSTANCE_ID = "vuejs__core-8911"
BENCHMARK_ID = "multi_swe_bench_mini"
REPOSITORY = "vuejs/core"
REPOSITORY_PATH = "/home/core"
EXPECTED_BASE_COMMIT = "3be4e3cbe34b394096210897c1be8deeb6d748d8"
EXPECTED_IMAGE = (
    "mswebench/vuejs_m_core@sha256:"
    "2883a52a2eb4054e820dc3a88f9fb0b93fbef7ce10801a57e718f1c6d9f8e9c1"
)
EXPECTED_TAG = "mswebench/vuejs_m_core:pr-8911"
REQUIRED_PATHS = ("/home/fix-run.sh", "/home/test.patch")
FAIL_ENDPOINT = "TRIMEM_MULTI_SWE_PREBUILT_IMAGE_CONTRACT_FAIL"
HEX40 = re.compile(r"[0-9a-f]{40}")


class ImageProbeError(RuntimeError):
    """The frozen image or the read-only contract probe differed."""

    def __init__(self, message: str, *, report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report = report


def _strict_object(path: Path) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise ImageProbeError(f"duplicate JSON key in {path.name}: {key}")
            value[key] = child
        return value

    try:
        value = json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=object_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImageProbeError(f"cannot load exact JSON contract: {path.name}") from exc
    if not isinstance(value, dict):
        raise ImageProbeError(f"JSON contract is not an object: {path.name}")
    return value


def _frozen_contract() -> dict[str, str]:
    manifest = _strict_object(MANIFEST_PATH)
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        raise ImageProbeError("grader-smoke manifest has no target rows")
    vue_rows = [
        row
        for row in targets
        if isinstance(row, dict)
        and row.get("benchmark_id") == BENCHMARK_ID
        and row.get("instance_id") == INSTANCE_ID
    ]
    if (
        len(vue_rows) != 2
        or [row.get("probe") for row in vue_rows] != ["GOLD", "NOOP_BASELINE"]
        or any(row.get("base_commit") != EXPECTED_BASE_COMMIT for row in vue_rows)
        or any(row.get("repository") != REPOSITORY for row in vue_rows)
    ):
        raise ImageProbeError("frozen Vue GOLD/NOOP identity pair differs")

    image_lock = _strict_object(IMAGE_LOCK_PATH)
    locked = image_lock.get("targets")
    if not isinstance(locked, list):
        raise ImageProbeError("grader image lock has no smoke targets")
    rows = [
        row
        for row in locked
        if isinstance(row, dict)
        and row.get("benchmark_id") == BENCHMARK_ID
        and row.get("instance_id") == INSTANCE_ID
    ]
    if len(rows) != 1:
        raise ImageProbeError("frozen Vue image lock row is missing or duplicated")
    row = rows[0]
    expected_digest = EXPECTED_IMAGE.rsplit("@", 1)[1]
    if (
        row.get("image") != EXPECTED_IMAGE
        or row.get("harness_image_tag") != EXPECTED_TAG
        or row.get("expected_digest") != expected_digest
    ):
        raise ImageProbeError("frozen Vue image identity differs")
    return {
        "base_commit": EXPECTED_BASE_COMMIT,
        "expected_digest": expected_digest,
        "image": EXPECTED_IMAGE,
        "tag": EXPECTED_TAG,
    }


def _run(argv: Sequence[str], *, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ImageProbeError(f"Docker probe command could not complete: {argv[1]}") from exc
    if completed.returncode != 0:
        raise ImageProbeError(f"Docker probe stage failed closed: {argv[1]}")
    return completed


def _observed_digests(image: str) -> list[str]:
    completed = _run(
        ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image]
    )
    try:
        values = json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        raise ImageProbeError("Docker returned malformed RepoDigests JSON") from exc
    if not isinstance(values, list):
        raise ImageProbeError("Docker RepoDigests is not a list")
    return sorted(
        {
            str(value).rsplit("@", 1)[-1]
            for value in values
            if isinstance(value, str) and "@sha256:" in value
        }
    )


def _inside_image(tag: str) -> tuple[dict[str, bool], bool, str]:
    # The command tests metadata only.  It never reads either patch and never
    # invokes fix-run.sh, test.patch, a package command, or an official test.
    script = (
        "set -eu; "
        "test -f /home/fix-run.sh; "
        "test -f /home/test.patch; "
        "test -d /home/core/.git; "
        "printf 'fix_run=true\\ntest_patch=true\\nrepository_checkout=true\\n'; "
        "git -C /home/core rev-parse HEAD"
    )
    completed = _run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=64",
            "--no-healthcheck",
            "--entrypoint",
            "/bin/sh",
            tag,
            "-c",
            script,
        ]
    )
    lines = completed.stdout.splitlines()
    if len(lines) != 4 or lines[:3] != [
        "fix_run=true",
        "test_patch=true",
        "repository_checkout=true",
    ]:
        raise ImageProbeError("image path-probe output is not exact")
    head = lines[3].strip()
    if HEX40.fullmatch(head) is None:
        raise ImageProbeError("image repository HEAD is not a commit SHA")
    return {
        "/home/fix-run.sh": True,
        "/home/test.patch": True,
    }, True, head


def _reference_absent(reference: str) -> bool:
    completed = subprocess.run(
        ["docker", "image", "inspect", reference],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if completed.returncode == 0:
        return False
    if completed.returncode == 1 and "no such image" in completed.stderr.lower():
        return True
    raise ImageProbeError("cannot establish exact post-probe image removal state")


def _cleanup(image: str, tag: str) -> dict[str, Any]:
    present = [reference for reference in (tag, image) if not _reference_absent(reference)]
    if present:
        completed = subprocess.run(
            ["docker", "image", "rm", "--force", *present],
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        if completed.returncode != 0:
            raise ImageProbeError("exact Vue image cleanup failed")
    tag_absent = _reference_absent(tag)
    digest_absent = _reference_absent(image)
    if not tag_absent or not digest_absent:
        raise ImageProbeError("Vue image references remain after cleanup")
    return {
        "digest_reference_absent": digest_absent,
        "removal_established": True,
        "removed_reference_count": len(present),
        "tag_reference_absent": tag_absent,
    }


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def run_probe() -> dict[str, Any]:
    # Start from non-secret constants so even a local freeze/manifest failure
    # can produce the same sanitized evidence shape and terminal failure label.
    contract = {
        "base_commit": EXPECTED_BASE_COMMIT,
        "expected_digest": EXPECTED_IMAGE.rsplit("@", 1)[1],
        "image": EXPECTED_IMAGE,
        "tag": EXPECTED_TAG,
    }
    observed: list[str] = []
    paths = {path: False for path in REQUIRED_PATHS}
    repository_checkout = False
    repository_head = "UNKNOWN"
    removal = {
        "digest_reference_absent": False,
        "removal_established": False,
        "removed_reference_count": 0,
        "tag_reference_absent": False,
    }
    probe_error: ImageProbeError | None = None
    pull_attempted = False
    try:
        contract = _frozen_contract()
        pull_attempted = True
        _run(["docker", "pull", contract["image"]])
        observed = _observed_digests(contract["image"])
        if observed != [contract["expected_digest"]]:
            raise ImageProbeError("observed Vue image digest differs")
        _run(["docker", "tag", contract["image"], contract["tag"]], timeout=120)
        paths, repository_checkout, repository_head = _inside_image(contract["tag"])
        if repository_head != contract["base_commit"]:
            raise ImageProbeError("image repository HEAD differs from frozen base")
    except ImageProbeError as exc:
        probe_error = exc
    finally:
        if pull_attempted:
            try:
                removal = _cleanup(contract["image"], contract["tag"])
            except (ImageProbeError, OSError, subprocess.SubprocessError) as exc:
                removal["removal_established"] = False
                if probe_error is None:
                    probe_error = ImageProbeError(str(exc))
                else:
                    probe_error = ImageProbeError(
                        f"{probe_error}; exact Vue image cleanup also failed"
                    )

    status = "PASS" if probe_error is None else "FAIL"
    report = {
        "expected_digest": contract["expected_digest"],
        "observed_digests": observed,
        "removal_evidence": removal,
        "repository": {
            "base_commit": contract["base_commit"],
            "checkout_present": repository_checkout,
            "head": repository_head,
            "path": REPOSITORY_PATH,
        },
        "required_paths_present": paths,
        "schema": "trimem/multi-swe-prebuilt-image-contract-probe/1.0",
        "status": status,
    }
    if probe_error is not None:
        report["endpoint"] = FAIL_ENDPOINT
        raise ImageProbeError(
            FAIL_ENDPOINT + ": " + str(probe_error),
            report=report,
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    status = "PASS"
    error: ImageProbeError | None = None
    try:
        report = run_probe()
    except ImageProbeError as exc:
        status = "FAIL"
        error = exc
        report = exc.report
    try:
        if report is None:
            raise ImageProbeError("probe failed before sanitized evidence was available")
        raw = _canonical_json(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(raw)
        print(
            json.dumps(
                {
                    "output_sha256": hashlib.sha256(raw).hexdigest(),
                    "status": status,
                },
                sort_keys=True,
            )
        )
        if error is not None:
            print(
                json.dumps(
                    {"endpoint": FAIL_ENDPOINT, "error": str(error), "status": "FAIL"},
                    sort_keys=True,
                )
            )
            return 1
        return 0
    except (ImageProbeError, OSError) as exc:
        print(
            json.dumps(
                {"endpoint": FAIL_ENDPOINT, "error": str(exc), "status": "FAIL"},
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
