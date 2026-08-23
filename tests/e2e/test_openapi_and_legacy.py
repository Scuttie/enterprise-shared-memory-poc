"""OpenAPI snapshot + legacy-API quarantine regression (P5 §3,§21). Imports only (no running services)."""
import os
import json
import pytest
from enterprise_memory.service.app import create_app, SolveRequest

_SNAP = os.path.join(os.path.dirname(__file__), "..", "..", "openapi_v1.json")
FORBIDDEN = {"org_id", "user_id", "installation_id", "patch", "test_passed", "editable_paths",
             "test_command", "hidden_test", "permissions", "arm", "experiment_arm", "experiment_id",
             "retrieval_policy"}


def test_openapi_snapshot_matches():
    spec = create_app().openapi()
    paths = sorted(spec["paths"].keys())
    snap = json.load(open(_SNAP, encoding="utf-8"))
    assert paths == snap["paths"]
    assert SolveRequest.model_json_schema() == snap["solve_request"]


def test_solve_schema_hides_authoritative_fields():
    sr = SolveRequest.model_json_schema()
    assert sr.get("additionalProperties") is False
    assert not (set(sr.get("properties", {})) & FORBIDDEN)


def test_all_15_endpoints_present():
    paths = set(create_app().openapi()["paths"].keys())
    expected = {"/health/live", "/health/ready", "/version", "/v1/solve", "/v1/jobs/{job_id}",
                "/v1/jobs/{job_id}/events", "/v1/jobs/{job_id}/cancel", "/v1/private/episodes",
                "/v1/private/episodes/{episode_id}", "/v1/contracts/candidates", "/v1/contracts",
                "/v1/contracts/{contract_id}", "/v1/memories/search", "/v1/feedback",
                "/v1/memories/{memory_id}"}
    assert expected <= paths and len(paths) == 15


def test_legacy_insecure_app_refused_in_ci():
    from enterprise_memory.serving.api import create_offline_demo_app, LegacyAppRefused
    saved = os.environ.get("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = "production"
    try:
        with pytest.raises(LegacyAppRefused):
            create_offline_demo_app()
    finally:
        if saved is not None:
            os.environ["ENVIRONMENT"] = saved
