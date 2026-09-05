from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_WORKFLOW = ROOT / ".github/workflows/trimem-benchmark.yml"
TOOLCHAIN_WORKFLOW = ROOT / ".github/workflows/ci-trimem-dev-toolchain.yml"
STATIC_WORKFLOW = ROOT / ".github/workflows/ci-trimem.yml"

INSTALL_COMMAND = "python scripts/trimem_install_pinned_gh.py"
VERIFY_COMMAND = "python scripts/trimem_verify_gh_lock.py"
LOCK_ARGUMENT = "--lock configs/trimem_v1/gh_cli_lock.json"
PREFIX_ARGUMENT = '--prefix "$RUNNER_TEMP/trimem-gh"'
ROUND_TRIP_STEP = "Verify production terminal-cell round trip before provider access"
ROUND_TRIP_COMMAND = (
    "python scripts/trimem_pytest_no_skip.py\n"
    "          tests/unit/test_trimem_d18_terminal_contract_integration.py"
)
EXACT_RUNNER_LABELS = (
    "runs-on: [self-hosted, linux, x64, ubuntu-24.04, trimem-benchmark]"
)
ZERO_FIELDS = {
    "api_calls",
    "database_operations",
    "decomposition_calls",
    "docker_image_pulls",
    "extraction_calls",
    "grader_calls",
    "grader_containers",
    "input_tokens",
    "model_calls",
    "model_gateway_calls",
    "official_grader_runs",
    "output_tokens",
    "paid_model_calls",
    "reasoning_tokens",
    "solve_calls",
    "support_service_containers",
    "support_service_image_pulls",
    "target_image_pulls",
    "task_arm_runs",
    "total_usd",
}


def _read(path: Path) -> str:
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    return raw.decode("utf-8")


def _install_and_verify_contract(text: str) -> None:
    install = text.index("- name: Install exact pinned GitHub CLI")
    verify = text.index("- name: Verify exact GitHub CLI")
    assert install < verify
    block = text[install:verify]
    assert INSTALL_COMMAND in block
    assert LOCK_ARGUMENT in block
    assert PREFIX_ARGUMENT in block
    assert 'expected_bin="$RUNNER_TEMP/trimem-gh/bin"' in block
    assert 'test "$observed_bin" = "$expected_bin"' in block
    assert '>> "$GITHUB_PATH"' in block

    verify_block = text[verify:]
    assert 'resolved_gh="$(command -v gh)"' in verify_block
    assert 'test "$resolved_gh" = "$RUNNER_TEMP/trimem-gh/bin/gh"' in verify_block
    assert "gh --version" in verify_block
    assert VERIFY_COMMAND in verify_block
    assert LOCK_ARGUMENT in verify_block
    assert PREFIX_ARGUMENT in verify_block

    lowered = text.casefold()
    assert "apt install gh" not in lowered
    assert "apt-get install gh" not in lowered
    assert "brew install gh" not in lowered
    assert "gh_latest" not in lowered


def _step_block(text: str, name: str) -> str:
    marker = f"- name: {name}"
    start = text.index(marker)
    end = text.find("\n      - name:", start + len(marker))
    return text[start:] if end == -1 else text[start:end]


def _assert_production_round_trip_precedes(
    text: str,
    *later_step_names: str,
) -> None:
    marker = f"- name: {ROUND_TRIP_STEP}"
    assert text.count(marker) == 1
    install = text.index("- name: Install hash-locked environment")
    round_trip = text.index(marker)
    assert install < round_trip
    assert ROUND_TRIP_COMMAND in _step_block(text, ROUND_TRIP_STEP)
    for name in later_step_names:
        assert round_trip < text.index(f"- name: {name}")


def test_benchmark_installs_and_byte_verifies_pinned_gh_before_exec_gate() -> None:
    text = _read(BENCHMARK_WORKFLOW)
    _install_and_verify_contract(text)
    install = text.index("- name: Install exact pinned GitHub CLI")
    verify = text.index("- name: Verify exact GitHub CLI")
    materialize = text.index("- name: Materialize protected external approval")
    gate = text.index("- name: Verify exact phase EXEC gate")
    assert install < verify < materialize < gate
    gate_block = text[gate : text.index(
        "- name: Validate exact OpenAI credential format before network access"
    )]
    assert "GH_TOKEN: ${{ github.token }}" in gate_block
    assert "--level benchmark-exec" in gate_block
    assert "--approval-file" in gate_block


