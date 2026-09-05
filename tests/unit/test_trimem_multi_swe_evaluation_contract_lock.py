from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "artifacts" / "trimem_v1" / "multi_swe_evaluation_contract_lock.json"
REPORT_PATH = ROOT / "reports" / "TRIMEM_MULTI_SWE_EVALUATION_CONTRACT.md"
SEMANTICS_REPORT_PATH = ROOT / "reports" / "TRIMEM_MULTI_SWE_REPORT_SEMANTICS.md"

REVISION = "24f493f8a103e72312ded4f6b9c89f081d69cb09"
D18_STARTING_HEAD = "8002847d0db8975dfd957a1322d31a7768fc098f"
D18_AMENDMENT_PATH = (
    ROOT / "artifacts" / "trimem_v1" / "development_terminal_contract_amendment.json"
)
EXPECTED_SOURCE_BLOBS = {
    "multi_swe_bench/harness/dataset.py": {
        "bytes": 2833,
        "git_blob_oid": "19aeb4370fcfdaeccef99b3a47d06c5a572d468c",
        "git_mode": "100644",
        "line_count": 79,
        "sha256": "dd49f55baf63b60fff309b6a5b2a1826697e2b85ad1a9bccff18321dcdc200fc",
    },
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
    "multi_swe_bench/harness/pull_request.py": {
        "bytes": 6015,
        "git_blob_oid": "0c2c99a4602bc6dc127cc0bb3ecaff56a6550d17",
        "git_mode": "100644",
        "line_count": 211,
        "sha256": "32b49f48b39124f67727f408898bd96cce91c0a362faa716ac858dcb0b0b47c7",
    },
    "multi_swe_bench/harness/report.py": {
        "bytes": 12942,
        "git_blob_oid": "a0b23ab1bf3c2407e15338fd0e644c0138fd3d90",
        "git_mode": "100644",
        "line_count": 347,
        "sha256": "5a025fd496d42c4b7377fc0702d64c6d0e356b117eaf2face47e73a52c29902f",
    },
    "multi_swe_bench/harness/test_result.py": {
        "bytes": 5164,
        "git_blob_oid": "bbdd5dc729582a1d06c79f416058bbc4d7db9c91",
        "git_mode": "100644",
        "line_count": 157,
        "sha256": "5411af794920cf4b170fe9dbe8c21c12cc63e2bbe2280d6d82acb850f4808be3",
    },
    "multi_swe_bench/harness/repos/c/jqlang/jq.py": {
        "bytes": 6431,
        "git_blob_oid": "9328e7683d5f269a6247292b388a7c7cb6592420",
        "git_mode": "100644",
        "line_count": 275,
        "sha256": "e523664fcf8a1b728f5d4d77caeebc7cecd34c575f295fdb66a441b910e3a8b0",
    },
    "multi_swe_bench/harness/repos/javascript/expressjs/express.py": {
        "bytes": 10209,
        "git_blob_oid": "15a98c72f2218925a31319dbb1a498b020a78f66",
        "git_mode": "100644",
        "line_count": 388,
        "sha256": "a673518e3b4d9e9e2396f97aacdc5c803d7e2298ce07dfd748cbb9f67ce36291",
    },
    "multi_swe_bench/harness/repos/python/django/django.py": {
        "bytes": 4392,
        "git_blob_oid": "98dd428523768d4c35ff119cc50dc453675ab5c7",
        "git_mode": "100644",
        "line_count": 100,
        "sha256": "9b9fbcfa6e165d42b39c589e2bdd657ec0ab5df1caec8fbace683314e21bd9a8",
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
    "multi_swe_bench/utils/args_util.py": {
        "bytes": 3277,
        "git_blob_oid": "24ed488f3a68927f517dca67a32e8dfbc6dc867a",
        "git_mode": "100644",
        "line_count": 97,
        "sha256": "26835412d5093091c771c7f99fe45a4ff141433decae23705b714b0ae2b250af",
    },
    "multi_swe_bench/utils/docker_util.py": {
        "bytes": 3395,
        "git_blob_oid": "f3b89d736a82fbf1dd31e303b0e8fe353380170a",
        "git_mode": "100644",
        "line_count": 108,
        "sha256": "dd5929ee952763ec11a22646f2725b306b573ddbc86dc8ffc7a6d9dfa53f493d",
    },
    "multi_swe_bench/utils/session_util.py": {
        "bytes": 17230,
        "git_blob_oid": "3d95889dec9e9a7e630c9b6a9552a4ea0bcdbf64",
        "git_mode": "100644",
        "line_count": 457,
        "sha256": "c4050c065520e35e7c0a7ad0f2ab2b124c3c692413f0c09a2591dd7dc30a3e8a",
    },
}
EXPECTED_LOCAL_VALIDATOR_FILES = {
    "scripts/trimem_benchmark_matrix.py": {
        "bytes": 163837,
        "role": "independent fail-closed aggregate revalidator",
        "sha256": "d5e561959f22bc0e13b59eb258fadc458bd013c84629ab7a6a260b3eae05557e",
    },
    "scripts/trimem_grader_smoke.py": {
        "bytes": 135285,
        "role": "per-cell evidence producer",
        "sha256": "15b1bae4a14ac74f53de016882e20f6962d0b5e2818b6a158ab26373c7fb748a",
    },
    "scripts/trimem_multi_swe_entrypoint.py": {
        "bytes": 25035,
        "role": "immutable-image and container-status execution guard",
        "sha256": "16c021ac3c0eb18bc78376164307b53cfb294ac0f206415d465a1b11f1ec63ac",
    },
    "scripts/trimem_official_grader.py": {
        "bytes": 101093,
        "role": "exact frozen-domain and conditional-status validator",
        "sha256": "fbd15718a88b4d733b313af83889aae8ef6ac7837529bba52f0bb4072f57b886",
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


def _git_blob(commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "cat-file", "blob", f"{commit}:{path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(
        "utf-8", errors="replace"
    )
    return completed.stdout


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

    assert lock["schema"] == "trimem/multi-swe-evaluation-contract-lock/1.2"
    assert lock["status"] == "PINNED_SOURCE_CONTRACT_LOCKED"
    assert lock["repository"] == "https://github.com/multi-swe-bench/multi-swe-bench"
    assert lock["revision"] == REVISION
    assert lock["commit_tree_oid"] == "741ce10a4ec220fec713112502850b381a6226b9"
    assert lock["source_blobs"] == EXPECTED_SOURCE_BLOBS

    projection = hashlib.sha256(_canonical(lock["contracts"])).hexdigest()
    assert projection == "32cdbd707a7d520cac9099487341f458f049697ffbb24a7baa3763b3c0fcd5c4"
    assert lock["contract_projection_sha256"] == projection

    body = dict(lock)
    observed_lock = body.pop("lock_sha256")
    assert observed_lock == hashlib.sha256(_canonical(body)).hexdigest()
    assert observed_lock == "21b1071c4aedddf878a5adc56af43d69041acc6bbd71b3f31f6391307f96d92c"

    assert lock["evidence_basis"] == {
        "blob_reader": "git cat-file blob <revision>:<path>",
        "commit_object_type": "commit",
        "local_validator_eol_attribute": "lf",
        "local_validator_reader": (
            "working tree raw bytes plus git cat-file blob HEAD:<path>"
        ),
        "local_validator_working_tree_equals_head_blob": True,
        "origin_verified": True,
        "revision_verified": True,
        "upstream_working_tree_bytes_used": False,
        "working_tree_bytes_used": False,
        "upstream_source_vendored": False,
    }


def test_local_validator_projection_locks_raw_lf_bytes_and_fail_closed_chain() -> None:
    projection = _load_lock()["contracts"]["local_validator_projection"]
    historical_matrix = _git_blob(
        D18_STARTING_HEAD, "scripts/trimem_benchmark_matrix.py"
    )

    assert projection["files"] == EXPECTED_LOCAL_VALIDATOR_FILES
    for path, expected in EXPECTED_LOCAL_VALIDATOR_FILES.items():
        if path == "scripts/trimem_benchmark_matrix.py":
            # D1.8 legitimately changes the aggregate consumer.  Preserve the
            # historical contract lock by checking it against the immutable
            # correction starting point rather than mutable working-tree bytes.
            raw = historical_matrix
        else:
            raw = (ROOT / path).read_bytes()
            assert raw == _git_blob("HEAD", path)
        assert b"\r" not in raw
        assert len(raw) == expected["bytes"]
        assert hashlib.sha256(raw).hexdigest() == expected["sha256"]

    current_matrix = (ROOT / "scripts/trimem_benchmark_matrix.py").read_bytes()
    assert b"\r" not in current_matrix
    assert current_matrix != historical_matrix
    amendment = json.loads(D18_AMENDMENT_PATH.read_text(encoding="utf-8"))
    assert amendment["implementation_sha256"]["scripts/trimem_benchmark_matrix.py"] == (
        hashlib.sha256(current_matrix).hexdigest()
    )

    assert projection["line_endings"] == {
        "gitattributes_pattern": "scripts/trimem_*.py",
        "required_eol": "lf",
        "tracked_head_blob_equality_required": True,
        "working_tree_raw_bytes_hashed": True,
    }
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "scripts/trimem_*.py text eol=lf" in attributes

    invariants = projection["invariants"]
    assert invariants["conditional_inner_status"] == {
        "evidence_schema": "trimem/multi-swe-container-exit-status/1.0",
        "fix_patch_run_command": "bash -e /home/fix-run.sh",
        "resolved_rule": "inner StatusCode must equal zero",
        "unresolved_rule": (
            "a nonzero inner StatusCode is admissible only after exact complete "
            "frozen test-domain evidence validates"
        ),
        "universal_zero_required": False,
    }
    assert invariants["exact_frozen_test_domain"] == {
        "fix_patch_result": "exact frozen test-name domain",
        "run_result": "exact frozen classifications",
        "test_patch_result": "exact frozen classifications",
        "validated_before_accepting": ["resolved", "unresolved"],
    }
    assert invariants["independent_aggregate_revalidation"] == {
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


def test_pinned_docker_run_boundary_requires_local_no_pull_and_exit_guards() -> None:
    contracts = _load_lock()["contracts"]
    boundary = contracts["docker_run_runtime_boundary"]

    assert boundary["client_initialization"] == {
        "at_module_import": True,
        "callee": "docker.from_env",
        "evidence": [
            {
                "end_line": 19,
                "path": "multi_swe_bench/utils/docker_util.py",
                "start_line": 17,
                "symbol": "module docker client initialization",
            }
        ],
    }
    assert boundary["container_start"] == {
        "callee": "docker_client.containers.run",
        "detach": True,
        "explicit_pull_argument": False,
        "image_argument": "image_full_name",
        "immutable_digest_preflight": False,
        "local_image_only_guard": False,
        "remove": False,
    }
    assert boundary["output_path_branch"] == {
        "container_wait_calls": 0,
        "log_stream": {"follow": True, "stream": True},
        "nonzero_exit_propagated": False,
        "status_code_checks": 0,
    }
    assert boundary["no_output_path_branch"] == {
        "container_wait_calls": 1,
        "nonzero_exit_propagated": False,
        "status_code_checks": 0,
        "wait_result_consumed": False,
    }
    assert len(boundary["derived_risks"]) == 3
    assert "immutable-digest preflight" in boundary["derived_risks"][0]
    assert "StatusCode" in boundary["derived_risks"][1]

    closure = contracts["adapter_fail_closed_closure"]
    assert closure["status"] == "ENFORCED_BY_TRIMEM_LOCAL_ADAPTER"
    assert closure["immutable_digest_no_pull_guard"]["adapter_requirement"] == (
        "require one local RepoDigest equal to the frozen immutable digest, create "
        "only the exact harness alias from that verified object, and forbid image "
        "pull or source-build operations inside the execution wrapper"
    )
    exit_guard = closure["container_exit_guard"]
    assert exit_guard["command_guard"] == (
        "fix_patch_run_cmd=bash -e /home/fix-run.sh"
    )
    assert "one integer StatusCode" in exit_guard["adapter_requirement"]
    assert "require zero for a resolved result" in exit_guard["adapter_requirement"]
    assert "nonzero unresolved result" in exit_guard["adapter_requirement"]
    assert "exact full-domain test evidence" in exit_guard["adapter_requirement"]
    assert "patch-application failure exits before tests" in exit_guard[
        "command_guard_effect"
    ]


def test_pinned_report_validity_and_coverage_map_invalid_to_unresolved() -> None:
    boundary = _load_lock()["contracts"]["evaluation_report_classification_boundary"]

    assert boundary["computed_resolved"] == (
        "REPORT_VALID AND ALL_FROZEN_EXPECTED_TRANSITION_KEYS_COVERED"
    )
    assert boundary["invalid_before_coverage"] is True
    assert boundary["validity_gate"] == (
        "if not report.valid: return (report, False)"
    )
    assert boundary["invalid_collection"] == "invalid_reports"
    assert boundary["coverage_check"] == {
        "domain_order": ["p2p_tests", "f2p_tests", "s2p_tests", "n2p_tests"],
        "exact_domain_equality": False,
        "failure_result": "(report, False)",
        "operation": (
            "require each frozen category member to appear in the same "
            "generated-report category"
        ),
    }
    assert boundary["final_report_mapping"] == {
        "invalid_reports": "unresolved_ids",
        "reports": "resolved_ids",
    }
    assert boundary["final_report_target_identity"] == {
        "format": "{org}/{repo}:pr-{number}",
        "upstream_symbol": "PullRequestBase.id",
    }
    assert boundary["report_valid_equals_final_resolved"] is False
    assert boundary["valid_true_final_unresolved_is_legal"] is True
    assert boundary["noop_definition"] == (
        "FinalReport unresolved; Report.valid may be true or false"
    )
    assert boundary["report_check"] == {
        "result": "REPORT_VALID",
        "rules_in_order": [
            "fix_patch_result contains at least one classified test",
            "no test has test=PASS and fix=FAIL",
            "at least one test has test!=PASS and fix=PASS",
            "no test has test in {NONE,SKIP}, fix=FAIL, and run=PASS",
        ],
        "unobserved_stage_classification": "NONE",
    }
    assert boundary["test_result_validation"] == {
        "trimem_fail_closed_raw_input": {
            "count_matches_raw_list_length": True,
            "duplicate_ids_rejected_before_set_construction": True,
            "pass_fail_skip_disjoint": True,
        },
        "upstream_materialized_test_result": {
            "count_matches_materialized_set_size": True,
            "pass_fail_skip_sets_disjoint": True,
            "raw_json_duplicates_unconditionally_rejected": False,
            "required_collection_type": "set",
        },
    }

    closure = _load_lock()["contracts"]["adapter_fail_closed_closure"]
    assert closure["frozen_test_domain_guard"] == {
        "adapter_requirement": (
            "require exact run_result and test_patch_result classifications from "
            "the frozen row and exact fix_patch_result test-name domain before "
            "accepting resolved or unresolved"
        ),
        "upstream_gap": (
            "gen_eval_reports checks expected category members but does not reject "
            "additional test names"
        ),
    }


def test_pinned_argument_parser_signature_requires_named_args_binding() -> None:
    parser = _load_lock()["contracts"]["argument_parser_config_dispatch"]
    assert parser == {
        "argparse_forwarding": "super().parse_args(*args, **kwargs)",
        "config_load_order": [
            "parse argparse arguments",
            "load config file when use_config and args.config are truthy",
            "load environment variables",
            "return namespace",
        ],
        "evidence": [
            {
                "end_line": 47,
                "path": "multi_swe_bench/utils/args_util.py",
                "start_line": 25,
                "symbol": "ArgumentParser.__init__ and ArgumentParser.parse_args",
            }
        ],
        "first_positional_parameter_after_self": "use_config",
        "positional_argv_hazard": (
            "a positional argv list binds to use_config, leaving argparse to "
            "consume process argv"
        ),
        "signature": "parse_args(self, use_config=True, *args, **kwargs)",
        "wrapper_required_call": "parser.parse_args(args=[--config, config_path])",
    }


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
        "fix_patch_run_cmd": "bash -e /home/fix-run.sh",
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
            "--harness-root <pinned-checkout> --config <one-row-config> "
            "--expected-image <immutable-digest> "
            "--expected-tag <frozen-harness-tag> "
            "--exit-status-output <exclusive-status-path>"
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
    entrypoint_source = entrypoint_raw.decode("utf-8")
    for required_flag in (
        "--harness-root",
        "--config",
        "--expected-image",
        "--expected-tag",
        "--exit-status-output",
    ):
        assert f'parser.add_argument("{required_flag}"' in entrypoint_source
    assert "containers.run = original_container_run" in entrypoint_source

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


def test_all_multi_smoke_targets_accept_fail_closed_patch_command() -> None:
    contract = _load_lock()["contracts"]["multi_smoke_target_patch_execution"]
    override = contract["adapter_override"]
    assert override["command"] == "bash -e /home/fix-run.sh"
    assert override["invariant"] == (
        "each registered target accepts fix_patch_run_cmd and returns it "
        "unchanged before its default command"
    )
    assert "patch application fail before the test command" in override["reason"]
    assert contract["frozen_cells"] == {
        "arms": ["GOLD", "NOOP_BASELINE"],
        "cell_count": 8,
        "target_count": 4,
    }

    targets = contract["targets"]
    assert set(targets) == {
        "django/django",
        "expressjs/express",
        "jqlang/jq",
        "vuejs/core",
    }
    for row in targets.values():
        assert row["override_accepted"] is True
        assert row["default_fix_patch_run"] == "bash /home/fix-run.sh"
        assert row["baked_fix_patch_apply"].endswith("/home/fix.patch")

    django = targets["django/django"]
    assert django["dependency"] == "SWEImageDefault"
    assert django["baked_shell_options"] == "set -uxo pipefail"
    assert django["embedded_errexit"] is False
    assert django["adapter_bash_e_required"] is True
    assert django["baked_fix_patch_apply"] == (
        "git apply --whitespace=nowarn /home/fix.patch"
    )

    expected = {
        "expressjs/express": (
            "ImageDefault",
            "git apply --whitespace=nowarn /home/test.patch /home/fix.patch",
        ),
        "jqlang/jq": (
            "ImageDefault",
            "git apply --whitespace=nowarn /home/test.patch /home/fix.patch",
        ),
        "vuejs/core": (
            "CoreImageDefault",
            "git apply /home/test.patch /home/fix.patch",
        ),
    }
    for name, (dependency, apply_command) in expected.items():
        assert targets[name]["dependency"] == dependency
        assert targets[name]["baked_shell_options"] == "set -e"
        assert targets[name]["embedded_errexit"] is True
        assert targets[name]["adapter_bash_e_required"] is False
        assert targets[name]["baked_fix_patch_apply"] == apply_command


def test_every_source_reference_is_bounded_by_its_locked_blob() -> None:
    lock = _load_lock()
    evidence = [
        value
        for value in _walk(lock["contracts"])
        if isinstance(value, dict)
        and {"path", "start_line", "end_line", "symbol"} <= set(value)
    ]

    assert len(evidence) == 34
    for reference in evidence:
        source = EXPECTED_SOURCE_BLOBS[reference["path"]]
        assert isinstance(reference["symbol"], str) and reference["symbol"]
        assert 1 <= reference["start_line"] <= reference["end_line"] <= source["line_count"]


def test_report_matches_lock_and_no_upstream_source_payload_is_vendored() -> None:
    lock = _load_lock()
    report = "\n".join(
        (
            REPORT_PATH.read_text(encoding="utf-8"),
            SEMANTICS_REPORT_PATH.read_text(encoding="utf-8"),
        )
    )

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
    assert "docker_util.py" in report
    assert "report.py" in report
    assert "StatusCode" in report
    assert "bash -e /home/fix-run.sh" in report
    assert "invalid_reports" in report
    assert "exact frozen" in report
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
