from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_grader_smoke_authority as authority  # noqa: E402
import trimem_grader_smoke_finalization as finalization  # noqa: E402


def _pretty(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _record(index: int, *, authoritative: bool = True) -> dict[str, object]:
    resolved = index % 2 == 0
    return {
        "schema": authority.TERMINAL_CELL_SCHEMA,
        "target_id": f"repository-{index // 2}/instance-{index // 2}:{index % 2}",
        "order_index": index,
        "probe": "GOLD" if index % 2 == 0 else "NOOP_BASELINE",
        "grader_invoked": True,
        "container_started": True,
        "harness_completed": True,
        "final_report_generated": True,
        "official_tests_executed": True,
        "raw_test_evidence_captured": True,
        "submitted_patch_identity_verified": True,
        "digest_verified": True,
        "adapter_normalized": True,
        "authoritative_cell": authoritative,
        "official_final_report_resolved": resolved,
        "scientific_resolved": resolved,
        "primary_failure": None,
        "secondary_evidence_failures": [],
        "execution_status": "SUCCESS",
        "actual_accounting": {
            "grader_calls": 1,
            "grader_containers": 1,
            "model_calls": 0,
        },
        "execution_evidence": {"raw": f"restricted-{index}"},
        "evidence": {"digest": f"sha256:{index:064x}"},
        # Production records carry adapter-specific extension fields.  The
        # rollback must preserve them even though they are not base-schema keys.
        "adapter_extension": {"nested": [index, "한글", {"kept": True}]},
    }


def _tree(root: Path, *, authority_states: list[bool] | None = None) -> list[Path]:
    states = authority_states or [True] * authority.EXPECTED_TERMINAL_RECORD_COUNT
    paths: list[Path] = []
    for index, state in enumerate(states):
        task = root / f"{index:03d}-target-{index}"
        task.mkdir(parents=True)
        path = task / f"target-{index}.result.json"
        path.write_bytes(_pretty(_record(index, authoritative=state)))
        paths.append(path)
    (root / "restricted-evidence").mkdir()
    (root / "restricted-evidence" / "raw.bin").write_bytes(
        b"\x00private-evidence\xff\r\n"
    )
    (root / "smoke-execution-summary.json").write_bytes(b'{"before":true}\n')
    return paths


def _read_records(root: Path) -> list[dict[str, object]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(root.glob("**/*.result.json"))
    ]


def _rollback(root: Path) -> dict[str, object]:
    return authority.rollback_authoritative_terminal_records(
        root,
        cause_stage="public_artifact",
        failure_taxonomy="aggregate_failures",
        reason="public artifact validation failed",
    )


def _set_authority(root: Path, state: bool) -> None:
    for path in sorted(root.glob("**/*.result.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        value["authoritative_cell"] = state
        path.write_bytes(_pretty(value))


def _recover(root: Path, *, stage: str = "authority_finalization") -> dict[str, object] | None:
    taxonomy = authority.CAUSE_TAXONOMY[stage]
    return authority.recover_interrupted_authority_transaction(
        root,
        cause_stage=stage,
        failure_taxonomy=taxonomy,
        reason="campaign authority finalization did not succeed",
    )


def test_total_rollback_preserves_semantics_and_binds_raw_record_hashes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "official-smoke"
    paths = _tree(root)
    before_raw = {path.relative_to(root).as_posix(): path.read_bytes() for path in paths}
    before_values = {
        relative: json.loads(raw.decode("utf-8"))
        for relative, raw in before_raw.items()
    }
    unrelated = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in (root / "restricted-evidence" / "raw.bin", root / "smoke-execution-summary.json")
    }

    evidence = _rollback(root)

    records = _read_records(root)
    assert len(records) == 12
    assert all(record["authoritative_cell"] is False for record in records)
    assert evidence["status"] == "AUTHORITY_REVOKED"
    assert evidence["cause"] == {
        "stage": "public_artifact",
        "failure_taxonomy": "aggregate_failures",
        "reason": "public artifact validation failed",
    }
    assert [binding["order_index"] for binding in evidence["records"]] == list(range(12))

    for binding in evidence["records"]:
        relative = binding["relative_path"]
        after_raw = (root / Path(relative)).read_bytes()
        after_value = json.loads(after_raw.decode("utf-8"))
        expected_value = copy.deepcopy(before_values[relative])
        expected_value["authoritative_cell"] = False
        assert after_value == expected_value
        assert binding["before_raw_sha256"] == hashlib.sha256(
            before_raw[relative]
        ).hexdigest()
        assert binding["before_raw_bytes"] == len(before_raw[relative])
        assert binding["after_raw_sha256"] == hashlib.sha256(after_raw).hexdigest()
        assert binding["after_raw_bytes"] == len(after_raw)

    for relative, raw in unrelated.items():
        assert (root / Path(relative)).read_bytes() == raw
    evidence_path = root / authority.DEFAULT_EVIDENCE_RELATIVE_PATH
    assert authority.read_authority_rollback_evidence(evidence_path) == evidence
    assert evidence_path.read_bytes() == authority._canonical_file_bytes(evidence)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing", "exactly 12"),
        ("mixed", "authority state differs"),
        ("already_false", "authority state differs"),
        ("duplicate_target", "duplicate terminal target"),
        ("duplicate_order", "order indexes are missing or duplicated"),
        ("malformed", "duplicate JSON key"),
    ],
)
def test_invalid_record_sets_fail_before_any_mutation(
    tmp_path: Path, mutation: str, match: str
) -> None:
    root = tmp_path / mutation
    paths = _tree(root)
    if mutation == "missing":
        paths[-1].unlink()
        paths = paths[:-1]
    elif mutation == "mixed":
        value = json.loads(paths[-1].read_text(encoding="utf-8"))
        value["authoritative_cell"] = False
        paths[-1].write_bytes(_pretty(value))
    elif mutation == "already_false":
        for path in paths:
            value = json.loads(path.read_text(encoding="utf-8"))
            value["authoritative_cell"] = False
            path.write_bytes(_pretty(value))
    elif mutation == "duplicate_target":
        value = json.loads(paths[1].read_text(encoding="utf-8"))
        value["target_id"] = _record(0)["target_id"]
        paths[1].write_bytes(_pretty(value))
    elif mutation == "duplicate_order":
        value = json.loads(paths[1].read_text(encoding="utf-8"))
        value["order_index"] = 0
        paths[1].write_bytes(_pretty(value))
    elif mutation == "malformed":
        paths[4].write_bytes(b'{"schema":"first","schema":"second"}\n')
    original = {path: path.read_bytes() for path in paths}

    with pytest.raises(authority.AuthorityRollbackError, match=match):
        _rollback(root)

    assert {path: path.read_bytes() for path in paths} == original
    assert not (root / authority.DEFAULT_EVIDENCE_RELATIVE_PATH).exists()


