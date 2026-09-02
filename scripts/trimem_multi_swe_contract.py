"""Verify the exact pinned Multi-SWE evaluation contract from Git objects.

The verifier reads the upstream checkout's object database.  It neither
imports nor copies upstream source into this repository and it performs no
Docker, dataset, grader, or model operation.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "artifacts/trimem_v1/multi_swe_evaluation_contract_lock.json"
ENTRYPOINT_PATH = ROOT / "scripts/trimem_multi_swe_entrypoint.py"
PINNED_ORIGIN = "https://github.com/multi-swe-bench/multi-swe-bench"
PINNED_REVISION = "24f493f8a103e72312ded4f6b9c89f081d69cb09"
SHA256 = re.compile(r"[0-9a-f]{64}")


class ContractError(ValueError):
    """Pinned Git material or its locked semantic contract differs."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _git(
    repository: Path, *args: str, text: bool = True
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=repository,
        capture_output=True,
        text=text,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        raise ContractError(f"pinned Git object query failed: {stderr.strip()}")
    return result


def _strict_lock() -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            _require(key not in value, f"duplicate contract-lock key: {key}")
            value[key] = child
        return value

    try:
        value = json.loads(
            LOCK_PATH.read_bytes().decode("utf-8"), object_pairs_hook=object_pairs
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("Multi-SWE contract lock is not strict UTF-8 JSON") from exc
    _require(isinstance(value, dict), "Multi-SWE contract lock root is not an object")
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _origin_matches(value: str) -> bool:
    normalized = value.strip().removesuffix(".git").removesuffix("/")
    return normalized == PINNED_ORIGIN


def _source_text(blobs: dict[str, bytes], path: str) -> str:
    try:
        return blobs[path].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"pinned source blob is not UTF-8: {path}") from exc


def _ordered(text: str, fragments: Sequence[str], *, label: str) -> None:
    cursor = -1
    for fragment in fragments:
        position = text.find(fragment, cursor + 1)
        _require(position >= 0, f"pinned {label} contract fragment is missing")
        _require(position > cursor, f"pinned {label} control-flow order differs")
        cursor = position


