from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_benchmark_run as benchmark_run  # noqa: E402
import trimem_harness_lock as harness_lock  # noqa: E402


EXPECTED_DEPENDENCIES = [
    {
        "benchmark_ids": ["swebench_verified"],
        "bytes": 2_131,
        "git_blob_sha256": (
            "a28097ccddef94f8a22d9ca4037ab066ac37462e95547f3136bf4059109aaac9"
        ),
        "path": "pyproject.toml",
        "repository": "https://github.com/SWE-bench/SWE-bench",
        "revision": "7a21e05772954cc81471ae19d56f436cecf43c54",
    },
    {
        "benchmark_ids": ["swebench_verified"],
        "bytes": 861_799,
        "git_blob_sha256": (
            "66ada0bfcc5177def68d5307e0c6fdaf5b91b5659258faa1fb2cc4862809d39e"
        ),
        "path": "uv.lock",
        "repository": "https://github.com/SWE-bench/SWE-bench",
        "revision": "7a21e05772954cc81471ae19d56f436cecf43c54",
    },
    {
        "benchmark_ids": [
            "multi_swe_bench_mini",
            "multi_swe_bench_flash",
        ],
        "bytes": 921,
        "git_blob_sha256": (
            "7a19f0081d9feee2fa2262e215080b4daa91c452db36d6c2ddf54dfcfb971c40"
        ),
        "path": "setup.py",
        "repository": "https://github.com/multi-swe-bench/multi-swe-bench",
        "revision": "24f493f8a103e72312ded4f6b9c89f081d69cb09",
    },
]
EXPECTED_PROJECTION_SHA256 = (
    "042c8cfb2478f5515541a387575c7124312095df7e82d4e30798c7d82926df39"
)


def _git(
    repository: Path,
    *arguments: str,
    input_bytes: bytes | None = None,
) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        input=input_bytes,
        capture_output=True,
        text=False,
        check=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def git_blob_fixture(tmp_path: Path) -> dict[str, Any]:
    """Create regular, tree, and symlink entries without OS symlink support."""

    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.name", "TriMem Harness Test")
    _git(repository, "config", "user.email", "trimem@example.invalid")
    # Keep fixture object bytes invariant even on a Windows host whose global
    # Git configuration enables checkout conversion.
    _git(repository, "config", "core.autocrlf", "false")

    lf_blob = b"alpha\nbeta\n"
    second_blob = b"[tool]\nportable = true\n"
    dependency = repository / "dependency.txt"
    dependency.write_bytes(lf_blob)
    (repository / "other.lock").write_bytes(second_blob)
    (repository / "nested").mkdir()
    (repository / "nested" / "child.txt").write_bytes(b"child\n")
    _git(repository, "add", "dependency.txt", "other.lock", "nested/child.txt")
    _git(repository, "commit", "-m", "regular dependency blobs")

    symlink_blob = _git(
        repository,
        "hash-object",
        "-w",
        "--stdin",
        input_bytes=b"dependency.txt",
    ).decode("ascii")
    _git(
        repository,
        "update-index",
        "--add",
        "--cacheinfo",
        f"120000,{symlink_blob},dependency-link",
    )
    _git(repository, "commit", "-m", "add a Git symlink entry")
    commit = _git(repository, "rev-parse", "HEAD").decode("ascii")

    # Deliberately diverge from the committed LF bytes. The lock reader must
    # never observe these platform-shaped working-tree bytes.
    dependency.write_bytes(lf_blob.replace(b"\n", b"\r\n"))
    return {
        "commit": commit,
        "dependency": dependency,
        "lf_blob": lf_blob,
        "repository": repository,
        "second_blob": second_blob,
    }


