"""Offline promotion amendment lineage; original proposals and grades stay immutable."""
from copy import deepcopy
from pathlib import Path
import shutil

import pytest

import trimem_skhynix_architecture_pipeline as core
import trimem_skhynix_architecture_memory as memory
import trimem_skhynix_architecture_learning_recovery as cloning
import trimem_skhynix_architecture_promotion_revalidation as driver
import trimem_skhynix_architecture_reflection_recovery as evaluation
from test_trimem_skhynix_architecture_learning import inputs, write
from test_trimem_skhynix_architecture_learning_recovery import authority, tree
from test_trimem_skhynix_architecture_reflection_recovery import publication


def runtime_fixture(tmp_path, execution_reference):
    execution = core.check(execution_reference)
    root = tmp_path / "promotion-runtime"
    before = execution["source_sha256"]
    for relative in before:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(execution["source_root"]) / relative, destination)
    changed = root / driver.CHANGED_PATH
    changed.write_bytes(changed.read_bytes() + b"\n# distinct reviewed fixture scanner revision\n")
    after = {name: memory._file_hash(root / name) for name in before}
    tests = tmp_path / "scanner-tests.xml"
    tests.write_text('<testsuite tests="1" failures="0" errors="0"/>')
    value = {"schema": driver.RUNTIME_SCHEMA, "previous_execution_reference": execution_reference,
        "old_source_root": execution["source_root"], "source_root": str(root),
        "old_source_sha256": before, "source_sha256": after, "changed_paths": [driver.CHANGED_PATH],
        "model_calls": 0, "solver_runs": 0, "official_grader_runs": 0, "test_references": [core.ref(tests)]}
    return write(tmp_path / "runtime-amendment.json", value)


def test_runtime_only_accepts_one_explicit_offline_scanner_change(inputs, authority):
    previous = core.check(authority["predecessor_pipeline_reference"])
    reference = runtime_fixture(inputs.tmp, previous["training_experiment_reference"])
    assert driver.validate_runtime(reference)["changed_paths"] == [driver.CHANGED_PATH]
    with pytest.raises(core.PipelineError, match="outside"):
        driver.validate_runtime(reference, check_imports=True)


@pytest.mark.parametrize("mutation", ["extra_change", "old_map", "same_root", "no_tests", "new_model_call"])
def test_runtime_rejects_hidden_execution_changes(inputs, authority, mutation):
    previous = core.check(authority["predecessor_pipeline_reference"])
    reference = runtime_fixture(inputs.tmp, previous["training_experiment_reference"])
    changed = deepcopy(core.check(reference))
    if mutation == "extra_change":
        name = next(key for key in changed["source_sha256"] if key != driver.CHANGED_PATH)
        changed["source_sha256"][name] = "f" * 64
    elif mutation == "old_map":
        changed["old_source_sha256"][driver.CHANGED_PATH] = "f" * 64
    elif mutation == "same_root":
        changed["source_root"] = changed["old_source_root"]
    elif mutation == "no_tests":
        changed["test_references"] = []
    else:
        changed["model_calls"] = 1
    amended = write(inputs.tmp / "bad-runtime.json", changed)
    with pytest.raises(core.PipelineError):
        driver.validate_runtime(amended)


@pytest.fixture
def amended(publication, authority, monkeypatch):
    inputs = publication.inputs
    previous = core.check(authority["predecessor_pipeline_reference"])
    runtime_ref = runtime_fixture(inputs.tmp, previous["training_experiment_reference"])
    original_validate = driver.validate_runtime
    validations = []
    def validated(ref, *, check_imports=False):
        validations.append(check_imports)
        # Real import-origin rejection is independently covered above; this
        # process uses the same reviewed classes for public SQLite fixtures.
        return original_validate(ref)
    monkeypatch.setattr(driver, "validate_runtime", validated)
    monkeypatch.setattr(driver, "EXPECTED_GROUPS", 1)
    monkeypatch.setattr(evaluation, "PROMOTION_GROUPS", 1)
    monkeypatch.setattr(driver.core, "validate_native_publication", lambda config, completion, outer, **kw:
        publication.operations.validate_publisher(config, completion, outer, kw["reflection_reference"]))
    old = {**publication.manifest, "status": "READY"}
    old_ref = write(inputs.tmp / "original-publisher/manifest.json", old)
    destination = inputs.tmp / "second-clone"
    clone_ref = cloning.clone_learning_authority(**{**authority, "destination_root": destination})
    request = {"schema": driver.REQUEST_SCHEMA, "predecessor_manifest_reference": old_ref,
        "clone_reference": clone_ref, "runtime_reference": runtime_ref,
        "output_root": str(inputs.tmp / "reverification"), "bank_output": str(inputs.tmp / "new-bank/bank.json")}
    request_ref = write(inputs.tmp / "reverify-request.json", request)
    publication.amendment = request
    publication.amendment_request = request_ref
    publication.validation_calls = validations
    publication.original_validate = original_validate
    return publication


