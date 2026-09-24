from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import trimem_install_pinned_gh as pinned_gh  # noqa: E402
import trimem_verify_gh_lock as verify_gh_lock  # noqa: E402


LOCK_PATH = ROOT / "configs/trimem_v1/gh_cli_lock.json"
EXPECTED_ARCHIVE_SHA256 = (
    "a2c9b8497e1f85b1ad0dfcb78b5a622e098801b8e461e459e88e1ee12f018112"
)
EXPECTED_BINARY_SHA256 = (
    "141507c337e8b202ad398550c3b73d72f5af92e86f71665214538a81efd4c409"
)
EXPECTED_CHECKSUM_FILE_SHA256 = (
    "61905c69ec8660f310814ec98395cdd0c2d07aabf024c597ec45813984a02334"
)
EXPECTED_VERSION_LINE = "gh version 2.97.0 (2026-07-31)"
EXPECTED_WINDOWS_ARCHIVE_SHA256 = (
    "35d7fe05c4dd1411ffda1e73dfc7c6f44b75c936ca51fa6595c657fdc0350cec"
)
EXPECTED_WINDOWS_BINARY_SHA256 = (
    "e2efa10a5d2ce93cac9bc4b676932b62947c0967c01c8f2c3a9cb4437ad358d3"
)
ARCHIVE_ROOT = "gh_2.97.0_linux_amd64"
BINARY_PATH = f"{ARCHIVE_ROOT}/bin/gh"


def _tar_member(name: str, payload: bytes, *, mode: int = 0o644) -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(name)
    member.mode = mode
    member.size = len(payload)
    member.mtime = 0
    member.uid = 0
    member.gid = 0
    member.uname = ""
    member.gname = ""
    return member, payload


def _write_archive(
    path: Path,
    binary: bytes,
    *,
    extra_members: list[tuple[tarfile.TarInfo, bytes | None]] | None = None,
) -> None:
    members: list[tuple[tarfile.TarInfo, bytes | None]] = [
        _tar_member(f"{ARCHIVE_ROOT}/LICENSE", b"fixture license\n"),
        _tar_member(BINARY_PATH, binary, mode=0o755),
    ]
    members.extend(extra_members or [])
    with tarfile.open(path, mode="w:gz") as archive:
        for member, payload in members:
            archive.addfile(member, io.BytesIO(payload) if payload is not None else None)


