from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import trimem_audit_encrypted_evidence as custody  # noqa: E402


def _inventory(root: str, files: dict[str, bytes]) -> dict:
    rows = [
        {
            "bytes": len(raw),
            "path": path,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        for path, raw in sorted(files.items())
    ]
    payload = {
        "files": rows,
        "root": root,
        "schema": custody.INVENTORY_SCHEMA,
        "total_bytes": sum(row["bytes"] for row in rows),
        "total_files": len(rows),
    }
    return {
        **payload,
        "inventory_sha256": hashlib.sha256(custody.canonical_bytes(payload)).hexdigest(),
    }


def _tar(files: dict[str, bytes], *, symlink: bool = False) -> io.BytesIO:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for path, raw in files.items():
            info = tarfile.TarInfo(path)
            if symlink:
                info.type = tarfile.SYMTYPE
                info.linkname = "elsewhere"
                info.size = 0
                archive.addfile(info)
            else:
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
    output.seek(0)
    return output


def _model_access() -> bytes:
    return custody.canonical_bytes(
        {
            "status": "PASS",
            "http_status": 200,
            "returned_model": custody.MODEL_ID,
            "credential_binding": "PASS",
            "provider_control_plane_requests": 1,
            "model_generation_requests": 0,
            "model_tokens": 0,
            "benchmark_image_pulls": 0,
            "task_arm_reservations": 0,
        }
    ) + b"\n"


def test_stream_audit_matches_every_path_type_size_and_digest() -> None:
    files = {
        "development/control/model-access-result.json": _model_access(),
        "development/restricted/raw": b"provider response",
    }
    inventories = {"benchmark_exec": _inventory("benchmark_exec", files)}
    result = custody.audit_tar_stream(
        _tar({f"benchmark_exec/{path}": raw for path, raw in files.items()}),
        inventories,
        forbidden=(b"secret-not-present",),
    )
    assert result == {
        "model_access_envelope": "PASS",
        "roots": ["benchmark_exec"],
        "total_bytes": sum(map(len, files.values())),
        "total_files": 2,
    }


def test_stream_audit_rejects_digest_drift_and_non_regular_members() -> None:
    files = {"development/control/model-access-result.json": _model_access()}
    inventory = _inventory("benchmark_exec", files)
    with pytest.raises(custody.EvidenceCustodyError, match="inventory differs"):
        custody.audit_tar_stream(
            _tar({"benchmark_exec/development/control/model-access-result.json": b"changed"}),
            {"benchmark_exec": inventory},
        )
    with pytest.raises(custody.EvidenceCustodyError, match="non-regular"):
        custody.audit_tar_stream(
            _tar({"benchmark_exec/link": b""}, symlink=True),
            {"benchmark_exec": inventory},
        )


def test_stream_and_zip_scans_reject_secret_without_disclosing_it(tmp_path: Path) -> None:
    secret = b"credential-material-for-test"
    files = {"development/control/model-access-result.json": _model_access()}
    inventory = _inventory("benchmark_exec", files)
    with pytest.raises(custody.EvidenceCustodyError) as caught:
        custody.audit_tar_stream(
            _tar(
                {
                    "benchmark_exec/development/control/model-access-result.json": _model_access(),
                    "benchmark_exec/development/log.txt": b"prefix" + secret + b"suffix",
                }
            ),
            {"benchmark_exec": inventory},
            forbidden=(secret,),
        )
    assert secret.decode() not in str(caught.value)

    archive_path = tmp_path / "logs.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("logs/job.txt", b"prefix" + secret + b"suffix")
    with pytest.raises(custody.EvidenceCustodyError) as caught:
        custody.scan_zip_for_forbidden(archive_path, (secret,))
    assert secret.decode() not in str(caught.value)


def test_model_access_envelope_keeps_401_and_403_distinct() -> None:
    base = {
        "status": "FAIL",
        "credential_binding": "PASS",
        "provider_control_plane_requests": 1,
        "model_generation_requests": 0,
        "model_tokens": 0,
        "benchmark_image_pulls": 0,
        "task_arm_reservations": 0,
        "raw_restricted_evidence_reference": "restricted://fixture",
    }
    for status, classification in (
        (401, "HTTP_401_AUTHENTICATION_FAILED"),
        (403, "HTTP_403_PERMISSION_DENIED"),
    ):
        raw = custody.canonical_bytes(
            {**base, "http_status": status, "http_classification": classification}
        )
        assert custody._validate_model_access_envelope(raw) == "FAIL"