def test_same_native_proposal_is_reverified_in_new_authority_without_source_or_model_retry(amended):
    old_clone = core.check(amended.manifest["clone_reference"])
    before = tree(Path(old_clone["destination_root"]))
    reference = driver.run(amended.amendment_request["path"])
    result = core.check(reference)
    assert result["status"] == "READY" and result["L3_skills"] == 1
    assert amended.validation_calls == [True, True]
    assert result["model_calls"] == result["solver_runs"] == result["official_grader_runs"] == result["native_proposal_retries"] == 0
    assert tree(Path(old_clone["destination_root"])) == before
    revision = core.check(result["promotion_revision_reference"])
    assert revision["jobs"][0]["old_ingestion_reference"] == amended.manifest["jobs"][0]["ingestion_reference"]
    assert revision["jobs"][0]["new_ingestion_reference"] != revision["jobs"][0]["old_ingestion_reference"]
    expected = {key: value for key, value in amended.manifest["jobs"][0].items() if key != "ingestion_reference"}
    assert {key: value for key, value in result["jobs"][0].items() if key != "ingestion_reference"} == expected
    config = {**amended.config, "reflection_recovery_reference": reference,
              "training_experiment_reference": amended.previous["training_experiment_reference"]}
    validated = evaluation.validate_recovered_bank(config, amended.previous, amended.operations)
    assert validated["status"] == "READY" and validated["layer_counts"]["L3_skills"] == 1
    with pytest.raises(core.PipelineError, match="fresh"):
        driver.run(amended.amendment_request["path"])


@pytest.mark.parametrize("mutation", ["omitted_job", "old_clone", "new_capture"])
def test_revalidation_rejects_selective_or_changed_original_proposals(amended, mutation):
    request = deepcopy(amended.amendment)
    if mutation == "old_clone":
        request["clone_reference"] = amended.manifest["clone_reference"]
    else:
        old = core.check(request["predecessor_manifest_reference"])
        if mutation == "omitted_job":
            old["jobs"] = []
        else:
            old["jobs"][0]["capture_ids"] = ["x", "y"]
        request["predecessor_manifest_reference"] = write(amended.inputs.tmp / "changed-prior.json", old)
    changed = write(amended.inputs.tmp / "changed-request.json", request)
    with pytest.raises((core.PipelineError, ValueError)):
        driver.run(changed["path"])
    assert not Path(request["output_root"]).exists()


def test_scanner_revision_cannot_write_into_predecessor_pipeline(amended):
    request = {**amended.amendment, "bank_output": str(Path(amended.previous["pipeline_root"]) / "unauthorized-bank.json")}
    reference = write(amended.inputs.tmp / "unsafe-bank-request.json", request)
    with pytest.raises(core.PipelineError, match="separate"):
        driver.run(reference["path"])
    assert not Path(request["bank_output"]).exists()


def test_evaluation_rejects_amendment_that_rewrites_the_original_native_template(amended):
    reference = driver.run(amended.amendment_request["path"])
    manifest = core.check(reference)
    manifest["jobs"][0]["native_proof"]["proposal_reference"] = {"path": "/new-proposal", "sha256": "a" * 64}
    new_ref = write(amended.inputs.tmp / "rewritten-proposal-manifest.json", manifest)
    config = {**amended.config, "reflection_recovery_reference": new_ref,
              "training_experiment_reference": amended.previous["training_experiment_reference"]}
    with pytest.raises(core.PipelineError, match="identical retained native proposal"):
        evaluation.validate_recovered_bank(config, amended.previous, amended.operations)
