import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deveval_prepare.py"
spec = importlib.util.spec_from_file_location("deveval_prepare_tested", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture_rows():
    return [
        {"namespace": f"synthetic_{i}_{j}", "project_path": project,
         "dependency": {"cross_file": ["synthetic_dependency"]}, "tests": ["synthetic_test"]}
        for i, project in enumerate(module.PROJECTS) for j in range(4)
    ]


def test_selection_is_order_and_outcome_independent():
    rows = fixture_rows()
    first = [r["namespace"] for r in module.select_controls(rows)]
    for i, row in enumerate(rows):
        row["unrelated_outcome"] = i % 2 == 0
    second = [r["namespace"] for r in module.select_controls(rows[::-1])]
    assert first == second
    assert len(set(first)) == 10
    assert all(sum(r["project_path"] == project for r in module.select_controls(rows)) == 2 for project in module.PROJECTS)


def test_no_substitution_when_selected_project_has_insufficient_cross_file_tasks():
    rows = fixture_rows()
    for row in rows[:3]:
        row["dependency"]["cross_file"] = []
    with pytest.raises(ValueError, match="INSUFFICIENT"):
        module.select_controls(rows)


@pytest.mark.parametrize("path", ["../escape", "/absolute", "Source_Code/a/../../outside", r"Source_Code\unsafe", "C:/absolute", "a\x00b"])
def test_unsafe_archive_paths_rejected(path):
    with pytest.raises(ValueError, match="UNSAFE"):
        module.safe_relative(path)


def test_reference_receipt_cannot_be_overwritten(tmp_path):
    target = tmp_path / "receipt.json"
    module.write_new(target, {"value": 1})
    before = target.read_bytes()
    module.write_new(target, {"value": 1})
    with pytest.raises(ValueError, match="EXISTING_RECEIPT_DIFFERS"):
        module.write_new(target, {"value": 2})
    assert target.read_bytes() == before


def test_failed_collection_is_not_confirmed_assertion_negative(tmp_path):
    path = tmp_path / "result.xml"
    path.write_text('<testsuites><testsuite tests="1" failures="0" errors="1"><testcase><error>synthetic private payload</error></testcase></testsuite></testsuites>')
    result = module.xml_counts(path)
    assert result["errors"] == 1 and result["negative_marker_seen"] is False
    assert "private payload" not in json.dumps(result)
    path.write_text(f'<testsuites><testsuite tests="1" failures="1" errors="0"><testcase><failure>E   AssertionError: {module.NEGATIVE_MARKER}</failure></testcase></testsuite></testsuites>')
    result = module.xml_counts(path)
    assert result["failures"] == 1 and result["negative_marker_seen"] is True


def test_fixture_assertion_is_distinct_from_unrelated_collection_error(tmp_path):
    path = tmp_path / "result.xml"
    path.write_text(f'<testsuites><testsuite tests="1" failures="0" errors="1"><testcase><error>E   AssertionError: {module.NEGATIVE_MARKER}</error></testcase></testsuite></testsuites>')
    result = module.xml_counts(path)
    assert result["confirmed_negative_error_nodes"] == 1
    assert result["unconfirmed_error_nodes"] == 0
    path.write_text(f'<testsuites><testsuite tests="1" failures="0" errors="1"><testcase><error>raise AssertionError("{module.NEGATIVE_MARKER}")\nE   ImportError: unrelated</error></testcase></testsuite></testsuites>')
    result = module.xml_counts(path)
    assert result["negative_marker_seen"] is False
    assert result["unconfirmed_error_nodes"] == 1


def test_only_generated_cache_and_egg_metadata_exempt_from_working_source_hash():
    assert module.is_generated_build_metadata("Source_Code/X/Y/.pytest_cache/v/cache/lastfailed")
    assert module.is_generated_build_metadata("Source_Code/X/Y/package.egg-info/SOURCES.txt")
    assert not module.is_generated_build_metadata("Source_Code/X/Y/tests/test_file.py")
    assert not module.is_generated_build_metadata("Source_Code/X/Y/src/cache.py")


def test_source_archive_mismatch_blocks_before_destination_creation(tmp_path):
    (tmp_path / "Source_Code.tar.gz").write_bytes(b"untrusted")
    destination = tmp_path / "extracted"
    with pytest.raises(ValueError, match="SOURCE_ARCHIVE_HASH_MISMATCH"):
        module.extract_selected(tmp_path, destination)
    assert not destination.exists()
