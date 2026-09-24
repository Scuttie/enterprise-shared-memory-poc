from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_verify_remote_custody as custody  # noqa: E402


RUN_ID = 34008674563
REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
DIGESTS = {
    "PUBLIC": "1" * 64,
    "RESTRICTED": "2" * 64,
    "INVENTORY": "3" * 64,
}
NAMES = {
    "PUBLIC": "trimem-benchmark-public",
    "RESTRICTED": "trimem-benchmark-restricted-encrypted",
    "INVENTORY": "trimem-benchmark-evidence-inventories",
}
IDS = {"PUBLIC": "101", "RESTRICTED": "102", "INVENTORY": "103"}


def binding(label: str) -> custody.ArtifactBinding:
    return custody.ArtifactBinding(
        label=label,
        name=NAMES[label],
        artifact_id=IDS[label],
        digest=DIGESTS[label],
    )


class FakeRunner:
    def __init__(self, names: dict[str, str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.names = dict(NAMES if names is None else names)

    def __call__(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        artifact_id = argv[-1].rsplit("/", 1)[-1]
        label = next(key for key, value in IDS.items() if value == artifact_id)
        payload = {
            "id": int(artifact_id),
            "name": self.names[label],
            "expired": False,
            "size_in_bytes": 17,
            "digest": "sha256:" + DIGESTS[label],
            "workflow_run": {"id": RUN_ID},
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")


def test_success_path_requires_and_verifies_all_three_artifacts() -> None:
    runner = FakeRunner()
    result = custody.verify_remote_custody(
        repository=REPOSITORY,
        workflow_run_id=RUN_ID,
        public_upload_outcome="success",
        public=binding("PUBLIC"),
        restricted=binding("RESTRICTED"),
        inventory=binding("INVENTORY"),
        runner=runner,
    )

    assert result["status"] == custody.SUCCESS_MARKER
    assert result["campaign_result_available"] is True
    assert result["public_artifact"] == "VERIFIED"
    assert [row["label"] for row in result["verified_artifacts"]] == [
        "PUBLIC",
        "RESTRICTED",
        "INVENTORY",
    ]
    assert len(runner.calls) == 3


def test_failure_path_requires_only_encrypted_and_inventory_artifacts() -> None:
    runner = FakeRunner()
    result = custody.verify_remote_custody(
        repository=REPOSITORY,
        workflow_run_id=RUN_ID,
        public_upload_outcome="skipped",
        public=None,
        restricted=binding("RESTRICTED"),
        inventory=binding("INVENTORY"),
        runner=runner,
    )

    assert result["status"] == custody.FAILURE_MARKER
    assert result["campaign_result_available"] is False
    assert result["public_artifact"] == "ABSENT_EXPECTED"
    assert [row["label"] for row in result["verified_artifacts"]] == [
        "RESTRICTED",
        "INVENTORY",
    ]
    assert len(runner.calls) == 2


def test_cli_failure_path_uses_explicit_names_and_empty_public_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    diagnostic_names = {
        "PUBLIC": "trimem-dev-activation-diagnostic-public",
        "RESTRICTED": "trimem-dev-activation-diagnostic-restricted-encrypted",
        "INVENTORY": "trimem-dev-activation-diagnostic-evidence-inventory",
    }
    runner = FakeRunner(diagnostic_names)

    def fake_run(argv, **_kwargs):
        return runner(list(argv))

    output = tmp_path / "custody.json"
    monkeypatch.setattr(custody.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "trimem_verify_remote_custody.py",
            "--repository",
            REPOSITORY,
            "--workflow-run-id",
            str(RUN_ID),
            "--public-upload-outcome",
            "skipped",
            "--public-artifact-name",
            diagnostic_names["PUBLIC"],
            "--public-artifact-id",
            "",
            "--public-artifact-digest",
            "",
            "--restricted-artifact-name",
            diagnostic_names["RESTRICTED"],
            "--restricted-artifact-id",
            IDS["RESTRICTED"],
            "--restricted-artifact-digest",
            DIGESTS["RESTRICTED"],
            "--inventory-artifact-name",
            diagnostic_names["INVENTORY"],
            "--inventory-artifact-id",
            IDS["INVENTORY"],
            "--inventory-artifact-digest",
            DIGESTS["INVENTORY"],
            "--output",
            str(output),
        ],
    )

    assert custody.main() == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == custody.FAILURE_MARKER
    assert result["public_artifact"] == "ABSENT_EXPECTED"
    assert [row["name"] for row in result["verified_artifacts"]] == [
        diagnostic_names["RESTRICTED"],
        diagnostic_names["INVENTORY"],
    ]
    assert len(runner.calls) == 2


def test_failure_path_rejects_unexpected_public_binding() -> None:
    with pytest.raises(custody.RemoteCustodyError, match="unexpectedly supplied"):
        custody.verify_remote_custody(
            repository=REPOSITORY,
            workflow_run_id=RUN_ID,
            public_upload_outcome="skipped",
            public=binding("PUBLIC"),
            restricted=binding("RESTRICTED"),
            inventory=binding("INVENTORY"),
            runner=FakeRunner(),
        )


@pytest.mark.parametrize("outcome", ["failure", "cancelled", "unknown"])
def test_custody_rejects_failed_or_unknown_public_upload(outcome: str) -> None:
    with pytest.raises(custody.RemoteCustodyError, match="neither success nor skipped"):
        custody.verify_remote_custody(
            repository=REPOSITORY,
            workflow_run_id=RUN_ID,
            public_upload_outcome=outcome,
            public=None,
            restricted=binding("RESTRICTED"),
            inventory=binding("INVENTORY"),
            runner=FakeRunner(),
        )


def test_remote_digest_or_run_mismatch_fails_closed() -> None:
    def mismatched(argv: list[str]) -> subprocess.CompletedProcess[str]:
        payload = {
            "id": int(IDS["RESTRICTED"]),
            "name": NAMES["RESTRICTED"],
            "expired": False,
            "size_in_bytes": 17,
            "digest": "sha256:" + "0" * 64,
            "workflow_run": {"id": RUN_ID + 1},
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    with pytest.raises(custody.RemoteCustodyError, match="custody differs"):
        custody.verify_artifact(
            binding("RESTRICTED"),
            repository=REPOSITORY,
            workflow_run_id=RUN_ID,
            runner=mismatched,
        )


def test_canonical_output_never_contains_remote_command_streams() -> None:
    runner = FakeRunner()
    result = custody.verify_remote_custody(
        repository=REPOSITORY,
        workflow_run_id=RUN_ID,
        public_upload_outcome="skipped",
        public=None,
        restricted=binding("RESTRICTED"),
        inventory=binding("INVENTORY"),
        runner=runner,
    )
    raw = custody.canonical_bytes(result)
    assert b"stderr" not in raw
    assert b"stdout" not in raw
    assert json.loads(raw)["schema"] == custody.SCHEMA
