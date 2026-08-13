"""Positive HTTP -> durable job -> separate worker -> SUCCEEDED (P5 §10). Traverses real HTTP and a
separately running worker process; asserts full PostgreSQL evidence and cross_user_private_injection_count=0."""
from sqlalchemy import text
from conftest import run, su


async def _evidence(org, job_id):
    e = su()
    async with e.connect() as c:                         # superuser bypasses RLS -> sees the durable evidence
        oc = (await c.execute(text("SELECT count(*) FROM outcome_observations WHERE job_id=:j"), {"j": job_id})).scalar()
        mc = (await c.execute(text("SELECT count(*) FROM model_calls WHERE job_id=:j"), {"j": job_id})).scalar()
        rc = (await c.execute(text("SELECT count(*) FROM retrieval_candidates WHERE job_id=:j AND scope='shared'"
                                   " AND accepted AND injected"), {"j": job_id})).scalar()
        cx = (await c.execute(text("SELECT cross_user_private_injection_count FROM solve_jobs WHERE id=:j"),
                              {"j": job_id})).scalar()
        ob = (await c.execute(text("SELECT count(*) FROM outbox_events WHERE event_type='CONTRACT_CANDIDATE'"
                                   " AND payload_json->>'job_id'=:j"), {"j": job_id})).scalar()
        art = (await c.execute(text("SELECT count(*) FROM artifacts WHERE job_id=:j AND deletion_state='AVAILABLE'"),
                               {"j": job_id})).scalar()
        classes = [r[0] for r in (await c.execute(text("SELECT DISTINCT artifact_class FROM artifacts"
                                                       " WHERE job_id=:j"), {"j": job_id})).fetchall()]
        pe = (await c.execute(text("SELECT count(*) FROM private_episodes WHERE org_id=:o"), {"o": org})).scalar()
        aud = (await c.execute(text("SELECT count(*) FROM audit_events WHERE event_type='solve_succeeded'"
                                    " AND subject_id=:j"), {"j": job_id})).scalar()
    await e.dispose()
    return {"outcome": oc, "model_call": mc, "retrieval_injected": rc, "cross_user": cx, "candidate_event": ob,
            "artifacts_available": art, "classes": set(classes), "private_episode": pe, "audit": aud}


def test_positive_http_worker_e2e(seed, keyring, client):
    s = seed()
    token = keyring(s["user"], s["org"], ["solve:submit", "solve:read"])
    hdr = {"authorization": "Bearer " + token, "Idempotency-Key": "idem-pos-1"}
    body = {"repository_id": s["repo"], "task_id": "fix-return", "instruction": "make f return 1",
            "desired_ref": "refs/heads/main"}
    r = client.post("/v1/solve", headers=hdr, json=body)
    assert r.status_code == 202, r.text
    j = r.json()
    job_id = j["job_id"]
    assert j["state"] == "QUEUED" and j["status_url"].endswith(job_id) and j["created"] is True

    # idempotency: same key -> same job, created=False
    r2 = client.post("/v1/solve", headers=hdr, json=body)
    assert r2.status_code == 202 and r2.json()["job_id"] == job_id and r2.json()["created"] is False

    # a client cannot smuggle authoritative fields
    bad = dict(body); bad["patch"] = "x"; bad["test_passed"] = True; bad["org_id"] = "evil"
    assert client.post("/v1/solve", headers=hdr, json=bad).status_code == 422

    # the SEPARATE worker completes the job
    final = poll = None
    from conftest import poll_job
    final = poll_job(client, token, job_id)
    assert final["state"] == "SUCCEEDED", final
    assert final["cross_user_private_injection_count"] == 0

    # ordered events with a terminal SUCCEEDED
    events = client.get("/v1/jobs/%s/events" % job_id, headers={"authorization": "Bearer " + token}).json()["events"]
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and any(e["state"] == "SUCCEEDED" for e in events)

    ev = run(_evidence(s["org"], job_id))
    assert ev["outcome"] == 1 and ev["model_call"] >= 1 and ev["retrieval_injected"] >= 1
    assert ev["cross_user"] == 0 and ev["candidate_event"] == 1 and ev["private_episode"] == 1
    assert ev["audit"] == 1 and ev["artifacts_available"] >= 5
    assert {"repository_snapshot", "sanitized_model_response", "parsed_patch", "sandbox_result"} <= ev["classes"]


def test_memories_search_governed(seed, keyring, client):
    s = seed()
    token = keyring(s["user"], s["org"], ["memory:shared:read"])
    r = client.post("/v1/memories/search",
                    headers={"authorization": "Bearer " + token},
                    json={"scope": "shared", "query": "return 1"})
    assert r.status_code == 200
    hits = r.json()["hits"]
    assert hits and hits[0]["content_hash"] and "canonical" in hits[0]   # canonical from PostgreSQL, not index text
