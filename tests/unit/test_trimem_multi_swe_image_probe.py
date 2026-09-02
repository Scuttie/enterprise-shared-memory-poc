from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_multi_swe_image_probe as probe  # noqa: E402


def _completed(
    argv: list[str], *, returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def test_probe_consumes_only_the_exact_frozen_vue_identity() -> None:
    contract = probe._frozen_contract()
    assert contract == {
        "base_commit": "3be4e3cbe34b394096210897c1be8deeb6d748d8",
        "expected_digest": (
            "sha256:2883a52a2eb4054e820dc3a88f9fb0b93fbef7ce10801a57e718f1c6d9f8e9c1"
        ),
        "image": (
            "mswebench/vuejs_m_core@sha256:"
            "2883a52a2eb4054e820dc3a88f9fb0b93fbef7ce10801a57e718f1c6d9f8e9c1"
        ),
        "tag": "mswebench/vuejs_m_core:pr-8911",
    }


def test_probe_checks_metadata_without_applying_or_reading_a_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    expected_digest = probe.EXPECTED_IMAGE.rsplit("@", 1)[1]
    removed = False

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal removed
        calls.append(list(argv))
        if argv[:3] == ["docker", "image", "inspect"] and "--format" in argv:
            return _completed(
                argv,
                stdout=json.dumps([f"mswebench/vuejs_m_core@{expected_digest}"]) + "\n",
            )
        if argv[:3] == ["docker", "run", "--rm"]:
            return _completed(
                argv,
                stdout=(
                    "fix_run=true\n"
                    "test_patch=true\n"
                    "repository_checkout=true\n"
                    f"{probe.EXPECTED_BASE_COMMIT}\n"
                ),
            )
        if argv[:3] == ["docker", "image", "inspect"]:
            return (
                _completed(argv, returncode=1, stderr="Error: No such image\n")
                if removed
                else _completed(argv, stdout="[]\n")
            )
        if argv[:3] == ["docker", "image", "rm"]:
            removed = True
            return _completed(argv)
        return _completed(argv)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    report = probe.run_probe()

    assert report["status"] == "PASS"
    assert "endpoint" not in report
    assert report["expected_digest"] == expected_digest
    assert report["observed_digests"] == [expected_digest]
    assert report["required_paths_present"] == {
        "/home/fix-run.sh": True,
        "/home/test.patch": True,
    }
    assert report["repository"] == {
        "base_commit": probe.EXPECTED_BASE_COMMIT,
        "checkout_present": True,
        "head": probe.EXPECTED_BASE_COMMIT,
        "path": "/home/core",
    }
    assert report["removal_evidence"] == {
        "digest_reference_absent": True,
        "removal_established": True,
        "removed_reference_count": 2,
        "tag_reference_absent": True,
    }

    assert calls[0] == ["docker", "pull", probe.EXPECTED_IMAGE]
    assert calls[2] == ["docker", "tag", probe.EXPECTED_IMAGE, probe.EXPECTED_TAG]
    container_argv = calls[3]
    assert container_argv[:3] == ["docker", "run", "--rm"]
    assert "--pull=never" in container_argv
    assert "--network=none" in container_argv
    assert "--read-only" in container_argv
    assert "--cap-drop=ALL" in container_argv
    assert "--security-opt=no-new-privileges" in container_argv
    assert "--no-healthcheck" in container_argv
    assert container_argv[-4:-2] == ["/bin/sh", probe.EXPECTED_TAG]
    assert container_argv[-2] == "-c"
    metadata_script = container_argv[-1]
    assert "test -f /home/fix-run.sh" in metadata_script
    assert "test -f /home/test.patch" in metadata_script
    assert "git -C /home/core rev-parse HEAD" in metadata_script
    for forbidden in ("git apply", "cat /home/test.patch", "cat /home/fix.patch", "pnpm", "pytest"):
        assert forbidden not in metadata_script
    assert [
        "docker", "image", "rm", "--force", probe.EXPECTED_TAG, probe.EXPECTED_IMAGE
    ] in calls
    assert not any("GOLD" in " ".join(argv) or "NOOP" in " ".join(argv) for argv in calls)


def test_probe_fails_closed_on_digest_mismatch_and_still_removes_exact_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    removed = False

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal removed
        calls.append(list(argv))
        if argv[:3] == ["docker", "image", "inspect"] and "--format" in argv:
            return _completed(
                argv,
                stdout=json.dumps(["mswebench/vuejs_m_core@sha256:" + "0" * 64]) + "\n",
            )
        if argv[:3] == ["docker", "image", "inspect"]:
            if argv[-1] == probe.EXPECTED_TAG or removed:
                return _completed(argv, returncode=1, stderr="No such image\n")
            return _completed(argv, stdout="[]\n")
        if argv[:3] == ["docker", "image", "rm"]:
            removed = True
            return _completed(argv)
        return _completed(argv)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    with pytest.raises(
        probe.ImageProbeError, match="observed Vue image digest differs"
    ) as captured:
        probe.run_probe()

    report = captured.value.report
    assert report is not None
    assert report["endpoint"] == probe.FAIL_ENDPOINT
    assert report["status"] == "FAIL"
    assert report["observed_digests"] == ["sha256:" + "0" * 64]
    assert report["removal_evidence"] == {
        "digest_reference_absent": True,
        "removal_established": True,
        "removed_reference_count": 1,
        "tag_reference_absent": True,
    }
    assert ["docker", "image", "rm", "--force", probe.EXPECTED_IMAGE] in calls
    assert not any(argv[:3] == ["docker", "run", "--rm"] for argv in calls)


def test_main_persists_sanitized_failure_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "probe.json"
    report = {
        "endpoint": probe.FAIL_ENDPOINT,
        "expected_digest": probe.EXPECTED_IMAGE.rsplit("@", 1)[1],
        "observed_digests": [],
        "removal_evidence": {
            "digest_reference_absent": False,
            "removal_established": False,
            "removed_reference_count": 0,
            "tag_reference_absent": False,
        },
        "repository": {
            "base_commit": probe.EXPECTED_BASE_COMMIT,
            "checkout_present": False,
            "head": "UNKNOWN",
            "path": probe.REPOSITORY_PATH,
        },
        "required_paths_present": {
            "/home/fix-run.sh": False,
            "/home/test.patch": False,
        },
        "schema": "trimem/multi-swe-prebuilt-image-contract-probe/1.0",
        "status": "FAIL",
    }

    def fail() -> dict[str, object]:
        raise probe.ImageProbeError("sanitized failure", report=report)

    monkeypatch.setattr(probe, "run_probe", fail)
    monkeypatch.setattr(sys, "argv", ["probe", "--output", str(output)])
    assert probe.main() == 1
    assert json.loads(output.read_bytes()) == report
    assert b"sanitized failure" not in output.read_bytes()


def test_frozen_contract_failure_still_has_sanitized_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        probe,
        "_frozen_contract",
        lambda: (_ for _ in ()).throw(probe.ImageProbeError("frozen identity differs")),
    )
    with pytest.raises(probe.ImageProbeError) as captured:
        probe.run_probe()
    report = captured.value.report
    assert report is not None
    assert report["endpoint"] == probe.FAIL_ENDPOINT
    assert report["status"] == "FAIL"
    assert report["observed_digests"] == []
    assert report["removal_evidence"]["removal_established"] is False


