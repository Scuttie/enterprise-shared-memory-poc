from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_freeze as freeze  # noqa: E402
import trimem_grader_smoke_trigger_preflight as trigger  # noqa: E402
import trimem_multi_swe_probe_evidence as evidence  # noqa: E402
import trimem_multi_swe_probe_request as probe_request  # noqa: E402


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"


def _write_json(path: Path, value: object) -> bytes:
    raw = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _artifact_zip(result_raw: bytes, *, extra_member: bool = False) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        member = zipfile.ZipInfo(evidence.ARTIFACT_MEMBER, (2026, 9, 1, 0, 0, 0))
        member.create_system = 3
        member.external_attr = 0o100644 << 16
        archive.writestr(member, result_raw)
        if extra_member:
            archive.writestr("unexpected.txt", b"not allowlisted\n")
    return stream.getvalue()


def _provenance(
    marker_head: str,
    result_raw: bytes,
    *,
    run_attempt: int = 1,
    run_conclusion: str = "success",
    extra_member: bool = False,
) -> tuple[bytes, bytes, bytes, bytes]:
    run_id = 123456789
    job_id = 234567890
    artifact_id = 345678901
    api_root = f"https://api.github.com/repos/{evidence.EXPECTED_REPOSITORY}"
    run = {
        "conclusion": run_conclusion,
        "event": "push",
        "head_branch": evidence.EXPECTED_BRANCH,
        "head_sha": marker_head,
        "html_url": (
            f"https://github.com/{evidence.EXPECTED_REPOSITORY}/actions/runs/{run_id}"
        ),
        "id": run_id,
        "name": evidence.WORKFLOW_NAME,
        "path": evidence.WORKFLOW_PATH,
        "run_attempt": run_attempt,
        "status": "completed",
        "url": f"{api_root}/actions/runs/{run_id}",
    }
    steps = [
        {"conclusion": "success", "name": name, "status": "completed"}
        for name in evidence.REQUIRED_JOB_STEPS
    ]
    jobs = {
        "jobs": [
            {
                "conclusion": "success",
                "head_branch": evidence.EXPECTED_BRANCH,
                "head_sha": marker_head,
                "id": job_id,
                "name": evidence.PROBE_JOB_NAME,
                "run_id": run_id,
                "status": "completed",
                "steps": steps,
            }
        ],
        "total_count": 1,
    }
    archive_raw = _artifact_zip(result_raw, extra_member=extra_member)
    artifact = {
        "archive_download_url": f"{api_root}/actions/artifacts/{artifact_id}/zip",
        "created_at": "2026-09-01T01:02:03Z",
        "digest": "sha256:" + hashlib.sha256(archive_raw).hexdigest(),
        "expired": False,
        "expires_at": "2026-10-01T01:02:03Z",
        "id": artifact_id,
        "name": evidence.ARTIFACT_NAME,
        "size_in_bytes": len(archive_raw),
        "url": f"{api_root}/actions/artifacts/{artifact_id}",
        "workflow_run": {
            "head_branch": evidence.EXPECTED_BRANCH,
            "head_sha": marker_head,
            "id": run_id,
        },
    }
    return (
        _json_bytes(run),
        _json_bytes(jobs),
        _json_bytes(artifact),
        archive_raw,
    )


