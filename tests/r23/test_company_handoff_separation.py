"""R23 research state must not contaminate the product handoff/status artifacts."""
from __future__ import annotations

import importlib.util
import json
import os


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _module():
    path = os.path.join(ROOT, "scripts", "make_handoff_manifest.py")
    spec = importlib.util.spec_from_file_location("handoff_manifest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seal_module():
    path = os.path.join(ROOT, "scripts", "r23_research_seal.py")
    spec = importlib.util.spec_from_file_location("r23_research_seal", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_company_hash_uses_only_git_tracked_files():
    module = _module()
    tracked = module._git_files("src")
    digest, count = module._tree_hash("src")
    assert count == len(tracked) == 113
    assert len(digest) == 64
    assert all(not module._is_forbidden_tracked(path) for path in tracked)


def test_generated_artifact_paths_are_rejected():
    module = _module()
    for path in (
        "src/pkg/__pycache__/mod.cpython-311.pyc",
        "src/pkg/mod.pyc",
        "src/pkg.egg-info/PKG-INFO",
        "src/build/lib/pkg.py",
        "dist/package.whl",
    ):
        assert module._is_forbidden_tracked(path)


def test_product_status_is_not_the_r23_research_status():
    status = open(os.path.join(ROOT, "docs", "STATUS.yaml"), encoding="utf-8").read()
    assert "workflow_count: 87" not in status
    assert "R23_B0_" not in status
    manifest = json.load(open(os.path.join(ROOT, "COMPANY_HANDOFF_MANIFEST.json"), encoding="utf-8"))
    assert manifest["manifest_scope"] == "PRODUCT_HANDOFF_ONLY_NOT_R23_RESEARCH_STATE"
    assert manifest["hash_basis"].startswith("git ls-files")


def test_r23_research_seal_excludes_product_artifacts():
    module = _seal_module()
    seal = module.build()
    paths = {entry["path"] for entry in seal["files"]}
    assert "COMPANY_HANDOFF_MANIFEST.json" not in paths
    assert "docs/STATUS.yaml" not in paths
    assert seal["product_artifacts_excluded"] == ["COMPANY_HANDOFF_MANIFEST.json", "docs/STATUS.yaml"]
    assert seal["paid_model_calls"] == 0 and seal["final_endpoint"] is False
    assert seal["manifest_hash"] == module._manifest_hash(seal)
