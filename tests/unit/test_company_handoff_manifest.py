"""Product handoff inventory must stay separate from research readiness seals."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _module():
    path = ROOT / "scripts/make_handoff_manifest.py"
    spec = importlib.util.spec_from_file_location("company_handoff_manifest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_company_hash_uses_only_git_tracked_files() -> None:
    module = _module()
    tracked = module._git_files("src")
    digest, count = module._tree_hash("src")
    assert count == len(tracked)
    assert len(digest) == 64
    assert all(not module._is_forbidden_tracked(path) for path in tracked)


def test_generated_artifact_paths_are_rejected() -> None:
    module = _module()
    for path in (
        "src/pkg/__pycache__/mod.cpython-311.pyc",
        "src/pkg/mod.pyc",
        "src/pkg/mod.pyo",
        "src/pkg.egg-info/PKG-INFO",
        "src/build/lib/pkg.py",
        "dist/package.whl",
    ):
        assert module._is_forbidden_tracked(path)


def test_product_manifest_is_not_trimem_research_state() -> None:
    manifest = json.loads(
        (ROOT / "COMPANY_HANDOFF_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert manifest["manifest_scope"] == "PRODUCT_HANDOFF_ONLY_NOT_TRIMEM_RESEARCH_STATE"
    assert manifest["hash_basis"].startswith("git ls-files -z")
    assert manifest["trimem_research_state_authority"] == "artifacts/trimem_v1/freeze.json"
    assert manifest["manifest_hash"] == _module()._manifest_hash(manifest)

    status = (ROOT / "docs/STATUS.yaml").read_text(encoding="utf-8")
    assert "TRIMEM_V1_READY" not in status
    assert "MEMORY_TRANSFER_EFFICACY_NULL" in status
    assert "production_certification_status: NOT_CLAIMED" in status


def test_r23_branch_cannot_rewrite_product_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    monkeypatch.setattr(module, "_branch", lambda: "codex/r23-research")
    monkeypatch.setattr(
        module,
        "build",
        lambda: pytest.fail("R23 refusal must happen before manifest construction"),
    )
    monkeypatch.setattr(module.sys, "argv", ["make_handoff_manifest.py"])
    assert module.main() == 2
