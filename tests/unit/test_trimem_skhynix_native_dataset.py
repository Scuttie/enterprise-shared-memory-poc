"""The additive stream cannot silently alter selection, rows or image locks."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import trimem_skhynix_native_dataset as dataset


def test_selection_uses_only_public_identity_fields():
    class PublicOnly(dict):
        def get(self, key, default=None):
            if key not in {"instance_id", "repo"}:
                raise AssertionError("Selection touched a restricted field")
            return super().get(key, default)

    rows = [PublicOnly(instance_id=f"sympy__sympy-{number}", repo="sympy/sympy")
            for number in (23950, 23262, 23824, 23534, 23413, 23500, 24400)]
    assert dataset.select_identities(rows, {"sympy__sympy-23500"}) == [
        "sympy__sympy-23413", "sympy__sympy-23534", "sympy__sympy-23824", "sympy__sympy-23950"]


def test_duplicate_identity_is_terminal():
    row = {"instance_id": "sympy__sympy-23413", "repo": "sympy/sympy"}
    with pytest.raises(dataset.SupplementalDatasetError, match="Duplicate"):
        dataset.select_identities([row, row], set())


def test_native003_selection_is_additive_and_ignores_content():
    class PublicOnly(dict):
        def get(self, key, default=None):
            assert key in {"instance_id", "repo"}
            return super().get(key, default)
    rows = [PublicOnly(instance_id=f"sympy__sympy-{number}", repo="sympy/sympy")
            for number in (24562, 24213, 23950, 24066, 24443, 24539, 24600, 24000)]
    assert dataset.select_identities(rows, {"sympy__sympy-24000"}, dataset.NATIVE003_SELECTION) == [
        "sympy__sympy-24066", "sympy__sympy-24213", "sympy__sympy-24443",
        "sympy__sympy-24539", "sympy__sympy-24562"]


def test_native003_excludes_every_previous_manifest(tmp_path):
    prior = {"instance_id": dataset.PRIOR_INSTANCE}
    for index, relative in enumerate(dataset.NATIVE003_EXCLUSION_PATHS):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(dataset.canonical({"targets": [prior, {"instance_id": f"excluded-{index}"}]}))
    excluded, bindings, observed_prior = dataset._exclusions(tmp_path, dataset.NATIVE003_SELECTION)
    assert excluded == {dataset.PRIOR_INSTANCE, *[f"excluded-{i}" for i in range(4)]}
    assert [binding["path"] for binding in bindings] == list(dataset.NATIVE003_EXCLUSION_PATHS)
    assert observed_prior == prior
    old_excluded, old_bindings, _ = dataset._exclusions(tmp_path)
    assert "excluded-3" not in old_excluded
    assert [binding["path"] for binding in old_bindings] == list(dataset.EXCLUSION_PATHS)


@pytest.fixture(params=[dataset.SELECTION, dataset.NATIVE003_SELECTION], ids=["native002", "native003"])
def frozen(tmp_path, monkeypatch, request):
    selection = request.param
    numbers = (23413, 23534, 23824, 23950) if selection == dataset.SELECTION else (
        24066, 24213, 24443, 24539, 24562)
    instances = [f"sympy__sympy-{number}" for number in numbers]
    spec = {"benchmark_id": dataset.BENCHMARK, "dataset_revision": "f" * 40}
    rows = {instance: {"base_commit": str(i + 1) * 40, "created_at": "2022-01-01T00:00:00Z",
                       "private_gold": "OPAQUE RESTRICTED SOURCE", "instance_id": instance}
            for i, instance in enumerate(instances)}
    targets = [dataset._target(instance, rows[instance], spec, i, selection)
               for i, instance in enumerate(instances)]
    prior = {"target_id": "prior", "instance_id": dataset.PRIOR_INSTANCE,
             "base_commit": "a" * 40, "source_row_sha256": "b" * 64}
    exclusions = [{"path": "frozen-original", "raw_sha256": "c" * 64}]
    images = []
    for instance in instances:
        name = "swebench/sweb.eval.x86_64." + instance.replace("__", "_1776_")
        response = {"digest": "sha256:" + "d" * 64, "last_updated": "2026-01-01T00:00:00Z",
                    "images": [{"architecture": "amd64", "os": "linux"}]}
        images.append({"instance_id": instance, "benchmark_id": dataset.BENCHMARK,
                       "image": name + "@" + response["digest"], "harness_image_tag": name + ":latest",
                       "registry_evidence_url": f"https://hub.docker.com/v2/repositories/{name}/tags/latest",
                       "registry_response": response,
                       "registry_response_canonical_sha256": dataset.sha(dataset.canonical(response))})
    value = {"schema": dataset.SCHEMA, "status": "FROZEN", "selection": copy.deepcopy(selection),
             "dataset": spec, "excluded_manifests": exclusions, "targets": targets,
             "prior_training_target": prior, "images": images, "history_path": str(tmp_path),
             "ancestry": [{"status": "observed"}],
             "chronology_claim": "TRAINING_BASE_ANCESTRY_ONLY_NOT_NATIVE_PATCH_UPSTREAM_MERGE",
             "scope_claim": "IDENTITY_SELECTED_SYMPY_PILOT_NOT_ORIGINAL_HELDOUT_ENDPOINT",
             "model_calls_at_selection": 0, "new_target_grader_runs_at_selection": 0}
    additional_priors = [] if selection == dataset.SELECTION else [{
        "target_id": "swebench_verified--sympy__sympy-23413", "instance_id": "sympy__sympy-23413",
        "base_commit": "9" * 40, "source_row_sha256": "8" * 64}]
    if selection == dataset.NATIVE003_SELECTION:
        value["additional_prior_training_targets"] = copy.deepcopy(additional_priors)
    monkeypatch.setattr(dataset, "_exclusions", lambda *args: ({dataset.PRIOR_INSTANCE}, exclusions, prior))
    monkeypatch.setattr(dataset, "_additional_prior_training_targets", lambda *args: additional_priors)
    monkeypatch.setattr(dataset, "_locked_dataset", lambda *args: (tmp_path / "cache.parquet", spec))
    monkeypatch.setattr(dataset, "_selected_rows", lambda *args: (instances, rows))
    monkeypatch.setattr(dataset, "ancestry_evidence", lambda *args: [{"status": "observed"}])
    return tmp_path, value, rows


def write_and_load(frozen, value=None, expected_sha=None):
    root, original, _rows = frozen
    raw = dataset.canonical(original if value is None else value) + b"\n"
    path = root / "manifest.json"
    path.write_bytes(raw)
    return dataset.load_supplemental_rows(path, root / "cache", expected_sha256=expected_sha or dataset.sha(raw))


def test_restricted_rows_stay_separate_from_public_manifest(frozen):
    targets, rows, images, manifest = write_and_load(frozen)
    training_count = manifest["selection"]["new_training_count"]
    assert len(targets) == len(images) == len(rows) == training_count + 3
    assert [target["role"] for target in targets[:training_count]] == ["TRAINING"] * training_count
    assert [target["role"] for target in targets[training_count:]] == ["EVALUATION"] * 3
    assert "OPAQUE RESTRICTED SOURCE" not in dataset.canonical(manifest).decode()
    assert rows is frozen[2]


def test_wrong_manifest_raw_hash_fails_before_dataset_read(frozen, monkeypatch):
    monkeypatch.setattr(dataset, "_locked_dataset", lambda *args: pytest.fail("Must reject hash first"))
    with pytest.raises(dataset.SupplementalDatasetError, match="raw hash"):
        write_and_load(frozen, expected_sha="0" * 64)


def test_prior_training_expansion_is_required_only_for_native003(frozen):
    value = copy.deepcopy(frozen[1])
    if value["selection"] == dataset.SELECTION:
        assert "additional_prior_training_targets" not in write_and_load(frozen)[3]
    else:
        value["additional_prior_training_targets"] = []
        with pytest.raises(dataset.SupplementalDatasetError, match="Additional prior"):
            write_and_load(frozen, value)


@pytest.mark.parametrize("mutation", ["selection", "target_order", "row_hash", "original_lock",
                                      "prior", "ancestry", "image", "tag", "registry", "architecture",
                                      "training_count", "target_role"])
def test_recomputed_outer_hash_cannot_authorize_changed_scientific_inputs(frozen, mutation):
    value = copy.deepcopy(frozen[1])
    if mutation == "selection":
        value["selection"]["minimum_instance_number_exclusive"] = 23413
    elif mutation == "training_count":
        value["selection"]["new_training_count"] += 1
    elif mutation == "target_role":
        value["targets"][-1]["role"] = "TRAINING"
    elif mutation == "target_order":
        value["targets"][1:3] = reversed(value["targets"][1:3])
    elif mutation == "row_hash":
        value["targets"][0]["source_row_sha256"] = "e" * 64
    elif mutation == "original_lock":
        value["excluded_manifests"][0]["raw_sha256"] = "e" * 64
    elif mutation == "prior":
        value["prior_training_target"]["base_commit"] = "e" * 40
    elif mutation == "ancestry":
        value["ancestry"] = []
    elif mutation == "image":
        value["images"][0]["image"] = "unofficial/image@sha256:" + "d" * 64
    elif mutation == "tag":
        value["images"][0]["harness_image_tag"] += "changed"
    elif mutation == "registry":
        value["images"][0]["registry_response"]["digest"] = "sha256:" + "e" * 64
    elif mutation == "architecture":
        value["images"][0]["registry_response"]["images"] = [{"architecture": "arm64", "os": "linux"}]
        value["images"][0]["registry_response_canonical_sha256"] = dataset.sha(
            dataset.canonical(value["images"][0]["registry_response"]))
    with pytest.raises(dataset.SupplementalDatasetError):
        write_and_load(frozen, value)


def test_builder_never_overwrites_an_existing_manifest(tmp_path):
    path = tmp_path / "existing.json"
    path.write_text("original")
    with pytest.raises(dataset.SupplementalDatasetError, match="never overwrite"):
        dataset.build_supplemental_manifest(cache_root=tmp_path, history=tmp_path,
                                            registry_directory=tmp_path, output_path=path)
    assert path.read_text() == "original"


def test_ancestry_checks_actual_git_and_rejects_nonancestor(tmp_path, monkeypatch):
    calls = []
    def git(history, args):
        calls.append(args)
        if args[:2] == ["remote", "get-url"]:
            return SimpleNamespace(returncode=0, stdout="https://github.com/sympy/sympy.git\n")
        return SimpleNamespace(returncode=1, stdout="")
    monkeypatch.setattr(dataset, "_git", git)
    prior = {"instance_id": dataset.PRIOR_INSTANCE, "base_commit": "a" * 40}
    targets = [{"instance_id": f"sympy__sympy-{23413+i}", "base_commit": str(i+1) * 40} for i in range(4)]
    with pytest.raises(dataset.SupplementalDatasetError, match="not an evaluation ancestor"):
        dataset.ancestry_evidence(tmp_path, prior, targets)
    assert calls[-1] == ["merge-base", "--is-ancestor", "a" * 40, "1" * 40]


def test_native003_checks_second_training_ancestry_to_every_eval(tmp_path, monkeypatch):
    checked_pairs = []
    def git(history, args):
        if args[:2] == ["remote", "get-url"]:
            return SimpleNamespace(returncode=0, stdout="https://github.com/sympy/sympy.git\n")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            checked_pairs.append(tuple(args[2:]))
            return SimpleNamespace(returncode=0, stdout="")
        return SimpleNamespace(returncode=0, stdout=f"committer Test <test@example.org> {int(args[2][0])} +0000\n\nmessage")
    monkeypatch.setattr(dataset, "_git", git)
    prior = {"instance_id": dataset.PRIOR_INSTANCE, "base_commit": "1" * 40}
    targets = [{"instance_id": f"sympy__sympy-{24066+i}", "base_commit": str(i+2) * 40}
               for i in range(5)]
    additional_prior = {"instance_id": "sympy__sympy-23413", "base_commit": "0" * 40}
    evidence = dataset.ancestry_evidence(tmp_path, prior, targets, dataset.NATIVE003_SELECTION,
                                         [additional_prior])
    assert len(evidence) == 17
    assert checked_pairs == [("1" * 40, "2" * 40), ("0" * 40, "2" * 40),
                             ("1" * 40, "3" * 40), ("0" * 40, "3" * 40), ("2" * 40, "3" * 40)] + [
        (str(source) * 40, str(target) * 40) for source in (1, 0, 2, 3) for target in (4, 5, 6)]


@pytest.fixture
def native004_frozen(tmp_path, monkeypatch):
    return _independent_frozen(tmp_path, monkeypatch, dataset.NATIVE004_SELECTION)


@pytest.fixture
def native005_frozen(tmp_path, monkeypatch):
    return _independent_frozen(tmp_path, monkeypatch, dataset.NATIVE005_SELECTION)


def _independent_frozen(tmp_path, monkeypatch, selection):
    """Exercise build/load against synthetic parquet, without a solver or grader."""
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq
    instances = [*selection["training_instance_ids"], *selection["evaluation_instance_ids"]]
    rows = [{"instance_id": instance, "repo": dataset.REPOSITORY,
             "base_commit": f"{index + 1:040x}", "created_at": f"2020-01-{index + 1:02}T00:00:00Z",
             "problem_statement": f"Public printing title {index}\nFULL_BODY_MUST_NOT_BE_PUBLISHED",
             "patch": "SYNTHETIC_GOLD_MUST_NOT_BE_PUBLISHED", "test_patch": "SYNTHETIC_TEST"}
            for index, instance in enumerate(instances + ["sympy__sympy-17000", "sympy__sympy-18000"])]
    path = tmp_path / "source.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path)
    spec = {"benchmark_id": dataset.BENCHMARK, "dataset_revision": "f" * 40,
            "path": "source.parquet", "bytes": path.stat().st_size, "sha256": dataset.sha(path.read_bytes())}
    exclusion_paths = (dataset.NATIVE004_EXCLUSION_PATHS if selection == dataset.NATIVE004_SELECTION
                       else dataset.NATIVE005_EXCLUSION_PATHS)
    for relative in exclusion_paths:
        excluded_path = tmp_path / relative
        excluded_path.parent.mkdir(parents=True, exist_ok=True)
        # No legacy prior needs to exist: the old cohorts only provide exclusions.
        excluded_path.write_bytes(dataset.canonical({"targets": [{"instance_id": "sympy__sympy-18000"}]}))
    registry = tmp_path / "registry"
    registry.mkdir()
    images = []
    for instance in instances:
        name = "swebench/sweb.eval.x86_64." + instance.replace("__", "_1776_")
        response = {"digest": "sha256:" + "d" * 64,
                    "images": [{"architecture": "amd64", "os": "linux"}]}
        raw = dataset.canonical(response)
        (registry / ("registry-" + instance.rsplit("-", 1)[1] + ".json")).write_bytes(raw)
        images.append({"instance_id": instance, "benchmark_id": dataset.BENCHMARK,
                       "image": name + "@" + response["digest"], "harness_image_tag": name + ":latest",
                       "registry_evidence_url": f"https://hub.docker.com/v2/repositories/{name}/tags/latest",
                       "registry_response_sha256": dataset.sha(raw)})
    (registry / "images.json").write_bytes(dataset.canonical(images))
    monkeypatch.setattr(dataset, "_locked_dataset", lambda *args: (path, spec))
    monkeypatch.setattr(dataset, "ancestry_evidence", lambda *args: [{"status": "observed"}])
    if selection == dataset.NATIVE005_SELECTION:
        def git(history, args):
            if args[:2] == ["merge-base", "--is-ancestor"]:
                return SimpleNamespace(returncode=0, stdout="")
            return SimpleNamespace(returncode=0, stdout=(
                f"committer Test <test@example.org> {int(args[2], 16)} +0000\n\nmessage"))
        monkeypatch.setattr(dataset, "_git", git)
        monkeypatch.setattr(dataset, "_public_runner_evidence", lambda history, candidates: [
            {"instance_id": row["instance_id"], "base_commit": row["base_commit"], "runner_path": "bin/test",
             "runner_returncode": 0 if row["instance_id"] in instances else 128,
             "runner_sha256": dataset.NATIVE005_RUNNER_SHA256 if row["instance_id"] in instances else None}
            for row in candidates])
        screening = _runtime_screening_fixture(registry, images)
        raw = dataset.canonical(screening) + b"\n"
        (registry / "runtime-screening.json").write_bytes(raw)
        monkeypatch.setitem(dataset.NATIVE005_SELECTION, "runtime_screening_raw_sha256", dataset.sha(raw))
    output = tmp_path / "independent.json"
    value = dataset.build_supplemental_manifest(cache_root=tmp_path, history=tmp_path,
        registry_directory=registry, output_path=output, root=tmp_path, selection=selection)
    return tmp_path, output, value


def _runtime_screening_fixture(registry, images):
    """Synthetic public Docker probe receipts, never an actual container call."""
    rows = []
    for image in images:
        instance, pinned = image["instance_id"], image["image"]
        number = instance.rsplit("-", 1)[1]
        registry_path = registry / ("registry-" + number + ".json")
        registry_value = dataset.benchmark.strict_json_loads(registry_path.read_text())
        # Older-profile synthetic fixtures need no registry timestamp; add it
        # only here, before any native005 evidence is frozen.
        registry_value["last_updated"] = "2026-01-01T00:00:00Z"
        registry_path.write_bytes(dataset.canonical(registry_value))
        image["registry_response_sha256"] = dataset.sha(registry_path.read_bytes())
        registry_entry = {**image, "registry_response": registry_value,
            "registry_response_canonical_sha256": dataset.sha(dataset.canonical(registry_value)),
            "registry_last_updated_utc": registry_value["last_updated"]}
        public = {"instance_id": instance, "image": pinned,
            "command": ["docker", "run", "--name", "native005-screening-preflight-" + number,
                "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--pids-limit", "64", "--entrypoint", "/bin/sh", pinned, "-c",
                "sha256sum /testbed/bin/test && /opt/miniconda3/envs/testbed/bin/python --version"],
            "returncode": 0, "stdout": dataset.NATIVE005_RUNNER_SHA256 + "  /testbed/bin/test\nPython 3.9.20\n",
            "stderr": "", "checked_at_utc": "2026-01-01T00:00:00Z", "read_only_container": True, "network": "none"}
        runtime_path, digest_path = registry / (number + "-runtime.json"), registry / (number + "-digest.json")
        runtime_path.write_bytes(dataset.canonical(public) + b"\n")
        digest = {"instance_id": instance, "image": pinned,
            "command": ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", pinned],
            "repo_digests": [pinned], "pull_returncode": 0}
        digest_path.write_bytes(dataset.canonical(digest) + b"\n")
        rows.append({"instance_id": instance, "image": pinned, "image_digest": pinned.rsplit("@", 1)[1],
            "repo_digest_verified": True, "runner_sha256": dataset.NATIVE005_RUNNER_SHA256,
            "public_runner_sha256": dataset.NATIVE005_RUNNER_SHA256, "python_version": "Python 3.9.20",
            "public_python_version": "Python 3.9.20", "python_executable": "/opt/miniconda3/envs/testbed/bin/python",
            "eligible": True, "ineligibility_reasons": [], "registry_evidence_path": str(registry_path.resolve()),
            "registry_response_sha256": image["registry_response_sha256"],
            "registry_response_canonical_sha256": registry_entry["registry_response_canonical_sha256"],
            "registry_entry_canonical_sha256": dataset.sha(dataset.canonical(registry_entry)),
            "runtime_evidence_path": str(runtime_path.resolve()), "runtime_evidence_sha256": dataset.sha(runtime_path.read_bytes()),
            "digest_verification_evidence_path": str(digest_path.resolve()),
            "digest_verification_evidence_sha256": dataset.sha(digest_path.read_bytes()),
            "public_preflight": public, "public_runner_preflight_returncode": 0,
            "public_runner_preflight_stdout": public["stdout"], "public_runner_preflight_stderr": ""})
    (registry / "images.json").write_bytes(dataset.canonical(images))
    return {"schema": 1, "status": "PUBLIC_RUNTIME_SCREENING_COMPLETE", "selection_or_experiment_ready": False,
        "solver_model_calls": 0, "new_grader_calls": 0, "required_public_runner_sha256": dataset.NATIVE005_RUNNER_SHA256,
        "required_public_python_version": "Python 3.9.20",
        "eligibility_rule": "repo_digest_verified AND public_preflight_returncode == 0 AND exact runner SHA AND exact Python version",
        "requested_image_count": len(rows), "screened_image_count": len(rows), "eligible_image_count": len(rows), "images": rows}


def load_native004(frozen, value=None):
    root, path, original = frozen
    raw = dataset.canonical(original if value is None else value) + b"\n"
    path.write_bytes(raw)
    return dataset.load_supplemental_rows(path, root, expected_sha256=dataset.sha(raw), root=root)


def test_native004_is_independent_and_binds_public_candidate_metadata(native004_frozen):
    targets, rows, images, value = load_native004(native004_frozen)
    assert [target["instance_id"] for target in targets] == [f"sympy__sympy-{number}" for number in (
        14976, 16766, 19346, 20916, 21930, 22080, 22456, 22914)]
    assert [target["role"] for target in targets] == ["TRAINING"] * 2 + ["EVALUATION"] * 6
    assert len(rows) == len(images) == 8
    assert value["prior_training_target"] is None
    assert value["additional_prior_training_targets"] == []
    assert value["model_calls_at_selection"] is None
    assert value["planner_llm_involved_at_selection"] is True
    assert value["solver_model_calls_at_selection"] == value["new_target_grader_runs_at_selection"] == 0
    assert [entry["path"] for entry in value["excluded_manifests"]] == list(dataset.NATIVE004_EXCLUSION_PATHS)
    evidence = value["selection_evidence"]
    assert len(evidence["candidates"]) == 9
    assert "sympy__sympy-17000" in {row["instance_id"] for row in evidence["candidates"]}
    assert "sympy__sympy-18000" not in {row["instance_id"] for row in evidence["candidates"]}
    assert evidence["candidates_canonical_sha256"] == dataset.sha(dataset.canonical(evidence["candidates"]))
    assert [row["instance_id"] for row in evidence["selected_public_metadata"]] == [
        target["instance_id"] for target in targets]
    assert all(set(row) == set(dataset.NATIVE004_CANDIDATE_FIELDS) for row in evidence["candidates"])
    published = dataset.canonical(value).decode()
    assert "FULL_BODY_MUST_NOT_BE_PUBLISHED" not in published
    assert "SYNTHETIC_GOLD_MUST_NOT_BE_PUBLISHED" not in published
    assert "SYNTHETIC_TEST" not in published


def test_native004_candidate_read_is_restricted_to_declared_public_columns(native004_frozen, monkeypatch):
    import pyarrow.parquet as pq
    root, _path, _value = native004_frozen
    original = pq.read_table
    calls = []
    def read(path, **kwargs):
        calls.append(kwargs)
        assert kwargs == {"columns": list(dataset.NATIVE004_PUBLIC_COLUMNS)}
        return original(path, **kwargs)
    monkeypatch.setattr(pq, "read_table", read)
    dataset._native004_selection_evidence(root / "source.parquet", {"sympy__sympy-18000"})
    assert len(calls) == 1


@pytest.mark.parametrize("field", ["public_title", "base_commit", "created_at", "repo"])
def test_native004_rehashed_public_metadata_cannot_replace_pinned_candidate_view(native004_frozen, field):
    value = copy.deepcopy(native004_frozen[2])
    evidence = value["selection_evidence"]
    for row in (evidence["candidates"][0], evidence["selected_public_metadata"][0]):
        row[field] = "changed"
    for key in ("candidates", "selected_public_metadata"):
        evidence[key + "_canonical_sha256"] = dataset.sha(dataset.canonical(evidence[key]))
    with pytest.raises(dataset.SupplementalDatasetError, match="Public candidate metadata"):
        load_native004(native004_frozen, value)


@pytest.mark.parametrize("mutation", ["prior", "missing_prior", "additional_prior", "missing_additional",
    "planner", "model_calls", "solver_calls", "grader_runs", "scope", "selection", "boolean_count",
    "candidate_removed", "candidate_order", "metadata_hash", "selected_metadata", "target_role",
    "row_hash", "exclusions", "ancestry", "image", "extra_field", "superseded_training_split"])
def test_native004_rejects_profile_prior_or_scientific_input_tampering(native004_frozen, mutation):
    value = copy.deepcopy(native004_frozen[2])
    if mutation == "prior":
        value["prior_training_target"] = {"target_id": "future-training"}
    elif mutation == "missing_prior":
        del value["prior_training_target"]
    elif mutation == "additional_prior":
        value["additional_prior_training_targets"] = [{"target_id": "future-training"}]
    elif mutation == "missing_additional":
        del value["additional_prior_training_targets"]
    elif mutation == "planner":
        value["planner_llm_involved_at_selection"] = False
    elif mutation == "model_calls":
        value["model_calls_at_selection"] = 0
    elif mutation == "solver_calls":
        value["solver_model_calls_at_selection"] = False
    elif mutation == "grader_runs":
        value["new_target_grader_runs_at_selection"] = 1
    elif mutation == "scope":
        value["scope_claim"] = "IDENTITY_SELECTED_SYMPY_PILOT_NOT_ORIGINAL_HELDOUT_ENDPOINT"
    elif mutation == "selection":
        value["selection"]["training_instance_ids"][0] = dataset.PRIOR_INSTANCE
    elif mutation == "superseded_training_split":
        value["selection"]["training_instance_ids"] = ["sympy__sympy-16766", "sympy__sympy-18763"]
    elif mutation == "boolean_count":
        value["selection"]["new_training_count"] = 2.0
    elif mutation == "candidate_removed":
        value["selection_evidence"]["candidates"].pop()
    elif mutation == "candidate_order":
        value["selection_evidence"]["candidates"].reverse()
    elif mutation == "metadata_hash":
        value["selection_evidence"]["candidates_canonical_sha256"] = "0" * 64
    elif mutation == "selected_metadata":
        value["selection_evidence"]["selected_public_metadata"].reverse()
    elif mutation == "target_role":
        value["targets"][-1]["role"] = "TRAINING"
    elif mutation == "row_hash":
        value["targets"][0]["source_row_sha256"] = "0" * 64
    elif mutation == "exclusions":
        value["excluded_manifests"].pop()
    elif mutation == "ancestry":
        value["ancestry"] = []
    elif mutation == "image":
        value["images"][0]["image"] = "unofficial/image@sha256:" + "d" * 64
    elif mutation == "extra_field":
        value["undeclared_prior_training"] = [{"instance_id": dataset.PRIOR_INSTANCE}]
    with pytest.raises(dataset.SupplementalDatasetError):
        load_native004(native004_frozen, value)


def test_native004_rejects_selected_identity_in_exclusions(native004_frozen):
    root, _path, _value = native004_frozen
    path = root / dataset.NATIVE004_EXCLUSION_PATHS[-1]
    path.write_bytes(dataset.canonical({"targets": [{"instance_id": dataset.NATIVE004_TRAINING_IDS[0]}]}))
    with pytest.raises(dataset.SupplementalDatasetError, match="absent or excluded"):
        load_native004(native004_frozen)


@pytest.mark.parametrize("selection", [dataset.NATIVE004_SELECTION, dataset.NATIVE005_SELECTION],
                         ids=["native004", "native005"])
def test_independent_ancestry_has_only_new_training_sources(tmp_path, monkeypatch, selection):
    checked_pairs = []
    def git(history, args):
        if args[:2] == ["remote", "get-url"]:
            return SimpleNamespace(returncode=0, stdout="https://github.com/sympy/sympy.git\n")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            checked_pairs.append(tuple(args[2:]))
            return SimpleNamespace(returncode=0, stdout="")
        return SimpleNamespace(returncode=0, stdout=f"committer Test <test@example.org> {int(args[2], 16)} +0000\n\nmessage")
    monkeypatch.setattr(dataset, "_git", git)
    targets = [{"instance_id": instance, "base_commit": f"{index + 1:040x}"}
               for index, instance in enumerate([
                   *selection["training_instance_ids"], *selection["evaluation_instance_ids"]])]
    evidence = dataset.ancestry_evidence(tmp_path, None, targets, selection, [])
    assert len(evidence) == 13
    assert checked_pairs == [(f"{1:040x}", f"{2:040x}")] + [
        (f"{source:040x}", f"{target:040x}") for source in (1, 2) for target in range(3, 9)]
    for prior, additional in [({"instance_id": "future"}, []), (None, [{"instance_id": "future"}])]:
        with pytest.raises(dataset.SupplementalDatasetError, match="forbids prior training"):
            dataset.ancestry_evidence(tmp_path, prior, targets, selection, additional)


def load_native005(frozen, value=None):
    # The manifest envelope is shared; the loader validates the exact profile.
    return load_native004(frozen, value)


def test_native005_binds_all_public_runners_and_only_new_training(native005_frozen):
    targets, rows, images, value = load_native005(native005_frozen)
    assert [row["instance_id"] for row in targets] == [f"sympy__sympy-{number}" for number in (
        19637, 19783, 19954, 20154, 20428, 20438, 20801, 21379)]
    assert [row["role"] for row in targets] == ["TRAINING"] * 2 + ["EVALUATION"] * 6
    assert len(rows) == len(images) == 8
    assert value["prior_training_target"] is None and value["additional_prior_training_targets"] == []
    assert value["model_calls_at_selection"] is None and value["planner_llm_involved_at_selection"] is True
    assert value["solver_model_calls_at_selection"] == value["new_target_grader_runs_at_selection"] == 0
    assert [row["path"] for row in value["excluded_manifests"]] == list(dataset.NATIVE005_EXCLUSION_PATHS)
    assert len(value["excluded_manifests"]) == 6
    evidence = value["selection_evidence"]
    assert len(evidence["candidates"]) == len(evidence["runner_evidence"]) == 9
    assert evidence["runner_evidence"][0]["instance_id"] == "sympy__sympy-17000"
    assert evidence["runner_evidence"][0]["runner_sha256"] is None
    assert evidence["runner_evidence"][0]["runner_returncode"] == 128
    assert evidence["required_runner_sha256"] == dataset.NATIVE005_RUNNER_SHA256
    assert evidence["runner_evidence_canonical_sha256"] == dataset.sha(dataset.canonical(evidence["runner_evidence"]))
    assert [row["instance_id"] for row in evidence["selected_public_metadata"]] == [
        row["instance_id"] for row in targets]
    published = dataset.canonical(value).decode()
    assert "FULL_BODY_MUST_NOT_BE_PUBLISHED" not in published
    assert "SYNTHETIC_GOLD_MUST_NOT_BE_PUBLISHED" not in published
    assert "SYNTHETIC_TEST" not in published


@pytest.mark.parametrize("mutation", ["prior", "additional_prior", "missing_additional", "runner_contract", "runtime_contract",
    "training_ids", "evaluation_ids", "training_count", "evaluation_count", "content_selection", "scope",
    "planner", "solver_calls", "grader_runs", "unavailable_removed", "runner_hash", "runner_status",
    "runner_order", "runner_method", "runner_path", "runner_required_hash", "candidate_title",
    "exclusions", "ancestry", "selected_metadata", "row_hash", "extra_field"])
def test_native005_rejects_rehashed_scientific_input_tampering(native005_frozen, mutation):
    value = copy.deepcopy(native005_frozen[2])
    selection, evidence = value["selection"], value["selection_evidence"]
    if mutation == "prior":
        value["prior_training_target"] = {"target_id": "legacy"}
    elif mutation == "additional_prior":
        value["additional_prior_training_targets"] = [{"target_id": "legacy"}]
    elif mutation == "missing_additional":
        del value["additional_prior_training_targets"]
    elif mutation == "runner_contract":
        selection["required_runner_sha256"] = "f" * 64
    elif mutation == "runtime_contract":
        selection["runtime_screening_raw_sha256"] = "f" * 64
    elif mutation in ("training_ids", "evaluation_ids"):
        selection[mutation.replace("_ids", "_instance_ids")].reverse()
    elif mutation in ("training_count", "evaluation_count"):
        selection["new_training_count" if mutation == "training_count" else mutation] = 2.0
    elif mutation == "content_selection":
        selection["content_fields_used_for_selection"] = []
    elif mutation == "scope":
        value["scope_claim"] = dataset.NATIVE004_SCOPE_CLAIM
    elif mutation == "planner":
        value["planner_llm_involved_at_selection"] = False
    elif mutation == "solver_calls":
        value["solver_model_calls_at_selection"] = False
    elif mutation == "grader_runs":
        value["new_target_grader_runs_at_selection"] = 1
    elif mutation == "unavailable_removed":
        evidence["runner_evidence"].pop(0)
    elif mutation == "runner_hash":
        evidence["runner_evidence"][1]["runner_sha256"] = "f" * 64
    elif mutation == "runner_status":
        evidence["runner_evidence"][0]["runner_returncode"] = 0
    elif mutation == "runner_order":
        evidence["runner_evidence"].reverse()
    elif mutation == "runner_method":
        evidence["method"] = "RANDOM"
    elif mutation == "runner_path":
        evidence["runner_evidence"][1]["runner_path"] = "other"
    elif mutation == "runner_required_hash":
        evidence["required_runner_sha256"] = "f" * 64
    elif mutation == "candidate_title":
        evidence["candidates"][0]["public_title"] = "changed"
    elif mutation == "exclusions":
        value["excluded_manifests"].pop()
    elif mutation == "ancestry":
        value["ancestry"] = []
    elif mutation == "selected_metadata":
        evidence["selected_public_metadata"].reverse()
    elif mutation == "row_hash":
        value["targets"][0]["source_row_sha256"] = "f" * 64
    elif mutation == "extra_field":
        value["undeclared_prior_training"] = []
    for key in ("candidates", "selected_public_metadata", "runner_evidence"):
        evidence[key + "_canonical_sha256"] = dataset.sha(dataset.canonical(evidence[key]))
    with pytest.raises(dataset.SupplementalDatasetError):
        load_native005(native005_frozen, value)


def test_native005_rechecks_public_runner_bytes_before_decoding_restricted_rows(native005_frozen, monkeypatch):
    original = dataset._public_runner_evidence
    def changed(history, candidates):
        evidence = original(history, candidates)
        # Even a previously unavailable, unselected runner becoming available changes the snapshot.
        evidence[0]["runner_sha256"] = "f" * 64
        evidence[0]["runner_returncode"] = 0
        return evidence
    monkeypatch.setattr(dataset, "_public_runner_evidence", changed)
    monkeypatch.setattr(dataset, "_selected_rows", lambda *args: pytest.fail("Restricted rows decoded before validation"))
    with pytest.raises(dataset.SupplementalDatasetError, match="runner selection evidence"):
        load_native005(native005_frozen)


def test_native005_rejects_overlap_with_native004(native005_frozen):
    root, _path, _value = native005_frozen
    path = root / dataset.NATIVE005_EXCLUSION_PATHS[-1]
    path.write_bytes(dataset.canonical({"targets": [{"instance_id": dataset.NATIVE005_TRAINING_IDS[0]}]}))
    with pytest.raises(dataset.SupplementalDatasetError):
        load_native005(native005_frozen)


@pytest.mark.parametrize("change", ["receipt_bytes", "missing_candidate", "claimed_python", "eligibility",
    "probe_command", "probe_stdout", "registry_entry", "image_digest", "digest_membership", "schema_boolean",
    "screened_count", "eligible_count", "solver_calls", "required_python"])
def test_native005_runtime_screening_checks_actual_public_receipts(native005_frozen, change):
    evidence = copy.deepcopy(native005_frozen[2]["selection_evidence"])
    screening = evidence["runtime_screening"]
    row = screening["images"][0]
    if change == "receipt_bytes":
        Path(row["runtime_evidence_path"]).write_bytes(b"changed after public screening")
    elif change == "missing_candidate":
        screening["images"].pop()
    elif change == "claimed_python":
        row["python_version"] = "Python 3.9.21"
    elif change == "eligibility":
        row["eligible"] = False
    elif change in ("probe_command", "probe_stdout"):
        public = row["public_preflight"]
        if change == "probe_command":
            public["command"][-1] += " && echo UNDECLARED"
        else:
            public["stdout"] = public["stdout"].replace("  /testbed/bin/test", "  /different/path")
            row["public_runner_preflight_stdout"] = public["stdout"]
        raw = dataset.canonical(public) + b"\n"
        Path(row["runtime_evidence_path"]).write_bytes(raw)
        row["runtime_evidence_sha256"] = dataset.sha(raw)
    elif change == "registry_entry":
        row["registry_entry_canonical_sha256"] = "f" * 64
    elif change == "image_digest":
        row["image_digest"] = "sha256:" + "f" * 64
    elif change == "digest_membership":
        path = Path(row["digest_verification_evidence_path"])
        digest = dataset.benchmark.strict_json_loads(path.read_text())
        digest["repo_digests"] = []
        path.write_bytes(dataset.canonical(digest) + b"\n")
        row["digest_verification_evidence_sha256"] = dataset.sha(path.read_bytes())
    elif change == "schema_boolean":
        screening["schema"] = True
    elif change in ("screened_count", "eligible_count"):
        screening[change.replace("_count", "_image_count")] -= 1
    elif change == "solver_calls":
        screening["solver_model_calls"] = False
    elif change == "required_python":
        screening["required_public_python_version"] = "Python 3.9.21"
    # Rehashing a forged summary cannot bypass the raw receipt or semantic checks.
    with pytest.raises(dataset.SupplementalDatasetError):
        dataset._validated_runtime_screening(screening, evidence["runner_evidence"],
            expected_sha256=dataset.sha(dataset.canonical(screening) + b"\n"))


def test_native005_runtime_filter_retains_incompatible_python_as_ineligible(native005_frozen):
    evidence = copy.deepcopy(native005_frozen[2]["selection_evidence"])
    screening = evidence["runtime_screening"]
    row = screening["images"][0]
    public = row["public_preflight"]
    public["stdout"] = public["stdout"].replace("Python 3.9.20", "Python 3.9.21")
    row["public_runner_preflight_stdout"] = public["stdout"]
    row["python_version"] = row["public_python_version"] = "Python 3.9.21"
    row["eligible"] = False
    row["ineligibility_reasons"] = ["PYTHON_VERSION_MISMATCH"]
    raw = dataset.canonical(public) + b"\n"
    Path(row["runtime_evidence_path"]).write_bytes(raw)
    row["runtime_evidence_sha256"] = dataset.sha(raw)
    screening["eligible_image_count"] -= 1
    validated = dataset._validated_runtime_screening(screening, evidence["runner_evidence"],
        expected_sha256=dataset.sha(dataset.canonical(screening) + b"\n"))
    assert len(validated) == len(screening["images"])
    assert validated[row["instance_id"]]["eligible"] is False
    with pytest.raises(dataset.SupplementalDatasetError, match="eligible public runtime"):
        dataset._validate_selected_runtime_images(native005_frozen[2]["images"], screening)


def test_public_runner_hashes_preserve_blob_bytes_and_unavailable_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset, "_git", lambda *args: SimpleNamespace(
        returncode=0, stdout="https://github.com/sympy/sympy.git\n"))
    candidates = [{"instance_id": f"sympy__sympy-{index}", "base_commit": f"{index:040x}"}
                  for index in (1, 2)]
    calls = []
    def blob(history, object_name):
        calls.append(object_name)
        return SimpleNamespace(returncode=0, stdout=b"line1\r\nline2\n") if object_name.startswith(
            candidates[0]["base_commit"]) else SimpleNamespace(returncode=128, stdout=b"")
    monkeypatch.setattr(dataset, "_git_blob", blob)
    evidence = dataset._public_runner_evidence(tmp_path, candidates)
    assert calls == [row["base_commit"] + ":bin/test" for row in candidates]
    assert evidence[0]["runner_sha256"] == dataset.sha(b"line1\r\nline2\n")
    assert evidence[1]["runner_sha256"] is None
    assert evidence[1]["runner_returncode"] == 128
    assert [row["instance_id"] for row in evidence] == [row["instance_id"] for row in candidates]


def test_public_runner_git_reads_binary_without_lazy_fetch(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(dataset.subprocess, "run", lambda command, **kwargs: calls.append(
        (command, kwargs)) or SimpleNamespace(returncode=0, stdout=b"line1\r\nline2\n"))
    result = dataset._git_blob(tmp_path, "a" * 40 + ":bin/test")
    command, kwargs = calls[0]
    assert command[-3:] == ["cat-file", "blob", "a" * 40 + ":bin/test"]
    assert kwargs.get("text", False) is False
    assert kwargs["env"]["GIT_NO_LAZY_FETCH"] == "1"
    assert result.stdout == b"line1\r\nline2\n"


@pytest.mark.parametrize("change,expected", [
    ("none", [1, 2, 3, 4, 5]), ("nonancestor", [1, 3, 4, 5, 6]),
    ("runner", [1, 3, 4, 5, 6]), ("first_pair_infeasible", [2, 3, 4, 5, 6]),
    ("same_timestamp", [1, 3, 4, 5, 6])])
def test_public_runner_selection_uses_first_feasible_pair_and_descendants(tmp_path, monkeypatch, change, expected):
    candidates = [{"instance_id": f"sympy__sympy-{index}", "base_commit": f"{index:040x}"}
                  for index in range(1, 9)]
    runners = [{**row, "runner_returncode": 0, "runner_sha256": "a" * 64} for row in candidates]
    if change == "runner":
        runners[1]["runner_sha256"] = "b" * 64
    def git(history, args):
        if args[:2] == ["merge-base", "--is-ancestor"]:
            pair = tuple(int(commit, 16) for commit in args[2:])
            rejected = ((change == "nonancestor" and pair == (1, 2))
                        or (change == "first_pair_infeasible" and pair[0] == 1))
            return SimpleNamespace(returncode=int(rejected), stdout="")
        timestamp = int(args[2], 16)
        if change == "same_timestamp" and timestamp == 2:
            timestamp = 1
        return SimpleNamespace(returncode=0, stdout=f"committer Test <test@example.org> {timestamp} +0000\n\n")
    monkeypatch.setattr(dataset, "_git", git)
    assert dataset._runner_compatible_identities(tmp_path, candidates, runners,
        runner_sha256="a" * 64, evaluation_count=3) == [f"sympy__sympy-{index}" for index in expected]


@pytest.mark.parametrize("change", ["lookup_error", "short_evidence", "changed_commit", "no_compatible_runner"])
def test_public_runner_selection_rejects_incomplete_or_unverifiable_public_inputs(tmp_path, monkeypatch, change):
    candidates = [{"instance_id": f"sympy__sympy-{index}", "base_commit": f"{index:040x}"}
                  for index in range(1, 9)]
    runners = [{**row, "runner_returncode": 0, "runner_sha256": "a" * 64} for row in candidates]
    if change == "short_evidence":
        runners.pop()
    elif change == "changed_commit":
        runners[0]["base_commit"] = "f" * 40
    elif change == "no_compatible_runner":
        for row in runners:
            row["runner_returncode"] = 128
            row["runner_sha256"] = None
    monkeypatch.setattr(dataset, "_git", lambda *args: SimpleNamespace(returncode=128, stdout=""))
    with pytest.raises(dataset.SupplementalDatasetError):
        dataset._runner_compatible_identities(tmp_path, candidates, runners,
            runner_sha256="a" * 64, evaluation_count=3)
