from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_WORKFLOW = ROOT / ".github/workflows/trimem-benchmark.yml"
TOOLCHAIN_WORKFLOW = ROOT / ".github/workflows/ci-trimem-dev-toolchain.yml"
STATIC_WORKFLOW = ROOT / ".github/workflows/ci-trimem.yml"
LOADER_WORKFLOW = ROOT / ".github/workflows/ci-trimem-grader-loader.yml"
GENERIC_WORKFLOW = ROOT / ".github/workflows/ci.yml"

INSTALL_COMMAND = "python scripts/trimem_install_pinned_gh.py"
VERIFY_COMMAND = "python scripts/trimem_verify_gh_lock.py"
LOCK_ARGUMENT = "--lock configs/trimem_v1/gh_cli_lock.json"
PREFIX_ARGUMENT = '--prefix "$RUNNER_TEMP/trimem-gh"'
ROUND_TRIP_STEP = "Verify production terminal-cell round trip before provider access"
ROUND_TRIP_COMMAND = (
    "python scripts/trimem_pytest_no_skip.py\n"
    "          tests/unit/test_trimem_d18_terminal_contract_integration.py"
)
CONTEXT_ROUND_TRIP_STEP = "Verify bounded context round trip before provider access"
CONTEXT_ROUND_TRIP_COMMAND = "python scripts/trimem_context_roundtrip.py"
CHECKOUT_REHEARSAL_STEP = (
    "Rehearse all frozen DEV task checkouts before provider access"
)
CHECKOUT_REHEARSAL_COMMAND = "python scripts/trimem_d117_checkout_rehearsal.py"
EXACT_RUNNER = "runs-on: ubuntu-24.04"
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


def _assert_context_round_trip_precedes(
    text: str,
    *later_step_names: str,
) -> None:
    marker = f"- name: {CONTEXT_ROUND_TRIP_STEP}"
    assert text.count(marker) == 1
    context_round_trip = text.index(marker)
    assert CONTEXT_ROUND_TRIP_COMMAND in _step_block(
        text, CONTEXT_ROUND_TRIP_STEP
    )
    for name in later_step_names:
        assert context_round_trip < text.index(f"- name: {name}")


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


def test_benchmark_has_only_the_d121_021_active_development_trigger() -> None:
    text = _read(BENCHMARK_WORKFLOW)
    trigger = text[text.index("on:"):text.index("\nconcurrency:")]
    assert trigger == (
        "on:\n"
        "  workflow_dispatch:\n"
        "  push:\n"
        "    branches:\n"
        "      - codex/trimem-coder-v1\n"
        "    paths:\n"
        "      - artifacts/trimem_v1/exec_requests/"
        "DEVELOPMENT_TUNING_EXEC_REQUEST_021.json\n"
    )
    assert (
        "- artifacts/trimem_v1/exec_requests/"
        "DEVELOPMENT_TUNING_EXEC_REQUEST_021.json"
    ) in text
    assert "group: trimem-v1-development-tuning-exec-021" in text
    assert "group: trimem-v1-development-tuning-exec-020" not in text
    assert "group: trimem-v1-development-tuning-exec-019" not in text
    assert "group: trimem-v1-development-tuning-exec-018" not in text
    preflight = _step_block(text, "Verify one-time zero-authority DEV trigger")
    assert "scripts/trimem_development_trigger_d121.py" in preflight
    assert "scripts/trimem_development_trigger_d120.py" not in preflight
    assert "scripts/trimem_development_trigger_d119.py" not in preflight
    assert "scripts/trimem_development_trigger_d118.py" not in preflight
    assert "scripts/trimem_development_trigger_d117.py" not in preflight
    assert "scripts/trimem_development_trigger_d116.py" not in preflight
    assert "scripts/trimem_development_trigger_d115.py" not in preflight
    assert "scripts/trimem_development_trigger_d114.py" not in preflight
    assert "scripts/trimem_development_trigger_d113.py" not in preflight
    assert "scripts/trimem_development_trigger_d112.py" not in preflight
    assert "scripts/trimem_development_trigger_d110.py" not in preflight
    assert "scripts/trimem_development_trigger_d19.py" not in preflight
    assert "scripts/trimem_development_trigger_d18.py" not in preflight
    assert "DEVELOPMENT_TUNING_EXEC_REQUEST_010.json" not in trigger
    assert "DEVELOPMENT_TUNING_EXEC_REQUEST_013.json" not in trigger
    assert "DEVELOPMENT_TUNING_EXEC_REQUEST_014.json" not in trigger
    assert "trimem-v1-development-tuning-exec-010" not in text
    assert "trimem-v1-development-tuning-exec-013" not in text
    assert "trimem-v1-development-tuning-exec-014" not in text
    assert "scripts/trimem_development_trigger_d15.py" not in text


