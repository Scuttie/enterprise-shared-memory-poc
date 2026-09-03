from __future__ import annotations

import base64
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import trimem_verify_ready as readiness  # noqa: E402


EXPECTED_IMMUTABLE_SHA256 = {
    "trusted_root": "65ca537f6ed8a47fd0e560c421baa1f6c1efb8b25fc200d8c5c02c0e92eb2b9c",
    "attestation_subject": "647d9d3eaddaf2917bfaaa8fc47c0c54f814a50ddf5e900c3176d3c895513846",
    "attestation_bundle": "c1cc04284b8f1be1cde006fa2309f6af918e8478485002b4556df7fcb165335e",
    "evidence_inventory": "b1c3ba191c4d037f4f8ee70cf8a4821592b5b25a65700d7ce3faa2d0024add8e",
    "public_result": "4a1253e69a95b3058b9433fbfe51ef3f8bee538c90b5faf29c996a841224faa4",
}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _official_attestation_bytes() -> tuple[bytes, bytes]:
    return (
        (ROOT / readiness.OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH).read_bytes(),
        (ROOT / readiness.OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH).read_bytes(),
    )


def _mock_gh_verification_output(subject_raw: bytes, bundle_raw: bytes) -> bytes:
    subject = json.loads(subject_raw)
    bundle = json.loads(bundle_raw)
    certificate = readiness._expected_certificate_bindings(subject)
    certificate.pop("protectedEnvironment")
    cert_identity = readiness._smoke_cert_identity(
        subject["execution"]["source_ref"]
    )
    statement = json.loads(base64.b64decode(bundle["dsseEnvelope"]["payload"]))
    return _canonical([{
        "attestation": {"bundle": bundle, "bundle_url": "", "initiator": ""},
        "verificationResult": {
            "mediaType": (
                "application/vnd.dev.sigstore.verificationresult+json;version=0.1"
            ),
            "signature": {"certificate": certificate},
            "statement": statement,
            "verifiedIdentity": {
                "issuer": {"issuer": "", "regexp": ".*"},
                "runnerEnvironment": readiness.SMOKE_ATTESTATION_RUNNER,
                "subjectAlternativeName": {
                    "subjectAlternativeName": cert_identity,
                },
            },
            "verifiedTimestamps": [{
                "timestamp": "2026-09-01T00:00:00Z",
                "type": "TimestampAuthority",
                "uri": "timestamp.githubapp.com",
            }],
        },
    }])


def _mock_live_run_attempt_output(
    subject_raw: bytes, *, run_attempt_delta: int = 0
) -> bytes:
    execution = json.loads(subject_raw)["execution"]
    return _canonical({
        "conclusion": "success",
        "event": execution["event_name"],
        "head_branch": execution["source_ref"].removeprefix("refs/heads/"),
        "head_sha": execution["source_digest"],
        "id": int(execution["workflow_run_id"]),
        "path": readiness.SMOKE_ATTESTATION_WORKFLOW,
        "repository_full_name": readiness.SMOKE_ATTESTATION_REPOSITORY,
        "run_attempt": int(execution["workflow_run_attempt"]) + run_attempt_delta,
        "status": "completed",
        "workflow_id": 123456789,
    })


def _stub_static_evidence() -> dict[str, object]:
    return {
        "grader_exec_package": "PASS",
        "official_grader_viability": "ESTABLISHED",
        "performance": "NOT_MEASURED",
    }


