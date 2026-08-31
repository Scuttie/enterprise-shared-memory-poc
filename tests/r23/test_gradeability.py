"""Credential-free tests for the frozen, fail-closed R23 grader smoke path."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import r23_gradeability as runner  # noqa: E402
import r23_gradeability_aggregate as aggregate  # noqa: E402
import r23_gradeability_prepare as prepare  # noqa: E402


MANIFEST_PATH = ROOT / "artifacts" / "r23" / "grader_smoke_manifest.json"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci-r23-gradeability.yml"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_noop_patch_touches_only_the_noop_file():
    assert "+++ b/.r23_noop" in runner.NOOP_R23_PATCH
    assert runner.NOOP_R23_PATCH.count("+++ b/") == 1
    with pytest.raises(runner.EmptyBaselineRejected):
        runner.assert_valid_baseline("")
    assert runner.assert_valid_baseline(runner.NOOP_R23_PATCH) == runner.NOOP_R23_PATCH


def test_frozen_manifest_recomputes_repository_stratified_selection():
    manifest = prepare.validate_manifest(MANIFEST_PATH)
    targets = manifest["targets"]
    assert len(targets) == len({target["repository_key"] for target in targets}) == 12
    assert len({target["instance_id"] for target in targets}) == 12
    assert manifest["freeze_status"] == "FROZEN_PRE_EXECUTION"
    assert manifest["execution_status"] == "PENDING_EXEC_APPROVAL"
    assert manifest["benchmark_grader_viability"] == "PENDING_OFFICIAL_GRADER_SMOKE"
    assert [condition["name"] for condition in manifest["conditions"]] == ["GOLD", "NOOP"]
    assert all(prepare.DIGEST.fullmatch(target["image_digest"]) for target in targets)
    assert all(target["image_ref"].endswith("@" + target["image_digest"]) for target in targets)


def test_prepare_matrix_is_exactly_the_committed_manifest():
    manifest = prepare.validate_manifest(MANIFEST_PATH)
    matrix = prepare.matrix_from_manifest(manifest)
    assert matrix == {
        "include": [
            {"instance_id": target["instance_id"], "repository_key": target["repository_key"]}
            for target in manifest["targets"]
        ]
    }


def test_manifest_validator_rejects_selection_or_digest_drift(tmp_path):
    manifest = _manifest()
    manifest["targets"][0]["instance_id"] = manifest["targets"][1]["instance_id"]
    bad_selection = tmp_path / "bad-selection.json"
    bad_selection.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(prepare.ManifestError):
        prepare.validate_manifest(bad_selection)

    manifest = _manifest()
    manifest["targets"][0]["image_digest"] = "DEFERRED"
    bad_digest = tmp_path / "bad-digest.json"
    bad_digest.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(prepare.ManifestError):
        prepare.validate_manifest(bad_digest)


def test_workflow_has_only_manifest_matrix_and_propagates_failures():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "instance_ids:" not in workflow
    assert "r23_gradeability_prepare.py" in workflow
    assert "fromJson(needs.prepare.outputs.matrix)" in workflow
    assert "|| echo" not in workflow
    assert "continue-on-error" not in workflow
    assert '"datasets==2.21.0"' in workflow
    assert '"pyarrow==17.0.0"' in workflow
    assert "artifacts/r23/grader_run/${{ matrix.instance_id }}/" in workflow
    assert workflow.count("if: always()") >= 3


def test_workflow_event_specific_r23_sentinel_gate_is_prepared_but_not_approved():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    sentinel = ROOT / "artifacts" / "r23" / "EXEC_APPROVED_GRADER_SMOKE"
    assert "workflow_dispatch)" in workflow and "push)" in workflow
    assert "paths:\n      - artifacts/r23/EXEC_APPROVED_GRADER_SMOKE" in workflow
    assert "test \"$DISPATCH_CONFIRM\" = \"EXEC_APPROVED_R23_GRADEABILITY\"" in workflow
    assert "cat artifacts/r23/EXEC_APPROVED_GRADER_SMOKE" in workflow
    assert "artifacts/r22/" not in workflow and "EXEC_APPROVED_R22" not in workflow
    assert not sentinel.exists(), "EXEC sentinel must not exist before separate approval"


def test_execution_gate_refuses_before_dataset_or_docker(monkeypatch, tmp_path):
    monkeypatch.delenv(runner.APPROVAL_ENV, raising=False)
    monkeypatch.setattr(runner, "_load_pinned_row", lambda *_: pytest.fail("dataset must not load without approval"))
    out = tmp_path / "grade.json"
    rc = runner.main(["--instance-id", _manifest()["targets"][0]["instance_id"], "--out", str(out)])
    assert rc == 3
    assert not out.exists()


def test_digest_pull_and_observed_repo_digest_are_exact(monkeypatch, tmp_path):
    target = _manifest()["targets"][0]
    calls = []

    def fake_run(cmd, cwd, prefix, timeout=None):
        calls.append(cmd)
        prefix.parent.mkdir(parents=True, exist_ok=True)
        prefix.with_name(prefix.name + "_stdout.log").write_text("", encoding="utf-8")
        prefix.with_name(prefix.name + "_stderr.log").write_text("", encoding="utf-8")
        stdout = "" if cmd[1] == "pull" else json.dumps([target["image_ref"]])
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr(runner, "_run_logged", fake_run)
    observed = runner._pull_and_verify_image(target, tmp_path)
    assert calls[0] == ["docker", "pull", target["image_ref"]]
    assert calls[1][-1] == target["image_ref"]
    assert observed == [target["image_ref"]]


def test_digest_verification_fails_closed_on_observed_mismatch(monkeypatch, tmp_path):
    target = _manifest()["targets"][0]

    def fake_run(cmd, cwd, prefix, timeout=None):
        stdout = "" if cmd[1] == "pull" else json.dumps(["example.invalid/image@sha256:" + "0" * 64])
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr(runner, "_run_logged", fake_run)
    with pytest.raises(runner.GradeabilityInfraError, match="observed RepoDigests"):
        runner._pull_and_verify_image(target, tmp_path)


def test_logged_subprocess_preserves_complete_stdout_and_stderr(monkeypatch, tmp_path):
    stdout = "stdout-line\n" * 1000
    stderr = "stderr-line\n" * 1000
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout, stderr),
    )
    prefix = tmp_path / "harness"
    result = runner._run_logged(["python", "fake-grader"], tmp_path, prefix)
    assert result.returncode == 0
    assert (tmp_path / "harness_stdout.log").read_text(encoding="utf-8") == stdout
    assert (tmp_path / "harness_stderr.log").read_text(encoding="utf-8") == stderr


def test_runner_source_pins_parquet_revision_sha_and_local_harness_dataset():
    source = (SCRIPTS / "r23_gradeability.py").read_text(encoding="utf-8")
    assert "hf_hub_download" in source and 'revision=dataset["revision_sha"]' in source
    assert 'filename=dataset["parquet_path"]' in source
    assert 'observed_parquet_sha != dataset["parquet_sha256"]' in source
    assert 'row_for_harness["image"] = target["image_ref"]' in source
    assert '"--dataset_name"' in source and "dataset_path.resolve()" in source
    assert "swebench.harness.run_evaluation" in source
    assert "swebench_memory.harness" not in source


def _make_complete_shard(download_root: Path, manifest: dict, target: dict, label: str = "GRADEABLE") -> Path:
    iid = target["instance_id"]
    artifact_root = download_root / f"r23-gradeability-{iid}"
    evidence_root = artifact_root / "artifacts" / "r23" / "grader_run" / iid
    files = [
        evidence_root / "dataset.json",
        evidence_root / "image_pull_stdout.log",
        evidence_root / "image_pull_stderr.log",
        evidence_root / "image_inspect_stdout.log",
        evidence_root / "image_inspect_stderr.log",
        evidence_root / "gold" / "prediction.jsonl",
        evidence_root / "gold" / "harness_stdout.log",
        evidence_root / "gold" / "harness_stderr.log",
        evidence_root / "gold" / "r23.gold-run.json",
        evidence_root / "noop" / "prediction.jsonl",
        evidence_root / "noop" / "harness_stdout.log",
        evidence_root / "noop" / "harness_stderr.log",
        evidence_root / "noop" / "r23.noop-run.json",
    ]
    evidence = []
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"raw evidence for {iid}: {path.name}\n", encoding="utf-8")
        relpath = str(path.relative_to(artifact_root)).replace(os.sep, "/")
        evidence.append(
            {"relpath": relpath, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    gold_resolved = label != "UNGRADEABLE_GOLD"
    noop_resolved = label == "UNGRADEABLE_NOOP"
    summary = {
        "schema": aggregate.TARGET_SCHEMA,
        "instance_id": iid,
        "repository_key": target["repository_key"],
        "label": label,
        "gold": {
            "condition": "GOLD",
            "resolved": gold_resolved,
            "completed": True,
            "empty_patch": False,
            "infra_ok": True,
            "returncode": 0,
            "report_found": True,
            "report_path": f"artifacts/r23/grader_run/{iid}/gold/r23.gold-run.json",
            "patch_sha256": target["gold_patch_sha256"],
        },
        "noop": {
            "condition": "NOOP",
            "resolved": noop_resolved,
            "completed": True,
            "empty_patch": False,
            "infra_ok": True,
            "returncode": 0,
            "report_found": True,
            "report_path": f"artifacts/r23/grader_run/{iid}/noop/r23.noop-run.json",
            "patch_sha256": manifest["conditions"][1]["patch_sha256"],
        },
        "image_expected_ref": target["image_ref"],
        "image_expected_digest": target["image_digest"],
        "image_observed_repo_digests": [target["image_ref"]],
        "image_digest_verified": True,
        "dataset_revision": manifest["dataset"]["revision_sha"],
        "dataset_parquet_sha256": manifest["dataset"]["parquet_sha256"],
        "dataset_row_sha256": target["dataset_row_sha256"],
        "raw_evidence": evidence,
        "paid_model_calls": 0,
    }
    summary_path = artifact_root / "artifacts" / "r23" / f"grade_{iid}.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    return summary_path


def _complete_download(tmp_path: Path) -> tuple[Path, dict, list[Path]]:
    manifest = _manifest()
    root = tmp_path / "download"
    paths = [_make_complete_shard(root, manifest, target) for target in manifest["targets"]]
    return root, manifest, paths


def test_aggregate_accepts_only_exact_complete_all_gradeable_campaign(tmp_path):
    root, manifest, _ = _complete_download(tmp_path)
    result = aggregate.aggregate(root, MANIFEST_PATH)
    assert result["expected_target_set"] == [target["instance_id"] for target in manifest["targets"]]
    assert result["missing_targets"] == []
    assert result["duplicate_targets"] == {}
    assert result["condition_errors"] == []
    assert result["evidence_errors"] == []
    assert result["audit_complete"] is True
    assert result["benchmark_grader_viability"] == "PASS"


def test_aggregate_detects_missing_and_duplicate_target_shards(tmp_path):
    root, manifest, paths = _complete_download(tmp_path)
    missing_iid = manifest["targets"][0]["instance_id"]
    paths[0].unlink()
    duplicate_iid = manifest["targets"][1]["instance_id"]
    duplicate_path = root / "duplicate" / f"grade_{duplicate_iid}.json"
    duplicate_path.parent.mkdir(parents=True)
    duplicate_path.write_bytes(paths[1].read_bytes())
    result = aggregate.aggregate(root, MANIFEST_PATH)
    assert result["missing_targets"] == [missing_iid]
    assert result["duplicate_targets"] == {duplicate_iid: 2}
    assert result["audit_complete"] is False
    assert result["benchmark_grader_viability"] == "INCOMPLETE"


def test_aggregate_detects_condition_and_raw_evidence_corruption(tmp_path):
    root, _, paths = _complete_download(tmp_path)
    summary = json.loads(paths[0].read_text(encoding="utf-8"))
    summary["noop"]["patch_sha256"] = "0" * 64
    evidence_path = root / summary["raw_evidence"][0]["relpath"]
    # The evidence is below an artifact-name prefix, so resolve by suffix as the aggregate does.
    evidence_path = next(path for path in root.rglob(evidence_path.name) if str(path).replace("\\", "/").endswith(summary["raw_evidence"][0]["relpath"]))
    evidence_path.write_text("tampered\n", encoding="utf-8")
    paths[0].write_text(json.dumps(summary), encoding="utf-8")
    result = aggregate.aggregate(root, MANIFEST_PATH)
    assert any("NOOP patch hash mismatch" in error for error in result["condition_errors"])
    assert any("evidence" in error and "mismatch" in error for error in result["evidence_errors"])
    assert result["audit_complete"] is False


def test_complete_but_ungradeable_campaign_fails_viability(tmp_path):
    root, manifest, paths = _complete_download(tmp_path)
    target = manifest["targets"][0]
    # Replace one otherwise complete record with an internally consistent GOLD failure.
    paths[0].unlink()
    _make_complete_shard(root, manifest, target, label="UNGRADEABLE_GOLD")
    result = aggregate.aggregate(root, MANIFEST_PATH)
    assert result["audit_complete"] is True
    assert result["label_counts"]["UNGRADEABLE_GOLD"] == 1
    assert result["benchmark_grader_viability"] == "FAIL"


def test_credential_free_sources_have_no_model_secret_or_client_calls():
    sources = "\n".join(
        (SCRIPTS / name).read_text(encoding="utf-8")
        for name in ("r23_gradeability_prepare.py", "r23_gradeability.py", "r23_gradeability_aggregate.py")
    )
    for banned in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "api_key", "OpenAI("):
        assert banned not in sources