def _write_fixture_lock(lock_path: Path, archive_path: Path, binary: bytes) -> dict[str, Any]:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    archive_raw = archive_path.read_bytes()
    archive_sha256 = hashlib.sha256(archive_raw).hexdigest()
    lock["archive_sha256"] = archive_sha256
    lock["archive_sha256_source_line"] = (
        f"{archive_sha256}  {lock['archive_filename']}"
    )
    lock["extracted_gh_binary_sha256"] = hashlib.sha256(binary).hexdigest()
    lock["observed_archive_bytes"] = len(archive_raw)
    lock["observed_gh_binary_bytes"] = len(binary)
    lock_path.write_text(
        json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return lock


@pytest.fixture
def install_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    binary = b"#!/bin/sh\nprintf 'gh version 2.97.0 (2026-07-31)\\n'\n"
    archive_path = tmp_path / "fixture.tar.gz"
    _write_archive(archive_path, binary)
    lock_path = tmp_path / "gh-lock.json"
    lock = _write_fixture_lock(lock_path, archive_path, binary)

    monkeypatch.setattr(pinned_gh, "_verify_runtime_platform", lambda: None)
    for secret_name in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "TRIMEM_EVIDENCE_PASSPHRASE",
        "TRIMEM_EXEC_APPROVAL_B64",
    ):
        monkeypatch.setenv(secret_name, f"canary-{secret_name.lower()}")

    def fake_version(
        argv: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[bytes]:
        assert argv[1:] == ["--version"]
        assert kwargs["text"] is False
        for secret_name in (
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "OPENAI_API_KEY",
            "TRIMEM_EVIDENCE_PASSPHRASE",
            "TRIMEM_EXEC_APPROVAL_B64",
        ):
            assert secret_name not in kwargs["env"]
        return subprocess.CompletedProcess(
            argv, 0, (EXPECTED_VERSION_LINE + "\nhttps://github.com/cli/cli\n").encode(), b""
        )

    monkeypatch.setattr(pinned_gh.subprocess, "run", fake_version)

    downloads: list[str] = []

    def downloader(url: str, destination: Path, expected_bytes: int) -> None:
        assert url == lock["archive_url"]
        assert expected_bytes == archive_path.stat().st_size
        downloads.append(url)
        shutil.copyfile(archive_path, destination)

    return {
        "archive": archive_path,
        "binary": binary,
        "downloads": downloads,
        "downloader": downloader,
        "lock": lock,
        "lock_path": lock_path,
        "prefix": tmp_path / "install-prefix",
    }


def test_committed_lock_is_the_exact_official_github_cli_release() -> None:
    lock = pinned_gh.load_gh_cli_lock(LOCK_PATH)

    assert lock["schema"] == "trimem/gh-cli-lock/1.1"
    assert lock["version"] == "2.97.0"
    assert lock["release_tag"] == "v2.97.0"
    assert lock["platform"] == "linux_amd64"
    assert lock["archive_sha256"] == EXPECTED_ARCHIVE_SHA256
    assert lock["extracted_gh_binary_sha256"] == EXPECTED_BINARY_SHA256
    assert lock["checksum_file_sha256"] == EXPECTED_CHECKSUM_FILE_SHA256
    assert lock["expected_first_version_line"] == EXPECTED_VERSION_LINE
    assert lock["observed_archive_bytes"] == 14_770_812
    assert lock["observed_checksum_file_bytes"] == 1_950
    assert lock["observed_gh_binary_bytes"] == 40_992_930
    assert lock["archive_sha256_source_line"] == (
        f"{EXPECTED_ARCHIVE_SHA256}  gh_2.97.0_linux_amd64.tar.gz"
    )
    assert lock["install_layout"]["archive_binary_path"] == BINARY_PATH
    assert lock["archive_url"].startswith(
        "https://github.com/cli/cli/releases/download/v2.97.0/"
    )
    assert lock["checksum_file_url"].startswith(
        "https://github.com/cli/cli/releases/download/v2.97.0/"
    )
    assert "latest" not in lock["archive_url"]
    windows = lock["windows_observer"]
    assert windows == {
        "archive_binary_path": "bin/gh.exe",
        "archive_filename": "gh_2.97.0_windows_amd64.zip",
        "archive_sha256": EXPECTED_WINDOWS_ARCHIVE_SHA256,
        "archive_sha256_source_line": (
            f"{EXPECTED_WINDOWS_ARCHIVE_SHA256}  gh_2.97.0_windows_amd64.zip"
        ),
        "archive_url": (
            "https://github.com/cli/cli/releases/download/v2.97.0/"
            "gh_2.97.0_windows_amd64.zip"
        ),
        "extracted_gh_binary_sha256": EXPECTED_WINDOWS_BINARY_SHA256,
        "hash_source": {
            "archive_sha256": "OFFICIAL_GITHUB_CLI_RELEASE_CHECKSUM_FILE",
            "extracted_gh_binary_sha256": (
                "INDEPENDENT_SHA256_OF_EXACT_REGULAR_FILE_PAYLOAD_"
                "AFTER_ARCHIVE_VERIFICATION"
            ),
        },
        "observed_archive_bytes": 14_938_517,
        "observed_gh_binary_bytes": 41_775_416,
        "platform": "windows_amd64",
    }


def _windows_observer_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], Path]:
    payload = b"exact pinned Windows gh executable fixture"
    # ``shutil.which("gh")`` returns ``gh.EXE`` on the actual Windows writer.
    # Windows filenames are case-insensitive, so preserve that real spelling
    # in the regression while still requiring the exact gh.exe basename.
    binary = tmp_path / "gh.EXE"
    binary.write_bytes(payload)
    lock = deepcopy(pinned_gh.load_gh_cli_lock(LOCK_PATH))
    lock["windows_observer"]["observed_gh_binary_bytes"] = len(payload)
    lock["windows_observer"]["extracted_gh_binary_sha256"] = hashlib.sha256(
        payload
    ).hexdigest()
    monkeypatch.setattr(pinned_gh.platform, "system", lambda: "Windows")
    monkeypatch.setattr(pinned_gh.platform, "machine", lambda: "AMD64")
    for secret_name in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "TRIMEM_EVIDENCE_PASSPHRASE",
        "TRIMEM_EXEC_APPROVAL_B64",
    ):
        monkeypatch.setenv(secret_name, f"canary-{secret_name.lower()}")
    return lock, binary