def test_benchmark_has_only_the_d18_009_active_development_trigger() -> None:
    text = _read(BENCHMARK_WORKFLOW)
    assert (
        "- artifacts/trimem_v1/exec_requests/"
        "DEVELOPMENT_TUNING_EXEC_REQUEST_009.json"
    ) in text
    assert "group: trimem-v1-development-tuning-exec-009" in text
    assert "scripts/trimem_development_trigger_d18.py" in text
    assert "DEVELOPMENT_TUNING_EXEC_REQUEST_008.json" not in text
    assert "trimem-v1-development-tuning-exec-008" not in text
    assert "scripts/trimem_development_trigger_d15.py" not in text


def test_production_round_trip_runs_before_any_benchmark_provider_access() -> None:
    text = _read(BENCHMARK_WORKFLOW)
    _assert_production_round_trip_precedes(
        text,
        "Install exact pinned GitHub CLI",
        "Materialize protected external approval",
        "Validate exact OpenAI credential format before network access",
        "Retrieve exact model metadata before image materialization",
        "Execute one native-action protocol canary before benchmark images",
        "Pull committed images by digest and verify local observations",
        "Execute frozen serial streams with one atomic phase ledger",
    )


def test_benchmark_paid_job_and_scientific_steps_respect_cancellation() -> None:
    text = _read(BENCHMARK_WORKFLOW)
    job_start = text.index("  frozen-serial-phase:")
    job_steps = text.index("    steps:", job_start)
    job_header = text[job_start:job_steps]
    assert "always() &&\n      !cancelled() &&" in job_header
    assert "github.event_name == 'workflow_dispatch'" in job_header
    assert "needs.branch-trigger-preflight.result == 'success'" in job_header

    cancellation_safe_steps = (
        "Pull committed images by digest and verify local observations",
        "Execute frozen serial streams with one atomic phase ledger",
    )
    for name in cancellation_safe_steps:
        block = _step_block(text, name)
        assert "if: ${{ !cancelled() && success() }}" in block
        assert "always()" not in block

    paid_or_scientific_steps = (
        "Validate exact OpenAI credential format before network access",
        "Verify run-bound OpenAI credential commitment",
        "Retrieve exact model metadata before image materialization",
        "Execute one native-action protocol canary before benchmark images",
        *cancellation_safe_steps,
    )
    for name in paid_or_scientific_steps:
        assert "always()" not in _step_block(text, name)


