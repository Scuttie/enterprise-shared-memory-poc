"""Scientific input separation and frozen-cohort integrity for Native011."""
import copy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
import trimem_skhynix_native_controlled_dataset as controlled
import trimem_skhynix_native_dataset as dataset


def _public_runtime(tmp_path, identity, image, commit):
    directory = tmp_path / "runtime" / identity
    checkout = directory / "source" / ("sympy-" + commit)
    runner = checkout / "bin/test"
    runner.parent.mkdir(parents=True)
    runner.write_bytes(b"# Synthetic public runner fixture; never executed.\n")
    probe_path = directory / "public-runtime-probe.json"
    result_path = directory / "result.json"
    output = [{"python_version": "3.9.21", "python_executable": controlled.PUBLIC_PYTHON,
               "sympy_version": "fixture", "sympy_file": "/testbed/sympy/__init__.py"},
              {"help_returncode": 0, "help_stdout": "Usage: test [options ...] [tests ...]\n--help\n",
               "help_stderr": ""}]
    probe = {"argv": controlled._runtime_argv(str(checkout), image), "cwd": None,
             "returncode": 0, "stderr": "", "started_at_unix_seconds": 1.0, "wall_seconds": 0.1,
             "stdout": "\n".join(dataset.canonical(row).decode() for row in output) + "\n"}
    probe_path.write_bytes(dataset.canonical(probe) + b"\n")
    result = {"instance_id": identity, "image": image, "base_commit": commit,
              "base_checkout": str(checkout), "public_python": controlled.PUBLIC_PYTHON,
              "python_version": "3.9.21", "sympy_version": "fixture",
              "sympy_import_path": "/testbed/sympy/__init__.py",
              "image_architecture": "amd64", "image_os": "linux",
              "runtime_compatible": True, "repo_digest_verified": True,
              "help_returncode": 0, "public_probe_returncode": 0,
              "issue_probes": 0, "model_calls": 0, "official_grader_calls": 0, "test_commands": 0,
              "runner_sha256": dataset.sha(runner.read_bytes()),
              "runtime_probe_path": str(probe_path),
              "runtime_probe_sha256": dataset.sha(probe_path.read_bytes())}
    result_path.write_bytes(dataset.canonical(result) + b"\n")
    return {"instance_id": identity, "image": image, "python_executable": controlled.PUBLIC_PYTHON,
            "python_version": "Python 3.9.21", "runner_sha256": result["runner_sha256"],
            "probe_sha256": result["runtime_probe_sha256"], "status": "PASS_PUBLIC_RUNTIME_ONLY",
            "runtime_receipt_path": str(result_path),
            "runtime_receipt_sha256": dataset.sha(result_path.read_bytes())}


def _receipt(evidence):
    return dataset.benchmark.strict_json_loads(Path(evidence["runtime_receipt_path"]).read_text())


def _rewrite_receipt(evidence, receipt):
    path = Path(evidence["runtime_receipt_path"])
    path.write_bytes(dataset.canonical(receipt) + b"\n")
    evidence["runtime_receipt_sha256"] = dataset.sha(path.read_bytes())


