from __future__ import annotations

import hashlib
import io
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import trimem_atomic_evidence as atomic_evidence  # noqa: E402
import trimem_evidence_inventory as evidence_inventory  # noqa: E402
import trimem_grader_smoke_failure_closure as failure_closure  # noqa: E402
import trimem_grader_smoke_stage_evidence as stage_evidence  # noqa: E402
import trimem_official_grader as official_grader  # noqa: E402


def _approval() -> dict[str, str]:
    return {
        "approval_artifact_sha256": "a" * 64,
        "approved_request_sha256": "b" * 64,
        "approved_workflow_run_id": "1",
        "approved_workflow_run_attempt": "1",
        "freeze_sha256": "c" * 64,
        "git_head": "d" * 40,
        "phase": "GRADER_SMOKE",
    }


class _ShortWriter:
    def __init__(self, stream: io.FileIO, maximum: int = 3):
        self._stream = stream
        self._maximum = maximum

    def write(self, value: memoryview) -> int:
        return self._stream.write(value[: self._maximum])


def test_atomic_writer_retries_short_writes_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "evidence.json"
    raw = b'{"complete":true}\n'
    real_write_all = atomic_evidence._write_all

    def short_write_all(stream: io.FileIO, value: bytes) -> None:
        real_write_all(_ShortWriter(stream), value)

    monkeypatch.setattr(atomic_evidence, "_write_all", short_write_all)
    atomic_evidence.atomic_write_bytes(target, raw)

    assert target.read_bytes() == raw
    assert not list(tmp_path.glob(".trimem-*"))


@pytest.mark.parametrize(
    "publisher",
    ("pre_cell", "inventory", "failure_receipt", "restricted_blob"),
)
def test_evidence_publishers_never_publish_a_short_temporary_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    publisher: str,
) -> None:
    def short_then_fail(stream: io.FileIO, raw: bytes) -> None:
        stream.write(raw[: max(1, len(raw) // 2)])
        stream.flush()
        raise OSError("injected short temporary write")

    monkeypatch.setattr(atomic_evidence, "_write_all", short_then_fail)
    if publisher == "pre_cell":
        final = tmp_path / "pre-cell-failure-evidence.json"

        def publish() -> object:
            return stage_evidence.write_pre_cell_failure_evidence(
                tmp_path,
                approval_binding=_approval(),
                stage="EXEC_GATE",
                reason="injected failure",
            )

    elif publisher == "inventory":
        restricted = tmp_path / "restricted"
        restricted.mkdir()
        (restricted / "complete.bin").write_bytes(b"complete")
        final = tmp_path / "evidence-inventory.json"

        def publish() -> object:
            return evidence_inventory.write_inventory(
                restricted,
                final,
                root_label="grader_smoke_exec",
            )

    elif publisher == "failure_receipt":
        final = tmp_path / "failure-receipt.json"

        def publish() -> object:
            return failure_closure._write_exclusive(final, {"complete": True})

    else:
        gateway = object.__new__(official_grader.OfficialHarnessGraderGateway)
        gateway.output_root = tmp_path.resolve()
        gateway._restricted_root = tmp_path / "restricted-evidence"
        final = gateway._restricted_root / (
            "stage-kind-" + hashlib.sha256(b"complete").hexdigest() + ".bin"
        )

        def publish() -> object:
            return gateway._restricted_blob("stage", "kind", b"complete")

    with pytest.raises(OSError, match="injected short temporary write"):
        publish()

    assert not final.exists()
    assert not list(final.parent.glob(".trimem-*"))


def test_atomic_replace_failure_preserves_previous_valid_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "evidence.json"
    previous = b'{"valid":"previous"}\n'
    target.write_bytes(previous)

    def fail_replace(_source: object, _target: object) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(atomic_evidence.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        atomic_evidence.atomic_write_bytes(
            target,
            b'{"valid":"new"}\n',
            replace_existing=True,
        )

    assert target.read_bytes() == previous
    assert not list(tmp_path.glob(".trimem-*"))


def test_atomic_temporary_write_failure_preserves_previous_valid_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "evidence.bin"
    previous = b"previous-valid-bytes"
    target.write_bytes(previous)

    def short_then_fail(stream: io.FileIO, raw: bytes) -> None:
        stream.write(raw[:1])
        raise OSError("injected writer failure")

    monkeypatch.setattr(atomic_evidence, "_write_all", short_then_fail)
    with pytest.raises(OSError, match="injected writer failure"):
        atomic_evidence.atomic_write_bytes(
            target,
            b"replacement-valid-bytes",
            replace_existing=True,
        )

    assert target.read_bytes() == previous
    assert not list(tmp_path.glob(".trimem-*"))


def test_atomic_publication_fsyncs_destination_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[Path] = []
    monkeypatch.setattr(
        atomic_evidence,
        "_fsync_directory",
        lambda directory: observed.append(directory),
    )

    target = tmp_path / "evidence.bin"
    atomic_evidence.atomic_write_bytes(target, b"complete")

    assert target.read_bytes() == b"complete"
    assert observed
    assert set(observed) == {tmp_path.resolve()}


def test_atomic_create_only_publication_never_overwrites_existing_evidence(
    tmp_path: Path,
) -> None:
    target = tmp_path / "evidence.bin"
    target.write_bytes(b"immutable")

    with pytest.raises(FileExistsError, match="refusing to overwrite evidence"):
        atomic_evidence.atomic_write_bytes(target, b"different")

    assert target.read_bytes() == b"immutable"
    assert not list(tmp_path.glob(".trimem-*"))