def test_benchmark_evidence_uploads_stop_on_cancellation_but_cleanup_is_fail_closed() -> None:
    text = _read(BENCHMARK_WORKFLOW)
    public_upload = _step_block(text, "Upload public benchmark result")
    restricted_upload = _step_block(text, "Upload encrypted restricted evidence")
    inventory_upload = _step_block(
        text,
        "Upload non-sensitive benchmark evidence inventories",
    )
    inventory = _step_block(text, "Inventory complete restricted benchmark evidence")
    encryption = _step_block(text, "Encrypt complete restricted evidence")
    approval_cleanup = _step_block(
        text,
        "Remove plaintext external approval after encryption attempt",
    )
    custody = _step_block(
        text,
        "Verify durable external artifact custody before cleanup",
    )
    final_cleanup = _step_block(text, "Remove plaintext and temporary EXEC material")

    assert "always() && !cancelled() && success()" in public_upload
    assert (
        "always() && !cancelled() && steps.encrypt_evidence.outcome == 'success'"
        in restricted_upload
    )
    assert (
        "always() && !cancelled() && "
        "steps.benchmark_evidence_inventory.outcome == 'success'"
        in inventory_upload
    )
    assert "always() &&" in inventory
    assert "steps.approval_materialization.outcome == 'success'" in inventory
    assert "always() &&" in encryption
    assert "steps.benchmark_evidence_inventory.outcome == 'success'" in encryption
    assert "id: public-upload" in public_upload
    assert "id: restricted-upload" in restricted_upload
    assert "id: inventory-upload" in inventory_upload
    assert "id: external-custody-verification" in custody
    assert "always() &&\n          !cancelled() &&" in custody
    for upload_id, label in (
        ("public-upload", "PUBLIC"),
        ("restricted-upload", "RESTRICTED"),
        ("inventory-upload", "INVENTORY"),
    ):
        assert f"steps.{upload_id}.outcome == 'success'" in custody
        assert (
            f"{label}_ARTIFACT_ID: "
            f"${{{{ steps.{upload_id}.outputs.artifact-id }}}}"
        ) in custody
        assert (
            f"{label}_ARTIFACT_DIGEST: "
            f"${{{{ steps.{upload_id}.outputs.artifact-digest }}}}"
        ) in custody
    assert "GH_TOKEN: ${{ github.token }}" in custody
    assert 're.fullmatch(r"[1-9][0-9]*", artifact_id)' in custody
    assert 're.fullmatch(r"[0-9a-f]{64}", artifact_digest)' in custody
    assert '"gh", "api", "--method", "GET"' in custody
    assert 'remote.get("digest") != "sha256:" + artifact_digest' in custody
    assert 'workflow_run.get("id") != int(os.environ["GITHUB_RUN_ID"])' in custody
    assert text.index("- name: Upload public benchmark result") < text.index(
        "- name: Verify durable external artifact custody before cleanup"
    )
    assert text.index("- name: Upload encrypted restricted evidence") < text.index(
        "- name: Verify durable external artifact custody before cleanup"
    )
    assert text.index("- name: Upload non-sensitive benchmark evidence inventories") < (
        text.index("- name: Verify durable external artifact custody before cleanup")
    )
    assert text.index("- name: Verify durable external artifact custody before cleanup") < (
        text.index("- name: Remove plaintext external approval after encryption attempt")
    )
    assert "always() && steps.approval_materialization.outcome == 'success'" in approval_cleanup
    assert "if: always()" in final_cleanup
    assert 'if [ "$RESTRICTED_UPLOAD_OUTCOME" != "success" ]' in final_cleanup
    assert '[ "$INVENTORY_UPLOAD_OUTCOME" != "success" ]' in final_cleanup
    assert (
        "EXTERNAL_CUSTODY_VERIFICATION_OUTCOME: "
        "${{ steps.external-custody-verification.outcome }}"
    ) in final_cleanup
    assert (
        '[ "$EXTERNAL_CUSTODY_VERIFICATION_OUTCOME" != "success" ]'
        in final_cleanup
    )
    assert "external artifact custody was not verified" in final_cleanup


