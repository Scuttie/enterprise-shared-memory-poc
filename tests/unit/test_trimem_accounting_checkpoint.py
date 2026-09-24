import json

import pytest

from enterprise_memory.trimem.accounting import (
    CallRecord,
    RawEvidenceLedger,
    RunAccounting,
    sha256_bytes,
)
from enterprise_memory.trimem.checkpoint import (
    CheckpointMismatch,
    FileCheckpointStore,
    RuntimeCheckpoint,
)


ZERO = "0" * 64


def _digest(value: str) -> str:
    return sha256_bytes(value.encode())


def test_actual_call_accounting_separates_paid_replay_and_call_kind():
    accounting = RunAccounting()
    accounting.add_call(
        CallRecord(
            task_id="t1",
            arm="M2",
            step_no=1,
            call_kind="decompose",
            logical_call_id="t1:decompose:1",
            provider="replay",
            model="fixture-v1",
            input_tokens=11,
            output_tokens=7,
            wall_time_ms=3,
            prompt_hash=_digest("prompt-1"),
            response_hash=_digest("response-1"),
            paid=False,
        )
    )
    accounting.add_call(
        CallRecord(
            task_id="t1",
            arm="M2",
            step_no=2,
            call_kind="solve",
            logical_call_id="t1:solve:2",
            provider="paid-provider",
            model="model-revision",
            input_tokens=23,
            output_tokens=5,
            wall_time_ms=9,
            prompt_hash=_digest("prompt-2"),
            response_hash=_digest("response-2"),
            paid=True,
            active_node_id="subtask-a",
        )
    )
    summary = accounting.summary()
    assert summary["model_gateway_calls"] == 2
    assert summary["paid_model_calls"] == 1
    assert summary["actual_input_tokens"] == 34
    assert summary["by_call_kind"]["decompose"]["calls"] == 1
    assert summary["by_call_kind"]["solve"]["paid_calls"] == 1


def test_duplicate_call_attempt_is_refused():
    kwargs = dict(
        task_id="t",
        arm="M0",
        step_no=1,
        call_kind="solve",
        logical_call_id="stable",
        provider="replay",
        model="fixture",
        input_tokens=1,
        output_tokens=1,
        wall_time_ms=1,
        prompt_hash=_digest("p"),
        response_hash=_digest("r"),
    )
    accounting = RunAccounting()
    accounting.add_call(CallRecord(**kwargs))
    with pytest.raises(ValueError, match="duplicate"):
        accounting.add_call(CallRecord(**kwargs))


def test_raw_evidence_is_blob_addressed_hash_chained_and_reopenable(tmp_path):
    ticks = iter(["2026-08-31T00:00:00Z", "2026-08-31T00:00:01Z"])
    ledger = RawEvidenceLedger(tmp_path / "evidence", clock=lambda: next(ticks))
    blob = ledger.put_blob("full grader stdout")
    first = ledger.append("grader_started", {"task_id": "t1"})
    second = ledger.append("grader_finished", {"stdout": blob})

    assert first["previous_event_hash"] == ZERO
    assert second["previous_event_hash"] == first["event_hash"]
    assert (tmp_path / "evidence" / "blobs" / blob["sha256"]).read_text() == "full grader stdout"
    assert ledger.verify([blob["sha256"]])["events"] == 2

    reopened = RawEvidenceLedger(tmp_path / "evidence")
    assert reopened.last_event_hash == second["event_hash"]
    assert reopened.next_sequence == 3
    assert reopened.verified_suffix(first["event_hash"]) == (second,)
    assert reopened.verified_suffix(ZERO) == (first, second)


def test_evidence_suffix_requires_a_verified_ancestor(tmp_path):
    ledger = RawEvidenceLedger(
        tmp_path / "evidence", clock=lambda: "2026-08-31T00:00:00Z"
    )
    ledger.append("one", {"safe": True})

    with pytest.raises(ValueError, match="not an ancestor"):
        ledger.verified_suffix(_digest("unrelated"))
    with pytest.raises(ValueError, match="sha256"):
        ledger.verified_suffix("not-a-digest")


