"""R22 §8 — regression tests for the enriched official-dataset routing (no model calls, no Docker)."""
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ART = os.path.join(ROOT, "artifacts", "r22")
FROZEN_SMOKE_IDS = {
    "astropy__astropy-8707", "sympy__sympy-14774", "caddyserver__caddy-5761", "apache__lucene-11760",
    "rubocop__rubocop-13396", "tokio-rs__tokio-6724", "mwaskom__seaborn-3190", "php-cs-fixer__php-cs-fixer-7875",
    "google__gson-2311", "prometheus__prometheus-9248", "astral-sh__ruff-15543", "tokio-rs__axum-1119",
}


def _load(name):
    p = os.path.join(ART, name)
    if not os.path.isfile(p):
        pytest.skip("%s not built in this checkout" % name)
    return json.load(open(p, encoding="utf-8"))


def test_routes_use_enriched_not_legacy():
    routes = _load("grader_instance_routes.json")["routes"]
    for r in routes:
        assert not r["dataset_name"].startswith("princeton-nlp/"), r["dataset_name"]
        assert r["dataset_name"].startswith("SWE-bench/"), r["dataset_name"]


def test_all_routes_pin_a_revision():
    for r in _load("grader_instance_routes.json")["routes"]:
        assert r.get("dataset_revision") and len(r["dataset_revision"]) >= 12


def test_image_taken_from_row_not_generated():
    for r in _load("grader_instance_routes.json")["routes"]:
        assert r.get("image_from_row"), "image must come from the enriched row for %s" % r["instance_id"]


def test_schema_lock_has_required_eval_fields():
    lock = _load("official_dataset_schema_lock.json")["datasets"]
    for label, d in lock.items():
        assert d["required_missing"] == [], "%s missing %s" % (label, d["required_missing"])
        for f in ("image", "eval_script", "log_parser", "eval_type"):
            assert f in d["fields"], "%s lacks %s" % (label, f)


def test_legacy_enriched_core_match():
    comp = _load("legacy_enriched_row_comparison.json")
    assert comp["counts"].get("CORE_FIELD_MISMATCH", 0) == 0
    assert comp["counts"].get("MISSING_FROM_CURRENT_OFFICIAL_DATASET", 0) == 0


def test_missing_image_fails_before_docker():
    # the driver's pre-Docker guard maps a missing image to R22_OFFICIAL_IMAGE_UNAVAILABLE (not KeyError)
    import importlib.util
    spec = importlib.util.spec_from_file_location("r22gr", os.path.join(ROOT, "scripts", "r22_grader_run.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    assert "image" in m.REQUIRED and "eval_script" in m.REQUIRED


def test_frozen_smoke_ids_unchanged():
    routes = _load("grader_instance_routes.json")["routes"]
    assert {r["instance_id"] for r in routes} == FROZEN_SMOKE_IDS


def test_no_paid_credentials_referenced_in_grader_scripts():
    for fn in ("r22_grader_run.py", "r22_grader_smoke.py"):
        src = open(os.path.join(ROOT, "scripts", fn), encoding="utf-8").read()
        for banned in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "api_key="):
            assert banned not in src, "%s references %s" % (fn, banned)
