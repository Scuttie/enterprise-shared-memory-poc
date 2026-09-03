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


def test_benchmark_installs_and_byte_verifies_pinned_gh_before_exec_gate() -> None:
    text = _read(BENCHMARK_WORKFLOW)
    _install_and_verify_contract(text)
    install = text.index("- name: Install exact pinned GitHub CLI")
    verify = text.index("- name: Verify exact GitHub CLI")
    materialize = text.index("- name: Materialize protected external approval")
    gate = text.index("- name: Verify exact phase EXEC gate")
    assert install < verify < materialize < gate
    gate_block = text[gate : text.index(
        "- name: Verify required protected runtime secrets before paid work"
    )]
    assert "GH_TOKEN: ${{ github.token }}" in gate_block
    assert "--level benchmark-exec" in gate_block
    assert "--approval-file" in gate_block


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
        ".github/workflows/trimem-benchmark.yml",
        "configs/trimem_v1/gh_cli_lock.json",
        "scripts/trimem_install_pinned_gh.py",
        "scripts/trimem_verify_gh_lock.py",
        "scripts/trimem_verify_ready.py",
        "tests/unit/test_trimem_dev_toolchain_workflows.py",
        "tests/unit/test_trimem_pinned_gh.py",
        "tests/unit/test_trimem_smoke_attestation_only.py",
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
    assert "trimem_benchmark_run.py" not in text
    assert "GH_TOKEN: ${{ github.token }}" in text
    assert text.count("GH_TOKEN: ${{ github.token }}") == 1
    assert "--level smoke-attestation-only" in text
    assert "--require-git-tracked" in text
    for field in ZERO_FIELDS:
        assert f'"{field}"' in text
    assert 'report.get("status") != "PASS"' in text
    assert 'attestation.get("status") != "PASS"' in text
    assert 'attestation.get("live_run_attempt_query_count") != 1' in text


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
