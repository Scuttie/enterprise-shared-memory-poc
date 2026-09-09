from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_compiled_prefix_alias as alias_contract  # noqa: E402


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path: Path) -> dict[str, object]:
    if os.name != "posix":
        pytest.skip("compiled-prefix alias contract is POSIX-only")
    opt = tmp_path / "opt"
    target = opt / "trimem-runner-cache/work-ci/_tool"
    prefix_relative = Path("Python/3.11.10/x64")
    prefix = target / prefix_relative
    python = prefix / "bin/python3.11"
    libpython = prefix / "lib/libpython3.11.so.1.0"
    python.parent.mkdir(parents=True)
    libpython.parent.mkdir(parents=True)
    python_raw = b"frozen-python\n"
    libpython_raw = b"frozen-libpython\n"
    python.write_bytes(python_raw)
    libpython.write_bytes(libpython_raw)
    directories = {opt, target, prefix, python.parent, libpython.parent}
    for leaf in list(directories):
        directories.update(
            parent for parent in leaf.parents if parent == opt or opt in parent.parents
        )
    for directory in directories:
        directory.chmod(0o755)
    python.chmod(0o755)
    libpython.chmod(0o755)
    alias = opt / "hostedtoolcache"
    alias.symlink_to(target, target_is_directory=True)
    return {
        "alias": alias,
        "target": target,
        "prefix_relative": prefix_relative,
        "python": python,
        "python_hash": _sha256(python_raw),
        "libpython": libpython,
        "libpython_hash": _sha256(libpython_raw),
    }


def _model_root_owned_secure_metadata(
    monkeypatch: pytest.MonkeyPatch,
    *,
    alias: Path,
    secure_through: Path,
) -> None:
    original = alias_contract._path_lstat

    def wrapped(path: Path) -> object:
        metadata = original(path)
        # Unit-test temp roots commonly live below sticky /tmp.  Model the
        # frozen /opt boundary while preserving each target mutation below it.
        if path == alias:
            return SimpleNamespace(st_mode=metadata.st_mode, st_uid=0)
        if (
            path == Path(path.anchor)
            or path in secure_through.parents
            or path == secure_through
        ):
            return SimpleNamespace(
                st_mode=(metadata.st_mode & ~0o022),
                st_uid=0,
            )
        return metadata

    monkeypatch.setattr(alias_contract, "_path_lstat", wrapped)


def _validate(fixture: dict[str, object]) -> dict[str, object]:
    return alias_contract.validate_compiled_prefix_alias(
        alias_path=fixture["alias"],
        expected_target=fixture["target"],
        python_prefix_relative=fixture["prefix_relative"],
        expected_python_sha256=str(fixture["python_hash"]),
        expected_libpython_sha256=str(fixture["libpython_hash"]),
    )


def test_exact_single_hop_alias_returns_canonical_identity_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    _model_root_owned_secure_metadata(
        monkeypatch,
        alias=fixture["alias"],
        secure_through=Path(fixture["alias"]).parent,
    )

    evidence = _validate(fixture)

    assert evidence["schema"] == "trimem/compiled-prefix-alias/1.0"
    assert evidence["status"] == "PASS"
    assert evidence["alias_uid"] == 0
    assert evidence["expected_lexical_target"] == str(fixture["target"])
    assert evidence["observed_lexical_target"] == str(fixture["target"])
    assert evidence["resolved_target"] == str(fixture["target"])
    assert evidence["python_binary_realpath"] == str(fixture["python"])
    assert evidence["python_binary_sha256"] == fixture["python_hash"]
    assert evidence["libpython_realpath"] == str(fixture["libpython"])
    assert evidence["libpython_sha256"] == fixture["libpython_hash"]
    assert evidence["libdir_mode"] == "0755"
    assert alias_contract.canonical_bytes(evidence) == json.dumps(
        evidence,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def test_missing_alias_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    Path(fixture["alias"]).unlink()
    _model_root_owned_secure_metadata(
        monkeypatch,
        alias=fixture["alias"],
        secure_through=Path(fixture["alias"]).parent,
    )

    with pytest.raises(alias_contract.CompiledPrefixAliasError, match="does not exist"):
        _validate(fixture)


def test_wrong_lexical_target_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    alias = Path(fixture["alias"])
    alias.unlink()
    wrong = alias.parent / "wrong-target"
    wrong.mkdir()
    wrong.chmod(0o755)
    alias.symlink_to(wrong, target_is_directory=True)
    _model_root_owned_secure_metadata(
        monkeypatch, alias=alias, secure_through=alias.parent
    )

    with pytest.raises(alias_contract.CompiledPrefixAliasError, match="lexical target"):
        _validate(fixture)


def test_multi_hop_expected_target_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    alias = Path(fixture["alias"])
    original_target = Path(fixture["target"])
    indirect_target = alias.parent / "indirect-target"
    original_target.rename(indirect_target)
    original_target.symlink_to(indirect_target, target_is_directory=True)
    _model_root_owned_secure_metadata(
        monkeypatch, alias=alias, secure_through=alias.parent
    )

    with pytest.raises(
        alias_contract.CompiledPrefixAliasError, match="indirect symlink"
    ):
        _validate(fixture)


def test_non_root_owned_alias_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    alias = Path(fixture["alias"])
    _model_root_owned_secure_metadata(
        monkeypatch, alias=alias, secure_through=alias.parent
    )
    secured_reader = alias_contract._path_lstat

    def non_root_alias(path: Path) -> object:
        metadata = secured_reader(path)
        if path == alias:
            return SimpleNamespace(st_mode=metadata.st_mode, st_uid=1000)
        return metadata

    monkeypatch.setattr(alias_contract, "_path_lstat", non_root_alias)

    with pytest.raises(alias_contract.CompiledPrefixAliasError, match="not root-owned"):
        _validate(fixture)


def test_writable_target_component_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    alias = Path(fixture["alias"])
    writable = Path(fixture["target"]) / "Python"
    writable.chmod(0o775)
    _model_root_owned_secure_metadata(
        monkeypatch, alias=alias, secure_through=alias.parent
    )

    with pytest.raises(
        alias_contract.CompiledPrefixAliasError, match="group/world writable"
    ):
        _validate(fixture)


def test_libpython_hash_mismatch_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    alias = Path(fixture["alias"])
    _model_root_owned_secure_metadata(
        monkeypatch, alias=alias, secure_through=alias.parent
    )
    Path(fixture["libpython"]).write_bytes(b"different-libpython\n")

    with pytest.raises(alias_contract.CompiledPrefixAliasError, match="libpython hash"):
        _validate(fixture)


def test_cli_prints_one_canonical_json_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = {
        "schema": alias_contract.EVIDENCE_SCHEMA,
        "status": "PASS",
    }
    monkeypatch.setattr(
        alias_contract,
        "validate_compiled_prefix_alias",
        lambda **_kwargs: expected,
    )

    assert alias_contract.main(["--check"]) == 0
    assert capsys.readouterr().out == (
        '{"schema":"trimem/compiled-prefix-alias/1.0","status":"PASS"}\n'
    )


def test_cli_rejects_runtime_identity_overrides() -> None:
    with pytest.raises(SystemExit) as exc_info:
        alias_contract.main(
            ["--check", "--expected-target", "/tmp/attacker-controlled"]
        )

    assert exc_info.value.code == 2