def test_benchmark_checks_exact_compiled_prefix_alias_before_each_loader() -> None:
    text = _read(BENCHMARK_WORKFLOW)
    bounded = text[
        text.index("  bounded-context-preflight:"):
        text.index("  frozen-serial-phase:")
    ]
    protected = text[text.index("  frozen-serial-phase:"):]
    expected_python = 'exact_python="$pythonLocation/bin/python3.11"'
    alias_check = (
        '"$exact_python" -I -S '
        "scripts/trimem_compiled_prefix_alias.py --check"
    )
    loader_check = (
        '"$exact_python" '
        "scripts/trimem_official_harness_loader_preflight.py"
    )
    assert text.count(alias_check) == 2
    for job in (bounded, protected):
        assert expected_python in job
        assert job.index(alias_check) < job.index(loader_check)
        lines = [line.strip() for line in job.splitlines()]
        loader_line = next(
            index for index, line in enumerate(lines) if line.startswith(loader_check)
        )
        assert loader_line == lines.index(alias_check) + 1
    assert protected.index(alias_check) < protected.index(
        "Materialize protected external approval"
    )


def test_production_round_trip_runs_before_any_benchmark_provider_access() -> None:
    text = _read(BENCHMARK_WORKFLOW)
    context_job = text[
        text.index("  bounded-context-preflight:"):
        text.index("  frozen-serial-phase:")
    ]
    assert "services:" not in context_job
    assert "environment:" not in context_job
    assert "secrets." not in context_job
    assert "OPENAI_API_KEY" not in context_job
    assert "TRIMEM_EXEC_APPROVAL" not in context_job
    assert text.index(f"- name: {CONTEXT_ROUND_TRIP_STEP}") < text.index(
        f"- name: {ROUND_TRIP_STEP}"
    )
    _assert_production_round_trip_precedes(
        text,
        CHECKOUT_REHEARSAL_STEP,
        "Install exact pinned GitHub CLI",
        "Materialize protected external approval",
        "Validate exact OpenAI credential format before network access",
        "Retrieve exact model metadata before image materialization",
        "Execute one native-action protocol canary before benchmark images",
        "Pull committed images by digest and verify local observations",
        "Execute frozen serial streams with one atomic phase ledger",
    )
    _assert_context_round_trip_precedes(
        text,
        CHECKOUT_REHEARSAL_STEP,
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
    assert "needs.bounded-context-preflight.result == 'success'" in job_header

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
    custody_upload = _step_block(
        text,
        "Upload sanitized remote-custody result before cleanup",
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
    assert "steps.public-upload.outcome == 'success' ||" in custody
    assert "steps.public-upload.outcome == 'skipped'" in custody
    assert (
        "PUBLIC_UPLOAD_OUTCOME: ${{ steps.public-upload.outcome }}" in custody
    )
    for upload_id, label in (
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
    for suffix in ("ID", "DIGEST"):
        assert (
            f"PUBLIC_ARTIFACT_{suffix}: "
            f"${{{{ steps.public-upload.outputs.artifact-{suffix.casefold()} }}}}"
        ) in custody
    assert "GH_TOKEN: ${{ github.token }}" in custody
    assert "python scripts/trimem_verify_remote_custody.py" in custody
    assert '--public-upload-outcome "$PUBLIC_UPLOAD_OUTCOME"' in custody
    assert '--restricted-artifact-id "$RESTRICTED_ARTIFACT_ID"' in custody
    assert '--inventory-artifact-id "$INVENTORY_ARTIFACT_ID"' in custody
    assert '--output "$RUNNER_TEMP/trimem-remote-custody-result.json"' in custody
    assert "id: custody-result-upload" in custody_upload
    assert "steps.external-custody-verification.outcome == 'success'" in custody_upload
    assert "name: trimem-benchmark-remote-custody" in custody_upload
    assert "${{ runner.temp }}/trimem-remote-custody-result.json" in custody_upload
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
    assert "always() &&" in approval_cleanup
    assert "steps.approval_materialization.outcome == 'success'" in approval_cleanup
    assert (
        "steps.external-custody-verification.outcome == 'success'"
        in approval_cleanup
    )
    assert "steps.custody-result-upload.outcome == 'success'" in approval_cleanup
    assert "if: always()" in final_cleanup
    assert 'if [ "$RESTRICTED_UPLOAD_OUTCOME" != "success" ]' in final_cleanup
    assert '[ "$INVENTORY_UPLOAD_OUTCOME" != "success" ]' in final_cleanup
    assert '[ "$CUSTODY_RESULT_UPLOAD_OUTCOME" != "success" ]' in final_cleanup
    assert (
        "EXTERNAL_CUSTODY_VERIFICATION_OUTCOME: "
        "${{ steps.external-custody-verification.outcome }}"
    ) in final_cleanup
    assert (
        "CUSTODY_RESULT_UPLOAD_OUTCOME: "
        "${{ steps.custody-result-upload.outcome }}"
    ) in final_cleanup
    assert (
        '[ "$EXTERNAL_CUSTODY_VERIFICATION_OUTCOME" != "success" ]'
        in final_cleanup
    )
    assert "external artifact custody was not verified" in final_cleanup


def test_toolchain_rehearsal_is_narrow_credential_free_and_github_hosted() -> None:
    text = _read(TOOLCHAIN_WORKFLOW)
    _install_and_verify_contract(text)
    assert EXACT_RUNNER in text
    assert "self-hosted" not in text
    trigger = (
        text[text.index("on:\n") : text.index("\npermissions:")].rstrip("\n")
        + "\n"
    )
    assert trigger == (
        "on:\n"
        "  push:\n"
        "    branches:\n"
        "      - codex/trimem-coder-v1\n"
    )
    assert "paths:" not in trigger
    assert "paths-ignore:" not in trigger
    assert "workflow_dispatch:" not in text
    assert "pull_request:" not in text
    assert "artifacts/trimem_v1/exec_requests/" not in text
    for d113_test in (
        "tests/unit/test_trimem_d113_e1_trigger.py",
        "tests/unit/test_trimem_d113_gate_contract.py",
        "tests/unit/test_trimem_d113_status_and_reseal.py",
    ):
        assert text.count(d113_test) == 1
    for d114_test in (
        "tests/unit/test_trimem_d114_e1_trigger.py",
        "tests/unit/test_trimem_d114_gate_contract.py",
        "tests/unit/test_trimem_d114_post_setup_environment.py",
        "tests/unit/test_trimem_d114_status_and_reseal.py",
    ):
        assert text.count(d114_test) == 1
    for d115_test in (
        "tests/unit/test_trimem_d115_compiled_prefix_alias.py",
        "tests/unit/test_trimem_d115_gate_contract.py",
        "tests/unit/test_trimem_d115_status_and_reseal.py",
        "tests/unit/test_trimem_d115_trigger.py",
    ):
        assert text.count(d115_test) == 1
    assert text.count("tests/unit/test_trimem_d116_trigger.py") == 1
    assert text.count("tests/unit/test_trimem_d117_trigger.py") == 1
    assert text.count("tests/unit/test_trimem_d118_trigger.py") == 1
    assert (
        text.count("tests/unit/test_trimem_d118_grader_factory_rehearsal.py")
        == 1
    )
    assert text.count("tests/unit/test_trimem_d119_trigger.py") == 1
    assert text.count("tests/unit/test_trimem_d119_approval_secret.py") == 1
    assert text.count("tests/unit/test_trimem_d120_trigger.py") == 1
    assert text.count("tests/unit/test_trimem_d121_trigger.py") == 1
    assert text.count("tests/unit/test_trimem_d122_trigger.py") == 1
    assert (
        text.count("tests/unit/test_trimem_d122_qdrant_nofile_rehearsal.py")
        == 1
    )
    assert "environment:" not in text
    assert "services:" not in text
    assert "secrets." not in text
    assert "OPENAI_API_KEY" not in text
    assert "TRIMEM_EXEC_APPROVAL" not in text
    assert "TRIMEM_EVIDENCE_PASSPHRASE" not in text
    assert "trimem_pull_locked_images.py" not in text
    assert "python scripts/trimem_run_with_resume.py" not in text
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
        "Validate exact D1.22 credential-free recovery source",
        "Install exact pinned GitHub CLI",
        "Verify official smoke attestation only with zero scientific work",
    )
    _assert_context_round_trip_precedes(
        text,
        "Validate exact D1.22 credential-free recovery source",
        "Install exact pinned GitHub CLI",
        "Verify official smoke attestation only with zero scientific work",
    )
    round_trip = _step_block(text, ROUND_TRIP_STEP)
    context_round_trip = _step_block(text, CONTEXT_ROUND_TRIP_STEP)
    source_validation = _step_block(
        text,
        "Validate exact D1.22 credential-free recovery source",
    )
    for block in (round_trip, context_round_trip):
        assert "secrets." not in block
        assert "OPENAI_API_KEY" not in block
        assert "GH_TOKEN" not in block
    assert "python -I -S scripts/trimem_freeze.py --check --require-git-tracked" in source_validation
    assert "scripts/trimem_development_trigger_d122.py" in source_validation
    assert "scripts/trimem_development_trigger_d121.py" not in source_validation
    assert "python -I -S scripts/trimem_d122_reseal.py --check" in source_validation
    assert "scripts/trimem_development_trigger_d119.py" not in source_validation
    assert "scripts/trimem_development_trigger_d118.py" not in source_validation
    assert "scripts/trimem_development_trigger_d117.py" not in source_validation
    assert "scripts/trimem_development_trigger_d116.py" not in source_validation
    assert "--validate-current" in source_validation
    assert "python scripts/trimem_d115_reseal.py --check" not in source_validation
    assert "scripts/trimem_d115_gate_contract.py" in source_validation
    assert "scripts/trimem_d114_gate_contract.py" in source_validation
    assert "scripts/trimem_d113_gate_contract.py" in source_validation
    assert "scripts/trimem_d111_gate_contract.py" in source_validation
    assert "secrets." not in source_validation
    assert "OPENAI_API_KEY" not in source_validation
    assert "GH_TOKEN" not in source_validation


def test_d122_qdrant_rehearsal_pulls_and_verifies_exact_pinned_digest() -> None:
    text = _read(TOOLCHAIN_WORKFLOW)
    block = _step_block(
        text,
        "Rehearse exact Qdrant nofile topology with zero model or grader work",
    )
    expected = (
        "qdrant/qdrant@sha256:"
        "241edb9d7778327516ef218f8c74e1bd61b5ea42cd4f193cb8d0896199705636"
    )
    assert f'qdrant_image="{expected}"' in block
    assert 'docker pull "$qdrant_image"' in block
    assert 'docker image inspect "$qdrant_image"' in block
    assert "--format '{{json .RepoDigests}}'" in block
    assert '| tee "$qdrant_repo_digests"' in block
    assert "expected not in observed" in block
    assert '"support_service_image_pulls": 1' in block
    assert "print(json.dumps(report" in block
    assert "OPENAI_API_KEY" not in block
    assert "secrets." not in block


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
    assert "persist-credentials: false" in text
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in text
    assert "python -I -S scripts/trimem_compiled_prefix_alias.py --help" in text
    assert "python -I -S scripts/trimem_development_trigger_d122.py --help" in text
    assert "python -I -S scripts/trimem_d122_reseal.py --help" in text
    assert "python -I -S scripts/trimem_d119_approval_secret.py --help" in text
    assert "python scripts/make_handoff_manifest.py --check" in text
    assert "python scripts/release_check.py --secrets" in text


def test_generic_ci_uses_exact_head_and_d110_python() -> None:
    text = _read(GENERIC_WORKFLOW)
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in text
    assert "persist-credentials: false" in text
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in text
    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in text
    assert 'python-version: "3.11.10"' in text


def test_d110_loader_workflow_is_exact_ubuntu_credential_free_preflight() -> None:
    text = _read(LOADER_WORKFLOW)
    assert "runs-on: ubuntu-24.04" in text
    assert "environment:" not in text
    assert "services:" not in text
    assert "secrets." not in text
    assert "GH_TOKEN" not in text
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in text
    assert "persist-credentials: false" in text
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in text
    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in text
    assert "python-version: 3.11.10" in text
    assert "--require-hashes -r configs/trimem_v1/benchmark_environment.lock" in text
    assert "prepare_harnesses(checkout_root)" in text
    assert 'exact_python="$pythonLocation/bin/python"' in text
    assert "scripts/trimem_official_harness_loader_preflight.py" in text
    assert "TRIMEM_OFFICIAL_HARNESS_LOADER_PREFLIGHT_PASS" in text
    assert "Reproduce exact _010 loader failure and corrected launch" in text
    assert "validate_exec_010_sanitized_fixture" in text
    assert "toolcache_stripped_has_embedded_loader_path" in text
    assert "toolcache stripped-loader behavior was unexpected" in text
    assert "TRIMEM_D110_EXACT_010_LOADER_REGRESSION_PASS" in text
    assert "TRIMEM_D110_EXACT_010_LOADER_REGRESSION_NOT_READY" in text
    assert "preserve_failure_evidence" in text
    assert "libpython3.11.so.1.0" in text
    assert "historical_exit_code" in text
    assert "corrected_exit_code" in text
    assert "trimem_official_grader.minimal_subprocess_env" in text
    assert '"$exact_python" - \\' in text
    assert '"$exact_python" <<\'PY\'' in text
    assert "python_binary=sys.argv[2]" in text
    assert 'python_binary=report["python_loader"]' not in text
    for field in (
        "grader_attempts",
        "grader_containers",
        "image_pulls",
        "model_generation_calls",
        "model_metadata_requests",
        "paid_calls",
        "usd",
    ):
        assert f'"{field}": 0' in text
    for forbidden in (
        "OPENAI_API_KEY",
        "TRIMEM_EXEC_APPROVAL",
        "TRIMEM_EVIDENCE_PASSPHRASE",
        "trimem_pull_locked_images.py",
        "trimem_run_with_resume.py",
        "docker pull",
        "docker run",
    ):
        assert forbidden not in text


def test_benchmark_exact_loader_preflight_precedes_every_credential_and_exec_step() -> None:
    text = _read(BENCHMARK_WORKFLOW)
    prepare = text.index(
        "- name: Materialize exact pinned harness sources before credentials"
    )
    preflight = text.index(
        "- name: Verify exact official harness Python loader before credentials"
    )
    assert prepare < preflight
    for later in (
        "Materialize protected external approval",
        "Validate exact OpenAI credential format before network access",
        "Retrieve exact model metadata before image materialization",
        "Execute one native-action protocol canary before benchmark images",
        "Pull committed images by digest and verify local observations",
        "Execute frozen serial streams with one atomic phase ledger",
    ):
        assert preflight < text.index(f"- name: {later}")
    preflight_block = _step_block(
        text, "Verify exact official harness Python loader before credentials"
    )
    assert 'exact_python="$pythonLocation/bin/python3.11"' in preflight_block
    assert "scripts/trimem_compiled_prefix_alias.py --check" in preflight_block
    assert "scripts/trimem_official_harness_loader_preflight.py" in preflight_block
    assert "secrets." not in preflight_block
    assert "OPENAI_API_KEY" not in preflight_block

    execution_block = _step_block(
        text, "Execute frozen serial streams with one atomic phase ledger"
    )
    assert (
        '"$pythonLocation/bin/python3.11" scripts/trimem_run_with_resume.py'
        in execution_block
    )
    assert "\n          python scripts/trimem_run_with_resume.py" not in execution_block

    factory_rehearsal = _step_block(
        text,
        "Rehearse full grader factory across launcher aliases before credentials",
    )
    assert "python scripts/trimem_d118_grader_factory_rehearsal.py" in factory_rehearsal
    assert '--preflight "$RUNNER_TEMP/trimem-official-harness-loader-preflight.json"' in factory_rehearsal
    assert '--harness-root "$RUNNER_TEMP/trimem-d112-harnesses"' in factory_rehearsal
    assert '--dataset-cache-root "$RUNNER_TEMP/trimem-d117-datasets"' in factory_rehearsal
    assert "--synthetic" not in factory_rehearsal
    assert "secrets." not in factory_rehearsal
    assert "OPENAI_API_KEY" not in factory_rehearsal
    unprotected_loader = text.index(
        "- name: Gate protected job on unprotected exact loader preflight"
    )
    assert unprotected_loader < text.index(
        "- name: Rehearse full grader factory across launcher aliases before credentials"
    ) < text.index("  frozen-serial-phase:")

    protected_factory_name = (
        "Rehearse protected grader factory across launcher aliases before credentials"
    )
    protected_factory = _step_block(text, protected_factory_name)
    assert "python scripts/trimem_d118_grader_factory_rehearsal.py" in (
        protected_factory
    )
    assert "--synthetic" in protected_factory
    assert (
        "--preflight artifacts/trimem_v1/benchmark_exec/control/"
        "official-harness-loader-preflight.json"
    ) in protected_factory
    assert "--harness-root .trimem-exec/harnesses" in protected_factory
    assert "secrets." not in protected_factory
    assert "OPENAI_API_KEY" not in protected_factory

    rehearsal_markers = (
        "Rehearse full grader factory across launcher aliases before credentials",
        protected_factory_name,
    )
    for rehearsal_name in rehearsal_markers:
        rehearsal_index = text.index(f"- name: {rehearsal_name}")
        for later_name in (
            "Materialize protected external approval",
            "Validate exact OpenAI credential format before network access",
            "Retrieve exact model metadata before image materialization",
        ):
            assert rehearsal_index < text.index(f"- name: {later_name}")
    assert preflight < text.index(f"- name: {protected_factory_name}")


def test_benchmark_loader_preflight_is_not_hidden_behind_protected_environment() -> None:
    text = _read(BENCHMARK_WORKFLOW)
    unprotected_job = text[
        text.index("  bounded-context-preflight:"):
        text.index("  frozen-serial-phase:")
    ]
    protected_header = text[
        text.index("  frozen-serial-phase:"):
        text.index("    steps:", text.index("  frozen-serial-phase:"))
    ]

    assert "Materialize pinned harnesses in unprotected loader preflight" in (
        unprotected_job
    )
    assert "Gate protected job on unprotected exact loader preflight" in (
        unprotected_job
    )
    assert "prepare_harnesses(checkout_root)" in unprotected_job
    assert "scripts/trimem_official_harness_loader_preflight.py" in unprotected_job
    assert "validate_official_harness_loader_preflight_evidence" in unprotected_job
    assert 'exact_python="$pythonLocation/bin/python3.11"' in unprotected_job
    assert "scripts/trimem_compiled_prefix_alias.py --check" in unprotected_job
    assert '"$exact_python" - "$preflight_output" "$exact_python"' in unprotected_job
    assert "python_binary=sys.argv[2]" in unprotected_job
    assert "environment:" not in unprotected_job
    assert "services:" not in unprotected_job
    assert "secrets." not in unprotected_job
    assert "OPENAI_API_KEY" not in unprotected_job
    assert "TRIMEM_EXEC_APPROVAL" not in unprotected_job
    assert "environment: trimem-benchmark-exec" in protected_header
    assert "needs.bounded-context-preflight.result == 'success'" in protected_header


def test_benchmark_rehearses_all_dev_checkouts_before_provider_or_images() -> None:
    text = _read(BENCHMARK_WORKFLOW)
    bounded = text[
        text.index("  bounded-context-preflight:"):
        text.index("  frozen-serial-phase:")
    ]
    marker = f"- name: {CHECKOUT_REHEARSAL_STEP}"
    assert text.count(marker) == 1
    block = _step_block(text, CHECKOUT_REHEARSAL_STEP)
    assert CHECKOUT_REHEARSAL_COMMAND in block
    assert '--checkout-root "$RUNNER_TEMP/trimem-d117-task-checkouts"' in block
    assert '--cache-root "$RUNNER_TEMP/trimem-d117-datasets"' in block
    assert '--output "$RUNNER_TEMP/trimem-d117-checkout-rehearsal.json"' in block
    assert bounded.index(marker) < bounded.index(
        "- name: Materialize pinned harnesses in unprotected loader preflight"
    )
    assert bounded.index(marker) < bounded.index(
        "- name: Gate protected job on unprotected exact loader preflight"
    )
    assert text.index(marker) < text.index("  frozen-serial-phase:")
    for forbidden in (
        "secrets.",
        "OPENAI_API_KEY",
        "TRIMEM_EXEC_APPROVAL",
        "docker pull",
        "docker run",
    ):
        assert forbidden not in bounded