def _marker_repository(tmp_path: Path) -> tuple[Path, str, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-b", evidence.EXPECTED_BRANCH)
    _git(repository, "config", "user.name", "TriMem Evidence Test")
    _git(repository, "config", "user.email", "trimem@example.invalid")
    _git(repository, "config", "core.autocrlf", "false")
    for path in probe_request.MATERIAL_PATHS:
        if path == probe_request.FREEZE_PATH:
            continue
        target = repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / path).read_bytes())
    closure: dict[str, dict[str, object]] = {}
    for path in probe_request.MATERIAL_PATHS:
        if path == probe_request.FREEZE_PATH:
            continue
        raw = (repository / path).read_bytes()
        closure[path] = {
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    _write_json(
        repository / probe_request.FREEZE_PATH,
        {"files": closure, "schema": "trimem/freeze/1.0"},
    )
    correction_head = _commit(repository, "correction")
    marker = probe_request.build_request_document(
        repository, correction_head=correction_head
    )
    marker_path = repository / evidence.PROBE_REQUEST_PATH
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_bytes(probe_request.canonical_bytes(marker, trailing_lf=True))
    marker_head = _commit(repository, "marker only")
    return repository, correction_head, marker_head


def _closed_repository(
    tmp_path: Path,
) -> tuple[Path, str, str, str, dict[str, bytes]]:
    repository, correction_head, marker_head = _marker_repository(tmp_path)
    result_raw = evidence.canonical_bytes(evidence.expected_probe_result(), pretty=True)
    provenance = _provenance(marker_head, result_raw)
    receipt = evidence.build_receipt_document(
        repository,
        correction_head=correction_head,
        marker_head=marker_head,
        result_raw=result_raw,
        workflow_run_raw=provenance[0],
        workflow_jobs_raw=provenance[1],
        artifact_raw=provenance[2],
        artifact_archive_raw=provenance[3],
        observed_at_utc="2026-09-01T01:05:00Z",
    )
    receipt_raw = evidence.canonical_bytes(receipt, pretty=True)
    result_path = repository / evidence.PROBE_RESULT_PATH
    receipt_path = repository / evidence.PROBE_RECEIPT_PATH
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_bytes(result_raw)
    receipt_path.write_bytes(receipt_raw)
    freeze_path = repository / evidence.FREEZE_PATH
    freeze_value = json.loads(freeze_path.read_bytes())
    for path, raw in (
        (evidence.PROBE_REQUEST_PATH, (repository / evidence.PROBE_REQUEST_PATH).read_bytes()),
        (evidence.PROBE_RESULT_PATH, result_raw),
        (evidence.PROBE_RECEIPT_PATH, receipt_raw),
    ):
        freeze_value["files"][path] = {
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    _write_json(freeze_path, freeze_value)
    evidence_head = _commit(repository, "close probe evidence")
    return repository, correction_head, marker_head, evidence_head, {
        "result": result_raw,
        "receipt": receipt_raw,
        "run": provenance[0],
        "jobs": provenance[1],
        "artifact": provenance[2],
        "archive": provenance[3],
    }


def test_exact_pass_result_is_canonical_and_singleton_digest() -> None:
    raw = evidence.canonical_bytes(evidence.expected_probe_result(), pretty=True)
    assert len(raw) == 749
    assert hashlib.sha256(raw).hexdigest() == (
        "4e3aaebcc4a7a812d480145f252cbf0851ad478cc078a6ef7b4aa606d7dd1dba"
    )
    assert evidence.validate_probe_result(raw)["observed_digests"] == [
        evidence.EXPECTED_DIGEST
    ]
    changed = evidence.expected_probe_result()
    changed["observed_digests"].append("sha256:" + "0" * 64)
    with pytest.raises(evidence.ProbeEvidenceError, match="PASS result differs"):
        evidence.validate_probe_result(evidence.canonical_bytes(changed, pretty=True))


def test_receipt_is_built_from_api_projections_and_exact_downloaded_zip(
    tmp_path: Path,
) -> None:
    repository, correction_head, marker_head = _marker_repository(tmp_path)
    result_raw = evidence.canonical_bytes(evidence.expected_probe_result(), pretty=True)
    run_raw, jobs_raw, artifact_raw, archive_raw = _provenance(marker_head, result_raw)
    receipt = evidence.build_receipt_document(
        repository,
        correction_head=correction_head,
        marker_head=marker_head,
        result_raw=result_raw,
        workflow_run_raw=run_raw,
        workflow_jobs_raw=jobs_raw,
        artifact_raw=artifact_raw,
        artifact_archive_raw=archive_raw,
        observed_at_utc="2026-09-01T01:05:00Z",
    )
    raw = evidence.canonical_bytes(receipt, pretty=True)
    assert evidence.validate_receipt_document(
        repository, raw, result_raw=result_raw
    ) == receipt
    assert receipt["accounting"] == evidence.ACCOUNTING
    assert receipt["workflow_run"]["attempt"] == 1
    assert receipt["workflow_job"]["head_sha"] == marker_head
    assert receipt["artifact"]["result_member_raw_sha256"] == (
        "sha256:" + hashlib.sha256(result_raw).hexdigest()
    )
    assert receipt["source_documents"]["artifact_archive"]["raw_sha256"] == (
        receipt["artifact"]["digest"]
    )


@pytest.mark.parametrize(
    ("provenance_options", "message"),
    [
        ({"run_attempt": 2}, "attempt is not exactly one"),
        ({"run_conclusion": "failure"}, "run is not completed/success"),
        ({"extra_member": True}, "exactly one entry"),
    ],
)
def test_receipt_builder_rejects_non_exact_provenance(
    tmp_path: Path, provenance_options: dict[str, object], message: str
) -> None:
    repository, correction_head, marker_head = _marker_repository(tmp_path)
    result_raw = evidence.canonical_bytes(evidence.expected_probe_result(), pretty=True)
    provenance = _provenance(marker_head, result_raw, **provenance_options)
    with pytest.raises(evidence.ProbeEvidenceError, match=message):
        evidence.build_receipt_document(
            repository,
            correction_head=correction_head,
            marker_head=marker_head,
            result_raw=result_raw,
            workflow_run_raw=provenance[0],
            workflow_jobs_raw=provenance[1],
            artifact_raw=provenance[2],
            artifact_archive_raw=provenance[3],
            observed_at_utc="2026-09-01T01:05:00Z",
        )


def test_receipt_builder_rejects_archive_digest_or_result_member_drift(
    tmp_path: Path,
) -> None:
    repository, correction_head, marker_head = _marker_repository(tmp_path)
    result_raw = evidence.canonical_bytes(evidence.expected_probe_result(), pretty=True)
    run_raw, jobs_raw, artifact_raw, archive_raw = _provenance(marker_head, result_raw)
    artifact = json.loads(artifact_raw)
    artifact["digest"] = "sha256:" + "0" * 64
    with pytest.raises(evidence.ProbeEvidenceError, match="archive digest differs"):
        evidence.build_receipt_document(
            repository,
            correction_head=correction_head,
            marker_head=marker_head,
            result_raw=result_raw,
            workflow_run_raw=run_raw,
            workflow_jobs_raw=jobs_raw,
            artifact_raw=_json_bytes(artifact),
            artifact_archive_raw=archive_raw,
            observed_at_utc="2026-09-01T01:05:00Z",
        )
    artifact["digest"] = "sha256:" + hashlib.sha256(archive_raw).hexdigest()
    artifact["size_in_bytes"] = len(archive_raw) + 1
    with pytest.raises(evidence.ProbeEvidenceError, match="archive size differs"):
        evidence.build_receipt_document(
            repository,
            correction_head=correction_head,
            marker_head=marker_head,
            result_raw=result_raw,
            workflow_run_raw=run_raw,
            workflow_jobs_raw=jobs_raw,
            artifact_raw=_json_bytes(artifact),
            artifact_archive_raw=archive_raw,
            observed_at_utc="2026-09-01T01:05:00Z",
        )


def test_committed_evidence_proves_exact_chain_freeze_and_provenance(
    tmp_path: Path,
) -> None:
    repository, correction, marker, evidence_head, raw = _closed_repository(tmp_path)
    binding = evidence.validate_committed_evidence(
        repository, evidence_head=evidence_head
    )
    assert binding["correction_head"] == correction
    assert binding["marker_head"] == marker
    assert binding["evidence_head"] == evidence_head
    assert binding["accounting"] == evidence.ACCOUNTING
    assert binding["files"]["probe_result"]["raw_sha256"] == (
        "sha256:" + hashlib.sha256(raw["result"]).hexdigest()
    )
    assert binding["files"]["probe_receipt"]["raw_sha256"] == (
        "sha256:" + hashlib.sha256(raw["receipt"]).hexdigest()
    )


def test_evidence_head_must_be_ancestral_and_unique_introduction(
    tmp_path: Path,
) -> None:
    repository, _, _, evidence_head, _ = _closed_repository(tmp_path)
    _git(repository, "checkout", "--orphan", "unrelated")
    _git(repository, "rm", "-r", "--cached", ".")
    for child in list(repository.iterdir()):
        if child.name != ".git" and child.is_file():
            child.unlink()
    (repository / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
    _commit(repository, "unrelated")
    with pytest.raises(evidence.ProbeEvidenceError, match="not an ancestor"):
        evidence.validate_committed_evidence(repository, evidence_head=evidence_head)


def test_freeze_probe_phase_is_absent_marker_only_or_exact_trio(tmp_path: Path) -> None:
    assert freeze.conditional_probe_evidence_paths(tmp_path) == ()
    marker = tmp_path / evidence.PROBE_REQUEST_PATH
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b"{}\n")
    assert freeze.conditional_probe_evidence_paths(tmp_path) == ()
    result = tmp_path / evidence.PROBE_RESULT_PATH
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_bytes(b"{}\n")
    with pytest.raises(ValueError, match="exact trio"):
        freeze.conditional_probe_evidence_paths(tmp_path)
    receipt = tmp_path / evidence.PROBE_RECEIPT_PATH
    receipt.write_bytes(b"{}\n")
    assert freeze.conditional_probe_evidence_paths(tmp_path) == (
        evidence.PROBE_REQUEST_PATH,
        evidence.PROBE_RESULT_PATH,
        evidence.PROBE_RECEIPT_PATH,
    )


def test_004_builder_requires_evidence_head_and_binds_full_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, correction, marker, evidence_head, _ = _closed_repository(tmp_path)
    material = {
        trigger.FROZEN_REQUEST_PATH: b"request",
        trigger.FREEZE_PATH: b"freeze",
        trigger.MANIFEST_PATH: b"manifest",
        trigger.IMAGE_LOCK_PATH: b"image-lock",
        trigger.CREDENTIAL_FREE_BUNDLE_PATH: b"bundle",
        trigger.OFFICIAL_GRADER_PATH: b"adapter",
        trigger.MULTI_SWE_ENTRYPOINT_PATH: b"entrypoint",
        trigger.MULTI_SWE_PROBE_EVIDENCE_PATH: b"evidence-verifier",
        trigger.MULTI_SWE_EVALUATION_CONTRACT_LOCK_PATH: b"contract-lock",
    }
    matrix_order = [f"target-{index}" for index in range(12)]
    monkeypatch.setattr(
        trigger,
        "_validate_frozen_material",
        lambda _repository, _commit: (
            material,
            {"target_set_sha256": trigger.BASELINE_TARGET_SET_SHA256},
            matrix_order,
        ),
    )
    for premature_head in (correction, marker):
        with pytest.raises(
            trigger.TriggerPreflightError, match="image-probe evidence is not closed"
        ):
            trigger.build_request_document(repository, source_head=premature_head)
    follow_up = repository / "post-probe-ci-correction.txt"
    follow_up.write_text("unrelated correction\n", encoding="utf-8")
    source_head = _commit(repository, "post-probe CI correction")
    document = trigger.build_request_document(repository, source_head=source_head)
    expected = evidence.validate_committed_evidence(
        repository, evidence_head=evidence_head
    )
    assert document["schema"] == "trimem/grader-smoke-branch-trigger/1.5"
    assert document["source_head"] == source_head
    assert document["multi_swe_probe_evidence"] == expected
    assert document["multi_swe_probe_evidence"]["evidence_head"] == evidence_head
    assert document["multi_swe_probe_evidence"]["workflow_run"]["attempt"] == 1
    assert document["multi_swe_probe_evidence"]["accounting"] == evidence.ACCOUNTING


def test_receipt_writer_uses_saved_api_documents_and_downloaded_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, correction, marker = _marker_repository(tmp_path)
    result_raw = evidence.canonical_bytes(evidence.expected_probe_result(), pretty=True)
    result_path = repository / evidence.PROBE_RESULT_PATH
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_bytes(result_raw)
    provenance = _provenance(marker, result_raw)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    paths = []
    for name, raw in zip(("run.json", "jobs.json", "artifact.json", "artifact.zip"), provenance):
        path = inputs / name
        path.write_bytes(raw)
        paths.append(path)
    output = repository / evidence.PROBE_RECEIPT_PATH
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "probe-evidence",
            "--repository",
            str(repository),
            "--write-receipt",
            "--correction-head",
            correction,
            "--marker-head",
            marker,
            "--result",
            str(result_path),
            "--workflow-run-json",
            str(paths[0]),
            "--workflow-jobs-json",
            str(paths[1]),
            "--artifact-json",
            str(paths[2]),
            "--artifact-zip",
            str(paths[3]),
            "--observed-at-utc",
            "2026-09-01T01:05:00Z",
            "--output",
            str(output),
        ],
    )
    assert evidence.main() == 0
    value = evidence.validate_receipt_document(
        repository, output.read_bytes(), result_raw=result_raw
    )
    assert value["workflow_run"]["head_sha"] == marker
    assert value["artifact"]["digest"] == (
        "sha256:" + hashlib.sha256(provenance[3]).hexdigest()
    )
