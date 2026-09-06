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


def _github_event(
    tmp_path: Path,
    *,
    head_repository: str | None = None,
    head_ref: str = "codex/trimem-coder-v1",
) -> Path:
    repository = "Scuttie/enterprise-shared-memory-poc"
    payload = {
        "repository": {"full_name": repository},
        "pull_request": {
            "head": {
                "ref": head_ref,
                "repo": {"full_name": head_repository or repository},
            }
        },
    }
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_detached_github_pr_uses_same_repository_head_ref(tmp_path: Path) -> None:
    module = _module()
    event = _github_event(tmp_path)
    branch = module._branch(
        {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_HEAD_REF": "codex/trimem-coder-v1",
            "GITHUB_REF_NAME": "18/merge",
            "GITHUB_EVENT_PATH": str(event),
            "GITHUB_REPOSITORY": "Scuttie/enterprise-shared-memory-poc",
        }
    )
    assert branch == "codex/trimem-coder-v1"


def test_github_pull_request_rejects_fork_branch_spoof(tmp_path: Path) -> None:
    module = _module()
    event = _github_event(tmp_path, head_repository="attacker/fork")
    assert module._branch(
        {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_HEAD_REF": "codex/trimem-coder-v1",
            "GITHUB_REF_NAME": "18/merge",
            "GITHUB_EVENT_PATH": str(event),
            "GITHUB_REPOSITORY": "Scuttie/enterprise-shared-memory-poc",
        }
    ) == ""


def test_github_push_uses_bound_ref_name(tmp_path: Path) -> None:
    module = _module()
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {"repository": {"full_name": "Scuttie/enterprise-shared-memory-poc"}}
        ),
        encoding="utf-8",
    )
    branch = module._branch(
        {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_HEAD_REF": "",
            "GITHUB_REF_NAME": "codex/trimem-coder-v1",
            "GITHUB_REF": "refs/heads/codex/trimem-coder-v1",
            "GITHUB_EVENT_PATH": str(event),
            "GITHUB_REPOSITORY": "Scuttie/enterprise-shared-memory-poc",
        }
    )
    assert branch == "codex/trimem-coder-v1"


@pytest.mark.parametrize(
    "candidate",
    ("", " codex/trimem-coder-v1", "codex/trimem-coder-v1\n", "../trimem"),
)
def test_github_branch_identity_rejects_malformed_values(
    tmp_path: Path,
    candidate: str,
) -> None:
    module = _module()
    event = _github_event(tmp_path, head_ref=candidate)
    assert (
        module._branch(
            {
                "GITHUB_ACTIONS": "true",
                "GITHUB_EVENT_NAME": "pull_request",
                "GITHUB_HEAD_REF": candidate,
                "GITHUB_REF_NAME": "18/merge",
                "GITHUB_EVENT_PATH": str(event),
                "GITHUB_REPOSITORY": "Scuttie/enterprise-shared-memory-poc",
            }
        )
        == ""
    )
