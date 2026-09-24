"""Public synthetic broker traces; no models, grader, or production bank access."""
from copy import deepcopy

import pytest

from enterprise_memory.trimem.accounting import canonical_bytes
import trimem_skhynix_architecture_learning as learning
import trimem_skhynix_architecture_memory as memory
import trimem_skhynix_architecture_repair_windows as windows
from test_trimem_skhynix_architecture_learning import inputs, captured, ARGV
from test_trimem_skhynix_architecture_scale_reflection import proposals


def loaded(ctx):
    with learning._session(ctx.root, mutable=False) as (_, enrollment, registry, _):
        available = learning._available_captures(ctx.root, registry)
    index = windows.build_repair_window_index(available)
    return enrollment, available, [row["capture_id"] for row in index["representatives"]]


def tree_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_exact_window_context_aliases_mapping_and_no_bank_mutation(inputs):
    captured(inputs)
    enrollment, available, selected = loaded(inputs)
    original, mapping = learning._reflection_documents(inputs.root, enrollment, available, sorted(selected))
    before = tree_bytes(inputs.root)
    public, compact_mapping = windows.build_public_repair_windows(inputs.root, enrollment, available, selected)
    assert tree_bytes(inputs.root) == before
    assert compact_mapping == mapping
    assert public["schema"] == original["schema"] == "skhynix/native-architecture-public-reflection/2.0"
    assert public["publisher_map_sha256"] == memory._hash(mapping)
    assert public["projection"]["policy"] == windows.POLICY
    assert public["later_mutations"] == original["later_mutations"]
    assert len({source["task_group"] for source in public["sources"]}) == 2
    for source, prior in zip(public["sources"], original["sources"]):
        assert source["checkpoint"] == prior["checkpoint"]
        assert source["checkpoint_reference"] == prior["checkpoint_reference"]
        assert source["repair_window"]["required_step_numbers"] == [5, 6, 7]
        assert source["repair_window"]["context_step_numbers"] == [3]
        assert source["repair_window"]["omitted_prefix_rows"] == 1
        assert source["repair_window"]["original_prefix_remains_verification_authority"]
        identity = mapping["sources"][source["source_alias"]]["capture_id"]
        capture = available[identity][1]
        original_rows = {row["step_no"]: row for row in capture["history"]}
        rows = [public["trace_rows"][index] for index in source["history_row_indices"]]
        assert [row["step_no"] for row in rows] == [3, 5, 6, 7]
        assert all(row["task_id"] == source["task_group"] for row in rows)
        for row in rows:
            expected = {**original_rows[row["step_no"]], "task_id": source["task_group"],
                        "original_row_sha256": memory._hash(original_rows[row["step_no"]])}
            assert row == expected
        assert memory._argv(rows[1]) == memory._argv(rows[-1]) == ARGV
        assert memory._test_outcome(rows[1]) == "RED"
        assert memory._test_outcome(rows[-1]) == "GREEN"


def test_existing_ingestion_still_verifies_full_original_captures_and_promotes(inputs):
    captured(inputs)
    enrollment, available, selected = loaded(inputs)
    public, mapping = windows.build_public_repair_windows(inputs.root, enrollment, available, selected)
    with learning._session(inputs.root) as (root, _, registry, _):
        reference = learning._retain_reflection(root, registry, public, mapping,
            inputs.tmp / "repair-window-export.json", windows.LIMIT)
    # The unchanged test proposal cites the optional earlier read at step 3.
    result = learning.ingest_proposals(inputs.root, proposals(inputs, reference), reflection_reference=reference)
    receipt = memory._read(result["path"])
    assert receipt["failures"] == []
    assert receipt["promotions_added"] == 1
    assert receipt["outcomes"][0]["status"] == "PROMOTED"


@pytest.mark.parametrize("limit", [0, 1])
def test_context_can_be_omitted_but_never_truncated(inputs, limit):
    captured(inputs)
    enrollment, available, selected = loaded(inputs)
    public, _ = windows.build_public_repair_windows(inputs.root, enrollment, available, selected,
        max_context_bytes_per_source=limit)
    for source in public["sources"]:
        assert source["repair_window"]["context_step_numbers"] == []
        assert source["repair_window"]["available_pre_red_context_windows"] == 1
        assert source["repair_window"]["omitted_pre_red_context_windows"] == 1
        rows = [public["trace_rows"][index] for index in source["history_row_indices"]]
        assert [row["step_no"] for row in rows] == [5, 6, 7]
        assert all("result_payload" in row for row in rows)


def test_global_cap_omits_optional_context_and_never_required_rows(inputs):
    captured(inputs)
    enrollment, available, selected = loaded(inputs)
    baseline, _ = windows.build_public_repair_windows(inputs.root, enrollment, available, selected,
        max_context_reads_per_source=0)
    cap = len(canonical_bytes(baseline)) + 1
    public, _ = windows.build_public_repair_windows(inputs.root, enrollment, available, selected, max_bytes=cap)
    assert len(canonical_bytes(public)) + 1 <= cap
    assert all(source["repair_window"]["context_step_numbers"] == [] for source in public["sources"])
    assert all(source["repair_window"]["required_step_numbers"] == [5, 6, 7] for source in public["sources"])