def test_windows_observer_requires_exact_locked_bytes_and_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock, binary = _windows_observer_fixture(tmp_path, monkeypatch)

    def fake_version(
        argv: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[bytes]:
        assert argv == [str(binary), "--version"]
        assert kwargs["text"] is False
        for secret_name in (
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "OPENAI_API_KEY",
            "TRIMEM_EVIDENCE_PASSPHRASE",
            "TRIMEM_EXEC_APPROVAL_B64",
        ):
            assert secret_name not in kwargs["env"]
        return subprocess.CompletedProcess(
            argv, 0, (EXPECTED_VERSION_LINE + "\n").encode(), b""
        )

    monkeypatch.setattr(pinned_gh.subprocess, "run", fake_version)
    observed = pinned_gh.verify_observer_gh(lock, binary)

    assert observed == {
        "binary_sha256": lock["windows_observer"]["extracted_gh_binary_sha256"],
        "first_version_line": EXPECTED_VERSION_LINE,
        "observer_platform": "windows_amd64",
        "status": "PASS",
        "version": "2.97.0",
    }


def test_windows_observer_rejects_same_size_wrong_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock, binary = _windows_observer_fixture(tmp_path, monkeypatch)
    lock["windows_observer"]["extracted_gh_binary_sha256"] = "0" * 64
    monkeypatch.setattr(
        pinned_gh.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("wrong bytes were executed"),
    )

    with pytest.raises(pinned_gh.GhCliInstallError, match="binary hash mismatch"):
        pinned_gh.verify_observer_gh(lock, binary)


def test_windows_observer_rejects_wrong_version_and_noncanonical_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock, binary = _windows_observer_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        pinned_gh.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(
            argv, 0, b"gh version 2.96.0 (2026-07-15)\n", b""
        ),
    )
    with pytest.raises(pinned_gh.GhCliInstallError, match="first version line mismatch"):
        pinned_gh.verify_observer_gh(lock, binary)

    renamed = tmp_path / "github-cli.exe"
    renamed.write_bytes(binary.read_bytes())
    with pytest.raises(pinned_gh.GhCliInstallError, match="absolute gh.exe path"):
        pinned_gh.verify_observer_gh(lock, renamed)


