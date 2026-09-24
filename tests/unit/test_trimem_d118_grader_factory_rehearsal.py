from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_d118_grader_factory_rehearsal as rehearsal


def test_rehearsal_rejects_credentials_before_loading_evidence(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="protected credentials"):
        rehearsal.build_rehearsal(
            preflight_path=tmp_path / "missing.json",
            harness_root=tmp_path / "harnesses",
            dataset_cache_root=tmp_path / "datasets",
            output_root=tmp_path / "output",
            environment={"OPENAI_API_KEY": "must-not-be-read"},
        )


def test_rehearsal_exercises_factory_and_journal_preflight_for_all_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preflight = {
        "environment_identity_sha256": "a" * 64,
        "python_loader": {"python_binary": "preflight-python3.11"},
    }
    targets = [
        {
            "benchmark_id": "swebench_verified",
            "instance_id": f"owner__repo-{index}",
            "target_id": f"target-{index:02d}",
        }
        for index in range(12)
    ]
    rows = {target["instance_id"]: {"row": target["target_id"]} for target in targets}
    images = {target["instance_id"]: {"image": target["target_id"]} for target in targets}
    observed_factory: list[str] = []
    observed_journal: list[str] = []

    monkeypatch.setattr(rehearsal, "read_json", lambda _path: preflight)
    monkeypatch.setattr(
        rehearsal,
        "validate_official_harness_loader_preflight_evidence",
        lambda value: value,
    )
    monkeypatch.setattr(
        rehearsal, "validate_preflight_harness_root_binding", lambda *_args: None
    )
    monkeypatch.setattr(
        rehearsal, "load_frozen_rows", lambda *_args: (targets, rows)
    )
    monkeypatch.setattr(rehearsal, "image_entries", lambda **_kwargs: (images, ()))

    def factory(target: dict[str, object], *_args: object, **_kwargs: object) -> object:
        observed_factory.append(str(target["target_id"]))
        return SimpleNamespace(target=target)

    class Journal:
        def __init__(self, gateway: object, _journal: object, **kwargs: object) -> None:
            assert kwargs["python_binary"] == "preflight-python3.11"
            self.gateway = gateway

        def _preflight_sha256(self) -> str:
            target_id = str(self.gateway.target["target_id"])
            observed_journal.append(target_id)
            return rehearsal.sha256_bytes(rehearsal.canonical_bytes(preflight))

    monkeypatch.setattr(rehearsal, "grader_factory", factory)
    monkeypatch.setattr(rehearsal, "JournaledGraderGateway", Journal)
    monkeypatch.setattr(rehearsal, "TerminalInvocationJournal", lambda _path: object())

    report = rehearsal.build_rehearsal(
        preflight_path=tmp_path / "preflight.json",
        harness_root=tmp_path / "harnesses",
        dataset_cache_root=tmp_path / "datasets",
        output_root=tmp_path / "output",
        environment={},
    )

    expected = [str(target["target_id"]) for target in targets]
    assert observed_factory == expected
    assert observed_journal == expected
    assert report["status"] == "PASS"
    assert report["target_count"] == 12
    assert report["journal_preflight_checks"] == 12
    assert report["model_calls"] == 0
    assert report["grader_containers"] == 0


def test_synthetic_inputs_cover_all_official_adapter_routes() -> None:
    targets, rows, images = rehearsal._synthetic_inputs()

    assert [target["benchmark_id"] for target in targets] == [
        "swebench_verified",
        "multi_swe_bench_mini",
        "multi_swe_bench_flash",
    ]
    assert len(rows) == 3
    assert len(images) == 3
    for target in targets:
        instance_id = target["instance_id"]
        assert target["source_row_sha256"] == rehearsal.canonical_row_hash(
            rows[instance_id]
        )