@pytest.fixture
def study(tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq
    ids = ["sympy__sympy-10001", "sympy__sympy-10002", "sympy__sympy-10003", "sympy__sympy-10004"]
    selection = {"method": "PUBLIC_ISSUE_MECHANISM_MATCH_BEFORE_SOLVER_OUTCOMES",
        "source_instance_ids": list(controlled.SOURCES),
        "targets": [{"instance_id": identity, "family": "polynomial" if i < 2 else "sets",
                     "rationale": "Public issue mechanism only"} for i, identity in enumerate(ids)]}
    rows = [{"instance_id": identity, "repo": dataset.REPOSITORY,
             "base_commit": f"{i + 1:040x}", "created_at": "2017-01-01T00:00:00Z",
             "problem_statement": "Public task", "patch": "RESTRICTED_GOLD_SENTINEL",
             "test_patch": "RESTRICTED_TEST_SENTINEL"} for i, identity in enumerate(ids)]
    parquet = tmp_path / "source.parquet"
    pq.write_table(pa.Table.from_pylist(rows), parquet)
    spec = {"dataset_revision": "a" * 40, "sha256": dataset.sha(parquet.read_bytes())}
    monkeypatch.setattr(dataset, "_locked_dataset", lambda *args: (parquet, spec))
    for relative in controlled.PRIOR_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(dataset.canonical({"targets": [{"instance_id": "sympy__sympy-9999"}]}))
    images, runtime = [], []
    for identity in ids:
        name = "swebench/sweb.eval.x86_64." + identity.replace("__", "_1776_")
        registry = {"digest": "sha256:" + "d" * 64,
                    "images": [{"architecture": "amd64", "os": "linux"}]}
        image = name + "@" + registry["digest"]
        images.append({"instance_id": identity, "benchmark_id": dataset.BENCHMARK,
            "image": image, "harness_image_tag": name + ":latest",
            "registry_evidence_url": f"https://hub.docker.com/v2/repositories/{name}/tags/latest",
            "registry_response": registry,
            "registry_response_canonical_sha256": dataset.sha(dataset.canonical(registry))})
        runtime.append(_public_runtime(tmp_path, identity, image, rows[len(runtime)]["base_commit"]))
    kwargs = dict(cache_root=tmp_path, root=tmp_path, selection=selection, images=images, runtime=runtime)
    return kwargs, tmp_path / "manifest.json"


def test_freeze_loader_keeps_restricted_columns_only_in_grader_handoff(study):
    kwargs, path = study
    manifest = controlled.build_controlled_manifest(output_path=path, **kwargs)
    result = dataset.load_supplemental_rows(path, kwargs["cache_root"],
        expected_sha256=dataset.sha(path.read_bytes()), root=kwargs["root"])
    assert result[3] == manifest
    assert len(result[0]) == len(result[1]) == 4
    assert all(row["patch"] == "RESTRICTED_GOLD_SENTINEL" for row in result[1].values())
    assert b"RESTRICTED_GOLD_SENTINEL" not in path.read_bytes()
    assert b"RESTRICTED_TEST_SENTINEL" not in path.read_bytes()
    assert manifest["chronology_claim"] == controlled.CHRONOLOGY


@pytest.mark.parametrize("identity", [*controlled.SOURCES, "sympy__sympy-9999", "sympy__sympy-21596"])
def test_previously_used_or_source_target_rejected(study, identity):
    kwargs, path = study
    kwargs["selection"]["targets"][0]["instance_id"] = identity
    with pytest.raises(dataset.SupplementalDatasetError, match="overlap"):
        controlled.build_controlled_manifest(output_path=path, **kwargs)
    assert not path.exists()


@pytest.mark.parametrize("change", ["source", "duplicate", "family", "count", "extra_gold_field"])
def test_invalid_selection_rejected_before_row_decode(study, monkeypatch, change):
    kwargs, path = study
    selection = kwargs["selection"]
    if change == "source": selection["source_instance_ids"] = []
    elif change == "duplicate": selection["targets"][1]["instance_id"] = selection["targets"][0]["instance_id"]
    elif change == "family": selection["targets"][0]["family"] = "sets"
    elif change == "count": selection["targets"].pop()
    else: selection["targets"][0]["patch"] = "forbidden"
    monkeypatch.setattr(controlled, "_rows", lambda *a: pytest.fail("Rows decoded before valid selection"))
    with pytest.raises(dataset.SupplementalDatasetError):
        controlled.build_controlled_manifest(output_path=path, **kwargs)


@pytest.mark.parametrize("field,value", [("image", "other"), ("python_executable", "/bin/python"),
    ("python_version", "unknown"), ("runner_sha256", "bad"), ("probe_sha256", "bad"),
    ("status", "FAIL"), ("instance_id", "sympy__sympy-9999")])
def test_wrong_public_runtime_binding_rejected(study, field, value):
    kwargs, path = study
    kwargs["runtime"][0][field] = value
    with pytest.raises(dataset.SupplementalDatasetError, match="runtime"):
        controlled.build_controlled_manifest(output_path=path, **kwargs)


@pytest.mark.parametrize("field", ["targets", "chronology_claim", "public_selected_metadata", "excluded_manifests"])
def test_rehashed_manifest_scientific_changes_rejected(study, field):
    kwargs, path = study
    value = controlled.build_controlled_manifest(output_path=path, **kwargs)
    value[field] = "CHANGED"
    path.write_bytes(dataset.canonical(value))
    with pytest.raises(dataset.SupplementalDatasetError):
        controlled.load_controlled_rows(path, kwargs["cache_root"],
            expected_sha256=dataset.sha(path.read_bytes()), root=kwargs["root"])


def test_original_hash_and_single_freeze_required(study):
    kwargs, path = study
    controlled.build_controlled_manifest(output_path=path, **kwargs)
    with pytest.raises(dataset.SupplementalDatasetError, match="never overwrite"):
        controlled.build_controlled_manifest(output_path=path, **kwargs)
    with pytest.raises(dataset.SupplementalDatasetError, match="hash"):
        controlled.load_controlled_rows(path, kwargs["cache_root"], expected_sha256="0" * 64, root=kwargs["root"])


def test_prior_enrollment_change_detected(study):
    kwargs, path = study
    controlled.build_controlled_manifest(output_path=path, **kwargs)
    (kwargs["root"] / controlled.PRIOR_PATHS[0]).write_bytes(dataset.canonical({"targets": []}))
    with pytest.raises(dataset.SupplementalDatasetError):
        controlled.load_controlled_rows(path, kwargs["cache_root"],
            expected_sha256=dataset.sha(path.read_bytes()), root=kwargs["root"])


@pytest.mark.parametrize("field,value", [("runner_sha256", "e" * 64), ("probe_sha256", "f" * 64),
    ("python_version", "Python 3.9.99"), ("runtime_receipt_sha256", "e" * 64),
    ("runtime_receipt_path", "relative/result.json")])
def test_well_formed_but_unbound_runtime_claim_rejected(study, field, value):
    kwargs, path = study
    kwargs["runtime"][0][field] = value
    with pytest.raises(dataset.SupplementalDatasetError, match="runtime"):
        controlled.build_controlled_manifest(output_path=path, **kwargs)


@pytest.mark.parametrize("field,value", [("base_commit", "e" * 40), ("test_commands", 1),
    ("model_calls", 1), ("official_grader_calls", 1), ("help_returncode", False),
    ("image", "different-image"), ("python_version", "3.9.99"),
    ("runtime_probe_path", "relative/probe.json")])
def test_rehashed_runtime_receipt_must_match_public_base_and_probe(study, field, value):
    kwargs, path = study
    evidence = kwargs["runtime"][0]
    receipt = _receipt(evidence)
    receipt[field] = value
    _rewrite_receipt(evidence, receipt)
    with pytest.raises(dataset.SupplementalDatasetError, match="runtime"):
        controlled.build_controlled_manifest(output_path=path, **kwargs)


@pytest.mark.parametrize("change", ["image", "base_mount", "test_command", "returncode",
    "python_version", "import_path", "help_failure", "missing_help"])
def test_rehashed_probe_requires_public_import_and_help_only(study, change):
    kwargs, path = study
    evidence = kwargs["runtime"][0]
    receipt = _receipt(evidence)
    probe_path = Path(receipt["runtime_probe_path"])
    probe = dataset.benchmark.strict_json_loads(probe_path.read_text())
    if change == "image": probe["argv"][-3] = "other-image"
    elif change == "base_mount": probe["argv"][17] = "type=bind,source=/wrong,target=/testbed,readonly"
    elif change == "test_command": probe["argv"][-1] = "import os; os.system('bin/test')"
    elif change == "returncode": probe["returncode"] = 1
    else:
        output = [dataset.benchmark.strict_json_loads(line) for line in probe["stdout"].splitlines()]
        if change == "python_version": output[0]["python_version"] = "3.9.99"
        elif change == "import_path": output[0]["sympy_file"] = "/installed/sympy/__init__.py"
        elif change == "help_failure": output[1]["help_returncode"] = 1
        else: output.pop()
        probe["stdout"] = "\n".join(dataset.canonical(row).decode() for row in output) + "\n"
    probe_path.write_bytes(dataset.canonical(probe) + b"\n")
    receipt["runtime_probe_sha256"] = evidence["probe_sha256"] = dataset.sha(probe_path.read_bytes())
    _rewrite_receipt(evidence, receipt)
    with pytest.raises(dataset.SupplementalDatasetError, match="runtime"):
        controlled.build_controlled_manifest(output_path=path, **kwargs)


@pytest.mark.parametrize("changed", ["receipt", "probe", "runner"])
def test_runtime_source_bytes_are_rechecked_at_load(study, changed):
    kwargs, path = study
    controlled.build_controlled_manifest(output_path=path, **kwargs)
    evidence = kwargs["runtime"][0]
    receipt = _receipt(evidence)
    source = (Path(evidence["runtime_receipt_path"]) if changed == "receipt" else
              Path(receipt["runtime_probe_path"]) if changed == "probe" else
              Path(receipt["base_checkout"]) / "bin/test")
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(dataset.SupplementalDatasetError, match="runtime"):
        controlled.load_controlled_rows(path, kwargs["cache_root"],
            expected_sha256=dataset.sha(path.read_bytes()), root=kwargs["root"])


@pytest.mark.parametrize("help_text,accepted", [
    ("Usage: test [options ...] [tests ...]\n  --help\n", True),
    ("usage: test [-h] [-v]\n  -h, --help  show this help message and exit\n", True),
    ("usage: another-command [-h]\n  --help\n", False),
])
def test_optparse_and_argparse_public_help_are_supported(study, help_text, accepted):
    kwargs, path = study
    evidence = kwargs["runtime"][0]
    receipt = _receipt(evidence)
    probe_path = Path(receipt["runtime_probe_path"])
    probe = dataset.benchmark.strict_json_loads(probe_path.read_text())
    output = [dataset.benchmark.strict_json_loads(line) for line in probe["stdout"].splitlines()]
    output[1]["help_stdout"] = help_text
    probe["stdout"] = "\n".join(dataset.canonical(row).decode() for row in output) + "\n"
    probe_path.write_bytes(dataset.canonical(probe) + b"\n")
    receipt["runtime_probe_sha256"] = evidence["probe_sha256"] = dataset.sha(probe_path.read_bytes())
    _rewrite_receipt(evidence, receipt)
    if accepted:
        assert controlled.build_controlled_manifest(output_path=path, **kwargs)["status"] == "FROZEN"
    else:
        with pytest.raises(dataset.SupplementalDatasetError, match="runtime"):
            controlled.build_controlled_manifest(output_path=path, **kwargs)
