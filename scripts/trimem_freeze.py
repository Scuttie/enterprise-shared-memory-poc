"""Build and verify the explicit TriMem V1 hash-linked freeze.

The freeze is intentionally an allowlist.  It never walks the working tree, so
build products, bytecode, and unrelated product artifacts cannot silently enter
the research seal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

# Keep this module importable by the hosted base-Python preflight.  These are
# immutable repository paths, not executable behavior; importing their owner
# modules here would transitively load the grader/runtime dependency graph.
PROBE_REQUEST_PATH = (
    "artifacts/trimem_v1/probe_requests/"
    "MULTI_SWE_VUE_IMAGE_PROBE_REQUEST_001.json"
)
PROBE_RESULT_PATH = (
    "artifacts/trimem_v1/probe_evidence/"
    "MULTI_SWE_VUE_IMAGE_PROBE_RESULT_001.json"
)
PROBE_RECEIPT_PATH = (
    "artifacts/trimem_v1/probe_evidence/"
    "MULTI_SWE_VUE_IMAGE_PROBE_RECEIPT_001.json"
)
P014_FAILURE_RECEIPT_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/failure-receipt.json"
)
P014_EVIDENCE_INVENTORY_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/evidence-inventory.json"
)
OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/exec-005/failure-receipt.json"
)
OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/exec-005/evidence-inventory.json"
)


FREEZE_PATH = Path("artifacts/trimem_v1/freeze.json")
OFFICIAL_SMOKE_PUBLIC_RESULT_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/exec-005/public-results.json"
)
OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/exec-005/attestation-subject.json"
)
OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/exec-005/attestation-bundle.json"
)
DEV_ACTIVATION_SOURCE_BANK_PAYLOAD_NAMES = (
    "01128d2e2f332bec83f35a3f203ed93838786da14f8a76838e442059fe37585e.json",
    "13d3947c3a4c6c84ab5a28c63cb4f7cd24efa3700a642198fd2df8d26c3ae18e.json",
    "1c0f83594b835adb4806f432044f38cc2818fb9c724057fd9d4c13e8153b6990.json",
    "2c28a9ab6930384201eadce035550205c3651f4c1712645b564f54d37a86db43.json",
    "3f9f0e9e3b8c5d450a51b01a66af41f7ebc4498288c75a8240b9fc9736e6b3ab.json",
    "4cf3b388a8791da9a0a8972f55bd9d1f566adc73dddde70a5dc387dc7f6be53a.json",
    "1d961cd015356bd379f5aebae98026dccb744cd2af3dc019db3edfed87f79938.json",
    "6269b7396846686119ac9c07bcf0040add6a1ce4e8d5b11db58a97922bc33756.json",
    "6fcea77dac89d0649910b881617e775d1ddc689738c3a231d976d41f6943fb86.json",
    "8b12737e862360ca8ef909b11c916845b90f7ce6d45b77eebd817c9f64716558.json",
    "8b9d72af5b6db7f2747b31a062ad65843f9ec41e7ea2a30592d49041eeb8f95d.json",
    "fee09350b25c2d456313877e8900df3a2088c290a6c88f255892ca366a1253ac.json",
)
DEV_ACTIVATION_SOURCE_BANK_RAW_EVIDENCE_NAMES = (
    "06cfed5b2cb047fff19b3438b756fd0460ceb09f4afa54cad7e21b106b11123b.json",
    "1d2a83e7b2af4a13c34a3e10cb14d7fa66211eab01c88ae541289ce4436ec751.json",
    "05bc6ca8670f1d891bd5e22142d0cadc16d90ea34edf32241cfd4251fbbcdb05.json",
    "0889ddf9da937523541046c3a59f7c450a8733e6b631b9a3dc9ca6f0f7ee02f5.json",
    "0b0c5c2f439b984d422b221a62a82b170e9cc6a49ac64a9fec5a750ee7fcbcf6.diff",
    "0b3fa29f99b3e30fbdeefe3da6b57d555c15a8764cfeb0ac7c27c8199b2c4c0b.json",
    "10fc94a9b53c294a69e4fa2a43d0cd7d6c6caf804a0cae23bbb9986dbc3ee98a.diff",
    "11850361cf09a3777b4081159e191e65e03d5fbb6490623ac479c95e0a50dc60.json",
    "1353e63914918c4cbb9aa626280481851a26177ab395b5f3678f386428f4fd6a.json",
    "1ec81f99c1dc3b7cf91ef3a5683a5827da5a48dee0066e1fa89e8c6abb1d36b6.json",
    "1f0d5aa58ba92d789230a6998c27d8dfd8dd503ea7acea3e5ed56ccc1113c051.json",
    "293f32859d2b8f4d00698c484b2a266e9cb9115c70b8e7495f385d8810cdc778.diff",
    "2cec420554ab4049d10454fd338838adf615d424a1c1dfcd1dd03876019e7cf1.json",
    "31358c180f3c4f994a79a5cdd61fdf54c0364c335bc5f38cc5434bb3165e827a.json",
    "341d6e7a56e746ae72c1b630614ecaccdf6aede9a36f969050de413092787b14.diff",
    "350ac832420a524ae54973adec9d7fd391c75bb04f539bc87497d1ed775bb1a3.json",
    "21ba9e9b65fd3a979cd48699595f0df102079cbd2a86dd9e829ffd621521af64.json",
    "3a52fe11cc94557e798b6f30321ea74e48822fcec8237818b131d43abed2fc4d.json",
    "3cfbf86c1bf0362a74102d659da26a1f423e5c951dee58edf1ba8877f449b196.json",
    "406110276a4418dc01588cbcb7d8a9528a42fbdd616973ec233d02091e1f397c.json",
    "42c856f6927dca01b3ee096f423374d04d98533f5b74055537b60e759124da55.json",
    "502f1a93ac55445b26387da56a45bafc8ce30f2a54b451304965d51a636d62ec.json",
    "4810e8f1e887e0e11ffacfc9ae846f54d3aaa8e1540d723afad941b87336e060.diff",
    "49da009d1447333e85f83233688e0e0e0f3a874d98673b4b7d424b4e0365d9f5.json",
    "4c22ce4f55bfecb75e7b467dd446a2e6e728c6c2ccfe8e44862e211cee55de02.json",
    "57049885cb4fa24effc7df7fef5709ee2f19009e1b3ddcb4c40b00b9a69bf861.diff",
    "5ccd702fda2eca93b9cc10be02d5ab7c53aa3b94ee2baf33fdf43a607509ec01.json",
    "591c17dee36151f719e5b014121219417b84c2f060bd47f1670ef977a68f567f.json",
    "6e363ac6a83220911a34868533c0d87bdacd0414b36639c4f74b39a5c955a4ca.diff",
    "6f22c0527268df40f11a8cae01c0efb431883910ae47e10034c1a5760bf2abf4.json",
    "7153127206793dd1447c6dd84924b82f624c1b4682bcbd222346b7e5d99abc47.json",
    "79b3f7342890df335ad8cc4144d2d7c8cf11f6548faa5940c1de136909d3f766.json",
    "75648cd98cebaf3849bb16124ae58f0e15293bfd06f06137bfd2c565e6f1f1b9.json",
    "7a11c60edc442fc813f5e6f3382d1025d51886ae7fb864f2e73a6ea5048f3d52.json",
    "835791e68e8723933bf48f46ff0b67f55e3ecac0c10f6892b37d55fddb6dcc04.json",
    "87e733e1b78c66728ffe2e1c6785554b1e4b91df1da2039e44a103fe275807cf.diff",
    "953f0885ea97cbec6d0d6062b160e0a675ff958635fff0661c3b7e4ed485d9c1.json",
    "976f78e9eb4e5ffda0a1a0794003ce3f33ba7e3be47392438d6bc9602da1ce42.json",
    "821465a5bb2999b04008a0ac0af9e0058287e4eb262134ab7972f4f3fc2db2da.json",
    "913835d9d3b02199a66210f86f1989e4a2d474113f17a3a972f03b17efdc8b63.json",
    "a7d66b5c65070e2e4b5b05b28fd7b7bd2563d3579136aa4debd3e209d2b4dbc8.json",
    "ae265e14d131ca462ff32a81f4aa35a6db19d59e1d9ce42bc59b4a8d388c4cb9.json",
    "b1b134687cd7136d3fd66bbd6a9174d06a29ddadcb649cbbc3baa572fc03cdaf.diff",
    "b1c013a644130b0f32224501ea2e009f19646705e89788452615a5c32c3e5dd9.json",
    "b329f122377b07bbd1257fa3c7931cf9cb006937af3094215aaaf972b9765823.json",
    "b58fd312c7d5e39ccacb2ebf26efa65ed21a1689b992b6094fa6486e5ffd6fc2.diff",
    "c601489e1c511e01335af5ab942a07ae5d01f22d40a0ea358e4be1ba4986dfd8.json",
    "92e0d4c99b28381243b1947e8895cd73343e462de991ba47e650909fbc24f1f1.diff",
    "c6a93a8d021929c6b238093a125225b92e1e4d9c0fae6f441b44352f5a81eddf.json",
    "bb3cdc052c087657f5f56366d8fb414dbd864b2aa3437486390c0f562c45a35b.json",
    "cd7f15e17edc7914bf3996a113a51a3b24a5d40ab58dd593a46d84e3d9b9540a.json",
    "c263b2016c1fea1622a26fb055a6c55be5479f16ab5cae0bdf15e9c14d3389b1.json",
    "d24046511b99d906911060855845d409c1ac8e99abc345c1530abd2c254b69fd.json",
    "d9b70926aede778b58364e8e94ff341b5f830ebb301362fbbac78b5306c4d3c6.json",
    "d01bfa22a67368486089f11914f4012922c5708847bd541ba355dc368c14d366.html",
    "dd59ddf688620f61e3ec576b5c241969c1fdcf4ad289032732705d2c6e8607cc.json",
    "fd4e18e1d1067d01c563b00e00b7e96a82434aee373ad692dc697a76173e900f.json",
    "f152abbd67cd11e4aa9f3b4621a9d3b5dae31cf1e441eabede7a98f2dc9bceac.diff",
    "f7ecc29dd88c41e5a9dadcdfdd2f064c06bc08184f2a33b4761430966b108580.json",
    "f8d2cf5532b4ce298ddf5f4283ee3d861a8be763be9f03721a98b1d1c78221c2.json",
)
DEV_ACTIVATION_SOURCE_BANK_PAYLOAD_PATHS = tuple(
    f"configs/trimem_v1/dev_activation_source_bank_payloads/{name}"
    for name in DEV_ACTIVATION_SOURCE_BANK_PAYLOAD_NAMES
)
DEV_ACTIVATION_SOURCE_BANK_RAW_EVIDENCE_PATHS = tuple(
    f"artifacts/trimem_v1/dev_activation_diagnostic/github_raw/{name}"
    for name in DEV_ACTIVATION_SOURCE_BANK_RAW_EVIDENCE_NAMES
)
CONFIG_PATHS = (
    "configs/trimem_v1/arms.json",
    "configs/trimem_v1/benchmark_environment.in",
    "configs/trimem_v1/benchmark_environment.lock",
    "configs/trimem_v1/benchmark_environment_lock.json",
    "configs/trimem_v1/benchmark_exec_request.json",
    "configs/trimem_v1/cost_plan.json",
    "configs/trimem_v1/dev_activation_manifest.json",
    "configs/trimem_v1/dev_activation_policy.json",
    "configs/trimem_v1/dev_activation_source_bank_manifest.json",
    "configs/trimem_v1/dev_activation_source_bank_plan.json",
    *DEV_ACTIVATION_SOURCE_BANK_PAYLOAD_PATHS,
    "configs/trimem_v1/development_manifest.json",
    "configs/trimem_v1/gh_cli_lock.json",
    "configs/trimem_v1/grader_lock.json",
    "configs/trimem_v1/grader_smoke_manifest.json",
    "configs/trimem_v1/heldout_manifest.json",
    "configs/trimem_v1/m2_candidate_bundles.json",
    "configs/trimem_v1/m2_candidates/balanced.json",
    "configs/trimem_v1/m2_candidates/baseline.json",
    "configs/trimem_v1/m2_candidates/precision.json",
    "configs/trimem_v1/m2_candidates/recall.json",
    "configs/trimem_v1/m2_policy.json",
    "configs/trimem_v1/model_lock.json",
    "configs/trimem_v1/provider_output_schemas.json",
    "configs/trimem_v1/selected_m2.json",
    "configs/trimem_v1/selection_plan.json",
    "configs/trimem_v1/solve_output_budget_contract.json",
    "configs/trimem_v1/sigstore_trusted_root.jsonl",
    "configs/trimem_v1/smoke_attestation_policy.json",
    "configs/trimem_v1/tool_environment_lock.json",
)
ARTIFACT_PATHS = (
    "artifacts/trimem_v1/dev_activation_diagnostic/exec_022_abstention_projection.json",
    "artifacts/trimem_v1/dev_activation_diagnostic/exec_022_abstention_recoverability.json",
    "artifacts/trimem_v1/dev_activation_diagnostic/source_bank_candidate_audit.json",
    "artifacts/trimem_v1/dev_activation_diagnostic/source_chronology_cache.json",
    *DEV_ACTIVATION_SOURCE_BANK_RAW_EVIDENCE_PATHS,
    "tests/fixtures/trimem_d123/d122_remote_ci_evidence.json",
    "artifacts/trimem_v1/development_exec_022_activation_amendment.json",
    "artifacts/trimem_v1/development_exec_022_activation_inventory.json",
    "tests/fixtures/trimem_d122/exec_021_qdrant_nofile_portability_failure.json",
    "artifacts/trimem_v1/development_exec_022_recovery_amendment.json",
    "artifacts/trimem_v1/development_exec_022_recovery_inventory.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_021.json",
    "tests/fixtures/trimem_d121/exec_020_swe_p2p_outcome_misclassification.json",
    "artifacts/trimem_v1/development_exec_021_recovery_amendment.json",
    "artifacts/trimem_v1/development_exec_021_recovery_inventory.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_020.json",
    "tests/fixtures/trimem_d120/exec_019_shared_swe_harness_runtime_failure.json",
    "artifacts/trimem_v1/development_exec_020_recovery_amendment.json",
    "artifacts/trimem_v1/development_exec_020_recovery_inventory.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_019.json",
    "tests/fixtures/trimem_d119/exec_018_approval_bom_failure.json",
    "artifacts/trimem_v1/development_exec_019_recovery_amendment.json",
    "artifacts/trimem_v1/development_exec_019_recovery_inventory.json",
    "tests/fixtures/trimem_d118/exec_017_python_launcher_alias_failure.json",
    "artifacts/trimem_v1/development_exec_018_recovery_amendment.json",
    "artifacts/trimem_v1/development_exec_018_recovery_inventory.json",
    "tests/fixtures/trimem_d117/exec_016_checkout_portability_failure.json",
    "artifacts/trimem_v1/development_exec_017_recovery_amendment.json",
    "artifacts/trimem_v1/development_exec_017_recovery_inventory.json",
    "tests/fixtures/trimem_d116/exec_015_preapproval_freshness_scope_failure.json",
    "artifacts/trimem_v1/development_exec_016_recovery_amendment.json",
    "artifacts/trimem_v1/development_exec_016_recovery_inventory.json",
    "tests/fixtures/trimem_d115/exec_014_loader_failure.json",
    "artifacts/trimem_v1/development_exec_015_recovery_amendment.json",
    "artifacts/trimem_v1/development_exec_015_recovery_inventory.json",
    "tests/fixtures/trimem_d114/exec_013_post_setup_failure.json",
    "artifacts/trimem_v1/development_exec_014_recovery_amendment.json",
    "artifacts/trimem_v1/development_exec_014_recovery_inventory.json",
    "tests/fixtures/trimem_d113/exec_012_preprotected_failure.json",
    "artifacts/trimem_v1/development_exec_013_recovery_amendment.json",
    "artifacts/trimem_v1/development_exec_013_recovery_inventory.json",
    "artifacts/trimem_v1/development_exec_012_activation_amendment.json",
    "artifacts/trimem_v1/development_exec_012_activation_inventory.json",
    "artifacts/trimem_v1/development_activation_lifecycle_amendment.json",
    "artifacts/trimem_v1/development_activation_lifecycle_inventory.json",
    "artifacts/trimem_v1/development_grader_launch_stream_commit_amendment.json",
    "artifacts/trimem_v1/development_grader_launch_stream_commit_inventory.json",
    "artifacts/trimem_v1/development_bounded_context_inventory.json",
    "artifacts/trimem_v1/development_bounded_context_amendment.json",
    "artifacts/trimem_v1/development_terminal_contract_inventory.json",
    "artifacts/trimem_v1/development_terminal_contract_amendment.json",
    "artifacts/trimem_v1/development_credential_control_plane_amendment.json",
    "artifacts/trimem_v1/development_model_pricing_amendment.json",
    "artifacts/trimem_v1/development_runner_toolchain_amendment.json",
    "artifacts/trimem_v1/development_response_contract_amendment.json",
    "artifacts/trimem_v1/development_solve_execution_contract_amendment.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-004/solve-0005-output-shape-forensics.json",
    "artifacts/trimem_v1/solve_output_budget_contract_lock.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-001/preflight-failure-receipt.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-002/protected-exec-gate-failure-receipt.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-003/model-parser-failure-receipt.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-003/provider-observability-terminology-amendment.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-004/provider-incomplete-max-output-tokens-receipt.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-005/http-auth-error-receipt.json",
    "artifacts/trimem_v1/provider_output_schema_lock.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_001.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_002.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_003.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_004.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_005.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_006.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_007.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_008.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_009.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_010.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_011.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_012.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_013.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_014.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_015.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_016.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_017.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_018.json",
    "artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST.json",
    "artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST_002.json",
    "artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST_003.json",
    "artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST_004.json",
    "artifacts/trimem_v1/credential_free_e2e/credential_free_e2e_bundle.json",
    "artifacts/trimem_v1/credential_free_e2e/dqn_frozen_checkpoint.json",
    "artifacts/trimem_v1/credential_free_e2e/source-json-extension/checkpoints/source-json-extension-M2.json",
    "artifacts/trimem_v1/credential_free_e2e/source-json-extension/checkpoints/source-json-extension-M2.sha256",
    "artifacts/trimem_v1/credential_free_e2e/source-json-extension/evidence/events.ndjson",
    "artifacts/trimem_v1/credential_free_e2e/target-yaml-extension/checkpoints/target-yaml-extension-M2.json",
    "artifacts/trimem_v1/credential_free_e2e/target-yaml-extension/checkpoints/target-yaml-extension-M2.sha256",
    "artifacts/trimem_v1/credential_free_e2e/target-yaml-extension/evidence/events.ndjson",
    "artifacts/trimem_v1/grader_image_lock.json",
    "artifacts/trimem_v1/multi_swe_evaluation_contract_lock.json",
    "artifacts/trimem_v1/multi_swe_report_semantics_lock.json",
    "artifacts/trimem_v1/adapter_failure_envelope_contract.json",
    "artifacts/trimem_v1/development_action_protocol_amendment.json",
    "artifacts/trimem_v1/development_approval_consumer_contract_fix.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-006/action-protocol-failure-receipt.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-007/approval-schema-mismatch-receipt.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-008/terminal-status-contract-mismatch-receipt.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-009/bounded-short-term-context-failure-receipt.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-009/request-only-boundary-fixture.json",
    P014_FAILURE_RECEIPT_PATH,
    P014_EVIDENCE_INVENTORY_PATH,
    "artifacts/trimem_v1/benchmark_environment_protection.json",
    "artifacts/trimem_v1/grader_smoke_environment_protection.json",
    "artifacts/trimem_v1/grader_smoke_result.json",
    "artifacts/trimem_v1/noop_baseline_six_commit_audit.json",
    "artifacts/trimem_v1/readiness_requirements.json",
    "artifacts/trimem_v1/upstream_source_audit.json",
)
SCRIPT_PATHS = (
    "scripts/make_handoff_manifest.py",
    "scripts/run_trimem_replay_e2e.py",
    "scripts/trimem_atomic_evidence.py",
    "scripts/trimem_audit_encrypted_evidence.py",
    "scripts/trimem_approved_phase.py",
    "scripts/trimem_benchmark_matrix.py",
    "scripts/trimem_benchmark_run.py",
    "scripts/trimem_cleanup_exec.py",
    "scripts/trimem_development_trigger_preflight.py",
    "scripts/trimem_dev_activation_diagnostic.py",
    "scripts/trimem_dev_activation_approval.py",
    "scripts/trimem_dev_activation_executor.py",
    "scripts/trimem_dev_activation_gate.py",
    "scripts/trimem_dev_activation_github_capture.py",
    "scripts/trimem_dev_activation_source_bank.py",
    "scripts/trimem_development_trigger_d15.py",
    "scripts/trimem_development_trigger_d18.py",
    "scripts/trimem_development_trigger_d19.py",
    "scripts/trimem_development_trigger_d110.py",
    "scripts/trimem_development_trigger_d112.py",
    "scripts/trimem_development_trigger_d113.py",
    "scripts/trimem_development_trigger_d114.py",
    "scripts/trimem_development_trigger_d115.py",
    "scripts/trimem_development_trigger_d116.py",
    "scripts/trimem_d116_loader_rehearsal.py",
    "scripts/trimem_development_trigger_d117.py",
    "scripts/trimem_d117_checkout_rehearsal.py",
    "scripts/trimem_d117_loader_rehearsal.py",
    "scripts/trimem_development_trigger_d118.py",
    "scripts/trimem_d118_loader_rehearsal.py",
    "scripts/trimem_d118_grader_factory_rehearsal.py",
    "scripts/trimem_development_trigger_d119.py",
    "scripts/trimem_d119_approval_secret.py",
    "scripts/trimem_d119_loader_rehearsal.py",
    "scripts/trimem_development_trigger_d120.py",
    "scripts/trimem_d120_loader_rehearsal.py",
    "scripts/trimem_development_trigger_d121.py",
    "scripts/trimem_d121_loader_rehearsal.py",
    "scripts/trimem_d121_reseal.py",
    "scripts/trimem_development_trigger_d122.py",
    "scripts/trimem_d122_qdrant_nofile_rehearsal.py",
    "scripts/trimem_d122_reseal.py",
    "scripts/trimem_development_trigger_d123.py",
    "scripts/trimem_d123_loader_rehearsal.py",
    "scripts/trimem_d123_reseal.py",
    "scripts/trimem_swe_bench_entrypoint.py",
    "scripts/trimem_development_phase_cap.py",
    "scripts/trimem_context_roundtrip.py",
    "scripts/trimem_d110_reseal.py",
    "scripts/trimem_d111_gate_contract.py",
    "scripts/trimem_d111_reseal.py",
    "scripts/trimem_d112_reseal.py",
    "scripts/trimem_d113_gate_contract.py",
    "scripts/trimem_d113_reseal.py",
    "scripts/trimem_d114_gate_contract.py",
    "scripts/trimem_d114_reseal.py",
    "scripts/trimem_compiled_prefix_alias.py",
    "scripts/trimem_d115_gate_contract.py",
    "scripts/trimem_d115_loader_rehearsal.py",
    "scripts/trimem_d115_reseal.py",
    "scripts/trimem_d19_reseal.py",
    "scripts/trimem_action_canary.py",
    "scripts/trimem_evidence_inventory.py",
    "scripts/trimem_exec_approval.py",
    "scripts/trimem_freeze.py",
    "scripts/release_check.py",
    "scripts/trimem_grader_smoke.py",
    "scripts/trimem_grader_smoke_authority.py",
    "scripts/trimem_grader_smoke_failure_closure.py",
    "scripts/trimem_grader_smoke_failure_evidence.py",
    "scripts/trimem_grader_smoke_finalization.py",
    "scripts/trimem_grader_smoke_stage_evidence.py",
    "scripts/trimem_grader_smoke_protocol.py",
    "scripts/trimem_grader_smoke_trigger_preflight.py",
    "scripts/trimem_harness_lock.py",
    "scripts/trimem_install_pinned_gh.py",
    "scripts/trimem_m2_candidates.py",
    "scripts/trimem_multi_swe_contract.py",
    "scripts/trimem_multi_swe_entrypoint.py",
    "scripts/trimem_multi_swe_image_probe.py",
    "scripts/trimem_multi_swe_probe_evidence.py",
    "scripts/trimem_multi_swe_probe_request.py",
    "scripts/trimem_multi_swe_preexec.py",
    "scripts/trimem_multi_swe_report_semantics.py",
    "scripts/trimem_official_grader.py",
    "scripts/trimem_official_harness_loader.py",
    "scripts/trimem_official_harness_loader_preflight.py",
    "scripts/trimem_openai_model_access_check.py",
    "scripts/trimem_public_artifact.py",
    "scripts/trimem_pull_locked_images.py",
    "scripts/trimem_provider_output_contract.py",
    "scripts/trimem_pytest_no_skip.py",
    "scripts/trimem_run_with_resume.py",
    "scripts/trimem_select_targets.py",
    "scripts/trimem_smoke_attestation.py",
    "scripts/trimem_verify_credential_free.py",
    "scripts/trimem_validate_openai_credential.py",
    "scripts/trimem_verify_openai_key_binding.py",
    "scripts/trimem_verify_gh_lock.py",
    "scripts/trimem_verify_ready.py",
    "scripts/trimem_verify_remote_custody.py",
)
SOURCE_PATHS = (
    "src/enterprise_memory/contracts/codec.py",
    "src/enterprise_memory/contracts/schema.py",
    "src/enterprise_memory/indexing/canonical_loaders.py",
    "src/enterprise_memory/indexing/__init__.py",
    "src/enterprise_memory/indexing/drift.py",
    "src/enterprise_memory/indexing/embeddings.py",
    "src/enterprise_memory/indexing/index_worker.py",
    "src/enterprise_memory/indexing/models.py",
    "src/enterprise_memory/indexing/projection.py",
    "src/enterprise_memory/indexing/qdrant_indexes.py",
    "src/enterprise_memory/indexing/reindex.py",
    "src/enterprise_memory/indexing/validated_search.py",
    "src/enterprise_memory/persistence/__init__.py",
    "src/enterprise_memory/persistence/postgres/__init__.py",
    "src/enterprise_memory/persistence/postgres/repos.py",
    "src/enterprise_memory/persistence/tenant_context.py",
    "src/enterprise_memory/promotion/security_scan.py",
    "src/enterprise_memory/providers/__init__.py",
    "src/enterprise_memory/providers/base.py",
    "src/enterprise_memory/providers/openai_credential.py",
    "src/enterprise_memory/providers/openai_responses.py",
    "src/enterprise_memory/providers/redaction.py",
    "src/enterprise_memory/service/durable.py",
    "src/enterprise_memory/service/__init__.py",
    "src/enterprise_memory/service/injection.py",
    "src/enterprise_memory/service/private_view.py",
    "src/enterprise_memory/trimem/__init__.py",
    "src/enterprise_memory/trimem/accounting.py",
    "src/enterprise_memory/trimem/adaptive_horizon.py",
    "src/enterprise_memory/trimem/agent_runtime.py",
    "src/enterprise_memory/trimem/arms.py",
    "src/enterprise_memory/trimem/benchmark_seed.py",
    "src/enterprise_memory/trimem/checkpoint.py",
    "src/enterprise_memory/trimem/consolidation.py",
    "src/enterprise_memory/trimem/context_projection.py",
    "src/enterprise_memory/trimem/credential_free.py",
    "src/enterprise_memory/trimem/gateway.py",
    "src/enterprise_memory/trimem/function_tools.py",
    "src/enterprise_memory/trimem/git_workspace.py",
    "src/enterprise_memory/trimem/grader.py",
    "src/enterprise_memory/trimem/lifecycle.py",
    "src/enterprise_memory/trimem/policy.py",
    "src/enterprise_memory/trimem/postgres_retrieval.py",
    "src/enterprise_memory/trimem/postgres_store.py",
    "src/enterprise_memory/trimem/ppr.py",
    "src/enterprise_memory/trimem/provider_output_contracts.py",
    "src/enterprise_memory/trimem/production_lifecycle.py",
    "src/enterprise_memory/trimem/production_promotion.py",
    "src/enterprise_memory/trimem/production_runtime.py",
    "src/enterprise_memory/trimem/production_v03_lifecycle.py",
    "src/enterprise_memory/trimem/retrieval.py",
    "src/enterprise_memory/trimem/retrieval_store.py",
    "src/enterprise_memory/trimem/runtime_lock.py",
    "src/enterprise_memory/trimem/schema.py",
    "src/enterprise_memory/trimem/scientific_terminal.py",
    "src/enterprise_memory/trimem/solve_forensics.py",
    "src/enterprise_memory/trimem/store.py",
    "src/enterprise_memory/trimem/vector_index.py",
    "src/enterprise_memory/trimem/working_graph.py",
    "src/enterprise_memory/trimem/workspace.py",
)
MIGRATION_PATHS = (
    "migrations/env.py",
    "migrations/script.py.mako",
    "migrations/versions/0001_initial_production_schema.py",
    "migrations/versions/0002_p1_hardening.py",
    "migrations/versions/0003_canonical_and_dispatch_integrity.py",
    "migrations/versions/0004_index_worker_and_lease.py",
    "migrations/versions/0005_lease_invariants.py",
    "migrations/versions/0006_index_audit_and_heartbeat.py",
    "migrations/versions/0007_artifact_lifecycle.py",
    "migrations/versions/0008_solve_job_snapshot.py",
    "migrations/versions/0009_injection_provenance.py",
    "migrations/versions/0010_idempotent_terminal.py",
    "migrations/versions/0011_task_policy_expansion.py",
    "migrations/versions/0012_experiment_arm.py",
    "migrations/versions/0013_job_patches.py",
    "migrations/versions/0014_experience_memory.py",
    "migrations/versions/0015_trimem_graph_memory.py",
    *(f"migrations/sql/{revision:04d}_up.sql" for revision in range(1, 16)),
    *(f"migrations/sql/{revision:04d}_up.sha256" for revision in range(1, 16)),
)
TEST_PATHS = (
    "tests/trimem/e2e/test_full_replay.py",
    "tests/trimem/test_real_services_e2e.py",
    "tests/unit/test_company_handoff_manifest.py",
    "tests/unit/test_trimem_atomic_evidence.py",
    "tests/unit/test_trimem_accounting_checkpoint.py",
    "tests/unit/test_trimem_benchmark_checkpoint_recovery.py",
    "tests/unit/test_trimem_benchmark_readiness.py",
    "tests/unit/test_trimem_development_trigger.py",
    "tests/unit/test_trimem_dev_activation_diagnostic.py",
    "tests/unit/test_trimem_dev_activation_executor.py",
    "tests/unit/test_trimem_dev_activation_github_capture.py",
    "tests/unit/test_trimem_dev_activation_readiness.py",
    "tests/unit/test_trimem_dev_activation_source_bank.py",
    "tests/unit/test_trimem_d14_solve_contract.py",
    "tests/unit/test_trimem_d15_credential_control.py",
    "tests/unit/test_trimem_evidence_custody.py",
    "tests/unit/test_trimem_dev_toolchain_workflows.py",
    "tests/unit/test_trimem_d110_official_harness_loader.py",
    "tests/unit/test_trimem_d110_resume_fail_closed.py",
    "tests/unit/test_trimem_d110_atomic_resume.py",
    "tests/unit/test_trimem_d110_checkout_custody.py",
    "tests/unit/test_trimem_d110_status_and_reseal.py",
    "tests/unit/test_trimem_d110_e1_trigger.py",
    "tests/unit/test_trimem_d111_gate_contract.py",
    "tests/unit/test_trimem_d112_e1_trigger.py",
    "tests/unit/test_trimem_d112_status_and_reseal.py",
    "tests/unit/test_trimem_d113_e1_trigger.py",
    "tests/unit/test_trimem_d113_gate_contract.py",
    "tests/unit/test_trimem_d113_status_and_reseal.py",
    "tests/unit/test_trimem_d114_e1_trigger.py",
    "tests/unit/test_trimem_d114_gate_contract.py",
    "tests/unit/test_trimem_d114_post_setup_environment.py",
    "tests/unit/test_trimem_d114_status_and_reseal.py",
    "tests/unit/test_trimem_d115_compiled_prefix_alias.py",
    "tests/unit/test_trimem_d115_gate_contract.py",
    "tests/unit/test_trimem_d115_status_and_reseal.py",
    "tests/unit/test_trimem_d115_trigger.py",
    "tests/unit/test_trimem_d116_trigger.py",
    "tests/unit/test_trimem_d117_trigger.py",
    "tests/unit/test_trimem_d118_trigger.py",
    "tests/unit/test_trimem_d118_grader_factory_rehearsal.py",
    "tests/unit/test_trimem_d119_trigger.py",
    "tests/unit/test_trimem_d119_approval_secret.py",
    "tests/unit/test_trimem_d120_trigger.py",
    "tests/unit/test_trimem_d121_trigger.py",
    "tests/unit/test_trimem_d122_qdrant_nofile_rehearsal.py",
    "tests/unit/test_trimem_d122_trigger.py",
    "tests/unit/test_trimem_d123_trigger.py",
    "tests/unit/test_trimem_adaptive_horizon.py",
    "tests/unit/test_trimem_swe_bench_entrypoint.py",
    "tests/unit/test_trimem_grader_smoke_trigger.py",
    "tests/unit/test_trimem_grader_smoke_authority.py",
    "tests/unit/test_trimem_grader_smoke_execution_accounting.py",
    "tests/unit/test_trimem_grader_smoke_failure_evidence.py",
    "tests/unit/test_trimem_grader_terminal_evidence.py",
    "tests/unit/test_trimem_harness_lock.py",
    "tests/unit/test_trimem_remote_custody.py",
    "tests/unit/test_trimem_pinned_gh.py",
    "tests/unit/test_trimem_multi_prebuilt_evaluation.py",
    "tests/unit/test_trimem_multi_swe_entrypoint.py",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py",
    "tests/unit/test_trimem_multi_swe_image_probe.py",
    "tests/unit/test_trimem_multi_swe_probe_evidence.py",
    "tests/unit/test_trimem_multi_swe_probe_request.py",
    "tests/unit/test_trimem_multi_swe_preexec.py",
    "tests/unit/test_trimem_multi_swe_report_semantics.py",
    "tests/unit/test_trimem_p015_production_semantics_path.py",
    "tests/unit/test_trimem_git_workspace.py",
    "tests/unit/test_trimem_d16_native_action.py",
    "tests/unit/test_trimem_d17_approval_cap_integration.py",
    "tests/unit/test_trimem_d18_terminal_contract_integration.py",
    "tests/unit/test_trimem_d18_public_artifact_hardening.py",
    "tests/unit/test_trimem_d19_bounded_short_term_context.py",
    "tests/unit/test_trimem_d19_failed_cell_resume.py",
    "tests/unit/test_trimem_d19_list_files_pagination.py",
    "tests/unit/test_trimem_d19_model_preflight.py",
    "tests/unit/test_trimem_d19_request_only_resume.py",
    "tests/unit/test_trimem_d19_terminal_contract.py",
    "tests/unit/test_trimem_d19_trigger.py",
    "tests/unit/test_trimem_m1_postwrite_recovery.py",
    "tests/unit/test_trimem_policy_consolidation.py",
    "tests/unit/test_trimem_postgres_retrieval.py",
    "tests/unit/test_trimem_postgres_store.py",
    "tests/unit/test_trimem_production_lifecycle.py",
    "tests/unit/test_trimem_production_runtime.py",
    "tests/unit/test_trimem_production_storage_e2e.py",
    "tests/unit/test_trimem_retrieval_store.py",
    "tests/unit/test_trimem_runtime_boundaries.py",
    "tests/unit/test_trimem_schema_sql.py",
    "tests/unit/test_trimem_schema_store.py",
    "tests/unit/test_trimem_smoke_attestation_only.py",
    "tests/unit/test_trimem_vector_index.py",
    "tests/unit/test_trimem_working_retrieval.py",
)
FIXTURE_PATHS = (
    "tests/fixtures/trimem_d110/exec_010_sanitized.json",
    "tests/fixtures/trimem_d111/exec_011_branch_transition.json",
)
WORKFLOW_PATHS = (
    ".github/workflows/ci.yml",
    ".github/workflows/codeql.yml",
    ".github/workflows/ci-docs.yml",
    ".github/workflows/ci-company-package.yml",
    ".github/workflows/ci-company-harness.yml",
    ".github/workflows/ci-company-demo.yml",
    ".github/workflows/ci-experience-schema.yml",
    ".github/workflows/ci-oidc.yml",
    ".github/workflows/ci-oss-release.yml",
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/ci-trimem-e2e.yml",
    ".github/workflows/ci-trimem-harness-lock.yml",
    ".github/workflows/ci-trimem-grader-loader.yml",
    ".github/workflows/ci-trimem-multi-swe-contract.yml",
    ".github/workflows/ci-trimem-dev-toolchain.yml",
    ".github/workflows/ci-trimem-dev-activation-diagnostic.yml",
    ".github/workflows/trimem-benchmark.yml",
    ".github/workflows/trimem-grader-smoke.yml",
)
FROZEN_PATHS = (
    ".gitattributes",
    ".gitignore",
    "alembic.ini",
    "DEPENDENCY_PROVENANCE.json",
    "docs/TRIMEM_V1_SYSTEM.md",
    "reports/TRIMEM_D110_GRADER_LAUNCH_STREAM_COMMIT_CORRECTION.md",
    "reports/TRIMEM_D111_ACTIVATION_LIFECYCLE_CORRECTION.md",
    "reports/TRIMEM_D112_EXEC_012_ACTIVATION.md",
    "reports/TRIMEM_D113_EXEC_013_RECOVERY.md",
    "reports/TRIMEM_D114_EXEC_014_RECOVERY.md",
    "reports/TRIMEM_D115_EXEC_015_RECOVERY.md",
    "reports/TRIMEM_D116_EXEC_016_RECOVERY.md",
    "reports/TRIMEM_D117_EXEC_017_RECOVERY.md",
    "reports/TRIMEM_D118_EXEC_018_RECOVERY.md",
    "reports/TRIMEM_D119_EXEC_019_RECOVERY.md",
    "reports/TRIMEM_D120_EXEC_020_RECOVERY.md",
    "reports/TRIMEM_D121_EXEC_021_RECOVERY.md",
    "reports/TRIMEM_D122_EXEC_022_RECOVERY.md",
    "reports/TRIMEM_D123_EXEC_022_ACTIVATION.md",
    "reports/TRIMEM_DEV_ACTIVATION_DIAGNOSTIC.md",
    "reports/TRIMEM_DEV_ACTIVATION_DIAGNOSTIC_CONTRACT.md",
    "reports/TRIMEM_DEV_ACTIVATION_DIAGNOSTIC_EXEC_001_PREFLIGHT_FAILURE.md",
    "reports/TRIMEM_DEV_ACTIVATION_DIAGNOSTIC_EXEC_002_APPROVAL_GATE_FAILURE.md",
    "reports/TRIMEM_DEV_ACTIVATION_DIAGNOSTIC_EXEC_003_WORKSPACE_STATUS_FAILURE.md",
    "reports/TRIMEM_DEV_ACTIVATION_DIAGNOSTIC_EXEC_004_SOLVER_SANDBOX_MOUNT_FAILURE.md",
    "reports/TRIMEM_DEVELOPMENT_TUNING_EXEC_001_PREFLIGHT_FAILURE.md",
    "reports/TRIMEM_DEVELOPMENT_TUNING_EXEC_002_PROTECTED_GATE_FAILURE.md",
    "reports/TRIMEM_GRADER_SMOKE_EXEC_004_FAILURE.md",
    "reports/TRIMEM_MULTI_SWE_EVALUATION_CONTRACT.md",
    "reports/TRIMEM_MULTI_SWE_REPORT_SEMANTICS.md",
    "reports/TRIMEM_D14_SOLVE_0005_OUTPUT_SHAPE_FORENSICS.md",
    "reports/TRIMEM_DEVELOPMENT_TUNING_EXEC_005_HTTP_AUTH_FAILURE.md",
    "reports/TRIMEM_DEVELOPMENT_TUNING_EXEC_008_TERMINAL_STATUS_CONTRACT_MISMATCH.md",
    "reports/TRIMEM_DEVELOPMENT_TUNING_EXEC_009_BOUNDED_CONTEXT_FAILURE.md",
    "pyproject.toml",
    "requirements.lock",
    "scripts/check_migration_head.py",
    "scripts/postgres_bootstrap.py",
    "scripts/postgres_bootstrap_roles.sql",
    "src/enterprise_memory/service/app.py",
    "tests/openai/test_openai_provider.py",
    "tests/openai/test_openai_response_outcomes.py",
    "tests/unit/test_release_hygiene.py",
    *CONFIG_PATHS,
    *ARTIFACT_PATHS,
    *SCRIPT_PATHS,
    *SOURCE_PATHS,
    *MIGRATION_PATHS,
    *TEST_PATHS,
    *FIXTURE_PATHS,
    *WORKFLOW_PATHS,
)
POST_DEVELOPMENT_PATH_FIELDS = (
    "development_selection_evidence_path",
    "selected_checkpoint_path",
    "selected_full_policy_path",
)
OFFICIAL_SMOKE_EVIDENCE_PATH_FIELDS = {
    "attestation_bundle_path": OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH,
    "attestation_subject_path": OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH,
    "public_result_path": OFFICIAL_SMOKE_PUBLIC_RESULT_PATH,
    "evidence_inventory_path": OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
}
OFFICIAL_SMOKE_FAILURE_EVIDENCE_PATH_FIELDS = {
    "failure_receipt_path": OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH,
    "evidence_inventory_path": OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
}
EVIDENCE_EVENT_PATHS = (
    "artifacts/trimem_v1/credential_free_e2e/source-json-extension/evidence/events.ndjson",
    "artifacts/trimem_v1/credential_free_e2e/target-yaml-extension/evidence/events.ndjson",
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw: str, *, label: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key in {label}: {key}")
            value[key] = child
        return value
    return json.loads(raw, object_pairs_hook=reject_duplicate_keys)


def _safe_file(root: Path, relative: str) -> Path:
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError(f"unsafe freeze path: {relative}")
    target = (root / relative).resolve()
    if root.resolve() not in target.parents:
        raise ValueError(f"freeze path escapes repository: {relative}")
    if target.is_symlink() or not target.is_file():
        raise ValueError(f"required regular file is missing: {relative}")
    return target


def referenced_blob_paths(root: Path) -> tuple[str, ...]:
    """Derive the blob allowlist only from hash-bound committed event streams."""

    references: dict[str, int] = {}

    def collect(value: Any, *, event_path: Path) -> None:
        if isinstance(value, dict):
            marker = {"sha256", "bytes", "media_type"}
            if marker <= set(value):
                blob_hash, size = value.get("sha256"), value.get("bytes")
                if (
                    not isinstance(blob_hash, str)
                    or len(blob_hash) != 64
                    or any(character not in "0123456789abcdef" for character in blob_hash)
                    or type(size) is not int
                    or size < 0
                    or not isinstance(value.get("media_type"), str)
                    or not value["media_type"]
                ):
                    raise ValueError(f"malformed evidence blob reference: {event_path}")
                relative = (event_path.parent / "blobs" / blob_hash).relative_to(root).as_posix()
                previous = references.setdefault(relative, size)
                if previous != size:
                    raise ValueError(f"conflicting evidence blob sizes: {blob_hash}")
            for child in value.values():
                collect(child, event_path=event_path)
        elif isinstance(value, list):
            for child in value:
                collect(child, event_path=event_path)

    for relative in EVIDENCE_EVENT_PATHS:
        path = _safe_file(root, relative)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line:
                continue
            row = strict_json(line, label=f"{relative}:{line_number}")
            collect(row, event_path=path)
    if not references:
        raise ValueError("credential-free event streams contain no blob references")
    for relative, size in references.items():
        path = _safe_file(root, relative)
        raw = path.read_bytes()
        expected_hash = path.name
        if len(raw) != size or sha256(raw) != expected_hash:
            raise ValueError(f"evidence blob content-address mismatch: {relative}")
    return tuple(sorted(references))


def conditional_probe_evidence_paths(root: Path) -> tuple[str, ...]:
    """Return the all-or-none post-probe freeze extension.

    The correction commit has no marker and the marker-only child deliberately
    keeps the correction freeze byte-for-byte.  Once a result or receipt is
    present, all three regular files are mandatory and become freeze inputs.
    """

    paths = (PROBE_REQUEST_PATH, PROBE_RESULT_PATH, PROBE_RECEIPT_PATH)
    present = tuple(
        (root / relative).exists() or (root / relative).is_symlink()
        for relative in paths
    )
    if present == (False, False, False) or present == (True, False, False):
        if present[0]:
            _safe_file(root, PROBE_REQUEST_PATH)
        return ()
    if present != (True, True, True):
        raise ValueError(
            "probe evidence freeze phase must be absent, marker-only, or the exact trio"
        )
    for relative in paths:
        _safe_file(root, relative)
    return paths


def frozen_paths(root: Path) -> tuple[str, ...]:
    """Return the closed allowlist for the current pre/post-development phase."""

    paths = [
        *FROZEN_PATHS,
        *referenced_blob_paths(root),
        *conditional_probe_evidence_paths(root),
    ]
    smoke_path = root / "artifacts/trimem_v1/grader_smoke_result.json"
    smoke = strict_json(
        smoke_path.read_text(encoding="utf-8"), label=smoke_path.as_posix()
    )
    if not isinstance(smoke, dict):
        raise ValueError("grader smoke result root is not an object")
    smoke_status = smoke.get("status")
    if smoke_status == "PASS":
        if "official_execution_failure_evidence" in smoke:
            raise ValueError(
                "passed grader smoke cannot claim official execution failure evidence"
            )
        evidence = smoke.get("official_execution_evidence")
        if not isinstance(evidence, dict):
            raise ValueError("passed grader smoke lacks official execution evidence")
        for field, expected_path in OFFICIAL_SMOKE_EVIDENCE_PATH_FIELDS.items():
            if evidence.get(field) != expected_path:
                raise ValueError(f"passed grader smoke has noncanonical {field}")
            paths.append(expected_path)
    elif smoke_status == "FAIL":
        if "official_execution_evidence" in smoke:
            raise ValueError(
                "failed grader smoke cannot claim passed official execution evidence"
            )
        evidence = smoke.get("official_execution_failure_evidence")
        if not isinstance(evidence, dict):
            raise ValueError("failed grader smoke lacks official execution failure evidence")
        for field, expected_path in OFFICIAL_SMOKE_FAILURE_EVIDENCE_PATH_FIELDS.items():
            if evidence.get(field) != expected_path:
                raise ValueError(f"failed grader smoke has noncanonical {field}")
            if expected_path not in paths:
                paths.append(expected_path)
        for relative in (
            OFFICIAL_SMOKE_PUBLIC_RESULT_PATH,
            OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH,
            OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH,
        ):
            target = root / relative
            if target.exists() or target.is_symlink():
                raise ValueError(
                    f"failed grader smoke cannot retain passed execution artifact: {relative}"
                )
    elif smoke_status in {
        "CORRECTION_IN_PROGRESS",
        "CORRECTION_READY_FOR_EXECUTION",
    }:
        if (
            "official_execution_evidence" in smoke
            or "official_execution_failure_evidence" in smoke
        ):
            raise ValueError(
                "pre-exec grader smoke cannot claim official execution evidence"
            )
    else:
        raise ValueError("grader smoke result has an unknown freeze phase")
    selected_path = root / "configs/trimem_v1/selected_m2.json"
    selected = strict_json(selected_path.read_text(encoding="utf-8"), label=selected_path.as_posix())
    if not isinstance(selected, dict):
        raise ValueError("selected M2 manifest root is not an object")
    status = selected.get("status")
    if status == "FROZEN_AFTER_DEVELOPMENT":
        for field in POST_DEVELOPMENT_PATH_FIELDS:
            relative = selected.get(field)
            if not isinstance(relative, str) or relative.startswith("PENDING"):
                raise ValueError(f"frozen selected M2 lacks exact path: {field}")
            paths.append(relative)
    elif status != "PRE_DEVELOPMENT":
        raise ValueError("selected M2 has an unknown freeze phase")
    if len(paths) != len(set(paths)):
        raise ValueError("freeze allowlist contains duplicate paths")
    return tuple(paths)


def build_freeze(root: Path) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    for relative in sorted(frozen_paths(root)):
        raw = _safe_file(root, relative).read_bytes()
        files[relative] = {"bytes": len(raw), "sha256": sha256(raw)}
    return {
        "files": files,
        "hash_algorithm": "sha256",
        "path_policy": (
            "explicit_allowlist_plus_hash_bound_event_blob_references_plus_"
            "conditional_probe_evidence_triad_no_tree_walk"
        ),
        "schema": "trimem/freeze/1.0",
    }


def git_untracked_frozen_paths(root: Path) -> list[str]:
    required = frozen_paths(root)
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    tracked = {
        item.decode("utf-8", errors="strict").replace("\\", "/")
        for item in completed.stdout.split(b"\0")
        if item
    }
    return sorted(set(required) - tracked)


def check_freeze(root: Path, *, require_git_tracked: bool = False) -> dict[str, Any]:
    expected = build_freeze(root)
    path = root / FREEZE_PATH
    if not path.is_file():
        raise ValueError(f"missing freeze: {FREEZE_PATH.as_posix()}")
    try:
        observed = strict_json(path.read_text(encoding="utf-8"), label=FREEZE_PATH.as_posix())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("freeze is not valid UTF-8 JSON") from exc
    if observed != expected:
        expected_files = expected["files"]
        observed_files = observed.get("files", {}) if isinstance(observed, dict) else {}
        missing = sorted(set(expected_files) - set(observed_files))
        extra = sorted(set(observed_files) - set(expected_files))
        changed = sorted(
            path for path in set(expected_files) & set(observed_files) if expected_files[path] != observed_files[path]
        )
        raise ValueError(f"freeze mismatch: missing={missing}, extra={extra}, changed={changed}")
    if require_git_tracked:
        untracked = git_untracked_frozen_paths(root)
        if untracked:
            raise ValueError(f"frozen paths are not git-tracked: {untracked}")
        completed = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", FREEZE_PATH.as_posix()],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise ValueError("freeze.json is not git-tracked")
    return expected


def write_freeze(root: Path) -> None:
    target = root / FREEZE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_json(build_freeze(root))
    fd, temp_name = tempfile.mkstemp(prefix=".trimem-freeze-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--emit", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--require-git-tracked", action="store_true")
    args = parser.parse_args()
    root = repository_root()
    try:
        if args.emit:
            print(canonical_json(build_freeze(root)).decode("utf-8"), end="")
        elif args.write:
            write_freeze(root)
            print(f"wrote {FREEZE_PATH.as_posix()}")
        else:
            result = check_freeze(root, require_git_tracked=args.require_git_tracked)
            print(json.dumps({"files": len(result["files"]), "status": "PASS"}, sort_keys=True))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
