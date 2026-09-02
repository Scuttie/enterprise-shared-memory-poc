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
LOCAL_VALIDATOR_ROLES = {
    "scripts/trimem_benchmark_matrix.py": "independent fail-closed aggregate revalidator",
    "scripts/trimem_grader_smoke.py": "per-cell evidence producer",
    "scripts/trimem_multi_swe_entrypoint.py": (
        "immutable-image and container-status execution guard"
    ),
    "scripts/trimem_official_grader.py": "exact frozen-domain and conditional-status validator",
}
LOCAL_VALIDATOR_INVARIANTS = {
    "conditional_inner_status": {
        "evidence_schema": "trimem/multi-swe-container-exit-status/1.0",
        "fix_patch_run_command": "bash -e /home/fix-run.sh",
        "resolved_rule": "inner StatusCode must equal zero",
        "unresolved_rule": (
            "a nonzero inner StatusCode is admissible only after exact complete "
            "frozen test-domain evidence validates"
        ),
        "universal_zero_required": False,
    },
    "exact_frozen_test_domain": {
        "fix_patch_result": "exact frozen test-name domain",
        "run_result": "exact frozen classifications",
        "test_patch_result": "exact frozen classifications",
        "validated_before_accepting": ["resolved", "unresolved"],
    },
    "independent_aggregate_revalidation": {
        "aggregate_consumer": "scripts/trimem_benchmark_matrix.py",
        "expected_set_source": "committed grader-smoke manifest matrix",
        "per_cell_producer": "scripts/trimem_grader_smoke.py",
        "raw_status_evidence": (
            "copied into the cell evidence tree and bound by bytes and SHA-256"
        ),
        "required_set_checks": ["missing", "duplicate", "unknown"],
        "requirement": (
            "the aggregate reloads frozen source rows and independently validates "
            "the raw inner-status sidecar, exact test domain, and published summary"
        ),
    },
}
LOCAL_VALIDATOR_LINE_ENDINGS = {
    "gitattributes_pattern": "scripts/trimem_*.py",
    "required_eol": "lf",
    "tracked_head_blob_equality_required": True,
    "working_tree_raw_bytes_hashed": True,
}


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


def _only_function(tree: ast.AST, name: str, *, label: str) -> ast.FunctionDef:
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    _require(len(matches) == 1, f"pinned {label} function shape differs")
    return matches[0]


def _calls(nodes: Sequence[ast.stmt]) -> list[ast.Call]:
    return [
        child
        for node in nodes
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
    ]


