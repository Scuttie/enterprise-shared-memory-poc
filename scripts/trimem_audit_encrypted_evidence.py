"""Audit downloaded encrypted TriMem evidence without persisting plaintext."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
from typing import Any, BinaryIO, Iterable, Mapping
import zipfile


MODEL_ID = "gpt-5.4-mini-2026-03-17"
INVENTORY_SCHEMA = "trimem/restricted-evidence-inventory/1.0"
AUDIT_SCHEMA = "trimem/encrypted-evidence-custody-audit/1.0"


class EvidenceCustodyError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member_path(name: str) -> PurePosixPath:
    if not isinstance(name, str) or not name or "\\" in name:
        raise EvidenceCustodyError("encrypted evidence contains a noncanonical path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise EvidenceCustodyError("encrypted evidence contains an unsafe path")
    return path


def load_inventory(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes().decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceCustodyError("expected inventory is unreadable") from exc
    if not isinstance(value, dict) or value.get("schema") != INVENTORY_SCHEMA:
        raise EvidenceCustodyError("expected inventory schema differs")
    payload = {key: value.get(key) for key in ("files", "root", "schema", "total_bytes", "total_files")}
    if value.get("inventory_sha256") != hashlib.sha256(canonical_bytes(payload)).hexdigest():
        raise EvidenceCustodyError("expected inventory seal differs")
    root = value.get("root")
    rows = value.get("files")
    if (
        not isinstance(root, str)
        or not root
        or "/" in root
        or "\\" in root
        or not isinstance(rows, list)
    ):
        raise EvidenceCustodyError("expected inventory identity differs")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"bytes", "path", "sha256"}:
            raise EvidenceCustodyError("expected inventory row differs")
        relative = _safe_member_path(str(row.get("path", ""))).as_posix()
        size = row.get("bytes")
        digest = row.get("sha256")
        if (
            type(size) is not int
            or size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise EvidenceCustodyError("expected inventory row scalar differs")
        normalized.append({"bytes": size, "path": relative, "sha256": digest})
    if normalized != sorted(normalized, key=lambda row: row["path"]):
        raise EvidenceCustodyError("expected inventory order differs")
    if len({row["path"] for row in normalized}) != len(normalized):
        raise EvidenceCustodyError("expected inventory contains duplicate paths")
    if value.get("total_files") != len(normalized) or value.get("total_bytes") != sum(
        row["bytes"] for row in normalized
    ):
        raise EvidenceCustodyError("expected inventory totals differ")
    return value


def _contains_forbidden(stream: BinaryIO, forbidden: tuple[bytes, ...]) -> bool:
    if not forbidden:
        while stream.read(1024 * 1024):
            pass
        return False
    overlap = max(len(item) for item in forbidden) - 1
    suffix = b""
    while chunk := stream.read(1024 * 1024):
        sample = suffix + chunk
        if any(item in sample for item in forbidden):
            return True
        suffix = sample[-overlap:] if overlap > 0 else b""
    return False


def scan_zip_for_forbidden(path: Path, forbidden: tuple[bytes, ...]) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            members = sorted(archive.infolist(), key=lambda item: item.filename)
            for member in members:
                _safe_member_path(member.filename.rstrip("/"))
                if member.is_dir():
                    continue
                with archive.open(member) as stream:
                    if _contains_forbidden(stream, forbidden):
                        raise EvidenceCustodyError(
                            "forbidden secret material appears in an audited ZIP member"
                        )
    except (OSError, zipfile.BadZipFile) as exc:
        raise EvidenceCustodyError("audit ZIP is unreadable") from exc
    return {"path": path.name, "sha256": hash_file(path), "members_scanned": len(members)}


def _validate_model_access_envelope(raw: bytes) -> str:
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceCustodyError("model-access envelope is invalid JSON") from exc
    if not isinstance(value, dict):
        raise EvidenceCustodyError("model-access envelope is not an object")
    if (
        value.get("provider_control_plane_requests") != 1
        or value.get("model_generation_requests") != 0
        or value.get("model_tokens") != 0
        or value.get("benchmark_image_pulls") != 0
        or value.get("task_arm_reservations") != 0
        or value.get("credential_binding") != "PASS"
    ):
        raise EvidenceCustodyError("model-access zero-generation accounting differs")
    if value.get("status") == "PASS":
        if (
            value.get("http_status") != 200
            or value.get("returned_model") != MODEL_ID
        ):
            raise EvidenceCustodyError("model-access PASS identity differs")
        return "PASS"
    allowed = {
        401: "HTTP_401_AUTHENTICATION_FAILED",
        403: "HTTP_403_PERMISSION_DENIED",
        404: "HTTP_404_MODEL_NOT_AVAILABLE",
        429: "HTTP_429_RATE_OR_QUOTA_LIMIT",
    }
    status = value.get("http_status")
    expected = allowed.get(status, "HTTP_OTHER_CLIENT_ERROR")
    if value.get("status") != "FAIL" or value.get("http_classification") != expected:
        raise EvidenceCustodyError("model-access failure classification differs")
    if not isinstance(value.get("raw_restricted_evidence_reference"), str):
        raise EvidenceCustodyError("model-access raw evidence reference is absent")
    return "FAIL"


def audit_tar_stream(
    stream: BinaryIO,
    inventories: Mapping[str, Mapping[str, Any]],
    *,
    forbidden: tuple[bytes, ...] = (),
) -> dict[str, Any]:
    observed: dict[str, list[dict[str, Any]]] = {root: [] for root in inventories}
    model_access_raw: bytes | None = None
    with tarfile.open(fileobj=stream, mode="r|*") as archive:
        for member in archive:
            path = _safe_member_path(member.name.rstrip("/"))
            if member.isdir():
                continue
            if not member.isfile():
                raise EvidenceCustodyError("encrypted evidence contains a non-regular member")
            if not path.parts or path.parts[0] not in inventories:
                raise EvidenceCustodyError("encrypted evidence contains an unexpected root")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise EvidenceCustodyError("encrypted evidence member cannot be streamed")
            digest = hashlib.sha256()
            byte_count = 0
            chunks: list[bytes] | None = (
                []
                if path.as_posix()
                == "benchmark_exec/development/control/model-access-result.json"
                else None
            )
            overlap = max((len(item) for item in forbidden), default=1) - 1
            suffix = b""
            while chunk := extracted.read(1024 * 1024):
                digest.update(chunk)
                byte_count += len(chunk)
                sample = suffix + chunk
                if forbidden and any(item in sample for item in forbidden):
                    raise EvidenceCustodyError(
                        "forbidden secret material appears in encrypted evidence"
                    )
                suffix = sample[-overlap:] if overlap > 0 else b""
                if chunks is not None:
                    chunks.append(chunk)
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            observed[path.parts[0]].append(
                {"bytes": byte_count, "path": relative, "sha256": digest.hexdigest()}
            )
            if chunks is not None:
                model_access_raw = b"".join(chunks)
    for rows in observed.values():
        rows.sort(key=lambda row: row["path"])
    for root, expected in inventories.items():
        if observed[root] != expected.get("files"):
            raise EvidenceCustodyError(f"decrypted evidence inventory differs: {root}")
    if model_access_raw is None:
        raise EvidenceCustodyError("model-access envelope is missing from decrypted evidence")
    model_access_status = _validate_model_access_envelope(model_access_raw)
    total_files = sum(len(rows) for rows in observed.values())
    total_bytes = sum(row["bytes"] for rows in observed.values() for row in rows)
    return {
        "model_access_envelope": model_access_status,
        "roots": sorted(observed),
        "total_bytes": total_bytes,
        "total_files": total_files,
    }


def _ciphertext_member(artifact_zip: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(artifact_zip) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            if len(files) != 1 or not files[0].filename.endswith(".tar.enc"):
                raise EvidenceCustodyError("encrypted artifact ZIP member set differs")
            _safe_member_path(files[0].filename)
            with archive.open(files[0]) as source, destination.open("xb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
    except (OSError, zipfile.BadZipFile) as exc:
        raise EvidenceCustodyError("encrypted artifact ZIP is unreadable") from exc


def audit_downloaded_artifact(
    artifact_zip: Path,
    *,
    expected_zip_sha256: str,
    inventory_paths: Iterable[Path],
    forbidden: tuple[bytes, ...] = (),
) -> dict[str, Any]:
    observed_zip_sha256 = hash_file(artifact_zip)
    if observed_zip_sha256 != expected_zip_sha256.removeprefix("sha256:"):
        raise EvidenceCustodyError("uploaded artifact ZIP digest differs")
    inventories = {value["root"]: value for value in map(load_inventory, inventory_paths)}
    if not inventories:
        raise EvidenceCustodyError("at least one expected inventory is required")
    temporary_root = Path(tempfile.mkdtemp(prefix="trimem-custody-ciphertext-"))
    ciphertext = temporary_root / "evidence.tar.enc"
    try:
        _ciphertext_member(artifact_zip, ciphertext)
        process = subprocess.Popen(
            [
                "openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2",
                "-pass", "env:TRIMEM_EVIDENCE_PASSPHRASE", "-in", str(ciphertext),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdout is not None
        try:
            try:
                audited = audit_tar_stream(
                    process.stdout, inventories, forbidden=forbidden
                )
            except BaseException:
                process.kill()
                process.wait()
                raise
        finally:
            process.stdout.close()
        stderr = process.stderr.read() if process.stderr is not None else b""
        return_code = process.wait()
        if return_code != 0:
            raise EvidenceCustodyError(
                "encrypted evidence decryption failed (stderr_sha256="
                + hashlib.sha256(stderr).hexdigest()
                + ")"
            )
    finally:
        try:
            ciphertext.unlink(missing_ok=True)
            temporary_root.rmdir()
        except OSError:
            pass
    return {
        "artifact_zip_sha256": observed_zip_sha256,
        "plaintext_persisted": False,
        **audited,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-zip", type=Path, required=True)
    parser.add_argument("--artifact-zip-sha256", required=True)
    parser.add_argument("--inventory", action="append", type=Path, required=True)
    parser.add_argument("--scan-zip", action="append", type=Path, default=[])
    parser.add_argument(
        "--forbid-env",
        action="append",
        default=["OPENAI_API_KEY", "TRIMEM_EVIDENCE_PASSPHRASE"],
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    forbidden: list[bytes] = []
    for name in args.forbid_env:
        value = os.environ.get(name)
        if value:
            forbidden.append(value.encode("utf-8"))
    try:
        audited = audit_downloaded_artifact(
            args.artifact_zip,
            expected_zip_sha256=args.artifact_zip_sha256,
            inventory_paths=args.inventory,
            forbidden=tuple(forbidden),
        )
        scanned = [scan_zip_for_forbidden(path, tuple(forbidden)) for path in args.scan_zip]
        result = {
            "schema": AUDIT_SCHEMA,
            "status": "PASS",
            "forbidden_secret_scan": "PASS",
            "scanned_zip_artifacts": scanned,
            **audited,
        }
    except (OSError, EvidenceCustodyError, subprocess.SubprocessError) as exc:
        result = {
            "schema": AUDIT_SCHEMA,
            "status": "EVIDENCE_CUSTODY_INCOMPLETE",
            "error": str(exc),
        }
    raw = canonical_bytes(result) + b"\n"
    if args.output is not None:
        args.output.write_bytes(raw)
    print(raw.decode("utf-8"), end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
