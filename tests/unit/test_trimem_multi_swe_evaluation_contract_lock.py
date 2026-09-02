from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "artifacts" / "trimem_v1" / "multi_swe_evaluation_contract_lock.json"
REPORT_PATH = ROOT / "reports" / "TRIMEM_MULTI_SWE_EVALUATION_CONTRACT.md"

REVISION = "24f493f8a103e72312ded4f6b9c89f081d69cb09"
EXPECTED_SOURCE_BLOBS = {
    "multi_swe_bench/harness/gen_report.py": {
        "bytes": 21331,
        "git_blob_oid": "251e8b01059a18a9af5ae176c696eb4be8950ae4",
        "git_mode": "100644",
        "line_count": 589,
        "sha256": "02ebc8a5414898d12f4f5a9ba0c11a8f57c9f34a0bdc02c2311afac9f654847d",
    },
    "multi_swe_bench/harness/image.py": {
        "bytes": 5892,
        "git_blob_oid": "da1c613d4e7074f46889ffe1c31c0582c3535d2f",
        "git_mode": "100644",
        "line_count": 210,
        "sha256": "86074812495b97026efb42c57acbf7738864b1f0167f99e3b9f9309458972ae9",
    },
    "multi_swe_bench/harness/repos/typescript/vuejs/core.py": {
        "bytes": 5967,
        "git_blob_oid": "8562206faf6eb4fe739932f9a31ec578cc10af96",
        "git_mode": "100644",
        "line_count": 254,
        "sha256": "f154469392f1c52a5d8756c8f5332be35347b8b3bf4dd739a443b5ad4a5f3ce5",
    },
    "multi_swe_bench/harness/run_evaluation.py": {
        "bytes": 28647,
        "git_blob_oid": "f2dfa70df095d434cc6e5fd47f9a7a1bb027b824",
        "git_mode": "100644",
        "line_count": 833,
        "sha256": "b1a9b45022b9e79a5aa9a21908d9074b1258594c10d95f41938852d84ac38efb",
    },
    "multi_swe_bench/utils/session_util.py": {
        "bytes": 17230,
        "git_blob_oid": "3d95889dec9e9a7e630c9b6a9552a4ea0bcdbf64",
        "git_mode": "100644",
        "line_count": 457,
        "sha256": "c4050c065520e35e7c0a7ad0f2ab2b124c3c692413f0c09a2591dd7dc30a3e8a",
    },
}


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        assert key not in result, f"duplicate lock key: {key}"
        result[key] = value
    return result