def _verify_control_flow(blobs: dict[str, bytes]) -> None:
    run = _source_text(blobs, "multi_swe_bench/harness/run_evaluation.py")
    args_util = _source_text(blobs, "multi_swe_bench/utils/args_util.py")
    gen_report = _source_text(blobs, "multi_swe_bench/harness/gen_report.py")
    report = _source_text(blobs, "multi_swe_bench/harness/report.py")
    session = _source_text(blobs, "multi_swe_bench/utils/session_util.py")
    docker_util = _source_text(blobs, "multi_swe_bench/utils/docker_util.py")
    image = _source_text(blobs, "multi_swe_bench/harness/image.py")
    django = _source_text(
        blobs, "multi_swe_bench/harness/repos/python/django/django.py"
    )
    express = _source_text(
        blobs, "multi_swe_bench/harness/repos/javascript/expressjs/express.py"
    )
    jq = _source_text(blobs, "multi_swe_bench/harness/repos/c/jqlang/jq.py")
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
    _require(
        re.search(
            r"def parse_args\(\s*self, use_config: bool = True, \*args, \*\*kwargs\s*\)"
            r"\s*-> argparse\.Namespace:",
            args_util,
        )
        is not None,
        "pinned ArgumentParser.parse_args signature differs",
    )
    _ordered(
        args_util,
        (
            "args = super().parse_args(*args, **kwargs)",
            "if use_config:",
            "if args.config:",
            "self.load_from_config_file(args, args.config)",
            "self.load_from_env_variables(args)",
            "return args",
        ),
        label="ArgumentParser config dispatch",
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
        "instance.fix_patch_run(self.fix_patch_run_cmd)" in run,
        "pinned fix_patch_run override dispatch differs",
    )
    adapter_trees: dict[str, ast.Module] = {}
    for label, source in (
        ("Django", django),
        ("Express", express),
        ("JQ", jq),
        ("Vue", vue),
    ):
        try:
            source_tree = ast.parse(source, filename=f"pinned {label} adapter")
        except SyntaxError as exc:
            raise ContractError(f"pinned {label} adapter is not valid Python") from exc
        adapter_trees[label] = source_tree
        fix_patch_run = _only_function(
            source_tree, "fix_patch_run", label=f"{label}.fix_patch_run"
        )
        _require(
            len(fix_patch_run.body) >= 2
            and isinstance(fix_patch_run.body[0], ast.If)
            and ast.unparse(fix_patch_run.body[0].test) == "fix_patch_run_cmd"
            and any(
                isinstance(node, ast.Return)
                and ast.unparse(node.value) == "fix_patch_run_cmd"
                for node in ast.walk(fix_patch_run.body[0])
            )
            and isinstance(fix_patch_run.body[1], ast.Return)
            and isinstance(fix_patch_run.body[1].value, ast.Constant)
            and fix_patch_run.body[1].value.value == "bash /home/fix-run.sh",
            f"pinned {label} fix_patch_run override contract differs",
        )
    _ordered(
        image,
        (
            '"fix-run.sh"',
            "set -uxo pipefail",
            "git apply --whitespace=nowarn /home/fix.patch",
        ),
        label="Django generic baked fix script",
    )
    image_tree = ast.parse(image, filename="multi_swe_bench/harness/image.py")
    django_scripts = [
        node.value
        for node in ast.walk(image_tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "git apply --whitespace=nowarn /home/fix.patch" in node.value
    ]
    _require(
        len(django_scripts) == 1
        and "set -uxo pipefail" in django_scripts[0]
        and "set -e" not in django_scripts[0],
        "pinned Django generic baked script errexit boundary differs",
    )
    for label, source, apply_command in (
        (
            "Express",
            express,
            "git apply --whitespace=nowarn /home/test.patch /home/fix.patch",
        ),
        (
            "JQ",
            jq,
            "git apply --whitespace=nowarn /home/test.patch /home/fix.patch",
        ),
        ("Vue", vue, "git apply /home/test.patch /home/fix.patch"),
    ):
        _ordered(
            source,
            ('"fix-run.sh"', "set -e", apply_command),
            label=f"{label} baked fix script",
        )
        baked_scripts = [
            node.value
            for node in ast.walk(adapter_trees[label])
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and apply_command in node.value
        ]
        _require(
            len(baked_scripts) == 1 and "set -e" in baked_scripts[0],
            f"pinned {label} baked fix script errexit contract differs",
        )
    _require(
        re.search(r'--mode[\s\S]{0,220}?choices=\["dataset", "evaluation", "summary", "regen"\]', gen_report)
        is not None,
        "pinned report mode choices differ",
    )
    _ordered(
        gen_report,
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
            gen_report,
        )
        is not None,
        "pinned gen_report evaluation dispatch differs",
    )
    _require(
        "docker_util" not in gen_report and "docker.from_env" not in gen_report,
        "pinned report phase unexpectedly gained a Docker execution path",
    )

    # The pinned Docker helper has two material runtime hazards that the local
    # adapter must close: the streaming-output branch never waits for or checks
    # a container StatusCode, and containers.run has no local-only/no-pull
    # guard.  Lock these as AST properties rather than relying on prose or a
    # fragile whole-function substring.
    try:
        docker_tree = ast.parse(
            docker_util, filename="multi_swe_bench/utils/docker_util.py"
        )
        gen_report_tree = ast.parse(
            gen_report, filename="multi_swe_bench/harness/gen_report.py"
        )
        report_tree = ast.parse(report, filename="multi_swe_bench/harness/report.py")
    except SyntaxError as exc:
        raise ContractError("pinned runtime-boundary source is not valid Python") from exc

    from_env_calls = [
        node
        for node in ast.walk(docker_tree)
        if isinstance(node, ast.Call) and _call_name(node) == "docker.from_env"
    ]
    _require(
        len(from_env_calls) == 1,
        "pinned docker client import-time initialization differs",
    )
    client_assignments = [
        node
        for node in docker_tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "docker_client"
        and isinstance(node.value, ast.Call)
        and _call_name(node.value) == "docker.from_env"
    ]
    _require(
        len(client_assignments) == 1,
        "pinned docker client is not initialized at module import",
    )
    docker_run = _only_function(docker_tree, "run", label="docker_util.run")
    run_calls = _calls(docker_run.body)
    container_starts = [
        node
        for node in run_calls
        if _call_name(node) == "docker_client.containers.run"
    ]
    _require(len(container_starts) == 1, "pinned container start shape differs")
    start = container_starts[0]
    start_keywords = {keyword.arg: keyword.value for keyword in start.keywords}
    _require(
        start.args == []
        and set(start_keywords)
        == {
            "image",
            "command",
            "remove",
            "detach",
            "stdout",
            "stderr",
            "environment",
            "volumes",
        }
        and ast.unparse(start_keywords["image"]) == "image_full_name"
        and ast.unparse(start_keywords["command"]) == "run_command"
        and isinstance(start_keywords["remove"], ast.Constant)
        and start_keywords["remove"].value is False
        and isinstance(start_keywords["detach"], ast.Constant)
        and start_keywords["detach"].value is True
        and "pull" not in start_keywords,
        "pinned container start/pull boundary differs",
    )
    output_branches = [
        node
        for node in ast.walk(docker_run)
        if isinstance(node, ast.If) and ast.unparse(node.test) == "output_path"
    ]
    _require(len(output_branches) == 1, "pinned output_path branch shape differs")
    output_branch = output_branches[0]
    output_calls = _calls(output_branch.body)
    fallback_calls = _calls(output_branch.orelse)
    streaming_calls = [
        node for node in output_calls if _call_name(node) == "container.logs"
    ]
    _require(len(streaming_calls) == 1, "pinned streaming log call differs")
    stream_keywords = {
        keyword.arg: keyword.value for keyword in streaming_calls[0].keywords
    }
    _require(
        set(stream_keywords) == {"stream", "follow"}
        and all(
            isinstance(stream_keywords[name], ast.Constant)
            and stream_keywords[name].value is True
            for name in ("stream", "follow")
        )
        and all(_call_name(node) != "container.wait" for node in output_calls)
        and not any(
            isinstance(node, ast.Constant) and node.value == "StatusCode"
            for statement in output_branch.body
            for node in ast.walk(statement)
        ),
        "pinned streaming branch unexpectedly waits for or checks container status",
    )
    wait_calls = [
        node for node in fallback_calls if _call_name(node) == "container.wait"
    ]
    discarded_waits = [
        statement
        for statement in output_branch.orelse
        if isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and _call_name(statement.value) == "container.wait"
    ]
    _require(
        len(wait_calls) == 1 and len(discarded_waits) == 1,
        "pinned non-streaming wait boundary differs",
    )
    _require(
        not any(
            isinstance(node, ast.Constant) and node.value == "StatusCode"
            for statement in output_branch.orelse
            for node in ast.walk(statement)
        ),
        "pinned non-streaming branch unexpectedly checks container status",
    )
    _require(
        all(
            _call_name(node) not in {"docker_client.images.pull", "docker.pull"}
            for node in run_calls
        ),
        "pinned docker helper explicit pull surface differs",
    )
    _require(
        all(_call_name(node) != "docker_client.images.get" for node in run_calls),
        "pinned docker helper unexpectedly gained a local image preflight",
    )

    # In evaluation reporting, Report.valid is checked before the four frozen
    # category-coverage loops.  A failed validity or coverage check is routed
    # to invalid_reports, and FinalReport maps that collection to unresolved.
    gen_eval = _only_function(
        gen_report_tree, "gen_eval_reports", label="CliArgs.gen_eval_reports"
    )
    safe_generate = _only_function(
        gen_eval, "safe_generate_report", label="safe_generate_report"
    )
    invalid_checks = [
        node
        for node in ast.walk(safe_generate)
        if isinstance(node, ast.If) and ast.unparse(node.test) == "not report.valid"
    ]
    _require(len(invalid_checks) == 1, "pinned report-validity gate differs")
    invalid_check = invalid_checks[0]
    _require(
        any(
            isinstance(node, ast.Return)
            and ast.unparse(node.value) == "(report, False)"
            for node in ast.walk(invalid_check)
        ),
        "pinned invalid report does not fail before coverage",
    )
    coverage_fields = ("p2p_tests", "f2p_tests", "s2p_tests", "n2p_tests")
    coverage_loops: list[ast.For] = []
    for field in coverage_fields:
        matches = [
            node
            for node in ast.walk(safe_generate)
            if isinstance(node, ast.For)
            and ast.unparse(node.iter) == f"dataset.{field}"
        ]
        _require(len(matches) == 1, f"pinned {field} coverage loop differs")
        loop = matches[0]
        _require(
            loop.lineno > invalid_check.lineno
            and any(
                isinstance(node, ast.If)
                and ast.unparse(node.test)
                == f"{field.removesuffix('_tests')} not in report.{field}"
                and any(
                    isinstance(child, ast.Return)
                    and ast.unparse(child.value) == "(report, False)"
                    for child in ast.walk(node)
                )
                for node in ast.walk(loop)
            ),
            f"pinned {field} coverage failure contract differs",
        )
        coverage_loops.append(loop)
    _require(
        [node.lineno for node in coverage_loops]
        == sorted(node.lineno for node in coverage_loops),
        "pinned evaluation coverage order differs",
    )
    validity_routes = [
        node
        for node in ast.walk(gen_eval)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "valid"
        and any(
            isinstance(child, ast.Call) and _call_name(child) == "reports.append"
            for statement in node.body
            for child in ast.walk(statement)
        )
        and any(
            isinstance(child, ast.Call)
            and _call_name(child) == "invalid_reports.append"
            for statement in node.orelse
            for child in ast.walk(statement)
        )
    ]
    _require(
        len(validity_routes) == 1,
        "pinned report validity collection routing differs",
    )
    _ordered(
        gen_report,
        (
            "if not report.valid:",
            "for p2p in dataset.p2p_tests:",
            "for f2p in dataset.f2p_tests:",
            "for s2p in dataset.s2p_tests:",
            "for n2p in dataset.n2p_tests:",
            "invalid_reports.append(report)",
        ),
        label="invalid-before-coverage report routing",
    )

    final_report_class = [
        node
        for node in report_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "FinalReport"
    ]
    _require(len(final_report_class) == 1, "pinned FinalReport class differs")
    from_reports = _only_function(
        final_report_class[0], "from_reports", label="FinalReport.from_reports"
    )
    assignments = {
        ast.unparse(node.targets[0]): ast.unparse(node.value)
        for node in from_reports.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1
    }
    _require(
        assignments.get("resolved_ids") == "[report.id for report in reports]"
        and assignments.get("unresolved_ids")
        == "[report.id for report in invalid_reports]",
        "pinned valid/invalid to resolved/unresolved mapping differs",
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
            "--harness-root <pinned-checkout> --config <one-row-config> "
            "--expected-image <immutable-digest> "
            "--expected-tag <frozen-harness-tag> "
            "--exit-status-output <exclusive-status-path>"
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

    main_function = _only_function(tree, "main", label="production entrypoint main")
    main_calls = [
        node for node in ast.walk(main_function) if isinstance(node, ast.Call)
    ]
    argument_calls = [
        node for node in main_calls if _call_name(node) == "parser.add_argument"
    ]
    required_flags: set[str] = set()
    for call in argument_calls:
        _require(
            len(call.args) == 1
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[0].value, str)
            and any(
                keyword.arg == "required"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in call.keywords
            ),
            "production entrypoint CLI argument is not one required flag",
        )
        required_flags.add(call.args[0].value)
    _require(
        required_flags
        == {
            "--harness-root",
            "--config",
            "--expected-image",
            "--expected-tag",
            "--exit-status-output",
        }
        and len(argument_calls) == len(required_flags),
        "production entrypoint required CLI surface differs",
    )
    execution_calls = [
        node
        for node in main_calls
        if _call_name(node) == "execute_pinned_instance_only"
    ]
    _require(
        len(execution_calls) == 1
        and execution_calls[0].args == []
        and {
            keyword.arg: ast.unparse(keyword.value)
            for keyword in execution_calls[0].keywords
        }
        == {
            "harness_root": "args.harness_root",
            "config_path": "args.config",
            "expected_image": "args.expected_image",
            "expected_tag": "args.expected_tag",
            "exit_status_path": "args.exit_status_output",
        },
        "production entrypoint does not bind the exact five CLI values",
    )

    execute_function = _only_function(
        tree,
        "execute_pinned_instance_only",
        label="execute_pinned_instance_only",
    )
    guarded_dispatches = [
        node
        for node in ast.walk(execute_function)
        if isinstance(node, ast.Call) and _call_name(node) == "_execute_guarded_cli"
    ]
    _require(
        len(guarded_dispatches) == 1
        and [ast.unparse(value) for value in guarded_dispatches[0].args]
        == ["module", "cli"]
        and {
            keyword.arg: ast.unparse(keyword.value)
            for keyword in guarded_dispatches[0].keywords
        }
        == {
            "expected_image": "expected_image",
            "expected_tag": "expected_tag",
            "exit_status_path": "exit_status_path",
        },
        "production entrypoint guarded dispatch bindings differ",
    )
    parse_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _call_name(node) == "parser.parse_args"
        and any(keyword.arg == "args" for keyword in node.keywords)
    ]
    _require(
        len(parse_calls) == 1
        and parse_calls[0].args == []
        and len(parse_calls[0].keywords) == 1
        and parse_calls[0].keywords[0].arg == "args"
        and ast.unparse(parse_calls[0].keywords[0].value)
        == "['--config', str(config_path)]",
        "production entrypoint does not bind pinned parse_args args by keyword",
    )

    guarded = _only_function(tree, "_execute_guarded_cli", label="guarded CLI")
    guarded_calls = [
        node for node in ast.walk(guarded) if isinstance(node, ast.Call)
    ]
    create_calls = [
        node for node in guarded_calls if _call_name(node) == "original_container_create"
    ]
    _require(
        len(create_calls) == 1
        and create_calls[0].args == []
        and {
            keyword.arg: ast.unparse(keyword.value)
            for keyword in create_calls[0].keywords
        }
        == {
            "image": "expected_image",
            "command": "FIX_PATCH_RUN_COMMAND",
            "environment": "[]",
            "volumes": (
                "{expected_patch_path: {'bind': '/home/fix.patch', 'mode': 'rw'}}"
            ),
        },
        "production entrypoint direct immutable-digest create contract differs",
    )
    resolved_image_calls = [
        ast.unparse(node)
        for node in guarded_calls
        if _call_name(node) == "_resolved_image_id"
    ]
    _require(
        resolved_image_calls
        == [
            "_resolved_image_id(images, expected_image)",
            "_resolved_image_id(images, expected_tag)",
        ],
        "production entrypoint tag/digest local-image validation differs",
    )
    _require(
        all(
            _call_name(node) not in {"images.pull", "docker_util.build"}
            for node in guarded_calls
        )
        and "docker_util.docker_client = GuardedDockerClient()" in source
        and "docker_util.exists = forbidden_exists" in source
        and "docker_util.build = forbidden_build" in source
        and "if digest_id != tag_id:" in source,
        "production entrypoint immutable-image/no-pull tripwire differs",
    )
    _require(
        "containers.run = guarded_container_run" in source
        and "containers.run = original_container_run" in source,
        "production entrypoint Docker run proxy restoration differs",
    )

    capture_status = _only_function(
        tree, "_capture_status", label="container status capture"
    )
    status_waits = [
        node
        for node in ast.walk(capture_status)
        if isinstance(node, ast.Call) and _call_name(node) == "self._container.wait"
    ]
    _require(
        len(status_waits) == 1
        and status_waits[0].args == []
        and status_waits[0].keywords == []
        and 'result.get("StatusCode")' in source
        and "type(status_code) is not int or not 0 <= status_code <= 255" in source,
        "production entrypoint exact integer StatusCode capture differs",
    )
    _require(
        "os.O_EXCL" in source
        and "os.fsync(descriptor)" in source
        and '"schema": "trimem/multi-swe-container-exit-status/1.0"' in source
        and not any(
            "active_container.status_code" in ast.unparse(node)
            and any(
                isinstance(child, ast.Constant) and child.value == 0
                for child in ast.walk(node)
            )
            for node in ast.walk(guarded)
            if isinstance(node, ast.Compare)
        ),
        "production entrypoint sidecar or conditional-status boundary differs",
    )
    _require(
        PINNED_REVISION in source
        and 'FIX_PATCH_RUN_COMMAND = "bash -e /home/fix-run.sh"' in source
        and 'cli.mode != "instance_only"' in source
        and "cli.force_build is not False" in source
        and "cli.human_mode is not True" in source
        and "cli.need_clone is not False" in source,
        "production entrypoint pinned fail-closed invariants differ",
    )
    return observed