def test_ledger_detects_event_tampering(tmp_path):
    root = tmp_path / "evidence"
    ledger = RawEvidenceLedger(root, clock=lambda: "2026-08-31T00:00:00Z")
    ledger.append("one", {"safe": True})
    record = json.loads((root / "events.jsonl").read_text())
    record["payload"]["safe"] = False
    (root / "events.jsonl").write_text(json.dumps(record) + "\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        RawEvidenceLedger(root)


def test_ledger_rejects_duplicate_key_even_when_last_value_preserves_event_hash(tmp_path):
    root = tmp_path / "evidence-duplicate-key"
    ledger = RawEvidenceLedger(root, clock=lambda: "2026-08-31T00:00:00Z")
    ledger.append("one", {"safe": True})
    path = root / "events.jsonl"
    raw = path.read_text(encoding="utf-8")
    assert '"event_type":"one"' in raw
    path.write_text(
        raw.replace(
            '"event_type":"one"',
            '"event_type":"attacker","event_type":"one"',
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        RawEvidenceLedger(root)


def test_ledger_discovers_and_rejects_tampered_referenced_blob(tmp_path):
    root = tmp_path / "evidence"
    ledger = RawEvidenceLedger(root, clock=lambda: "2026-08-31T00:00:00Z")
    blob = ledger.put_blob("original full response")
    ledger.append("model_response", {"response": blob})
    (root / "blobs" / blob["sha256"]).write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="blob hash mismatch"):
        ledger.verify()


def _checkpoint(generation, previous=ZERO, next_step=1, config=None):
    return RuntimeCheckpoint(
        run_id="run-1",
        task_id="task-1",
        arm="M2",
        generation=generation,
        next_step_no=next_step,
        state="RUNNING",
        active_node_id="subtask-a",
        graph_snapshot={"nodes": ["subtask-a"]},
        workspace_state={"kind": "test", "files": {"src/a.py": "value = 1\n"}},
        injected_memory_ids=(),
        injected_bytes=0,
        injection_ledger=(),
        tool_history=(),
        completed_call_ids=(),
        accounting={"calls": [], "tools": [], "graders": []},
        config_hashes=config or {"runtime": _digest("lock")},
        evidence_event_hash=_digest("event"),
        previous_checkpoint_hash=previous,
        created_at="2026-08-31T00:00:00Z",
    )


def test_checkpoint_is_atomic_chained_and_runtime_lock_is_fail_closed(tmp_path):
    store = FileCheckpointStore(tmp_path / "checkpoints")
    first = _checkpoint(1)
    first_hash = store.save(first)
    loaded = store.load("run-1", required_config_hashes=first.config_hashes)
    assert loaded.content_hash == first_hash

    second = _checkpoint(2, previous=first_hash, next_step=2)
    store.save(second)
    assert store.load("run-1", required_config_hashes=second.config_hashes).generation == 2

    with pytest.raises(CheckpointMismatch, match="runtime lock changed"):
        store.load("run-1", required_config_hashes={"runtime": _digest("different")})
    with pytest.raises(CheckpointMismatch, match="generation"):
        store.save(_checkpoint(4, previous=second.content_hash, next_step=3))


def test_checkpoint_detects_payload_tampering(tmp_path):
    store = FileCheckpointStore(tmp_path / "checkpoints")
    store.save(_checkpoint(1))
    path = tmp_path / "checkpoints" / "run-1.json"
    payload = json.loads(path.read_text())
    payload["workspace_state"]["files"]["src/a.py"] = "malicious = True\n"
    path.write_text(json.dumps(payload))
    with pytest.raises(CheckpointMismatch, match="digest mismatch"):
        store.load("run-1", required_config_hashes=None)


def test_checkpoint_rejects_duplicate_keys_even_with_matching_byte_sidecar(tmp_path):
    store = FileCheckpointStore(tmp_path / "checkpoints-duplicate-key")
    store.save(_checkpoint(1))
    path = tmp_path / "checkpoints-duplicate-key" / "run-1.json"
    sidecar = path.with_suffix(".sha256")
    raw = path.read_text(encoding="utf-8")
    assert '"state":"RUNNING"' in raw
    raw = raw.replace(
        '"state":"RUNNING"',
        '"state":"DONE","state":"RUNNING"',
    )
    path.write_text(raw, encoding="utf-8")
    sidecar.write_text(sha256_bytes(raw.encode("utf-8")) + "\n", encoding="ascii")
    with pytest.raises(CheckpointMismatch, match="strict/canonical"):
        store.load("run-1", required_config_hashes=None)