def test_insufficient_mandatory_cap_fails_without_writes(inputs):
    captured(inputs)
    enrollment, available, selected = loaded(inputs)
    before = tree_bytes(inputs.root)
    with pytest.raises(learning.LearningError, match="mandatory repair windows exceed"):
        windows.build_public_repair_windows(inputs.root, enrollment, available, selected, max_bytes=1024)
    assert tree_bytes(inputs.root) == before


def test_index_retains_all_representatives_without_owner_or_outcome_filter(inputs):
    captured(inputs)
    _, available, _ = loaded(inputs)
    first = windows.build_repair_window_index(available)
    assert len(first["representatives"]) == 2
    assert all(row["cutoff_step"] == 7 for row in first["representatives"])
    assert first["candidate_shapes_are_verification"] is False
    assert first["semantic_transfer_claimed"] is False
    assert first["official_outcomes_used"] is False
    changed = deepcopy(available)
    for index, value in enumerate(changed.values()):
        value[1]["official_outcome"] = ["RESOLVED", "UNRESOLVED", "UNDETERMINED"][index % 3]
    assert windows.build_repair_window_index(changed) == first
    for value in changed.values():
        value[1]["owner_user_id"] = "same-logical-owner"
    second = windows.build_repair_window_index(changed)
    assert len(second["representatives"]) == 2
    assert len({row["contributor_group"] for row in second["representatives"]}) == 1
    assert len({row["task_group"] for row in second["representatives"]}) == 2


def test_index_and_export_are_deterministic_under_input_order(inputs):
    captured(inputs)
    enrollment, available, selected = loaded(inputs)
    reversed_available = dict(reversed(list(available.items())))
    assert windows.build_repair_window_index(available) == windows.build_repair_window_index(reversed_available)
    assert windows.build_public_repair_windows(inputs.root, enrollment, available, selected) == (
        windows.build_public_repair_windows(inputs.root, enrollment, reversed_available, list(reversed(selected))))


def test_all_intervening_rows_are_required_even_noncertifying_read_operations(inputs):
    captured(inputs)
    enrollment, available, selected = loaded(inputs)
    available = deepcopy(available)
    identity = selected[0]
    capture = available[identity][1]
    original = deepcopy(capture["history"])
    read = deepcopy(original[0])
    read["step_no"] = 6
    capture["history"] = original[:3] + [read] + original[3:]
    capture["history"][-2]["step_no"] = 7
    capture["history"][-1]["step_no"] = 8
    # This test isolates the pure projection input contract. Production callers
    # obtain available from the existing full-capture authority validator.
    public, _ = windows.build_public_repair_windows(inputs.root, enrollment, available, [identity],
        max_context_reads_per_source=0)
    source = public["sources"][0]
    assert source["repair_window"]["required_step_numbers"] == [5, 6, 7, 8]
    rows = [public["trace_rows"][index] for index in source["history_row_indices"]]
    assert [row["step_no"] for row in rows] == [5, 6, 7, 8]
    assert rows[1]["request_payload"] == read["request_payload"]
    assert rows[1]["result_payload_omission"]["sha256"] == read["result"]["sha256"]
    assert source["omitted_read_outputs"]["count"] == 1


@pytest.mark.parametrize("change", ["green_argv", "intervening_command", "evaluation", "task", "owner"])
def test_invalid_or_unenrolled_windows_are_rejected(inputs, change):
    captured(inputs)
    enrollment, available, selected = loaded(inputs)
    available = deepcopy(available)
    identity = selected[0]
    capture = available[identity][1]
    if change == "green_argv":
        capture["history"][-1]["request_payload"]["arguments"]["argv"] = ["python", "-m", "pytest", "another_test.py"]
    elif change == "intervening_command":
        extra = deepcopy(capture["history"][-3])
        extra["step_no"] = 6
        extra["request_payload"]["arguments"]["argv"] = ["python", "-c", "print('unaccounted')"]
        capture["history"][-2]["step_no"] = 7
        capture["history"][-1]["step_no"] = 8
        capture["history"].insert(-2, extra)
    elif change == "evaluation":
        capture["receipt"]["phase"] = "EVALUATION_QUARANTINE"
    elif change == "task":
        capture["task"]["task_id"] = "not-enrolled"
    else:
        capture["owner_user_id"] = "not-enrolled-owner"
    with pytest.raises(learning.LearningError):
        windows.build_public_repair_windows(inputs.root, enrollment, available, [identity])


@pytest.mark.parametrize("arguments", [{"max_bytes": True}, {"max_bytes": 190001},
    {"max_context_bytes_per_source": -1}, {"max_context_reads_per_source": True},
    {"max_context_reads_per_source": 9}])
def test_invalid_limits_fail_before_reading_any_source(arguments):
    with pytest.raises(learning.LearningError):
        windows.build_public_repair_windows(None, {}, {}, [], **arguments)