def _verify_local_validator_files(contracts: dict[str, Any]) -> list[dict[str, Any]]:
    projection = contracts.get("local_validator_projection")
    _require(isinstance(projection, dict), "local validator projection is missing")
    rows = projection.get("files")
    _require(
        isinstance(rows, dict) and set(rows) == set(LOCAL_VALIDATOR_ROLES),
        "local validator file set differs",
    )

    observed_rows: dict[str, dict[str, Any]] = {}
    verified: list[dict[str, Any]] = []
    for path in sorted(LOCAL_VALIDATOR_ROLES):
        source_path = ROOT / path
        try:
            raw = source_path.read_bytes()
            source = raw.decode("utf-8")
            ast.parse(source, filename=str(source_path))
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            raise ContractError(f"local validator is not valid UTF-8 Python: {path}") from exc
        _require(b"\r" not in raw, f"local validator is not LF-only: {path}")
        observed = {
            "bytes": len(raw),
            "role": LOCAL_VALIDATOR_ROLES[path],
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        _require(rows.get(path) == observed, f"local validator byte lock differs: {path}")
        observed_rows[path] = observed

        attributes = _git(ROOT, "check-attr", "eol", "--", path)
        assert isinstance(attributes.stdout, str)
        _require(
            attributes.stdout.strip() == f"{path}: eol: lf",
            f"local validator eol attribute differs: {path}",
        )
        tree_row = _git(ROOT, "ls-tree", "HEAD", "--", path)
        assert isinstance(tree_row.stdout, str)
        match = re.fullmatch(
            rf"100644 blob ([0-9a-f]{{40}})\t{re.escape(path)}\n?",
            tree_row.stdout,
        )
        _require(match is not None, f"local validator is not one tracked HEAD blob: {path}")
        head_blob = _git(ROOT, "cat-file", "blob", f"HEAD:{path}", text=False)
        assert isinstance(head_blob.stdout, bytes)
        _require(
            head_blob.stdout == raw,
            f"local validator working bytes differ from the tracked HEAD blob: {path}",
        )
        verified.append({"git_blob_oid": match.group(1), "path": path, **observed})
    _require(
        projection
        == {
            "files": observed_rows,
            "invariants": LOCAL_VALIDATOR_INVARIANTS,
            "line_endings": LOCAL_VALIDATOR_LINE_ENDINGS,
        },
        "local validator invariant projection differs",
    )
    return verified


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
    _require(
        isinstance(source_rows, dict) and len(source_rows) == 11,
        "source lock set differs",
    )
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
    local_validators = _verify_local_validator_files(contracts)
    return {
        "contract_lock_sha256": locked_self_hash,
        "docker_calls": 0,
        "grader_calls": 0,
        "model_api_calls": 0,
        "local_validator_files": local_validators,
        "production_entrypoint": entrypoint,
        "repository": PINNED_ORIGIN,
        "revision": PINNED_REVISION,
        "schema": "trimem/multi-swe-live-contract-verification/1.1",
        "source_blobs": verified,
        "status": "PASS",
        "upstream_source_copied": False,
        "local_validator_working_tree_bytes_used": True,
        "upstream_working_tree_bytes_used": False,
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
                    "local_validator_files": len(result["local_validator_files"]),
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