def test_attestation_only_cli_has_zero_scientific_operation_surface(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        raise AssertionError("scientific/service operation reached attestation-only mode")

    monkeypatch.setattr(readiness, "validate_static", lambda _tracked: _stub_static_evidence())
    monkeypatch.setattr(
        readiness,
        "verify_smoke_attestation_only",
        lambda: calls.append("shared-attestation") or {"status": "PASS"},
    )
    for name in (
        "validate_exec_approval",
        "execution_blockers",
        "preapproval_blockers",
        "open_benchmark_arm",
        "production_v03_controller_factory",
        "production_v03_lifecycle_factory",
        "seed_benchmark_identities",
    ):
        monkeypatch.setattr(readiness, name, forbidden)
    for name in (
        "OPENAI_API_KEY",
        "TRIMEM_DATABASE_URL",
        "TRIMEM_ADMIN_DATABASE_URL",
        "QDRANT_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["trimem_verify_ready.py", "--level", "smoke-attestation-only"],
    )

    assert readiness.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert calls == ["shared-attestation"]
    assert report["status"] == "PASS"
    assert report["git_tracked_freeze_required"] is True
    assert report["attestation_verification"] == {"status": "PASS"}
    assert set(report["attestation_only_execution"]) == set(
        readiness.ATTESTATION_ONLY_EXECUTION
    )
    assert all(value == 0 for value in report["attestation_only_execution"].values())


def test_attestation_only_and_benchmark_exec_share_exact_verifier() -> None:
    function_name = "verify_official_smoke_attestation_cryptographically"
    assert f"{function_name}()" in inspect.getsource(
        readiness.verify_smoke_attestation_only
    )
    assert f"{function_name}()" in inspect.getsource(readiness.execution_blockers)


def test_attestation_only_binds_version_to_pinned_lock_and_preserves_old_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = readiness.load_gh_cli_lock(ROOT / readiness.SMOKE_GH_CLI_LOCK_PATH)
    assert readiness.SMOKE_GH_VERSION_LINE == lock["expected_first_version_line"]
    paths = {
        "trusted_root": ROOT / readiness.SMOKE_TRUSTED_ROOT_PATH,
        "attestation_subject": ROOT / readiness.OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH,
        "attestation_bundle": ROOT / readiness.OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH,
        "evidence_inventory": ROOT / readiness.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
        "public_result": ROOT / readiness.OFFICIAL_SMOKE_PUBLIC_RESULT_PATH,
    }
    before = {name: path.read_bytes() for name, path in paths.items()}
    assert {
        name: hashlib.sha256(raw).hexdigest() for name, raw in before.items()
    } == EXPECTED_IMMUTABLE_SHA256
    calls: list[str] = []
    monkeypatch.setattr(
        readiness,
        "verify_official_smoke_attestation_cryptographically",
        lambda: calls.append("exact-shared-verifier"),
    )

    receipt = readiness.verify_smoke_attestation_only()

    assert calls == ["exact-shared-verifier"]
    assert receipt["status"] == "PASS"
    assert receipt["gh_cli_lock"]["expected_first_version_line"] == (
        lock["expected_first_version_line"]
    )
    assert receipt["immutable_files"] == {
        name: {
            "bytes": len(raw),
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": EXPECTED_IMMUTABLE_SHA256[name],
        }
        for (name, path), raw in zip(paths.items(), before.values(), strict=True)
    }
    assert {name: path.read_bytes() for name, path in paths.items()} == before


def test_attestation_only_performs_crypto_and_exact_live_run_attempt_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject_raw, bundle_raw = _official_attestation_bytes()
    commands: list[list[str]] = []
    monkeypatch.setenv("GH_TOKEN", "test-token-never-printed")
    monkeypatch.setattr(readiness.shutil, "which", lambda name: "/pinned/bin/gh")

    def fake_run(command, **_kwargs):
        commands.append(list(command))
        if command[1:] == ["--version"]:
            output = readiness.SMOKE_GH_VERSION_LINE.encode("ascii") + b"\n"
        elif command[1:3] == ["attestation", "verify"]:
            output = _mock_gh_verification_output(subject_raw, bundle_raw)
        else:
            output = _mock_live_run_attempt_output(subject_raw)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr=b"")

    monkeypatch.setattr(readiness.subprocess, "run", fake_run)
    receipt = readiness.verify_smoke_attestation_only()

    execution = json.loads(subject_raw)["execution"]
    assert receipt["workflow_run_id"] == execution["workflow_run_id"]
    assert receipt["workflow_run_attempt"] == execution["workflow_run_attempt"]
    assert receipt["live_run_attempt_query_count"] == 1
    assert len(commands) == 3
    assert commands[0] == ["/pinned/bin/gh", "--version"]
    assert commands[1][1:3] == ["attestation", "verify"]
    assert commands[2] == [
        "/pinned/bin/gh",
        "api",
        "--hostname",
        "github.com",
        readiness.SMOKE_RUN_API_ROUTE_TEMPLATE.format(
            repository=readiness.SMOKE_ATTESTATION_REPOSITORY,
            run_id=execution["workflow_run_id"],
            run_attempt=execution["workflow_run_attempt"],
        ),
        "--method",
        "GET",
        "-H",
        f"Accept: {readiness.SMOKE_GITHUB_API_ACCEPT}",
        "-H",
        f"X-GitHub-Api-Version: {readiness.SMOKE_GITHUB_API_VERSION}",
        "--jq",
        readiness.SMOKE_RUN_API_JSON_PROJECTION,
    ]


def test_attestation_only_fails_closed_on_wrong_live_run_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject_raw, bundle_raw = _official_attestation_bytes()
    monkeypatch.setenv("GH_TOKEN", "test-token-never-printed")
    monkeypatch.setattr(readiness.shutil, "which", lambda name: "/pinned/bin/gh")

    def fake_run(command, **_kwargs):
        if command[1:] == ["--version"]:
            output = readiness.SMOKE_GH_VERSION_LINE.encode("ascii") + b"\n"
        elif command[1:3] == ["attestation", "verify"]:
            output = _mock_gh_verification_output(subject_raw, bundle_raw)
        else:
            output = _mock_live_run_attempt_output(subject_raw, run_attempt_delta=1)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr=b"")

    monkeypatch.setattr(readiness.subprocess, "run", fake_run)
    with pytest.raises(readiness.ReadinessError, match="exact completed successful"):
        readiness.verify_smoke_attestation_only()