def _load_lock() -> dict[str, Any]:
    value = json.loads(LOCK_PATH.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    assert isinstance(value, dict)
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _walk(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_contract_lock_is_self_sealed_and_pins_exact_git_blob_bytes() -> None:
    lock = _load_lock()

    assert lock["schema"] == "trimem/multi-swe-evaluation-contract-lock/1.0"
    assert lock["status"] == "PINNED_SOURCE_CONTRACT_LOCKED"
    assert lock["repository"] == "https://github.com/multi-swe-bench/multi-swe-bench"
    assert lock["revision"] == REVISION
    assert lock["commit_tree_oid"] == "741ce10a4ec220fec713112502850b381a6226b9"
    assert lock["source_blobs"] == EXPECTED_SOURCE_BLOBS

    projection = hashlib.sha256(_canonical(lock["contracts"])).hexdigest()
    assert projection == "1cb00293db7bc45f4ef02b551b0d6d87ce3626fcc5b38c857eebe82081401b16"
    assert lock["contract_projection_sha256"] == projection

    body = dict(lock)
    observed_lock = body.pop("lock_sha256")
    assert observed_lock == hashlib.sha256(_canonical(body)).hexdigest()
    assert observed_lock == "c5de60415a95a78969a433d95855b827d67cc5a4b65b9a9af3abd7c37ce9feeb"

    assert lock["evidence_basis"] == {
        "blob_reader": "git cat-file blob <revision>:<path>",
        "commit_object_type": "commit",
        "origin_verified": True,
        "revision_verified": True,
        "working_tree_bytes_used": False,
        "upstream_source_vendored": False,
    }


def test_default_and_existing_image_early_return_contract_is_exact() -> None:
    contracts = _load_lock()["contracts"]

    assert contracts["argument_defaults"]["human_mode"]["default"] is True
    assert contracts["argument_defaults"]["force_build"]["default"] is False

    short_circuit = contracts["existing_image_short_circuit"]
    assert short_circuit["condition"] == {
        "docker_image_exists": True,
        "force_build": False,
    }
    assert short_circuit["outcome"] == "RETURN_BEFORE_BUILD_WORKDIR_OR_FILE_MATERIALIZATION"
    assert short_circuit["actions_before_return"] == [
        "docker_util.exists query",
        "debug log",
    ]
    assert short_circuit["filesystem_mutations_before_return"] == []
    assert short_circuit["skipped_operations"] == [
        "build workdir creation",
        "repository copy",
        "Dockerfile materialization",
        "image.files materialization",
        "docker_util.build",
    ]


def test_human_mode_paths_lock_host_prepare_and_patch_volume_contracts() -> None:
    contracts = _load_lock()["contracts"]
    dispatch = contracts["human_mode_dispatch"]

    false_path = dispatch["false_path"]
    assert false_path["predicate"] == "human_mode is false"
    assert false_path["callee"] == "multi_swe_bench.utils.session_util.run_and_save_logs"
    assert false_path["host_prepare_script_path"] == (
        "{workdir}/{org}/{repo}/images/pr-{number}/prepare.sh"
    )
    assert false_path["container_pull_policy"] == "never"
    assert false_path["prepare_script_contract"] == {
        "host_open_required": True,
        "split_delimiter": "###ACTION_DELIMITER###",
        "commands_replayed_in_container_session": True,
    }

    true_path = dispatch["true_path"]
    assert true_path["predicate"] == "human_mode is true"
    assert true_path["callee"] == "docker_util.run"
    assert true_path["patch_volume"] == {
        "container_path": "/home/fix.patch",
        "host_path": "{evaluation_instance_dir}/fix.patch",
        "mode": "rw",
    }

    failure = contracts["prebuilt_non_human_failure_mechanism"]
    assert failure["source_contract_status"] == "PROVEN_FROM_PINNED_CONTROL_FLOW"
    assert failure["conditions"] == [
        "force_build is false",
        "target image already exists",
        "human_mode is false",
        "host build workdir does not already contain prepare.sh",
    ]
    assert "opens the required host prepare.sh" in failure["derived_result"]


def test_safe_route_bypasses_all_image_builds_then_runs_the_pinned_reporter() -> None:
    contracts = _load_lock()["contracts"]
    route = contracts["adapter_safe_evaluation_route"]
    execution = route["execution_phase"]
    assert execution["config"] == {
        "force_build": False,
        "human_mode": True,
        "mode": "instance_only",
        "need_clone": False,
    }
    assert execution["dispatch"] == (
        "trimem_multi_swe_entrypoint.execute_pinned_instance_only -> pinned "
        "get_parser -> CliArgs.from_dict -> CliArgs.run -> run_mode_instance_only"
    )
    assert execution["support_container_bootstrap_calls"] == 0
    assert execution["upstream_module_main_executed"] is False
    assert execution["structurally_excluded_calls"] == [
        "run_evaluation.__main__.nix_swe_bootstrap",
        "run_mode_image",
        "check_commit_hashes",
        "build_image",
        "run_and_save_logs",
    ]
    report = route["report_phase"]
    assert report["command_contract"] == (
        "python -m multi_swe_bench.harness.gen_report --mode evaluation"
    )
    assert report["output"] == "output_dir/final_report.json"
    assert route["sequence"][-2:] == [
        "require zero exit and exact one-target final report",
        "require non-empty official fix-test evidence",
    ]

    entrypoint = contracts["production_entrypoint"]
    entrypoint_path = ROOT / entrypoint["path"]
    entrypoint_raw = entrypoint_path.read_bytes()
    assert entrypoint == {
        "bytes": len(entrypoint_raw),
        "invocation": (
            "python scripts/trimem_multi_swe_entrypoint.py "
            "--harness-root <pinned-checkout> --config <one-row-config>"
        ),
        "library_dispatch": (
            "execute_pinned_instance_only -> pinned get_parser -> "
            "CliArgs.from_dict -> CliArgs.run -> run_mode_instance_only"
        ),
        "path": "scripts/trimem_multi_swe_entrypoint.py",
        "sha256": hashlib.sha256(entrypoint_raw).hexdigest(),
        "support_container_bootstrap_calls": 0,
        "upstream_module": "multi_swe_bench.harness.run_evaluation",
        "upstream_module_main_executed": False,
        "upstream_revision": REVISION,
    }

    bootstrap = contracts["upstream_module_main_bootstrap"]
    assert bootstrap == {
        "container_image": "mswebench/nix_swe:v1.0",
        "container_name": "nix_swe",
        "evidence": bootstrap["evidence"],
        "execution_order": [
            "docker.from_env",
            "client.containers.get(nix_swe)",
            "client.containers.run(mswebench/nix_swe:v1.0) when absent",
            "get_parser",
            "CliArgs.from_dict",
            "CliArgs.run",
        ],
        "potential_support_container_creations": 1,
        "production_route_bypasses_entire_block": True,
        "runs_before_argument_parsing": True,
    }
    assert bootstrap["evidence"] == [
        {
            "end_line": 833,
            "path": "multi_swe_bench/harness/run_evaluation.py",
            "start_line": 818,
            "symbol": "module __main__ nix_swe bootstrap and CLI dispatch",
        }
    ]

    risk = contracts["full_evaluation_source_build_risk"]
    assert risk["unsafe_for_prebuilt_only_contract"] is True
    assert "dependency graph" in risk["derived_result"]
    assert "source-built" in risk["derived_result"]

    historical = _load_lock()["historical_failure"]
    assert historical["run_id"] == 33594270929
    assert historical["run_attempt"] == 1
    assert historical["source_image_builds_observed_before_failure"] == 1
    assert historical["authority"] == "DIAGNOSTIC_ONLY_NOT_PART_OF_AUTHORITATIVE_CAMPAIGN"


def test_vue_core_recipe_components_and_preparation_are_exact() -> None:
    contracts = _load_lock()["contracts"]
    shared = contracts["shared_image_contract"]
    recipe = contracts["vuejs_core_image_recipe"]

    assert shared["full_name_form"] == "{image_name}:{image_tag}"
    assert shared["name_form"] == "mswebench/{org}_m_{repo}, lower-cased"
    assert shared["fix_patch_container_path"] == "/home/fix.patch"
    assert shared["dockerfile_name"] == "Dockerfile"

    base = recipe["base_image"]
    assert (base["class"], base["dependency"], base["image_tag"], base["workdir"]) == (
        "CoreImageBase",
        "node:20",
        "base",
        "base",
    )
    assert base["dockerfile_steps"] == [
        "set optional global environment",
        "set /home as workdir",
        "apt install git",
        "npm install global pnpm",
        "clone repository when need_clone is true, otherwise copy repository",
        "clear configured environment",
    ]

    instance_image = recipe["instance_image"]
    assert instance_image["dependency"] == "CoreImageBase"
    assert instance_image["image_tag"] == "pr-{number}"
    assert instance_image["workdir"] == "pr-{number}"
    assert instance_image["generated_files"] == [
        "fix.patch",
        "test.patch",
        "check_git_changes.sh",
        "prepare.sh",
        "run.sh",
        "test-run.sh",
        "fix-run.sh",
    ]
    assert instance_image["prepare_actions"] == [
        "change to /home/{repo}",
        "git reset --hard",
        "assert clean worktree",
        "git checkout {base_sha}",
        "assert clean worktree",
        "pnpm install with failure tolerated",
    ]
    assert "run /home/prepare.sh during image build" in instance_image["dockerfile_steps"]

    registered = recipe["registered_instance"]
    assert registered == {
        "dependency": "CoreImageDefault",
        "evidence": registered["evidence"],
        "fix_run": "apply test.patch and fix.patch, then run pnpm test-unit",
        "registration": "vuejs/core",
    }


def test_every_source_reference_is_bounded_by_its_locked_blob() -> None:
    lock = _load_lock()
    evidence = [
        value
        for value in _walk(lock["contracts"])
        if isinstance(value, dict)
        and {"path", "start_line", "end_line", "symbol"} <= set(value)
    ]

    assert len(evidence) == 19
    for reference in evidence:
        source = EXPECTED_SOURCE_BLOBS[reference["path"]]
        assert isinstance(reference["symbol"], str) and reference["symbol"]
        assert 1 <= reference["start_line"] <= reference["end_line"] <= source["line_count"]


def test_report_matches_lock_and_no_upstream_source_payload_is_vendored() -> None:
    lock = _load_lock()
    report = REPORT_PATH.read_text(encoding="utf-8")

    for value in (
        REVISION,
        lock["commit_tree_oid"],
        lock["contract_projection_sha256"],
        lock["lock_sha256"],
        *(row["sha256"] for row in EXPECTED_SOURCE_BLOBS.values()),
    ):
        assert value in report
    for path in EXPECTED_SOURCE_BLOBS:
        assert path in report

    assert "human_mode=false" in report
    assert "human_mode=true" in report
    assert "force_build=false" in report
    assert "nix_swe" in report
    assert "trimem_multi_swe_entrypoint.py" in report
    assert "Docker or either grader" in report

    forbidden_payload_keys = {"content", "source_bytes", "source_text", "source_snippet"}
    for value in _walk(lock):
        if isinstance(value, dict):
            assert forbidden_payload_keys.isdisjoint(value)
        elif isinstance(value, str):
            assert "\n" not in value and "\r" not in value

    assert lock["scope"] == {
        "adapter_modified": True,
        "docker_or_grader_executed": False,
        "model_calls": 0,
        "paid_model_calls": 0,
        "upstream_source_copied_into_product": False,
        "workflow_modified": True,
    }
    assert "Copyright (c)" not in report
    assert "def build_image" not in report