def test_cleanup_failure_overrides_success_and_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_digest = probe.EXPECTED_IMAGE.rsplit("@", 1)[1]

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if argv[:3] == ["docker", "image", "inspect"] and "--format" in argv:
            return _completed(
                argv,
                stdout=json.dumps([f"mswebench/vuejs_m_core@{expected_digest}"]) + "\n",
            )
        if argv[:3] == ["docker", "run", "--rm"]:
            return _completed(
                argv,
                stdout=(
                    "fix_run=true\n"
                    "test_patch=true\n"
                    "repository_checkout=true\n"
                    f"{probe.EXPECTED_BASE_COMMIT}\n"
                ),
            )
        if argv[:3] == ["docker", "image", "inspect"]:
            return _completed(argv, stdout="[]\n")
        if argv[:3] == ["docker", "image", "rm"]:
            return _completed(argv, returncode=1, stderr="cleanup refused\n")
        return _completed(argv)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    with pytest.raises(probe.ImageProbeError, match="cleanup failed") as captured:
        probe.run_probe()
    report = captured.value.report
    assert report is not None
    assert report["endpoint"] == probe.FAIL_ENDPOINT
    assert report["status"] == "FAIL"
    assert report["observed_digests"] == [expected_digest]
    assert report["removal_evidence"]["removal_established"] is False