def test_toolchain_rehearsal_is_narrow_credential_free_and_self_hosted() -> None:
    text = _read(TOOLCHAIN_WORKFLOW)
    _install_and_verify_contract(text)
    assert EXACT_RUNNER_LABELS in text
    assert "branches:\n      - codex/trimem-coder-v1" in text
    assert "workflow_dispatch:" not in text
    assert "pull_request:" not in text
    assert "artifacts/trimem_v1/exec_requests/" not in text
    for path in (
        ".github/workflows/ci-trimem-dev-toolchain.yml",
        ".github/workflows/ci-trimem.yml",
        ".github/workflows/trimem-benchmark.yml",
        "artifacts/trimem_v1/development_terminal_contract_amendment.json",
        "artifacts/trimem_v1/development_terminal_contract_inventory.json",
        "artifacts/trimem_v1/development_tuning_exec/exec-008/terminal-status-contract-mismatch-receipt.json",
        "artifacts/trimem_v1/freeze.json",
        "artifacts/trimem_v1/readiness_requirements.json",
        "configs/trimem_v1/cost_plan.json",
        "configs/trimem_v1/development_manifest.json",
        "configs/trimem_v1/gh_cli_lock.json",
        "scripts/trimem_development_trigger_preflight.py",
        "scripts/trimem_development_trigger_d18.py",
        "scripts/trimem_freeze.py",
        "scripts/trimem_m2_candidates.py",
        "scripts/trimem_multi_swe_contract.py",
        "scripts/trimem_public_artifact.py",
        "scripts/trimem_pytest_no_skip.py",
        "scripts/trimem_install_pinned_gh.py",
        "scripts/trimem_verify_gh_lock.py",
        "scripts/trimem_verify_ready.py",
        "tests/unit/test_trimem_dev_toolchain_workflows.py",
        "tests/unit/test_trimem_pinned_gh.py",
        "tests/unit/test_trimem_development_trigger.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
        "tests/unit/test_trimem_d16_native_action.py",
        "tests/unit/test_trimem_d17_approval_cap_integration.py",
        "tests/unit/test_trimem_d18_public_artifact_hardening.py",
        "tests/unit/test_trimem_d18_terminal_contract_integration.py",
        "tests/unit/test_trimem_smoke_attestation_only.py",
        "src/enterprise_memory/trimem/scientific_terminal.py",
        "reports/TRIMEM_DEVELOPMENT_TUNING_EXEC_008_TERMINAL_STATUS_CONTRACT_MISMATCH.md",
    ):
        assert f"- {path}" in text
    assert "environment:" not in text
    assert "services:" not in text
    assert "secrets." not in text
    assert "OPENAI_API_KEY" not in text
    assert "TRIMEM_EXEC_APPROVAL" not in text
    assert "TRIMEM_EVIDENCE_PASSPHRASE" not in text
    assert "trimem_pull_locked_images.py" not in text
    assert "trimem_run_with_resume.py" not in text
    assert "python scripts/trimem_benchmark_run.py" not in text
    assert "GH_TOKEN: ${{ github.token }}" in text
    assert text.count("GH_TOKEN: ${{ github.token }}") == 1
    assert "--level smoke-attestation-only" in text
    assert "--require-git-tracked" in text
    for field in ZERO_FIELDS:
        assert f'"{field}"' in text
    assert 'report.get("status") != "PASS"' in text
    assert 'attestation.get("status") != "PASS"' in text
    assert 'attestation.get("live_run_attempt_query_count") != 1' in text


def test_toolchain_runs_production_round_trip_before_credentialed_attestation() -> None:
    text = _read(TOOLCHAIN_WORKFLOW)
    _assert_production_round_trip_precedes(
        text,
        "Validate D1.8 correction source before trigger",
        "Install exact pinned GitHub CLI",
        "Verify official smoke attestation only with zero scientific work",
    )
    round_trip = _step_block(text, ROUND_TRIP_STEP)
    source_validation = _step_block(
        text,
        "Validate D1.8 correction source before trigger",
    )
    assert "secrets." not in round_trip
    assert "OPENAI_API_KEY" not in round_trip
    assert "GH_TOKEN" not in round_trip
    assert "python -I -S scripts/trimem_development_trigger_d18.py" in source_validation
    assert "--repository ." in source_validation
    assert "--validate-source" in source_validation
    assert '--source-head "$GITHUB_SHA"' in source_validation
    assert "secrets." not in source_validation
    assert "OPENAI_API_KEY" not in source_validation
    assert "GH_TOKEN" not in source_validation


def test_toolchain_rehearsal_and_benchmark_use_same_installer_contract() -> None:
    benchmark = _read(BENCHMARK_WORKFLOW)
    rehearsal = _read(TOOLCHAIN_WORKFLOW)
    for required in (
        INSTALL_COMMAND,
        VERIFY_COMMAND,
        LOCK_ARGUMENT,
        PREFIX_ARGUMENT,
        'test "$resolved_gh" = "$RUNNER_TEMP/trimem-gh/bin/gh"',
    ):
        assert required in benchmark
        assert required in rehearsal


def test_required_static_gate_includes_company_handoff_and_secret_scan() -> None:
    text = _read(STATIC_WORKFLOW)
    assert "python scripts/make_handoff_manifest.py --check" in text
    assert "python scripts/release_check.py --secrets" in text
