"""REALBENCH-R2 §1 audit invariants: R4 is not an oracle, the heuristic transfer is marked superseded, the
production benchmark path does not use DeterministicTestEmbedder, and the frozen R1 result is untouched."""
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_r4_renamed_not_oracle():
    from experiments.realbench_r1 import arms as A
    assert A.R4.code == "R4"
    assert A.R4.name == "ALWAYS_INJECT_TOP1"
    assert "ORACLE" not in A.R4.name
    src = (ROOT / "experiments" / "realbench_r1" / "arms.py").read_text(encoding="utf-8")
    # the module must explicitly disclaim oracle/ceiling language for R4
    assert "NOT an oracle" in src


def test_heuristic_transfer_superseded():
    from experiments.realbench_r1 import analysis as AN
    assert "SUPERSEDED" in (AN.transfer.__doc__ or "")
    assert hasattr(AN, "transfer_forensic")


def test_forensic_classifier_has_unrelated_and_failure_classes():
    from experiments import patch_forensics as PF
    for c in ("UNRELATED_IMPLEMENTATION_ERROR", "PARSER_OR_APPLY_FAILURE", "GRADER_FAILURE"):
        assert c in PF.CLASSES


def test_runner_gates_not_hardcoded_true():
    src = (ROOT / "scripts" / "realbench_r1_run.py").read_text(encoding="utf-8")
    # the C4/C5 pass values must be computed predicates, not the literal True
    assert '"C4_retrieval": {"pass": (m0_inj == 0)' in src
    assert "_frozen_split_hash()" in src


def test_frozen_r1_result_untouched():
    # the sealed main result must still carry the original numbers (byte-level seal is ci-realbench-seal;
    # here we assert the headline values did not drift).
    p = ROOT / "artifacts" / "realbench_r1" / "results" / "main_results.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["arms"]["R0"]["pass1"] == 0.575
    assert round(d["primary"]["diff"], 3) == 0.05
    assert d["split_hash"].startswith("c3cbf496")