def test_stage_taxonomy_mismatch_and_unknown_stage_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "mismatch"
    paths = _tree(root)
    before = [path.read_bytes() for path in paths]

    with pytest.raises(authority.AuthorityRollbackError, match="stage/taxonomy"):
        authority.rollback_authoritative_terminal_records(
            root,
            cause_stage="image_cleanup",
            failure_taxonomy="aggregate_failures",
            reason="cleanup failed",
        )
    with pytest.raises(authority.AuthorityRollbackError, match="unsupported"):
        authority.rollback_authoritative_terminal_records(
            root,
            cause_stage="model_execution",
            failure_taxonomy="aggregate_failures",
            reason="must not run",
        )

    assert [path.read_bytes() for path in paths] == before
    assert all(record["authoritative_cell"] is True for record in _read_records(root))


def test_failed_second_directory_rename_restores_the_complete_true_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "rename-failure"
    _tree(root)
    real_replace = authority.os.replace
    calls = 0

    def fail_replacement(source: object, destination: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second rename failure")
        real_replace(source, destination)

    monkeypatch.setattr(authority.os, "replace", fail_replacement)
    with pytest.raises(authority.AuthorityRollbackError, match="directory swap"):
        _rollback(root)

    assert calls == 3
    assert root.is_dir()
    assert all(record["authoritative_cell"] is True for record in _read_records(root))
    assert not (root / authority.DEFAULT_EVIDENCE_RELATIVE_PATH).exists()


def test_shadow_tree_uses_same_filesystem_hardlinks_and_detaches_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "hardlink-shadow"
    paths = _tree(root)
    original = {path.relative_to(root): path.read_bytes() for path in paths}
    real_link = authority.os.link
    linked: list[tuple[object, object]] = []

    def observed_link(source: object, destination: object, *args: object, **kwargs: object) -> None:
        linked.append((source, destination))
        real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(authority.os, "link", observed_link)
    _rollback(root)

    # Twelve terminal files plus the two unrelated files are linked instead
    # of byte-copied.  The terminal links are then detached before mutation.
    assert len(linked) >= 14
    for relative, raw in original.items():
        value = json.loads(raw.decode("utf-8"))
        value["authoritative_cell"] = False
        assert (root / relative).read_bytes() == _pretty(value)


def test_existing_evidence_or_noncanonical_terminal_bytes_are_never_overwritten(
    tmp_path: Path,
) -> None:
    existing_root = tmp_path / "existing"
    existing_paths = _tree(existing_root)
    evidence_path = existing_root / authority.DEFAULT_EVIDENCE_RELATIVE_PATH
    evidence_path.write_bytes(b"immutable-existing-evidence")
    with pytest.raises(authority.AuthorityRollbackError, match="already exists"):
        _rollback(existing_root)
    assert evidence_path.read_bytes() == b"immutable-existing-evidence"
    assert all(record["authoritative_cell"] is True for record in _read_records(existing_root))

    noncanonical_root = tmp_path / "noncanonical"
    noncanonical_paths = _tree(noncanonical_root)
    value = json.loads(noncanonical_paths[0].read_text(encoding="utf-8"))
    noncanonical_paths[0].write_bytes(json.dumps(value).encode("utf-8"))
    before = [path.read_bytes() for path in noncanonical_paths]
    with pytest.raises(authority.AuthorityRollbackError, match="noncanonical"):
        _rollback(noncanonical_root)
    assert [path.read_bytes() for path in noncanonical_paths] == before


def test_cli_reads_reason_without_bom_and_reports_only_public_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "cli"
    _tree(root)
    reason = tmp_path / "reason.txt"
    reason.write_bytes(b"external aggregate failed\n")

    assert authority.main([
        "--output-root",
        str(root),
        "--cause-stage",
        "external_aggregate",
        "--failure-taxonomy",
        "aggregate_failures",
        "--reason-file",
        str(reason),
    ]) == 0

    captured = capsys.readouterr().out
    public = json.loads(captured)
    assert public == {
        "schema": authority.ROLLBACK_EVIDENCE_SCHEMA,
        "status": "AUTHORITY_REVOKED",
        "terminal_record_count": 12,
        "evidence_relative_path": authority.DEFAULT_EVIDENCE_RELATIVE_PATH.as_posix(),
        "payload_sha256": authority.read_authority_rollback_evidence(
            root / authority.DEFAULT_EVIDENCE_RELATIVE_PATH
        )["payload_sha256"],
    }
    assert "external aggregate failed" not in captured


def test_recovery_restores_false_tree_when_promotion_stopped_between_renames(
    tmp_path: Path,
) -> None:
    root = tmp_path / "results"
    _tree(root, authority_states=[False] * 12)
    transaction = tmp_path / ".results.authority-promotion.interrupted"
    transaction.mkdir()
    original = transaction / "original"
    replacement = transaction / "replacement"
    shutil.copytree(root, replacement)
    _set_authority(replacement, True)
    root.replace(original)

    evidence = _recover(root)

    assert evidence is not None
    assert evidence["schema"] == authority.RECOVERY_EVIDENCE_SCHEMA
    assert evidence["canonical_state_before"] == "ABSENT"
    assert evidence["canonical_state_after"] == "FALSE"
    assert evidence["recovery_source"] == "promotion_original"
    assert evidence["promotion_transaction_count"] == 1
    assert not transaction.exists()
    assert all(record["authoritative_cell"] is False for record in _read_records(root))
    recovery_path = root / authority.DEFAULT_RECOVERY_EVIDENCE_RELATIVE_PATH
    assert authority.read_authority_recovery_evidence(recovery_path) == evidence


def test_recovery_replaces_committed_true_tree_from_promotion_backup(
    tmp_path: Path,
) -> None:
    root = tmp_path / "results"
    _tree(root, authority_states=[False] * 12)
    transaction = tmp_path / ".results.authority-promotion.interrupted"
    transaction.mkdir()
    original = transaction / "original"
    root.replace(original)
    shutil.copytree(original, root)
    _set_authority(root, True)

    evidence = _recover(root)

    assert evidence is not None
    assert evidence["canonical_state_before"] == "TRUE"
    assert evidence["recovery_source"] == "promotion_original"
    assert not transaction.exists()
    assert all(record["authoritative_cell"] is False for record in _read_records(root))


def test_recovery_restores_rollback_replacement_when_rollback_was_interrupted(
    tmp_path: Path,
) -> None:
    root = tmp_path / "results"
    _tree(root, authority_states=[True] * 12)
    transaction = tmp_path / ".results.authority-rollback.interrupted"
    transaction.mkdir()
    original = transaction / "original"
    replacement = transaction / "replacement"
    shutil.copytree(root, replacement)
    _set_authority(replacement, False)
    root.replace(original)

    evidence = _recover(root, stage="public_artifact")

    assert evidence is not None
    assert evidence["canonical_state_before"] == "ABSENT"
    assert evidence["recovery_source"] == "rollback_replacement"
    assert evidence["rollback_transaction_count"] == 1
    assert evidence["cause"]["failure_taxonomy"] == "aggregate_failures"
    assert not transaction.exists()
    assert all(record["authoritative_cell"] is False for record in _read_records(root))


def test_complete_false_tree_without_summary_is_not_guessed_as_finalization_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "results"
    _tree(root, authority_states=[False] * 12)
    (root / "smoke-execution-summary.json").unlink()

    evidence = _recover(root)

    assert evidence is None
    assert not (root / authority.DEFAULT_RECOVERY_EVIDENCE_RELATIVE_PATH).exists()
    assert all(record["authoritative_cell"] is False for record in _read_records(root))


def test_partial_false_tree_is_owned_by_cell_terminal_and_needs_no_authority_action(
    tmp_path: Path,
) -> None:
    root = tmp_path / "results"
    paths = _tree(root, authority_states=[False] * 12)
    paths[-1].unlink()

    assert _recover(root) is None
    assert not (root / authority.DEFAULT_RECOVERY_EVIDENCE_RELATIVE_PATH).exists()


def test_complete_failed_false_tree_is_owned_by_its_terminal_primary_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "results"
    paths = _tree(root, authority_states=[False] * 12)
    terminal = json.loads(paths[-1].read_text(encoding="utf-8"))
    terminal["primary_failure"] = {
        "stage": "adapter_semantic_normalization",
        "status": "adapter_contract_failed",
        "reason": "synthetic terminal-owned failure",
    }
    terminal["scientific_resolved"] = None
    terminal["execution_status"] = "FAILURE"
    paths[-1].write_bytes(_pretty(terminal))

    assert _recover(root) is None
    assert not (root / authority.DEFAULT_RECOVERY_EVIDENCE_RELATIVE_PATH).exists()


def test_recovery_rejects_ambiguous_or_wrong_role_transaction_trees(
    tmp_path: Path,
) -> None:
    ambiguous_root = tmp_path / "ambiguous" / "results"
    _tree(ambiguous_root, authority_states=[False] * 12)
    for suffix in ("one", "two"):
        transaction = ambiguous_root.parent / f".results.authority-promotion.{suffix}"
        transaction.mkdir()
    with pytest.raises(authority.AuthorityRollbackError, match="ambiguous"):
        _recover(ambiguous_root)

    wrong_root = tmp_path / "wrong-role" / "results"
    _tree(wrong_root, authority_states=[True] * 12)
    transaction = wrong_root.parent / ".results.authority-promotion.wrong"
    transaction.mkdir()
    shutil.copytree(wrong_root, transaction / "original")
    with pytest.raises(authority.AuthorityRollbackError, match="state differs"):
        _recover(wrong_root)


def test_recovery_is_idempotent_after_evidence_commit(tmp_path: Path) -> None:
    root = tmp_path / "results"
    _tree(root, authority_states=[False] * 12)
    (root / "smoke-execution-summary.json").unlink()
    finalization.write_finalization_journal(
        root,
        status=finalization.AUTHORITY_PROMOTION_STARTED,
    )
    first = _recover(root)
    stale_lock = tmp_path / ".results.authority-rollback.lock"
    stale_lock.write_bytes(b"interrupted\n")
    second = _recover(root)

    assert first == second
    assert first is not None
    assert not stale_lock.exists()


def test_failed_recovery_swap_retains_false_source_and_next_call_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "results"
    _tree(root, authority_states=[False] * 12)
    transaction = tmp_path / ".results.authority-promotion.interrupted"
    transaction.mkdir()
    original = transaction / "original"
    root.replace(original)
    shutil.copytree(original, root)
    _set_authority(root, True)
    real_replace = authority.os.replace
    injected = False

    def fail_false_source_once(source: object, destination: object) -> None:
        nonlocal injected
        if (
            not injected
            and Path(source) == original
            and Path(destination) == root
        ):
            injected = True
            raise OSError("injected false-source rename failure")
        real_replace(source, destination)

    monkeypatch.setattr(authority.os, "replace", fail_false_source_once)
    with pytest.raises(authority.AuthorityRollbackError, match="directory swap"):
        _recover(root)

    assert injected
    assert root.is_dir()
    assert original.is_dir()
    assert all(record["authoritative_cell"] is True for record in _read_records(root))
    assert all(record["authoritative_cell"] is False for record in _read_records(original))

    monkeypatch.setattr(authority.os, "replace", real_replace)
    evidence = _recover(root)
    assert evidence is not None
    assert all(record["authoritative_cell"] is False for record in _read_records(root))
    assert not transaction.exists()


def test_finalization_journal_distinguishes_scientific_rejection_from_promotion(
    tmp_path: Path,
) -> None:
    root = tmp_path / "results"
    _tree(root, authority_states=[False] * 12)
    (root / "smoke-execution-summary.json").unlink()
    journal = finalization.write_finalization_journal(
        root,
        status=finalization.SCIENTIFIC_AGGREGATE_REJECTED,
        failures=("gold mismatch",),
    )
    assert finalization.read_finalization_journal(root) == journal

    evidence = _recover(root)
    assert evidence is not None
    assert evidence["cause"] == {
        "stage": "scientific_aggregate",
        "failure_taxonomy": "aggregate_failures",
        "reason": (
            "campaign-finalization journal records scientific aggregate rejection"
        ),
    }


def test_finalization_journal_allows_only_started_to_committed_transition(
    tmp_path: Path,
) -> None:
    root = tmp_path / "results"
    _tree(root, authority_states=[False] * 12)
    started = finalization.write_finalization_journal(
        root,
        status=finalization.AUTHORITY_PROMOTION_STARTED,
    )
    assert started["failure_taxonomy"] == "infrastructure_failures"
    _set_authority(root, True)
    committed = finalization.write_finalization_journal(
        root,
        status=finalization.AUTHORITY_PROMOTION_COMMITTED,
    )
    assert committed["failure_taxonomy"] is None
    assert committed["terminal_authority"] is True
    assert finalization.read_finalization_journal(root) == committed

    other = tmp_path / "invalid-transition"
    _tree(other, authority_states=[True] * 12)
    with pytest.raises(
        finalization.FinalizationJournalError,
        match="no started predecessor",
    ):
        finalization.write_finalization_journal(
            other,
            status=finalization.AUTHORITY_PROMOTION_COMMITTED,
        )


def test_finalization_journal_rejects_terminal_tampering(tmp_path: Path) -> None:
    root = tmp_path / "results"
    paths = _tree(root, authority_states=[False] * 12)
    finalization.write_finalization_journal(
        root,
        status=finalization.AUTHORITY_PROMOTION_STARTED,
    )
    value = json.loads(paths[0].read_text(encoding="utf-8"))
    value["adapter_extension"]["nested"].append("tampered")
    paths[0].write_bytes(_pretty(value))

    with pytest.raises(
        finalization.FinalizationJournalError,
        match="terminal bytes differ",
    ):
        finalization.read_finalization_journal(root)
