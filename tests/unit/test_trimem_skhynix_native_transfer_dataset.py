"""Transfer admission preserves prior cohorts and rechecks its public evidence."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import trimem_skhynix_native_dataset as dataset
import trimem_skhynix_native_transfer_dataset as transfer


def _runtime_receipts(directory, instances):
    images, rows = [], []
    for instance in instances:
        number = instance.rsplit("-", 1)[1]
        name = "swebench/sweb.eval.x86_64." + instance.replace("__", "_1776_")
        registry = {"digest": "sha256:" + "d" * 64, "last_updated": "2026-01-01T00:00:00Z",
                    "images": [{"architecture": "amd64", "os": "linux"}]}
        registry_path = directory / ("registry-" + number + ".json")
        registry_path.write_bytes(dataset.canonical(registry))
        image = {"instance_id": instance, "benchmark_id": dataset.BENCHMARK,
            "image": name + "@" + registry["digest"], "harness_image_tag": name + ":latest",
            "registry_evidence_url": f"https://hub.docker.com/v2/repositories/{name}/tags/latest",
            "registry_response_sha256": dataset.sha(registry_path.read_bytes())}
        images.append(image)
        registry_entry = {**image, "registry_response": registry,
            "registry_response_canonical_sha256": dataset.sha(dataset.canonical(registry)),
            "registry_last_updated_utc": registry["last_updated"]}
        public = {"instance_id": instance, "image": image["image"],
            "command": ["docker", "run", "--name", "native005-screening-preflight-" + number,
                "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--pids-limit", "64", "--entrypoint", "/bin/sh", image["image"], "-c",
                "sha256sum /testbed/bin/test && /opt/miniconda3/envs/testbed/bin/python --version"],
            "returncode": 0, "stdout": dataset.NATIVE005_RUNNER_SHA256 + "  /testbed/bin/test\nPython 3.9.20\n",
            "stderr": "", "read_only_container": True, "network": "none"}
        public_path, digest_path = directory / (number + "-runtime.json"), directory / (number + "-digest.json")
        public_path.write_bytes(dataset.canonical(public) + b"\n")
        digest_path.write_bytes(dataset.canonical({"instance_id": instance, "image": image["image"],
            "command": ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image["image"]],
            "repo_digests": [image["image"]], "pull_returncode": 0}) + b"\n")
        rows.append({"instance_id": instance, "image": image["image"], "image_digest": registry["digest"],
            "repo_digest_verified": True, "runner_sha256": dataset.NATIVE005_RUNNER_SHA256,
            "public_runner_sha256": dataset.NATIVE005_RUNNER_SHA256, "python_version": "Python 3.9.20",
            "public_python_version": "Python 3.9.20", "python_executable": "/opt/miniconda3/envs/testbed/bin/python",
            "eligible": True, "ineligibility_reasons": [], "registry_evidence_path": str(registry_path.resolve()),
            "registry_response_sha256": image["registry_response_sha256"],
            "registry_response_canonical_sha256": registry_entry["registry_response_canonical_sha256"],
            "registry_entry_canonical_sha256": dataset.sha(dataset.canonical(registry_entry)),
            "runtime_evidence_path": str(public_path.resolve()), "runtime_evidence_sha256": dataset.sha(public_path.read_bytes()),
            "digest_verification_evidence_path": str(digest_path.resolve()),
            "digest_verification_evidence_sha256": dataset.sha(digest_path.read_bytes()),
            "public_preflight": public, "public_runner_preflight_returncode": 0,
            "public_runner_preflight_stdout": public["stdout"], "public_runner_preflight_stderr": ""})
    screening = {"schema": 1, "status": "PUBLIC_RUNTIME_SCREENING_COMPLETE", "selection_or_experiment_ready": False,
        "solver_model_calls": 0, "new_grader_calls": 0, "required_public_runner_sha256": dataset.NATIVE005_RUNNER_SHA256,
        "required_public_python_version": "Python 3.9.20",
        "eligibility_rule": "repo_digest_verified AND public_preflight_returncode == 0 AND exact runner SHA AND exact Python version",
        "requested_image_count": len(rows), "screened_image_count": len(rows), "eligible_image_count": len(rows), "images": rows}
    return images, screening


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq
    instances = [*dataset.NATIVE005_TRAINING_IDS, *dataset.NATIVE005_EVALUATION_IDS,
                 *transfer.KNOWN_DEVELOPMENT_IDS, *transfer.TARGET_IDS]
    rows = [{"instance_id": instance, "repo": dataset.REPOSITORY,
             "base_commit": f"{index + 1:040x}", "created_at": f"2020-01-{index + 1:02}T00:00:00Z",
             "problem_statement": f"Synthetic public title {index}\nPUBLIC_BODY_MUST_NOT_BE_EXPORTED",
             "patch": "OPAQUE_SYNTHETIC_GOLD", "test_patch": "OPAQUE_SYNTHETIC_TEST"}
            for index, instance in enumerate(instances)]
    cache = tmp_path / "cache"
    parquet = cache / dataset.BENCHMARK / ("f" * 40) / "source.parquet"
    parquet.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows), parquet)
    spec = {"benchmark_id": dataset.BENCHMARK, "dataset_revision": "f" * 40, "path": "source.parquet",
            "bytes": parquet.stat().st_size, "sha256": dataset.sha(parquet.read_bytes())}
    for relative in dataset.NATIVE005_EXCLUSION_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(dataset.canonical({"targets": [{"instance_id": "sympy__sympy-18000"}]}))
    (tmp_path / "configs/trimem_v1/grader_lock.json").write_bytes(dataset.canonical({"dataset_files": [spec]}))
    git_calls = []

    def git(history, args):
        git_calls.append(args)
        if args[:2] == ["remote", "get-url"]:
            return SimpleNamespace(returncode=0, stdout="https://github.com/sympy/sympy.git\n")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return SimpleNamespace(returncode=0, stdout="")
        assert args[:2] == ["cat-file", "commit"]
        return SimpleNamespace(returncode=0, stdout=f"committer Test <test@example.org> {int(args[2], 16)} +0000\n\nmessage")

    monkeypatch.setattr(dataset, "_git", git)
    monkeypatch.setattr(dataset, "_public_runner_evidence", lambda history, candidates: [
        {"instance_id": row["instance_id"], "base_commit": row["base_commit"], "runner_path": "bin/test",
         "runner_returncode": 0, "runner_sha256": dataset.NATIVE005_RUNNER_SHA256} for row in candidates])
    registry = tmp_path / "registry"
    registry.mkdir()
    images, screening = _runtime_receipts(registry, instances)
    screening_raw = dataset.canonical(screening) + b"\n"
    (registry / "runtime-screening.json").write_bytes(screening_raw)
    monkeypatch.setitem(dataset.NATIVE005_SELECTION, "runtime_screening_raw_sha256", dataset.sha(screening_raw))
    (registry / "images.json").write_bytes(dataset.canonical(images[:8]))
    prior005 = tmp_path / transfer.NATIVE005_PATH
    dataset.build_supplemental_manifest(cache_root=cache, history=tmp_path, registry_directory=registry,
        output_path=prior005, root=tmp_path, selection=dataset.NATIVE005_SELECTION)
    for number in (6, 7):
        (tmp_path / f"configs/skhynix_v1/codex_{number:03}_manifest.json").write_bytes(prior005.read_bytes())
    prior_hashes = {relative: dataset.sha((tmp_path / relative).read_bytes()) for relative in transfer.PRIOR_PATHS}
    output = tmp_path / "transfer.json"
    value = transfer.build_transfer_manifest(cache_root=cache, history=tmp_path, output_path=output, root=tmp_path)
    return SimpleNamespace(root=tmp_path, cache=cache, parquet=parquet, output=output, value=value,
                           rows=rows, prior_hashes=prior_hashes, git_calls=git_calls)


def _load(frozen, value=None):
    if value is not None:
        frozen.output.write_bytes(dataset.canonical(value) + b"\n")
    return dataset.load_supplemental_rows(frozen.output, frozen.cache,
        expected_sha256=dataset.sha(frozen.output.read_bytes()), root=frozen.root)


def test_fixed_disjoint_transfer_uses_existing_environment_shape_and_no_training(frozen):
    targets, rows, images, manifest = _load(frozen)
    assert [row["instance_id"] for row in targets] == list(transfer.TARGET_IDS)
    assert [row["role"] for row in targets] == ["EVALUATION"] * 4
    assert list(rows) == list(images) == list(transfer.TARGET_IDS)
    assert manifest["selection"]["new_training_count"] == 0
    assert manifest["selection"]["known_development_exclusions"] == ["sympy__sympy-21596"]
    assert [row["instance_id"] for row in manifest["memory_source_targets"]] == list(transfer.SOURCE_IDS)
    assert all(row["role"] == "EVALUATION" and row["origin_manifest"] == transfer.NATIVE007_PATH
               for row in manifest["memory_source_targets"])
    assert len(manifest["ancestry"]) == 8
    assert {(row["source_instance_id"], row["target_instance_id"]) for row in manifest["ancestry"]} == {
        (source, target) for source in transfer.SOURCE_IDS for target in transfer.TARGET_IDS}
    assert [row["path"] for row in manifest["excluded_manifests"]] == list(transfer.PRIOR_PATHS)
    assert {relative: dataset.sha((frozen.root / relative).read_bytes()) for relative in transfer.PRIOR_PATHS} == frozen.prior_hashes
    assert "NOT_GLOBALLY_UNSEEN" in manifest["scope_claim"]
    assert manifest["runtime_evidence"]["required_public_python_version"] == "Python 3.9.20"
    tasks = dataset.benchmark.coding_tasks(targets, rows)
    assert [dataset.sha(task.instruction.encode()) for task in tasks] == [row["public_instruction_sha256"] for row in targets]
    public = dataset.canonical(manifest).decode()
    for forbidden in ("OPAQUE_SYNTHETIC_GOLD", "OPAQUE_SYNTHETIC_TEST", "PUBLIC_BODY_MUST_NOT_BE_EXPORTED"):
        assert forbidden not in public
    assert {call[0] for call in frozen.git_calls} <= {"remote", "cat-file", "merge-base"}


@pytest.mark.parametrize("change", ["selection", "training_count", "target_order", "target_role", "instruction_hash",
    "source_row_hash", "source_role", "source_identity", "source_commit", "source_instruction_hash", "ancestry",
    "scope", "chronology", "dataset", "prior_hash", "runtime_hash", "runtime_version", "runtime_receipt",
    "image", "extra_field", "boolean_count", "planner", "known_development", "missing_target"])
def test_rehashed_manifest_cannot_change_transfer_scientific_inputs(frozen, change):
    value = copy.deepcopy(frozen.value)
    if change == "selection": value["selection"]["evaluation_instance_ids"][0] = "sympy__sympy-21596"
    elif change == "training_count": value["selection"]["new_training_count"] = 1
    elif change == "target_order": value["targets"].reverse()
    elif change == "target_role": value["targets"][0]["role"] = "TRAINING"
    elif change == "instruction_hash": value["targets"][0]["public_instruction_sha256"] = "0" * 64
    elif change == "source_row_hash": value["targets"][0]["source_row_sha256"] = "0" * 64
    elif change == "source_role": value["memory_source_targets"][0]["role"] = "TRAINING"
    elif change == "source_identity": value["memory_source_targets"][0]["instance_id"] = transfer.TARGET_IDS[0]
    elif change == "source_commit": value["memory_source_targets"][0]["base_commit"] = "0" * 40
    elif change == "source_instruction_hash": value["memory_source_targets"][0]["public_instruction_sha256"] = "0" * 64
    elif change == "ancestry": value["ancestry"].pop()
    elif change == "scope": value["scope_claim"] = "GLOBALLY_UNSEEN_RANDOM_SAMPLE"
    elif change == "chronology": value["chronology_claim"] = "PATCH_MERGED_UPSTREAM"
    elif change == "dataset": value["dataset"]["sha256"] = "0" * 64
    elif change == "prior_hash": value["excluded_manifests"][0]["raw_sha256"] = "0" * 64
    elif change == "runtime_hash": value["runtime_evidence"]["runtime_screening_raw_sha256"] = "0" * 64
    elif change == "runtime_version": value["runtime_evidence"]["required_public_python_version"] = "Python 3.9.21"
    elif change == "runtime_receipt": value["runtime_evidence"]["selected_public_runtime_receipts"][0]["eligible"] = False
    elif change == "image": value["images"][0]["image"] += "changed"
    elif change == "extra_field": value["outcome_based_replacement"] = True
    elif change == "boolean_count": value["solver_model_calls_at_selection"] = False
    elif change == "planner": value["planner_llm_involved_at_selection"] = False
    elif change == "known_development": value["selection"]["known_development_exclusions"] = []
    elif change == "missing_target": value["targets"].pop()
    with pytest.raises(dataset.SupplementalDatasetError):
        _load(frozen, value)


def test_wrong_hash_rejects_before_any_dataset_or_history_read(frozen, monkeypatch):
    monkeypatch.setattr(transfer, "_assemble", lambda **kwargs: pytest.fail("must reject outer hash first"))
    with pytest.raises(dataset.SupplementalDatasetError, match="raw hash"):
        dataset.load_supplemental_rows(frozen.output, frozen.cache, expected_sha256="0" * 64, root=frozen.root)


def test_existing_manifest_is_never_overwritten(frozen, monkeypatch):
    raw = frozen.output.read_bytes()
    monkeypatch.setattr(transfer, "_assemble", lambda **kwargs: pytest.fail("must reject existing output first"))
    with pytest.raises(dataset.SupplementalDatasetError, match="never overwrite"):
        transfer.build_transfer_manifest(cache_root=frozen.cache, history=frozen.root, output_path=frozen.output, root=frozen.root)
    assert frozen.output.read_bytes() == raw


def test_returned_manifest_cannot_mutate_the_fixed_selection_contract(frozen):
    frozen.value["selection"]["evaluation_instance_ids"].append("sympy__sympy-21596")
    assert transfer.SELECTION["evaluation_instance_ids"] == list(transfer.TARGET_IDS)
    assert _load(frozen)[3]["selection"]["evaluation_instance_ids"] == list(transfer.TARGET_IDS)


@pytest.mark.parametrize("prior", ["configs/trimem_v1/heldout_manifest.json",
    "configs/skhynix_v1/codex_002_manifest.json", "configs/skhynix_v1/codex_007_manifest.json"])
def test_any_prior_enrollment_overlap_is_terminal(frozen, prior):
    path = frozen.root / prior
    value = dataset.benchmark.read_json(path)
    value["targets"].append({"instance_id": transfer.TARGET_IDS[0]})
    path.write_bytes(dataset.canonical(value))
    with pytest.raises(dataset.SupplementalDatasetError, match="overlap"):
        _load(frozen)


def test_changed_native007_source_cohort_is_terminal(frozen):
    path = frozen.root / transfer.NATIVE007_PATH
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(dataset.SupplementalDatasetError, match="reused enrollment bytes differ"):
        _load(frozen)


@pytest.mark.parametrize("kind", ["registry", "runtime", "digest"])
def test_actual_public_runtime_receipt_drift_is_rejected(frozen, kind):
    receipt = frozen.value["runtime_evidence"]["selected_public_runtime_receipts"][0]
    key = {"registry": "registry_evidence_path", "runtime": "runtime_evidence_path",
           "digest": "digest_verification_evidence_path"}[kind]
    path = Path(receipt[key])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(dataset.SupplementalDatasetError, match="receipt bytes differ"):
        _load(frozen)


def test_selected_row_decoder_uses_identity_first_and_only_four_restricted_rows(frozen, monkeypatch):
    import pyarrow.parquet as pq
    original, calls = pq.read_table, []

    def read(path, **kwargs):
        calls.append(kwargs)
        return original(path, **kwargs)

    monkeypatch.setattr(pq, "read_table", read)
    rows = transfer._selected_rows(frozen.parquet)
    assert list(rows) == list(transfer.TARGET_IDS)
    assert calls == [{"columns": ["instance_id", "repo"]},
                     {"filters": [("instance_id", "in", list(transfer.TARGET_IDS))]}]


def test_changed_locked_dataset_is_rejected(frozen):
    frozen.parquet.write_bytes(frozen.parquet.read_bytes() + b"changed")
    with pytest.raises(dataset.SupplementalDatasetError, match="cached SWE parquet bytes differ"):
        _load(frozen)


@pytest.mark.parametrize("change", ["duplicate", "missing", "repository"])
def test_selected_identity_validation_precedes_restricted_decoding(frozen, monkeypatch, change):
    import pyarrow as pa
    import pyarrow.parquet as pq
    identities = [{"instance_id": instance, "repo": dataset.REPOSITORY} for instance in transfer.TARGET_IDS]
    if change == "duplicate": identities.append(identities[0])
    elif change == "missing": identities.pop()
    else: identities[0]["repo"] = "different/repository"

    def read(path, **kwargs):
        assert kwargs == {"columns": ["instance_id", "repo"]}, "Must reject before restricted row decoding"
        return pa.Table.from_pylist(identities)

    monkeypatch.setattr(pq, "read_table", read)
    with pytest.raises(dataset.SupplementalDatasetError, match="public identity"):
        transfer._selected_rows(frozen.parquet)


@pytest.mark.parametrize("failure", ["not_ancestor", "equal_timestamp", "missing_timestamp", "wrong_origin"])
def test_every_memory_source_must_precede_every_target(frozen, monkeypatch, failure):
    sources, targets = frozen.value["memory_source_targets"], frozen.value["targets"]
    original = dataset._git
    last_pair = (sources[-1]["base_commit"], targets[-1]["base_commit"])

    def git(history, args):
        if failure == "wrong_origin" and args[:2] == ["remote", "get-url"]:
            return SimpleNamespace(returncode=0, stdout="https://example.com/different.git")
        if failure == "not_ancestor" and args == ["merge-base", "--is-ancestor", *last_pair]:
            return SimpleNamespace(returncode=1, stdout="")
        if args == ["cat-file", "commit", last_pair[1]]:
            if failure == "missing_timestamp": return SimpleNamespace(returncode=128, stdout="")
            if failure == "equal_timestamp":
                return SimpleNamespace(returncode=0, stdout=f"committer Test <test@example.org> {int(last_pair[0], 16)} +0000\n\nmessage")
        return original(history, args)

    monkeypatch.setattr(dataset, "_git", git)
    with pytest.raises(dataset.SupplementalDatasetError):
        transfer._ancestry(frozen.root, sources, targets)