def _verify_control_flow(blobs: dict[str, bytes]) -> None:
    run = _source_text(blobs, "multi_swe_bench/harness/run_evaluation.py")
    report = _source_text(blobs, "multi_swe_bench/harness/gen_report.py")
    session = _source_text(blobs, "multi_swe_bench/utils/session_util.py")
    image = _source_text(blobs, "multi_swe_bench/harness/image.py")
    vue = _source_text(
        blobs, "multi_swe_bench/harness/repos/typescript/vuejs/core.py"
    )

    _require(
        re.search(
            r'--human_mode[\s\S]{0,260}?default=True', run
        )
        is not None,
        "pinned human_mode parser default is not true",
    )
    _require(
        re.search(r'class CliArgs:[\s\S]{0,900}?human_mode: bool = True', run)
        is not None,
        "pinned CliArgs human_mode default is not true",
    )
    _require(
        re.search(r'--force_build[\s\S]{0,260}?default=False', run) is not None,
        "pinned force_build parser default is not false",
    )
    _ordered(
        run,
        (
            "if not self.force_build and docker_util.exists(image.image_full_name()):",
            "return",
            "image_dir.mkdir(parents=True, exist_ok=True)",
            "image.dockerfile()",
            "for file in image.files():",
            "docker_util.build(",
        ),
        label="existing-image short circuit",
    )
    _ordered(
        run,
        (
            "if not self.human_mode:",
            "from multi_swe_bench.utils.session_util import run_and_save_logs",
            '"prepare.sh"',
            "run_and_save_logs(",
            "else:",
            "run_and_save_output(",
        ),
        label="human-mode dispatch",
    )
    _ordered(
        run,
        (
            "output = docker_util.run(",
            "volumes={",
            '"bind": instance.dependency().fix_patch_path()',
            '"mode": "rw"',
        ),
        label="submitted-patch volume",
    )
    _require(
        re.search(
            r'def run\(self\):[\s\S]{0,500}?elif self\.mode == "instance_only":'
            r'[\s\S]{0,120}?self\.run_mode_instance_only\(\)',
            run,
        )
        is not None,
        "pinned instance_only dispatch differs",
    )
    instance_only = re.search(
        r"    def run_mode_instance_only\(self\):(?P<body>[\s\S]*?)\n    def run_mode_instance\(self\):",
        run,
    )
    _require(instance_only is not None, "pinned run_mode_instance_only body is missing")
    assert instance_only is not None
    for forbidden in ("run_mode_image", "check_commit_hashes", "build_image"):
        _require(
            forbidden not in instance_only.group("body"),
            f"pinned instance_only unexpectedly enters source-image path: {forbidden}",
        )
    _require(
        re.search(
            r"def run_mode_instance\(self\):\s+self\.run_mode_image\(\)\s+"
            r"self\.run_mode_instance_only\(\)",
            run,
        )
        is not None,
        "pinned full instance mode no longer enters image construction first",
    )
    _require(
        re.search(
            r"def run_mode_evaluation\(self\):\s+self\.run_mode_instance\(\)", run
        )
        is not None,
        "pinned full evaluation no longer enters the image phase",
    )
    _ordered(
        run,
        (
            "external_images: set[str] = set()",
            "required_image = instance.dependency()",
            "external_images.add(parent_image_name)",
            "for external_name in external_images:",
            "building_images.add(image)",
            "executor.submit(self.build_image, image)",
        ),
        label="full-evaluation dependency-image build risk",
    )
    _require(
        "with open(prepare_script_path) as f:" in session,
        "false-mode host prepare.sh read contract differs",
    )
    _require(
        'return "/home/fix.patch"' in image,
        "dependency fix-patch destination differs",
    )
    for component in (
        '"fix.patch"',
        '"test.patch"',
        '"prepare.sh"',
        '"fix-run.sh"',
        "RUN bash /home/prepare.sh",
        "git checkout {pr.base.sha}",
    ):
        _require(component in vue, f"pinned Vue recipe component differs: {component}")
    _require(
        re.search(r'--mode[\s\S]{0,220}?choices=\["dataset", "evaluation", "summary", "regen"\]', report)
        is not None,
        "pinned report mode choices differ",
    )
    _ordered(
        report,
        (
            "def run_evaluation(self):",
            "self.collect_report_tasks(EVALUATION_WORKDIR)",
            "self.gen_eval_reports(tasks)",
            "FinalReport.from_reports(reports, invalid_reports, failed_tasks)",
            "self.output_dir / FINAL_REPORT_FILE",
            "final_report.to_json(indent=4, ensure_ascii=False)",
        ),
        label="separate official evaluation report",
    )
    _require(
        re.search(
            r'def run\(self\):[\s\S]{0,350}?elif self\.mode == "evaluation":'
            r"[\s\S]{0,100}?self\.run_evaluation\(\)",
            report,
        )
        is not None,
        "pinned gen_report evaluation dispatch differs",
    )
    _require(
        "docker_util" not in report and "docker.from_env" not in report,
        "pinned report phase unexpectedly gained a Docker execution path",
    )
    _ordered(
        run,
        (
            'if __name__ == "__main__":',
            "client = docker.from_env()",
            'client.containers.get("nix_swe")',
            'client.containers.run("mswebench/nix_swe:v1.0", "true", name="nix_swe")',
            "sys.exit(1)",
            "parser = get_parser()",
            "args = parser.parse_args()",
            "cli = CliArgs.from_dict(vars(args))",
            "cli.run()",
        ),
        label="module-main nix_swe bootstrap before argument parsing",
    )