def test_read_pinned_git_blob_uses_exact_blob_not_crlf_working_tree(
    git_blob_fixture: dict[str, Any],
) -> None:
    repository = git_blob_fixture["repository"]
    commit = git_blob_fixture["commit"]
    expected = git_blob_fixture["lf_blob"]

    assert git_blob_fixture["dependency"].read_bytes() == b"alpha\r\nbeta\r\n"
    observed = harness_lock.read_pinned_git_blob(
        repository, commit, "dependency.txt"
    )

    assert observed == expected
    assert observed != git_blob_fixture["dependency"].read_bytes()
    assert hashlib.sha256(observed).hexdigest() == hashlib.sha256(expected).hexdigest()


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/absolute.txt",
        "../escape.txt",
        "nested/../dependency.txt",
        "./dependency.txt",
        "nested//child.txt",
        "-git-option",
        "drive:C/path.txt",
        "windows\\path.txt",
        "control\ncharacter.txt",
    ],
)
def test_read_pinned_git_blob_rejects_unsafe_paths(
    git_blob_fixture: dict[str, Any], path: str
) -> None:
    with pytest.raises(harness_lock.HarnessLockError):
        harness_lock.read_pinned_git_blob(
            git_blob_fixture["repository"], git_blob_fixture["commit"], path
        )


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("missing.lock", "one tree entry"),
        ("nested", "regular-file blob"),
        ("dependency-link", "regular-file blob"),
    ],
)
def test_read_pinned_git_blob_rejects_missing_tree_and_symlink_entries(
    git_blob_fixture: dict[str, Any], path: str, message: str
) -> None:
    with pytest.raises(harness_lock.HarnessLockError, match=message):
        harness_lock.read_pinned_git_blob(
            git_blob_fixture["repository"], git_blob_fixture["commit"], path
        )


def test_read_pinned_git_blob_rejects_invalid_or_noncommit_revisions(
    git_blob_fixture: dict[str, Any],
) -> None:
    repository = git_blob_fixture["repository"]
    commit = git_blob_fixture["commit"]
    blob_id = _git(repository, "rev-parse", f"{commit}:dependency.txt").decode("ascii")
    tree_id = _git(repository, "rev-parse", f"{commit}^{{tree}}").decode("ascii")
    invalid_revisions = (
        commit[:12],
        "A" + commit[1:],
        "g" * 40,
        "f" * 40,
        blob_id,
        tree_id,
    )

    for revision in invalid_revisions:
        with pytest.raises(harness_lock.HarnessLockError):
            harness_lock.read_pinned_git_blob(
                repository, revision, "dependency.txt"
            )


