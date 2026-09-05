"""Install one byte-pinned official GitHub CLI release without package managers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Callable, Mapping
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK_PATH = ROOT / "configs/trimem_v1/gh_cli_lock.json"
LOCK_SCHEMA = "trimem/gh-cli-lock/1.0"
SHA256_HEX_LENGTH = 64
MAX_ARCHIVE_MEMBERS = 4096
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_BINARY_BYTES = 128 * 1024 * 1024
MAX_CHECKSUM_FILE_BYTES = 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 180


class GhCliInstallError(ValueError):
    """The pinned GitHub CLI installation contract failed closed."""


def _strict_json_object(path: Path) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise GhCliInstallError(f"duplicate JSON key in GitHub CLI lock: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise GhCliInstallError(f"invalid JSON constant in GitHub CLI lock: {value}")

    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except GhCliInstallError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GhCliInstallError("GitHub CLI lock is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise GhCliInstallError("GitHub CLI lock root is not an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise GhCliInstallError(f"{label} has an unexpected shape")


def _nonempty_string(value: Any, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise GhCliInstallError(f"{label} is not an exact nonempty string")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise GhCliInstallError(f"{label} contains a control character")
    return value


def _positive_integer(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise GhCliInstallError(f"{label} is not a positive integer")
    return value


def _sha256_hex(value: Any, label: str) -> str:
    value = _nonempty_string(value, label)
    if len(value) != SHA256_HEX_LENGTH or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise GhCliInstallError(f"{label} is not a lowercase SHA-256")
    return value


def _safe_relative_posix_path(value: Any, label: str) -> str:
    value = _nonempty_string(value, label)
    if "\\" in value or ":" in value or value.startswith("-"):
        raise GhCliInstallError(f"{label} is not safe relative POSIX syntax")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or candidate.as_posix() != value
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise GhCliInstallError(f"{label} is not canonical and relative")
    return value


def load_gh_cli_lock(path: Path) -> dict[str, Any]:
    """Load and validate the complete immutable GitHub CLI lock."""

    lock = _strict_json_object(path)
    _exact_keys(
        lock,
        {
            "archive_filename",
            "archive_sha256",
            "archive_sha256_source_line",
            "archive_url",
            "checksum_file_sha256",
            "checksum_file_url",
            "expected_first_version_line",
            "extracted_gh_binary_sha256",
            "hash_source",
            "install_layout",
            "observed_archive_bytes",
            "observed_checksum_file_bytes",
            "observed_gh_binary_bytes",
            "platform",
            "release_tag",
            "schema",
            "verification_date",
            "version",
        },
        "GitHub CLI lock",
    )
    if lock["schema"] != LOCK_SCHEMA:
        raise GhCliInstallError("GitHub CLI lock schema mismatch")
    version = _nonempty_string(lock["version"], "version")
    if version != "2.97.0":
        raise GhCliInstallError("GitHub CLI version is not the approved exact pin")
    release_tag = _nonempty_string(lock["release_tag"], "release_tag")
    if release_tag != f"v{version}":
        raise GhCliInstallError("GitHub CLI release tag does not match version")
    if lock["platform"] != "linux_amd64":
        raise GhCliInstallError("GitHub CLI platform is not linux_amd64")

    archive_filename = _safe_relative_posix_path(
        lock["archive_filename"], "archive_filename"
    )
    if "/" in archive_filename or archive_filename != f"gh_{version}_linux_amd64.tar.gz":
        raise GhCliInstallError("GitHub CLI archive filename mismatch")
    release_base = f"https://github.com/cli/cli/releases/download/{release_tag}"
    if lock["archive_url"] != f"{release_base}/{archive_filename}":
        raise GhCliInstallError("GitHub CLI archive URL is not the official exact asset")
    checksum_filename = f"gh_{version}_checksums.txt"
    if lock["checksum_file_url"] != f"{release_base}/{checksum_filename}":
        raise GhCliInstallError(
            "GitHub CLI checksum-file URL is not the official exact asset"
        )

    archive_sha256 = _sha256_hex(lock["archive_sha256"], "archive_sha256")
    _sha256_hex(lock["checksum_file_sha256"], "checksum_file_sha256")
    _sha256_hex(
        lock["extracted_gh_binary_sha256"], "extracted_gh_binary_sha256"
    )
    expected_source_line = f"{archive_sha256}  {archive_filename}"
    if lock["archive_sha256_source_line"] != expected_source_line:
        raise GhCliInstallError("official checksum source line mismatch")
    archive_bytes = _positive_integer(
        lock["observed_archive_bytes"], "observed_archive_bytes"
    )
    checksum_bytes = _positive_integer(
        lock["observed_checksum_file_bytes"], "observed_checksum_file_bytes"
    )
    binary_bytes = _positive_integer(
        lock["observed_gh_binary_bytes"], "observed_gh_binary_bytes"
    )
    if archive_bytes > MAX_ARCHIVE_BYTES:
        raise GhCliInstallError("GitHub CLI archive byte lock exceeds safety cap")
    if checksum_bytes > MAX_CHECKSUM_FILE_BYTES:
        raise GhCliInstallError("GitHub CLI checksum byte lock exceeds safety cap")
    if binary_bytes > MAX_BINARY_BYTES:
        raise GhCliInstallError("GitHub CLI binary byte lock exceeds safety cap")

    expected_version = f"gh version {version} (2026-07-31)"
    if lock["expected_first_version_line"] != expected_version:
        raise GhCliInstallError("GitHub CLI expected version line mismatch")
    if lock["verification_date"] != "2026-09-03":
        raise GhCliInstallError("GitHub CLI verification date mismatch")

    layout = lock["install_layout"]
    if not isinstance(layout, dict):
        raise GhCliInstallError("GitHub CLI install layout is not an object")
    _exact_keys(
        layout,
        {
            "archive_binary_path",
            "archive_root",
            "bin_directory",
            "installed_binary_path",
        },
        "GitHub CLI install layout",
    )
    archive_root = _safe_relative_posix_path(layout["archive_root"], "archive_root")
    archive_binary_path = _safe_relative_posix_path(
        layout["archive_binary_path"], "archive_binary_path"
    )
    bin_directory = _safe_relative_posix_path(
        layout["bin_directory"], "bin_directory"
    )
    installed_binary_path = _safe_relative_posix_path(
        layout["installed_binary_path"], "installed_binary_path"
    )
    expected_root = f"gh_{version}_linux_amd64"
    if archive_root != expected_root:
        raise GhCliInstallError("GitHub CLI archive root mismatch")
    if archive_binary_path != f"{archive_root}/bin/gh":
        raise GhCliInstallError("GitHub CLI archive binary path mismatch")
    if bin_directory != "bin" or installed_binary_path != "bin/gh":
        raise GhCliInstallError("GitHub CLI prefix install layout mismatch")

    hash_source = lock["hash_source"]
    if not isinstance(hash_source, dict):
        raise GhCliInstallError("GitHub CLI hash source is not an object")
    _exact_keys(
        hash_source,
        {"archive_sha256", "extracted_gh_binary_sha256"},
        "GitHub CLI hash source",
    )
    if hash_source != {
        "archive_sha256": "OFFICIAL_GITHUB_CLI_RELEASE_CHECKSUM_FILE",
        "extracted_gh_binary_sha256": (
            "INDEPENDENT_SHA256_OF_EXACT_REGULAR_FILE_PAYLOAD_AFTER_ARCHIVE_VERIFICATION"
        ),
    }:
        raise GhCliInstallError("GitHub CLI hash provenance mismatch")
    return lock


def _verify_runtime_platform() -> None:
    machine = platform.machine().lower()
    if platform.system() != "Linux" or machine not in {"amd64", "x86_64"}:
        raise GhCliInstallError("pinned GitHub CLI requires Linux amd64")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise GhCliInstallError("GitHub CLI bytes could not be read") from exc
    return digest.hexdigest()


def _assert_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise GhCliInstallError(f"{label} is missing") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise GhCliInstallError(f"{label} is not a regular file")


def _download_archive(url: str, destination: Path, expected_bytes: int) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "trimem-pinned-gh-installer/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=DOWNLOAD_TIMEOUT_SECONDS
        ) as response, destination.open("xb") as output:
            observed = 0
            while True:
                chunk = response.read(min(1024 * 1024, expected_bytes + 1 - observed))
                if not chunk:
                    break
                observed += len(chunk)
                if observed > expected_bytes:
                    raise GhCliInstallError("GitHub CLI archive exceeds locked byte count")
                output.write(chunk)
    except GhCliInstallError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise GhCliInstallError("official GitHub CLI archive download failed") from exc
    if observed != expected_bytes:
        raise GhCliInstallError("GitHub CLI archive byte count mismatch")


def _safe_archive_member(name: str, archive_root: str) -> PurePosixPath:
    safe = _safe_relative_posix_path(name, "archive member path")
    path = PurePosixPath(safe)
    if not path.parts or path.parts[0] != archive_root:
        raise GhCliInstallError("archive member is outside the exact archive root")
    return path


def _extract_locked_binary(
    archive_path: Path,
    destination: Path,
    lock: Mapping[str, Any],
) -> None:
    layout = lock["install_layout"]
    expected_path = layout["archive_binary_path"]
    expected_root = layout["archive_root"]
    expected_bytes = lock["observed_gh_binary_bytes"]
    seen: set[str] = set()
    binary_member: tarfile.TarInfo | None = None
    uncompressed_bytes = 0
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            member_count = 0
            for member in archive:
                member_count += 1
                if member_count > MAX_ARCHIVE_MEMBERS:
                    raise GhCliInstallError(
                        "GitHub CLI archive member count is unsafe"
                    )
                member_path = _safe_archive_member(member.name, expected_root)
                if member.name in seen:
                    raise GhCliInstallError("GitHub CLI archive has duplicate members")
                seen.add(member.name)
                if member.type not in {tarfile.REGTYPE, tarfile.AREGTYPE}:
                    raise GhCliInstallError(
                        "GitHub CLI archive contains a link or non-regular member"
                    )
                if member.linkname:
                    raise GhCliInstallError("GitHub CLI archive member has a link target")
                if member.size < 0:
                    raise GhCliInstallError("GitHub CLI archive member size is invalid")
                uncompressed_bytes += member.size
                if uncompressed_bytes > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise GhCliInstallError("GitHub CLI archive expands beyond safety cap")
                is_binary_location = (
                    member_path.name == "gh"
                    or (len(member_path.parts) >= 2 and member_path.parts[-2] == "bin")
                    or bool(member.mode & 0o111)
                )
                if is_binary_location and member.name != expected_path:
                    raise GhCliInstallError(
                        "GitHub CLI archive contains an unexpected binary path"
                    )
                if member.name == expected_path:
                    if binary_member is not None:
                        raise GhCliInstallError(
                            "GitHub CLI archive binary member is duplicated"
                        )
                    binary_member = member
            if member_count == 0:
                raise GhCliInstallError("GitHub CLI archive has no members")
            if binary_member is None:
                raise GhCliInstallError("GitHub CLI archive binary is missing")
            if binary_member.size != expected_bytes:
                raise GhCliInstallError("GitHub CLI binary byte count mismatch")
            if binary_member.mode & 0o777 != 0o755:
                raise GhCliInstallError("GitHub CLI archive binary mode mismatch")
            source = archive.extractfile(binary_member)
            if source is None:
                raise GhCliInstallError("GitHub CLI binary payload is unavailable")
            with source, destination.open("xb") as output:
                remaining = expected_bytes
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise GhCliInstallError("GitHub CLI binary payload is truncated")
                    output.write(chunk)
                    remaining -= len(chunk)
                if source.read(1):
                    raise GhCliInstallError("GitHub CLI binary payload exceeds locked size")
    except GhCliInstallError:
        raise
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise GhCliInstallError("GitHub CLI archive validation failed") from exc


def resolve_installed_binary(lock: Mapping[str, Any], prefix: Path) -> Path:
    """Resolve the exact configured prefix-relative binary without PATH lookup."""

    raw_prefix = Path(prefix)
    if raw_prefix.is_symlink():
        raise GhCliInstallError("GitHub CLI prefix must not be a symbolic link")
    absolute_prefix = Path(os.path.abspath(raw_prefix))
    relative = PurePosixPath(lock["install_layout"]["installed_binary_path"])
    binary_path = absolute_prefix.joinpath(*relative.parts)
    if binary_path.parent.is_symlink():
        raise GhCliInstallError("GitHub CLI bin directory must not be a symbolic link")
    return binary_path


def verify_installed_gh(
    lock: Mapping[str, Any], binary_path: Path
) -> dict[str, Any]:
    """Verify exact installed bytes and the exact first `gh --version` line."""

    _verify_runtime_platform()
    _assert_regular_file(binary_path, "installed GitHub CLI")
    if binary_path.stat().st_size != lock["observed_gh_binary_bytes"]:
        raise GhCliInstallError("installed GitHub CLI binary byte count mismatch")
    observed_sha256 = _sha256_file(binary_path)
    if observed_sha256 != lock["extracted_gh_binary_sha256"]:
        raise GhCliInstallError("installed GitHub CLI binary hash mismatch")
    try:
        completed = subprocess.run(
            [str(binary_path), "--version"],
            capture_output=True,
            text=False,
            check=False,
            timeout=30,
            env={
                key: value
                for key, value in os.environ.items()
                if key
                not in {
                    "GH_TOKEN",
                    "GITHUB_TOKEN",
                    "OPENAI_API_KEY",
                    "TRIMEM_EVIDENCE_PASSPHRASE",
                    "TRIMEM_EXEC_APPROVAL_B64",
                }
            },
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GhCliInstallError("installed GitHub CLI version check failed") from exc
    if completed.returncode != 0:
        raise GhCliInstallError("installed GitHub CLI version check returned nonzero")
    try:
        version_lines = completed.stdout.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise GhCliInstallError("installed GitHub CLI version output is not UTF-8") from exc
    if not version_lines or version_lines[0] != lock["expected_first_version_line"]:
        raise GhCliInstallError("installed GitHub CLI first version line mismatch")
    return {
        "binary_sha256": observed_sha256,
        "first_version_line": version_lines[0],
        "status": "PASS",
        "version": lock["version"],
    }


def _repair_executable_mode_for_matching_bytes(
    lock: Mapping[str, Any], binary_path: Path
) -> None:
    """Make a byte-identical pre-existing payload executable without replacing it."""

    _assert_regular_file(binary_path, "installed GitHub CLI")
    if binary_path.stat().st_size != lock["observed_gh_binary_bytes"]:
        raise GhCliInstallError("installed GitHub CLI binary byte count mismatch")
    if _sha256_file(binary_path) != lock["extracted_gh_binary_sha256"]:
        raise GhCliInstallError("installed GitHub CLI binary hash mismatch")
    try:
        binary_path.chmod(0o755)
    except OSError as exc:
        raise GhCliInstallError("installed GitHub CLI mode could not be repaired") from exc


Downloader = Callable[[str, Path, int], None]


def install_pinned_gh(
    lock_path: Path,
    prefix: Path,
    *,
    downloader: Downloader | None = None,
) -> Path:
    """Install or idempotently verify the exact pinned `gh`, returning `bin/`."""

    lock = load_gh_cli_lock(lock_path)
    _verify_runtime_platform()
    binary_path = resolve_installed_binary(lock, prefix)
    bin_directory = binary_path.parent
    absolute_prefix = bin_directory.parent

    for directory, label in (
        (absolute_prefix, "GitHub CLI prefix"),
        (bin_directory, "GitHub CLI bin directory"),
    ):
        if directory.is_symlink():
            raise GhCliInstallError(f"{label} must not be a symbolic link")
        if directory.exists() and not directory.is_dir():
            raise GhCliInstallError(f"{label} must be a directory")
    if os.path.lexists(binary_path):
        _repair_executable_mode_for_matching_bytes(lock, binary_path)
        verify_installed_gh(lock, binary_path)
        return bin_directory

    parent = absolute_prefix.parent
    parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink() or not parent.is_dir():
        raise GhCliInstallError("GitHub CLI prefix parent is not a safe directory")
    fetch = downloader or _download_archive
    with tempfile.TemporaryDirectory(prefix=".trimem-gh-stage-", dir=parent) as raw_stage:
        stage = Path(raw_stage)
        archive_path = stage / lock["archive_filename"]
        staged_binary = stage / "gh"
        fetch(lock["archive_url"], archive_path, lock["observed_archive_bytes"])
        _assert_regular_file(archive_path, "downloaded GitHub CLI archive")
        if archive_path.stat().st_size != lock["observed_archive_bytes"]:
            raise GhCliInstallError("GitHub CLI archive byte count mismatch")
        if _sha256_file(archive_path) != lock["archive_sha256"]:
            raise GhCliInstallError("GitHub CLI archive hash mismatch")
        _extract_locked_binary(archive_path, staged_binary, lock)
        _assert_regular_file(staged_binary, "staged GitHub CLI binary")
        if _sha256_file(staged_binary) != lock["extracted_gh_binary_sha256"]:
            raise GhCliInstallError("extracted GitHub CLI binary hash mismatch")
        staged_binary.chmod(0o755)
        verify_installed_gh(lock, staged_binary)

        absolute_prefix.mkdir(parents=True, exist_ok=True)
        if absolute_prefix.is_symlink() or not absolute_prefix.is_dir():
            raise GhCliInstallError("GitHub CLI prefix changed during install")
        bin_directory.mkdir(mode=0o755, exist_ok=True)
        if bin_directory.is_symlink() or not bin_directory.is_dir():
            raise GhCliInstallError("GitHub CLI bin directory changed during install")
        try:
            os.link(staged_binary, binary_path)
        except FileExistsError:
            verify_installed_gh(lock, binary_path)
        except OSError as exc:
            raise GhCliInstallError("GitHub CLI binary could not be installed atomically") from exc
    verify_installed_gh(lock, binary_path)
    return bin_directory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    try:
        bin_directory = install_pinned_gh(args.lock, args.prefix)
    except Exception:
        print("pinned GitHub CLI installation failed closed", file=sys.stderr)
        return 1
    print(bin_directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