def test_observer_dispatch_rejects_unsupported_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = pinned_gh.load_gh_cli_lock(LOCK_PATH)
    binary = tmp_path / "gh"
    binary.write_bytes(b"untrusted")
    monkeypatch.setattr(pinned_gh.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(pinned_gh.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        pinned_gh.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("unsupported binary was executed"),
    )

    with pytest.raises(pinned_gh.GhCliInstallError, match="platform is unsupported"):
        pinned_gh.verify_observer_gh(lock, binary)


def test_linux_observer_dispatch_preserves_the_linux_binary_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = pinned_gh.load_gh_cli_lock(LOCK_PATH)
    binary = tmp_path / "gh"
    observed: list[tuple[dict[str, Any], Path]] = []
    monkeypatch.setattr(pinned_gh.platform, "system", lambda: "Linux")
    monkeypatch.setattr(pinned_gh.platform, "machine", lambda: "x86_64")

    def fake_verify(
        passed_lock: dict[str, Any], passed_binary: Path
    ) -> dict[str, Any]:
        observed.append((passed_lock, passed_binary))
        return {"status": "PASS", "version": "2.97.0"}

    monkeypatch.setattr(pinned_gh, "verify_installed_gh", fake_verify)

    assert pinned_gh.verify_observer_gh(lock, binary) == {
        "observer_platform": "linux_amd64",
        "status": "PASS",
        "version": "2.97.0",
    }
    assert observed == [(lock, binary)]


def test_missing_gh_is_repaired_and_only_the_locked_binary_is_extracted(
    install_fixture: dict[str, Any],
) -> None:
    bin_directory = pinned_gh.install_pinned_gh(
        install_fixture["lock_path"],
        install_fixture["prefix"],
        downloader=install_fixture["downloader"],
    )

    binary_path = bin_directory / "gh"
    assert bin_directory == install_fixture["prefix"] / "bin"
    assert binary_path.read_bytes() == install_fixture["binary"]
    assert sorted(
        path.relative_to(install_fixture["prefix"]).as_posix()
        for path in install_fixture["prefix"].rglob("*")
        if path.is_file()
    ) == ["bin/gh"]
    assert install_fixture["downloads"] == [install_fixture["lock"]["archive_url"]]


def test_install_is_idempotent_when_existing_bytes_match(
    install_fixture: dict[str, Any],
) -> None:
    first = pinned_gh.install_pinned_gh(
        install_fixture["lock_path"],
        install_fixture["prefix"],
        downloader=install_fixture["downloader"],
    )
    first_stat = (first / "gh").stat()

    def must_not_download(*_args: Any) -> None:
        raise AssertionError("idempotent install downloaded the archive again")

    second = pinned_gh.install_pinned_gh(
        install_fixture["lock_path"],
        install_fixture["prefix"],
        downloader=must_not_download,
    )
    second_stat = (second / "gh").stat()

    assert second == first
    assert second_stat.st_ino == first_stat.st_ino
    assert second_stat.st_mtime_ns == first_stat.st_mtime_ns
    assert install_fixture["downloads"] == [install_fixture["lock"]["archive_url"]]


def test_wrong_archive_hash_is_rejected(install_fixture: dict[str, Any]) -> None:
    lock = deepcopy(install_fixture["lock"])
    lock["archive_sha256"] = "0" * 64
    lock["archive_sha256_source_line"] = (
        f"{'0' * 64}  {lock['archive_filename']}"
    )
    install_fixture["lock_path"].write_text(
        json.dumps(lock), encoding="utf-8", newline="\n"
    )

    with pytest.raises(pinned_gh.GhCliInstallError, match="archive hash mismatch"):
        pinned_gh.install_pinned_gh(
            install_fixture["lock_path"],
            install_fixture["prefix"],
            downloader=install_fixture["downloader"],
        )
    assert not (install_fixture["prefix"] / "bin" / "gh").exists()


def test_wrong_binary_hash_is_rejected(install_fixture: dict[str, Any]) -> None:
    lock = deepcopy(install_fixture["lock"])
    lock["extracted_gh_binary_sha256"] = "0" * 64
    install_fixture["lock_path"].write_text(
        json.dumps(lock), encoding="utf-8", newline="\n"
    )

    with pytest.raises(pinned_gh.GhCliInstallError, match="binary hash mismatch"):
        pinned_gh.install_pinned_gh(
            install_fixture["lock_path"],
            install_fixture["prefix"],
            downloader=install_fixture["downloader"],
        )
    assert not (install_fixture["prefix"] / "bin" / "gh").exists()


def test_wrong_first_version_line_is_rejected(
    install_fixture: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pinned_gh.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(
            argv, 0, b"gh version 2.96.0 (2026-07-15)\n", b""
        ),
    )

    with pytest.raises(pinned_gh.GhCliInstallError, match="first version line mismatch"):
        pinned_gh.install_pinned_gh(
            install_fixture["lock_path"],
            install_fixture["prefix"],
            downloader=install_fixture["downloader"],
        )
    assert not (install_fixture["prefix"] / "bin" / "gh").exists()


def test_archive_path_traversal_is_rejected(
    install_fixture: dict[str, Any], tmp_path: Path
) -> None:
    traversal = _tar_member(f"{ARCHIVE_ROOT}/../escaped", b"escape\n")
    _write_archive(
        install_fixture["archive"],
        install_fixture["binary"],
        extra_members=[traversal],
    )
    install_fixture["lock"] = _write_fixture_lock(
        install_fixture["lock_path"],
        install_fixture["archive"],
        install_fixture["binary"],
    )

    with pytest.raises(pinned_gh.GhCliInstallError, match="canonical and relative"):
        pinned_gh.install_pinned_gh(
            install_fixture["lock_path"],
            install_fixture["prefix"],
            downloader=install_fixture["downloader"],
        )
    assert not (tmp_path / "escaped").exists()


def test_archive_links_and_unexpected_binary_paths_are_rejected(
    install_fixture: dict[str, Any],
) -> None:
    link = tarfile.TarInfo(f"{ARCHIVE_ROOT}/share/gh-link")
    link.type = tarfile.SYMTYPE
    link.linkname = BINARY_PATH
    link.mode = 0o777
    _write_archive(
        install_fixture["archive"],
        install_fixture["binary"],
        extra_members=[(link, None)],
    )
    install_fixture["lock"] = _write_fixture_lock(
        install_fixture["lock_path"],
        install_fixture["archive"],
        install_fixture["binary"],
    )
    with pytest.raises(pinned_gh.GhCliInstallError, match="link or non-regular"):
        pinned_gh.install_pinned_gh(
            install_fixture["lock_path"],
            install_fixture["prefix"],
            downloader=install_fixture["downloader"],
        )

    unexpected = _tar_member(f"{ARCHIVE_ROOT}/bin/helper", b"unexpected\n", mode=0o755)
    _write_archive(
        install_fixture["archive"],
        install_fixture["binary"],
        extra_members=[unexpected],
    )
    install_fixture["lock"] = _write_fixture_lock(
        install_fixture["lock_path"],
        install_fixture["archive"],
        install_fixture["binary"],
    )
    with pytest.raises(pinned_gh.GhCliInstallError, match="unexpected binary path"):
        pinned_gh.install_pinned_gh(
            install_fixture["lock_path"],
            install_fixture["prefix"],
            downloader=install_fixture["downloader"],
        )


def test_preexisting_mismatched_binary_is_rejected_without_download(
    install_fixture: dict[str, Any],
) -> None:
    binary_path = install_fixture["prefix"] / "bin" / "gh"
    binary_path.parent.mkdir(parents=True)
    binary_path.write_bytes(b"not the locked gh")

    def must_not_download(*_args: Any) -> None:
        raise AssertionError("mismatched pre-existing bytes triggered a download")

    with pytest.raises(
        pinned_gh.GhCliInstallError, match="binary (byte count|hash) mismatch"
    ):
        pinned_gh.install_pinned_gh(
            install_fixture["lock_path"],
            install_fixture["prefix"],
            downloader=must_not_download,
        )


def test_thin_verifier_uses_the_shared_lock_and_prefix_binary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = {"version": "2.97.0"}
    expected_binary = tmp_path / "bin" / "gh"
    observed: list[tuple[dict[str, Any], Path]] = []
    monkeypatch.setattr(sys, "argv", ["trimem_verify_gh_lock.py", "--prefix", str(tmp_path)])
    monkeypatch.setattr(verify_gh_lock, "load_gh_cli_lock", lambda _path: lock)
    monkeypatch.setattr(
        verify_gh_lock,
        "resolve_installed_binary",
        lambda passed_lock, prefix: expected_binary,
    )

    def fake_verify(passed_lock: dict[str, Any], binary: Path) -> dict[str, Any]:
        observed.append((passed_lock, binary))
        return {"status": "PASS", "version": "2.97.0"}

    monkeypatch.setattr(verify_gh_lock, "verify_installed_gh", fake_verify)

    assert verify_gh_lock.main() == 0
    assert observed == [(lock, expected_binary)]
    assert json.loads(capsys.readouterr().out) == {
        "status": "PASS",
        "version": "2.97.0",
    }