def test_read_pinned_git_blob_rejects_missing_or_nondirectory_repository(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    regular_file = tmp_path / "not-a-repository"
    regular_file.write_bytes(b"not Git")

    for repository in (missing, regular_file):
        with pytest.raises(harness_lock.HarnessLockError):
            harness_lock.read_pinned_git_blob(
                repository, "a" * 40, "dependency.txt"
            )


def test_generic_dependency_validator_reads_every_configured_blob(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payloads = {
        "pyproject.toml": b"project\n",
        "locks/runtime.lock": b"runtime\n",
        "build/setup.cfg": b"setup\n",
        "package.json": b'{"private":true}\n',
    }
    calls: list[tuple[Path, str, str]] = []

    def fake_reader(repository: Path, commit: str, path: str) -> bytes:
        calls.append((repository, commit, path))
        return payloads[path]

    monkeypatch.setattr(harness_lock, "read_pinned_git_blob", fake_reader)
    revision = "b" * 40
    declarations = [
        {
            "bytes": len(raw),
            "git_blob_sha256": hashlib.sha256(raw).hexdigest(),
            "path": path,
        }
        for path, raw in payloads.items()
    ]

    observed = harness_lock.validate_dependency_declarations(
        tmp_path, revision, declarations
    )

    assert [row["path"] for row in observed] == list(payloads)
    assert calls == [(tmp_path, revision, path) for path in payloads]

    tampered = deepcopy(declarations)
    tampered[0]["bytes"] += 1
    with pytest.raises(harness_lock.HarnessLockError, match="hash mismatch"):
        harness_lock.validate_dependency_declarations(tmp_path, revision, tampered)


def test_generic_dependency_rows_reject_legacy_duplicate_and_malformed_locks() -> None:
    raw = b"generic lock\n"
    environment = {
        "harness_dependency_hash_basis": harness_lock.HASH_BASIS,
        "harness_source_environment": [
            {
                "benchmark_ids": ["generic_benchmark"],
                "checkout_key": "generic",
                "dependency_declarations": [
                    {
                        "bytes": len(raw),
                        "git_blob_sha256": hashlib.sha256(raw).hexdigest(),
                        "path": "arbitrary/dependency.lock",
                    }
                ],
                "repository": "https://github.com/example/generic-harness",
                "revision": "c" * 40,
            }
        ],
    }
    rows = harness_lock._dependency_rows(environment)
    assert rows[0]["dependency_declarations"][0]["path"] == (
        "arbitrary/dependency.lock"
    )

    legacy = deepcopy(environment)
    legacy["harness_source_environment"][0]["dependency_declaration_sha256"] = (
        "d" * 64
    )
    with pytest.raises(harness_lock.HarnessLockError, match="working-tree"):
        harness_lock._dependency_rows(legacy)

    duplicate = deepcopy(environment)
    duplicate["harness_source_environment"][0]["dependency_declarations"] *= 2
    with pytest.raises(harness_lock.HarnessLockError, match="duplicate"):
        harness_lock._dependency_rows(duplicate)

    malformed = deepcopy(environment)
    malformed["harness_source_environment"][0]["dependency_declarations"][0][
        "unexpected"
    ] = True
    with pytest.raises(harness_lock.HarnessLockError, match="shape"):
        harness_lock._dependency_rows(malformed)


def test_committed_environment_has_exact_three_git_blob_locks_and_projection() -> None:
    environment_path = ROOT / "configs/trimem_v1/benchmark_environment_lock.json"
    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    rows = harness_lock._dependency_rows(environment)
    observed = [
        {
            "benchmark_ids": row["benchmark_ids"],
            "bytes": declaration["bytes"],
            "git_blob_sha256": declaration["git_blob_sha256"],
            "path": declaration["path"],
            "repository": row["repository"],
            "revision": row["revision"],
        }
        for row in rows
        for declaration in row["dependency_declarations"]
    ]

    assert observed == EXPECTED_DEPENDENCIES
    assert environment["harness_dependency_lock"] == {
        "basis": harness_lock.HASH_BASIS,
        "dependency_count": 3,
        "portable_projection_sha256": EXPECTED_PROJECTION_SHA256,
    }
    assert harness_lock._validate_lock_projection(environment, rows) == (
        EXPECTED_PROJECTION_SHA256
    )
    assert all(not harness_lock.LEGACY_HASH_FIELDS.intersection(row) for row in rows)

    tampered = deepcopy(environment)
    tampered["harness_dependency_lock"]["dependency_count"] = 4
    with pytest.raises(harness_lock.HarnessLockError, match="projection mismatch"):
        harness_lock._validate_lock_projection(tampered, rows)


def test_benchmark_runner_imports_the_single_shared_prepare_harnesses() -> None:
    benchmark_path = ROOT / "scripts/trimem_benchmark_run.py"
    benchmark_tree = ast.parse(benchmark_path.read_text(encoding="utf-8"))
    shared_imports = [
        alias
        for node in ast.walk(benchmark_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "trimem_harness_lock"
        for alias in node.names
        if alias.name == "prepare_harnesses"
    ]
    local_definitions = [
        node
        for node in ast.walk(benchmark_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "prepare_harnesses"
    ]

    assert len(shared_imports) == 1
    assert local_definitions == []
    assert benchmark_run.prepare_harnesses is harness_lock.prepare_harnesses

    definitions: list[str] = []
    for script in (ROOT / "scripts").glob("trimem_*.py"):
        tree = ast.parse(script.read_text(encoding="utf-8"))
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "prepare_harnesses"
            for node in ast.walk(tree)
        ):
            definitions.append(script.relative_to(ROOT).as_posix())
    assert definitions == ["scripts/trimem_harness_lock.py"]

    source = benchmark_path.read_text(encoding="utf-8")
    assert "dependency_declaration_sha256" not in source
    assert "upstream_uv_lock_sha256" not in source


def test_full_and_blob_only_preparation_share_the_pinned_blob_contract(
    git_blob_fixture: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = git_blob_fixture["repository"]
    revision = git_blob_fixture["commit"]
    raw = git_blob_fixture["lf_blob"]
    row = {
        "benchmark_ids": ["fixture_benchmark"],
        "checkout_key": "fixture",
        "dependency_declarations": [
            {
                "bytes": len(raw),
                "git_blob_sha256": hashlib.sha256(raw).hexdigest(),
                "path": "dependency.txt",
            }
        ],
        "repository": repository.as_posix(),
        "revision": revision,
    }
    monkeypatch.setattr(harness_lock, "_load_lock_rows", lambda: ({}, [row]))

    object_root = tmp_path / "object-only"
    object_only = harness_lock.prepare_harness_blob_sources(object_root)
    assert object_only == {"fixture_benchmark": object_root / "fixture"}
    assert not (object_root / "fixture" / "dependency.txt").exists()
    assert harness_lock.read_pinned_git_blob(
        object_root / "fixture", revision, "dependency.txt"
    ) == raw

    full_root = tmp_path / "full"
    full = harness_lock.prepare_harnesses(full_root)
    assert full == {"fixture_benchmark": full_root / "fixture"}
    assert _git(full_root / "fixture", "rev-parse", "HEAD").decode() == revision
    assert _git(full_root / "fixture", "status", "--porcelain=v1") == b""
    assert harness_lock.read_pinned_git_blob(
        full_root / "fixture", revision, "dependency.txt"
    ) == raw


def test_blob_only_rehearsal_reports_zero_execution_and_no_worktree(
    git_blob_fixture: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = git_blob_fixture["repository"]
    revision = git_blob_fixture["commit"]
    raw = git_blob_fixture["lf_blob"]
    row = {
        "benchmark_ids": ["fixture_benchmark"],
        "checkout_key": "fixture",
        "dependency_declarations": [
            {
                "bytes": len(raw),
                "git_blob_sha256": hashlib.sha256(raw).hexdigest(),
                "path": "dependency.txt",
            }
        ],
        "repository": repository.as_posix(),
        "revision": revision,
    }
    projection = harness_lock._portable_projection([row])
    projection_sha256 = hashlib.sha256(harness_lock._canonical(projection)).hexdigest()
    environment = {
        "harness_dependency_lock": {
            "basis": harness_lock.HASH_BASIS,
            "dependency_count": 1,
            "portable_projection_sha256": projection_sha256,
        }
    }
    monkeypatch.setattr(
        harness_lock, "_load_lock_rows", lambda: (environment, [row])
    )
    monkeypatch.setattr(
        harness_lock,
        "prepare_harness_blob_sources",
        lambda _root: {"fixture_benchmark": repository},
    )

    report = harness_lock.build_rehearsal(
        tmp_path / "fresh-report-root", materialize_worktrees=False
    )

    assert report["status"] == "PASS"
    assert report["rehearsal_boundary"] == "CROSS_PLATFORM_GIT_BLOB_LOCK_ONLY"
    assert report["official_grader_viability"] == "NOT_YET_ESTABLISHED"
    assert report["dependencies"] == [
        {
            "benchmark_ids": ["fixture_benchmark"],
            "bytes": len(raw),
            "git_blob_sha256": hashlib.sha256(raw).hexdigest(),
            "path": "dependency.txt",
            "repository": repository.as_posix(),
            "revision": revision,
        }
    ]
    assert all(value == 0 for value in report["execution_counters"].values())
    assert report["harnesses"][0]["working_tree_materialized"] is False


def test_full_rehearsal_report_rechecks_head_cleanliness_and_working_observation(
    git_blob_fixture: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = git_blob_fixture["repository"]
    revision = git_blob_fixture["commit"]
    raw = git_blob_fixture["lf_blob"]
    _git(repository, "checkout", "--", "dependency.txt", "dependency-link")
    assert _git(repository, "status", "--porcelain=v1") == b""
    row = {
        "benchmark_ids": ["fixture_benchmark"],
        "checkout_key": "fixture",
        "dependency_declarations": [
            {
                "bytes": len(raw),
                "git_blob_sha256": hashlib.sha256(raw).hexdigest(),
                "path": "dependency.txt",
            }
        ],
        "repository": repository.as_posix(),
        "revision": revision,
    }
    projection = harness_lock._portable_projection([row])
    environment = {
        "harness_dependency_lock": {
            "basis": harness_lock.HASH_BASIS,
            "dependency_count": 1,
            "portable_projection_sha256": hashlib.sha256(
                harness_lock._canonical(projection)
            ).hexdigest(),
        }
    }
    monkeypatch.setattr(
        harness_lock, "_load_lock_rows", lambda: (environment, [row])
    )
    monkeypatch.setattr(
        harness_lock,
        "prepare_harnesses",
        lambda _root: {"fixture_benchmark": repository},
    )

    report = harness_lock.build_rehearsal(
        tmp_path / "fresh-full-root", materialize_worktrees=True
    )

    assert report["rehearsal_boundary"] == "EXACT_PRODUCTION_PREPARE_HARNESSES"
    assert report["harnesses"][0]["head"] == revision
    assert report["harnesses"][0]["clean"] is True
    assert report["harnesses"][0]["working_tree_materialized"] is True
    assert report["dependencies"][0]["working_tree_equals_git_blob"] is True
    assert report["dependencies"][0]["working_tree_bytes_observation"] == len(raw)
    assert all(value == 0 for value in report["execution_counters"].values())


def test_rehearsal_fails_if_evidence_reread_differs_from_lock(
    git_blob_fixture: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = git_blob_fixture["repository"]
    revision = git_blob_fixture["commit"]
    raw = git_blob_fixture["lf_blob"]
    row = {
        "benchmark_ids": ["fixture_benchmark"],
        "checkout_key": "fixture",
        "dependency_declarations": [
            {
                "bytes": len(raw),
                "git_blob_sha256": hashlib.sha256(raw).hexdigest(),
                "path": "dependency.txt",
            }
        ],
        "repository": repository.as_posix(),
        "revision": revision,
    }
    projection = harness_lock._portable_projection([row])
    environment = {
        "harness_dependency_lock": {
            "basis": harness_lock.HASH_BASIS,
            "dependency_count": 1,
            "portable_projection_sha256": hashlib.sha256(
                harness_lock._canonical(projection)
            ).hexdigest(),
        }
    }
    monkeypatch.setattr(
        harness_lock, "_load_lock_rows", lambda: (environment, [row])
    )
    monkeypatch.setattr(
        harness_lock,
        "prepare_harness_blob_sources",
        lambda _root: {"fixture_benchmark": repository},
    )
    monkeypatch.setattr(
        harness_lock, "read_pinned_git_blob", lambda *_args: b"tampered\n"
    )

    with pytest.raises(harness_lock.HarnessLockError, match="evidence blob"):
        harness_lock.build_rehearsal(
            tmp_path / "fresh-tamper-root", materialize_worktrees=False
        )


def test_cli_failure_still_writes_zero_counter_report(tmp_path: Path) -> None:
    existing_checkout_root = tmp_path / "already-exists"
    existing_checkout_root.mkdir()
    report_path = tmp_path / "failed-rehearsal.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/trimem_harness_lock.py"),
            "--checkout-root",
            str(existing_checkout_root),
            "--output",
            str(report_path),
            "--blob-only",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "FAIL_CLOSED"
    assert report["endpoint"] == harness_lock.REHEARSAL_FAILURE_ENDPOINT
    assert report["official_grader_viability"] == "NOT_YET_ESTABLISHED"
    assert all(value == 0 for value in report["execution_counters"].values())


def test_cross_platform_rehearsal_workflow_is_credential_free_and_pinned() -> None:
    workflow = (
        ROOT / ".github/workflows/ci-trimem-harness-lock.yml"
    ).read_text(encoding="utf-8")

    assert "runner: ubuntu-24.04" in workflow
    assert "core_autocrlf: input" in workflow
    assert "runner: windows-2025" in workflow
    assert 'core_autocrlf: "true"' in workflow
    assert "python_version: 3.11.10" in workflow
    assert "python_version: 3.11.9" in workflow
    assert "python-version: ${{ matrix.python_version }}" in workflow
    assert "rehearsal_arg: --blob-only" in workflow
    assert "scope: exact-linux-production-prep" in workflow
    assert "scope: windows-git-blob-portability" in workflow
    assert "python scripts/trimem_harness_lock.py" in workflow
    assert "--checkout-root \"${{ runner.temp }}/trimem-harness-lock-checkouts\"" in workflow
    assert "workflow_dispatch" not in workflow
    assert "if: always()" in workflow
    for forbidden in (
        "environment:",
        "secrets.",
        "OPENAI_API_KEY",
        "docker ",
        "trimem_grader_smoke.py",
        "pip install",
    ):
        assert forbidden not in workflow
    action_uses = [
        line.strip().removeprefix("uses: ")
        for line in workflow.splitlines()
        if line.strip().startswith("uses: ")
    ]
    assert len(action_uses) == 3
    assert all(re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", use) for use in action_uses)