def _call_name(node: ast.Call) -> str:
    parts: list[str] = []
    value: ast.expr = node.func
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def _verify_production_entrypoint(contracts: dict[str, Any]) -> dict[str, Any]:
    try:
        raw = ENTRYPOINT_PATH.read_bytes()
        source = raw.decode("utf-8")
        tree = ast.parse(source, filename=str(ENTRYPOINT_PATH))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise ContractError("production Multi-SWE entrypoint is not valid UTF-8 Python") from exc

    observed = {
        "bytes": len(raw),
        "invocation": (
            "python scripts/trimem_multi_swe_entrypoint.py "
            "--harness-root <pinned-checkout> --config <one-row-config>"
        ),
        "library_dispatch": (
            "execute_pinned_instance_only -> pinned get_parser -> "
            "CliArgs.from_dict -> CliArgs.run -> run_mode_instance_only"
        ),
        "path": ENTRYPOINT_PATH.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "support_container_bootstrap_calls": 0,
        "upstream_module": "multi_swe_bench.harness.run_evaluation",
        "upstream_module_main_executed": False,
        "upstream_revision": PINNED_REVISION,
    }
    _require(
        contracts.get("production_entrypoint") == observed,
        "production Multi-SWE entrypoint byte/dispatch lock differs",
    )

    calls = [_call_name(node) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    for required in (
        "importlib.import_module",
        "module.get_parser",
        "module.CliArgs.from_dict",
        "cli.run",
    ):
        _require(required in calls, f"production entrypoint call is missing: {required}")
    for forbidden in (
        "runpy.run_module",
        "module.main",
        "client.containers.get",
        "client.containers.run",
    ):
        _require(
            forbidden not in calls,
            f"production entrypoint unexpectedly executes upstream bootstrap: {forbidden}",
        )
    _require(
        PINNED_REVISION in source
        and 'cli.mode != "instance_only"' in source
        and "cli.force_build is not False" in source
        and "cli.human_mode is not True" in source
        and "cli.need_clone is not False" in source,
        "production entrypoint pinned fail-closed invariants differ",
    )
    return observed


def verify_checkout(repository: Path) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    lock = _strict_lock()
    _require(lock.get("repository") == PINNED_ORIGIN, "contract-lock origin differs")
    _require(lock.get("revision") == PINNED_REVISION, "contract-lock revision differs")
    body = dict(lock)
    locked_self_hash = body.pop("lock_sha256", None)
    _require(
        isinstance(locked_self_hash, str)
        and SHA256.fullmatch(locked_self_hash) is not None
        and hashlib.sha256(_canonical(body)).hexdigest() == locked_self_hash,
        "Multi-SWE contract self-lock differs",
    )
    contracts = lock.get("contracts")
    locked_projection = lock.get("contract_projection_sha256")
    _require(
        isinstance(contracts, dict)
        and isinstance(locked_projection, str)
        and SHA256.fullmatch(locked_projection) is not None
        and hashlib.sha256(_canonical(contracts)).hexdigest() == locked_projection,
        "Multi-SWE contract projection differs",
    )

    origin = _git(repository, "remote", "get-url", "origin")
    assert isinstance(origin.stdout, str)
    _require(_origin_matches(origin.stdout), "pinned checkout origin differs")
    head = _git(repository, "rev-parse", "HEAD")
    assert isinstance(head.stdout, str)
    _require(head.stdout.strip() == PINNED_REVISION, "pinned checkout HEAD differs")
    object_type = _git(repository, "cat-file", "-t", PINNED_REVISION)
    assert isinstance(object_type.stdout, str)
    _require(object_type.stdout.strip() == "commit", "pinned revision is not a commit")
    tree = _git(repository, "rev-parse", f"{PINNED_REVISION}^{{tree}}")
    assert isinstance(tree.stdout, str)
    _require(tree.stdout.strip() == lock.get("commit_tree_oid"), "pinned tree differs")

    source_rows = lock.get("source_blobs")
    _require(isinstance(source_rows, dict) and len(source_rows) == 5, "source lock set differs")
    blobs: dict[str, bytes] = {}
    verified: list[dict[str, Any]] = []
    for path in sorted(source_rows):
        row = source_rows[path]
        _require(isinstance(row, dict), f"source lock row is malformed: {path}")
        tree_row = _git(repository, "ls-tree", PINNED_REVISION, "--", path)
        assert isinstance(tree_row.stdout, str)
        match = re.fullmatch(
            rf"(100644) blob ([0-9a-f]{{40}})\t{re.escape(path)}\n?",
            tree_row.stdout,
        )
        _require(match is not None, f"pinned path is not one regular blob: {path}")
        blob_result = _git(
            repository, "cat-file", "blob", f"{PINNED_REVISION}:{path}", text=False
        )
        assert isinstance(blob_result.stdout, bytes)
        raw = blob_result.stdout
        blobs[path] = raw
        observed = {
            "bytes": len(raw),
            "git_blob_oid": match.group(2),
            "git_mode": match.group(1),
            "line_count": len(raw.splitlines()),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        _require(observed == row, f"pinned Git blob lock differs: {path}")
        verified.append({"path": path, **observed})

    _verify_control_flow(blobs)
    entrypoint = _verify_production_entrypoint(contracts)
    return {
        "contract_lock_sha256": locked_self_hash,
        "docker_calls": 0,
        "grader_calls": 0,
        "model_api_calls": 0,
        "production_entrypoint": entrypoint,
        "repository": PINNED_ORIGIN,
        "revision": PINNED_REVISION,
        "schema": "trimem/multi-swe-live-contract-verification/1.0",
        "source_blobs": verified,
        "status": "PASS",
        "upstream_source_copied": False,
        "working_tree_bytes_used": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = verify_checkout(args.repository)
        raw = json.dumps(
            result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
        ).encode("utf-8") + b"\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(raw)
        print(
            json.dumps(
                {
                    "contract_lock_sha256": result["contract_lock_sha256"],
                    "source_blobs": len(result["source_blobs"]),
                    "status": "PASS",
                },
                sort_keys=True,
            )
        )
        return 0
    except (ContractError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
