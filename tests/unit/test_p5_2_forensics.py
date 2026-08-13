"""P5.2 §2 — offline forensics on PERSISTED P5.1 data (no Solar). Reproduces the aggregate facts from the
committed P5.1 calibration results and the deterministic view reconstructions used in the forensic reports.
Also asserts the P5.1 retrieval defect (per-cell singleton bank) structurally."""
import json
import os

from benchmarks.p5_1_static import generate
from experiments.p5_1 import memory_bank as MB
from enterprise_memory.service.private_view import compile_private_view
from enterprise_memory.contracts import codec

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RES = os.path.join(ROOT, "artifacts", "experiments", "p5_1", "results", "calibration_results.json")


def _results():
    return json.load(open(RES, encoding="utf-8"))["results"]


def test_m1_single_failure_is_schema_2():
    r = _results()
    m1_fail = [x for x in r if x["arm"] == "M1" and x["pass1"] == 0]
    assert len(m1_fail) == 1
    assert m1_fail[0]["family_id"] == "fam_calibration_schema_2"
    assert m1_fail[0]["domain"] == "schema"


def test_m1_failed_where_more_explicit_views_succeeded():
    # M2/M3/M4 for the same family all passed; only M1 (prose-only private view) failed -> failure correlates
    # with the least-explicit view rendering (evidence for P1_VIEW_INFORMATION_LOSS).
    r = _results()
    fam = "fam_calibration_schema_2"
    by = {x["arm"]: x["pass1"] for x in r if x["family_id"] == fam}
    assert by["M1"] == 0 and by["M2"] == 1 and by["M3"] == 1 and by["M4"] == 1


def test_view_explicitness_gap_reconstructed():
    fam = {f.family_id: f for f in generate("calibration", 4)}["fam_calibration_schema_2"]
    priv = MB.private_canonical(fam, "repo-x")
    item = {"id": "e", "owner": "u", "hash": "h", "repo_id": None, "body": priv["private_note"]}
    pview, _ = compile_private_view(item, requester_id="u", repo_id="r")
    gview, _ = codec.retrieval_text_and_path_scope(MB.canonical_of(MB.governed_contract("o", "r", fam,
                                                                                        "shared_governed")))
    # governed view exposes the literal formula; the private view renders it as prose requiring substitution
    assert ("value ** %d" % fam.world_constant) in gview
    assert '"convention_constant"' not in pview and "prior verified note" in pview


def test_s1_s4_injected_but_zero_pass_and_patches_not_persisted():
    r = _results()
    for arm in ("S1", "S4"):
        cells = [x for x in r if x["arm"] == arm]
        assert len(cells) == 16
        assert sum(x["injected"] for x in cells) == 16          # always injected (singleton bank)
        assert sum(x["pass1"] for x in cells) == 0              # never helped
        assert all("patch" not in x and "raw_response" not in x for x in cells)  # patches NOT persisted


def test_p5_1_retrieval_was_singleton_per_cell():
    # structural defect: P5.1 seeded exactly one memory per cell org, so retrieval had no competing pool and no
    # abstention threshold could ever separate relevant from irrelevant.
    import inspect
    from experiments.p5_1 import seeding
    src = inspect.getsource(seeding.seed_cell)
    assert "records = []" in src and "max_injected" not in src   # single-record seeding, no pool, no threshold
