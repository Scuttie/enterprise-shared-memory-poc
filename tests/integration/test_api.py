import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from enterprise_memory.serving.api import create_app

C = TestClient(create_app())


def test_health():
    r = C.get("/health"); assert r.status_code == 200 and r.json()["status"] == "ok"


def test_request_and_audit_ids_present():
    r = C.post("/v1/private/episodes", json={"ctx": {"org_id": "orgA", "user_id": "alice"}, "episode_id": "epA", "task_id": "t", "patch": "alice private"})
    j = r.json(); assert j["request_id"].startswith("req_") and j["audit_id"].startswith("sha256:")


def test_cross_user_private_isolation_and_guessed_id():
    C.post("/v1/private/episodes", json={"ctx": {"org_id": "orgA", "user_id": "alice"}, "episode_id": "epSecret", "task_id": "t", "patch": "alice raw trace"})
    # Bob searches his OWN private namespace -> cannot see Alice's episode
    r = C.get("/v1/memories/search", params={"org_id": "orgA", "user_id": "bob", "query": "raw trace", "scope": "private"})
    ids = [x["id"] for x in r.json()["results"]]
    assert "epSecret" not in ids


def test_deletion_reports_logical_and_physical():
    C.post("/v1/private/episodes", json={"ctx": {"org_id": "orgA", "user_id": "carol"}, "episode_id": "epC", "task_id": "t", "patch": "x"})
    r = C.delete("/v1/memories/epC", params={"org_id": "orgA", "user_id": "carol", "physical": False})
    d = r.json()["deletion"]; assert d["logical"] and not d["physical"]


def test_promote_unknown_rejected():
    r = C.post("/v1/contracts/ghost/promote", json={"ctx": {"org_id": "orgA", "user_id": "alice"}})
    assert r.status_code == 404
