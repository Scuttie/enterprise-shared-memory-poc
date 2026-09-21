"""Public synthetic selection and loader contracts; no model, grader or container."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2] / "scripts")]
import trimem_skhynix_architecture_dataset as dataset
import trimem_skhynix_architecture_plan as plan
import trimem_skhynix_architecture_scale_dataset as scale


def write(path, value):
    path.write_bytes(plan.canonical(value) + b"\n")
    return {"path": str(path), "sha256": plan.file_sha(path)}


def row(repo, number):
    families = ("queryset sql database migration", "parse regex string token", "shape indexing array broadcast", "validation invalid valueerror typeerror")
    return {"instance_id": repo.replace("/", "__") + f"-{number}", "repo": repo,
        "base_commit": f"{number:040x}", "created_at": "2020-01-01T00:00:00Z",
        "problem_statement": f"Public issue {repo} number {number}: {families[number % 4]}.\n",
        "version": "1.0", "environment_setup_commit": "d" * 40}


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    repositories = sorted(scale.ALLOCATIONS)
    final = [row(repositories[index % 12], index) for index in range(500)]
    candidates = [row(repo, 1000 + index) for repo in repositories
        for index in range(sum(scale.ALLOCATIONS[repo][1:]) + (0 if repo == "pallets/flask" else 3))]
    result = {"root": tmp_path, "candidates": {item["instance_id"]: item for item in candidates},
        "final": {item["instance_id"]: item for item in final}}
    for name, rows, pin in (("training", candidates, dataset.TRAINING_SOURCE), ("evaluation", final, plan.EVALUATION_SOURCE)):
        path = tmp_path / (name + ".parquet")
        # A forbidden column is present on disk but never requested by the public reader.
        pq.write_table(pa.Table.from_pylist([{**item, "unrequested_fixture_column": "UNREAD_PRIVATE_SENTINEL"} for item in rows]), path)
        metadata = {**pin, "bytes": path.stat().st_size, "sha256": plan.file_sha(path)}
        tasks = sorted((dataset._descriptor(item) for item in rows), key=lambda item: item["instance_id"])
        if name == "training":
            monkeypatch.setattr(dataset, "TRAINING_SOURCE", metadata)
        else:
            monkeypatch.setattr(plan, "EVALUATION_SOURCE", metadata)
            monkeypatch.setattr(plan, "EVALUATION_TASKS_SHA256", plan.sha(plan.canonical(tasks)))
        result[name] = write(tmp_path / (name + ".json"), {"schema": plan.INVENTORY_SCHEMA,
            "dataset": {**metadata, "path": str(path)}, "tasks": tasks})
    proposal = dataset.propose_training_enrollment(result["evaluation"], result["training"])
    original = dataset.build_architecture_manifest(result["evaluation"], result["training"],
        training_instance_ids=proposal["instance_ids"], output=tmp_path / "original24.json")
    result["original"] = {key: original[key] for key in ("path", "sha256")}
    result["targets"] = scale._read(result["original"])["targets"]
    return result


def build(inputs):
    protocol = scale.build_scale_protocol(inputs["original"], output=inputs["root"] / "protocol.json")
    manifests = {size: scale.build_scale_manifest(protocol, training_size=size, output=inputs["root"] / f"dataset-{size}.json")
                 for size in (24, 120, 240)}
    return protocol, manifests


def test_selection_preserves_exact_nested_prefixes_and_caps_with_dev_reserved_first(inputs):
    first = scale.select_public_tasks(inputs["targets"], inputs["candidates"], inputs["final"])
    second = scale.select_public_tasks(list(inputs["targets"]), dict(reversed(list(inputs["candidates"].items()))), inputs["final"])
    assert first == second
    stages = first["training_instance_ids_by_size"]
    assert stages["24"] == [target["instance_id"] for target in inputs["targets"] if target["role"] == "TRAINING"]
    assert stages["240"][:120] == stages["120"] and stages["120"][:24] == stages["24"]
    assert {size: len(values) for size, values in stages.items()} == {"24": 24, "120": 120, "240": 240}
    dev = first["development_instance_ids"]
    assert len(dev) == 60 and not set(dev) & set(stages["240"])
    for repo, (n120, n240, ndev) in scale.ALLOCATIONS.items():
        assert sum(inputs["candidates"][identity]["repo"] == repo for identity in stages["120"]) == n120
        assert sum(inputs["candidates"][identity]["repo"] == repo for identity in stages["240"]) == n240
        assert sum(inputs["candidates"][identity]["repo"] == repo for identity in dev) == ndev
    for repo in scale.ALLOCATIONS:
        per_repo = [identity for identity in stages["240"] if inputs["candidates"][identity]["repo"] == repo]
        assert [first["training_owner_by_instance"][identity] for identity in per_repo] == [1 + index % 2 for index in range(len(per_repo))]
    families = Counter(first["candidate_signals"][identity]["family"] for identity in stages["240"])
    assert len(families) >= 4 and min(families.values()) >= 3


def test_different_fixed_seed_changes_only_new_sources_not_mandatory_or_final(inputs):
    a = scale.select_public_tasks(inputs["targets"], inputs["candidates"], inputs["final"], seed="declared-a")
    b = scale.select_public_tasks(inputs["targets"], inputs["candidates"], inputs["final"], seed="declared-b")
    assert a["training_instance_ids_by_size"]["24"] == b["training_instance_ids_by_size"]["24"]
    assert a["final_evaluation_instance_ids"] == b["final_evaluation_instance_ids"]
    assert a["development_instance_ids"] != b["development_instance_ids"]


def test_public_reader_allowlist_full_source_reproduction_and_all_bank_views(inputs, monkeypatch):
    original_read = pq.read_table
    calls = []

    def public_read(path, **kwargs):
        assert kwargs.get("columns") and set(kwargs["columns"]) <= set(scale.POLICY["public_fields"])
        calls.append(kwargs["columns"])
        return original_read(path, **kwargs)

    monkeypatch.setattr(pq, "read_table", public_read)
    monkeypatch.setattr(dataset, "_private_grader_row", lambda *args: pytest.fail("Private boundary invoked"))
    protocol, manifests = build(inputs)
    assert scale.verify_scale_protocol(protocol) == scale._read(protocol)
    for size, reference in manifests.items():
        targets, rows, manifest = scale.load_scale_rows(reference["path"], expected_sha256=reference["sha256"])
        assert len(targets) == len(rows) == size + 560
        assert manifest["training_count"] == size and manifest["evaluation_count"] == 560
        assert Counter(item.get("evaluation_scope") for item in targets) == {None: size, "DEVELOPMENT": 60, "FINAL": 500}
        assert b"UNREAD_PRIVATE_SENTINEL" not in plan.canonical([manifest, rows])
        for scope in (None, "DEVELOPMENT", "FINAL"):
            target = next(item for item in targets if item.get("evaluation_scope") == scope)
            adapted = scale.public_grader_manifest(target, manifest)
            assert adapted["schema"] == dataset.SCHEMA and adapted["targets"] == [target]
            assert adapted["datasets"][target["role"]]["dataset_id"] == target["source_dataset_id"]
    assert len(calls) >= 10


@pytest.mark.parametrize("role,expected", [("TRAINING", 120), ("EVALUATION", 560)])
def test_role_filter_preserves_descriptor_alignment(inputs, role, expected):
    _, manifests = build(inputs)
    reference = manifests[120]
    targets, rows, manifest = scale.load_scale_rows(reference["path"], expected_sha256=reference["sha256"], role=role)
    assert len(targets) == len(rows) == expected
    assert all(target["role"] == role and target["instance_id"] in rows for target in targets)
    assert len(manifest["targets"]) == 680


def test_structural_validation_performs_no_parquet_reads(inputs, monkeypatch):
    _, manifests = build(inputs)
    monkeypatch.setattr(pq, "read_table", lambda *args, **kwargs: pytest.fail("Structural validation decoded Parquet"))
    value = scale._read(manifests[240])
    assert scale.validate_scale_manifest(value) == value


def test_normalized_and_near_duplicate_groups_use_public_text_only():
    original = " ".join(f"token{index}" for index in range(100))
    near = original.replace("token99", "changed99")
    different = " ".join(f"other{index}" for index in range(100))
    rows = {"a": {"repo": "r/repo", "problem_statement": original},
            "b": {"repo": "r/repo", "problem_statement": near},
            "c": {"repo": "r/repo", "problem_statement": "  " + near.upper() + " \n"},
            "d": {"repo": "r/repo", "problem_statement": different}}
    mapping, groups, edges = scale.duplicate_groups(rows)
    assert mapping["a"] == mapping["b"] == mapping["c"] != mapping["d"]
    assert groups == [{"group_id": mapping["a"], "instance_ids": ["a", "b", "c"]}]
    assert {edge["reason"] for edge in edges} == {"NORMALIZED_EXACT", "PUBLIC_SHINGLE_JACCARD_GE_85_PERCENT"}


def test_final_near_clone_is_excluded_without_changing_locked_final_targets(inputs):
    candidates, final = deepcopy(inputs["candidates"]), deepcopy(inputs["final"])
    target = next(identity for identity, value in final.items() if value["repo"] == "django/django")
    candidate = [identity for identity, value in candidates.items() if value["repo"] == "django/django"][-1]
    body = " ".join(f"word{index}" for index in range(100))
    final[target]["problem_statement"] = body
    candidates[candidate]["problem_statement"] = body.replace("word99", "changed99")
    result = scale.select_public_tasks(inputs["targets"], candidates, final)
    assert candidate in result["excluded_candidate_final_overlap_ids"]
    assert candidate not in result["training_instance_ids_by_size"]["240"] + result["development_instance_ids"]
    assert result["final_evaluation_instance_ids"] == [item["instance_id"] for item in inputs["targets"] if item["role"] == "EVALUATION"]


def test_mandatory_final_near_collision_blocks_without_dropping_original_source(inputs):
    candidates, final = deepcopy(inputs["candidates"]), deepcopy(inputs["final"])
    source = next(item["instance_id"] for item in inputs["targets"] if item["role"] == "TRAINING")
    target = next(identity for identity, value in final.items() if value["repo"] == candidates[source]["repo"])
    body = " ".join(f"word{index}" for index in range(100))
    final[target]["problem_statement"] = body
    candidates[source]["problem_statement"] = body.replace("word99", "changed99")
    with pytest.raises(scale.ScaleDatasetError, match="mandatory original source"):
        scale.select_public_tasks(inputs["targets"], candidates, final)


def test_shortage_is_explicit_and_does_not_relax_flask_or_total_quotas(inputs):
    rows = deepcopy(inputs["candidates"])
    flask = [identity for identity, value in rows.items() if value["repo"] == "pallets/flask"]
    del rows[flask[-1]]
    with pytest.raises(scale.ScaleDatasetError, match="Insufficient independent public candidates for pallets/flask"):
        scale.select_public_tasks(inputs["targets"], rows, inputs["final"])


def test_selection_rejects_nonpublic_columns_before_using_them(inputs):
    rows = deepcopy(inputs["candidates"])
    rows[next(iter(rows))]["unrequested_fixture_column"] = "UNREAD_PRIVATE_SENTINEL"
    with pytest.raises(scale.ScaleDatasetError, match="non-public"):
        scale.select_public_tasks(inputs["targets"], rows, inputs["final"])


@pytest.mark.parametrize("change", ["target", "owner", "prefix", "scope", "instruction", "readiness"])
def test_rehashed_tampered_protocol_does_not_create_an_authoritative_view(inputs, change):
    reference, _ = build(inputs)
    value = scale._read(reference)
    if change == "target":
        value["targets"][0]["target_id"] = "foreign--task"
    elif change == "owner":
        first = value["original_training_instance_ids"][0]
        value["training_owner_by_instance"][first] = 2
    elif change == "prefix":
        value["training_instance_ids_by_size"]["120"][0:2] = reversed(value["training_instance_ids_by_size"]["120"][0:2])
    elif change == "scope":
        value["targets"][240]["evaluation_scope"] = "FINAL"
    elif change == "instruction":
        value["public_task_descriptors"][0]["instruction"] = "invented public task"
    else:
        value["runtime_compatibility_verified"] = True
    tampered = write(inputs["root"] / "tampered.json", value)
    with pytest.raises(ValueError):
        scale.build_scale_manifest(tampered, training_size=240, output=inputs["root"] / "never-created.json")
    assert not (inputs["root"] / "never-created.json").exists()


def test_changed_manifest_reference_source_bytes_and_immutable_output_fail_closed(inputs):
    protocol, manifests = build(inputs)
    reference = manifests[24]
    with pytest.raises(ValueError):
        scale.build_scale_manifest(protocol, training_size=120, output=Path(reference["path"]))
    value = scale._read(reference)
    changed = deepcopy(value)
    changed["targets"][0]["base_commit"] = "e" * 40
    with pytest.raises(scale.ScaleDatasetError, match="protocol-derived"):
        scale.validate_scale_manifest(changed)
    source = Path(scale._read(inputs["training"])["dataset"]["path"])
    with source.open("ab") as stream:
        stream.write(b"changed source bytes")
    with pytest.raises(ValueError, match="Dataset bytes differ"):
        scale.load_scale_rows(reference["path"], expected_sha256=reference["sha256"])


def test_foreign_grader_target_rejected_without_any_private_decoder(inputs, monkeypatch):
    _, manifests = build(inputs)
    manifest = scale._read(manifests[24])
    monkeypatch.setattr(dataset, "_private_grader_row", lambda *args: pytest.fail("Private decoder invoked"))
    foreign = {**manifest["targets"][0], "instance_id": "foreign__repo-1"}
    with pytest.raises(scale.ScaleDatasetError, match="outside"):
        scale.public_grader_manifest(foreign, manifest)
