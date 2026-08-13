"""Separate solve worker (P5 §6-§8). A durable, standalone lifecycle: claim a PostgreSQL job lease,
heartbeat, snapshot the immutable repo, search private+shared separately, reload every candidate from
PostgreSQL, compile <=2 compact governed views, call the CodingExecutionBackend, validate the patch against
the server-owned edit policy, run the controlled sandbox, persist all evidence + artifacts, and only then
atomically finalize. cross_user_private_injection_count is COMPUTED from candidate owners (must be 0). No
benchmark/research imports; no client patch/test result is trusted."""
from __future__ import annotations
import asyncio
import fnmatch
import json
import os
import uuid

from sqlalchemy import text
from ..persistence.tenant_context import tenant_tx
from ..persistence.postgres import claim_job, heartbeat, redact
from ..indexing.validated_search import validated_search
from ..indexing.models import PRIVATE, SHARED, SearchResult
from ..artifacts import records as AR
from . import durable as D
from .execution import ExecutionResult
from .injection import plan_injection

STAGE_DEADLINE = float(os.environ.get("WORKER_STAGE_DEADLINE", "120"))
_FORBIDDEN = ("tests/**", "**/test_*.py", "**/conftest.py", "**/*_test.py")


class EditPolicyError(Exception):
    pass


class LeaseLost(Exception):
    """This worker no longer owns the live lease. It must abort immediately: no further model/sandbox/artifact
    work, no terminal evidence, and it must NOT write any terminal state (it is now a stale worker)."""


class Cancelled(Exception):
    """The job was cancel-requested. The worker stops and, if it still owns the lease, transitions CANCELLED."""


def _patch_paths(patch_text):
    paths = []
    for ln in patch_text.splitlines():
        if ln.startswith("+++ ") or ln.startswith("--- "):
            p = ln[4:].strip()
            if p.startswith(("a/", "b/")):
                p = p[2:]
            if p and p != "/dev/null":
                paths.append(p)
    return sorted(set(paths))


def validate_edit_policy(patch_text, editable_paths, max_changed_lines, snapshot, target_path):
    from ..patches import apply_unified_diff, PatchError
    paths = _patch_paths(patch_text)
    if not paths:
        raise EditPolicyError("no_files")
    for p in paths:
        if ".." in p.split("/") or p.startswith("/"):
            raise EditPolicyError("path_traversal")
        if any(fnmatch.fnmatch(p, g) for g in _FORBIDDEN):
            raise EditPolicyError("test_or_hidden_path")
        if not any(fnmatch.fnmatch(p, g) for g in editable_paths):
            raise EditPolicyError("path_not_editable")
    try:
        new_text, meta = apply_unified_diff(snapshot[target_path], patch_text)
    except PatchError as e:
        raise EditPolicyError("unapplyable:%s" % e)
    if (meta["add"] + meta["del"]) > max_changed_lines:
        raise EditPolicyError("line_budget_exceeded")
    return new_text, meta


async def _heartbeat_loop(engine, org, job_id, worker_id, stop, lease_lost, interval=5):
    """Renew the lease. If renewal fails because the lease is no longer owned/live, SIGNAL lease_lost so the
    pipeline aborts before the next expensive stage — it must not keep running on a lost lease."""
    while not stop.is_set():
        try:
            await heartbeat(engine, org, job_id, worker_id)
        except PermissionError:
            lease_lost.set()
            return
        except Exception:
            # transient error renewing (e.g. a dropped connection): treat conservatively as lease-at-risk
            lease_lost.set()
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def _checkpoint(engine, org, job_id, worker_id, lease_lost):
    """Guard called before every expensive stage. Raises LeaseLost if the lease was lost (signalled by the
    heartbeat loop OR observable now as an owner change / expiry), or Cancelled if a cancel was requested."""
    if lease_lost.is_set():
        raise LeaseLost("lease_lost")
    async with tenant_tx(engine, org) as c:
        r = (await c.execute(text(
            "SELECT cancel_requested_at, lease_owner, state,"
            " (lease_expires_at IS NOT NULL AND lease_expires_at > now()) AS live"
            " FROM solve_jobs WHERE id=:j"), {"j": job_id})).first()
    if r is None:
        raise LeaseLost("job_vanished")
    cancel_at, owner, state, live = r[0], r[1], r[2], r[3]
    if owner != worker_id or not live or state in ("SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER"):
        lease_lost.set()
        raise LeaseLost("not_owner_or_expired")
    if cancel_at is not None:
        raise Cancelled("cancel_requested")


async def process_job(container, worker_id, ev):
    e = container.worker_engine
    org, user, job_id = ev["org_id"], ev.get("submitter"), ev["job_id"]
    spec = ev["spec_json"] if isinstance(ev["spec_json"], dict) else json.loads(ev["spec_json"])
    repo_id = spec["repository_id"]; target = spec["target_path"]; commit = spec["commit_sha"]
    # the repository/task adapter is keyed by the server-owned fixture id (falls back to the DB repo id for
    # the demo provider). Authorization always uses the DB repo id (repo_id), never the fixture ref.
    repo_ref = spec.get("repository_fixture_id") or repo_id
    lrq = "mc-%s" % job_id
    seq = 1
    stop = asyncio.Event()
    lease_lost = asyncio.Event()
    hb = asyncio.create_task(_heartbeat_loop(e, org, job_id, worker_id, stop, lease_lost))
    try:
        await D.add_event(e, org, job_id, seq, "RETRIEVING", "claimed", {"worker": worker_id}); seq += 1
        # revalidate repository modify authorization (server-side, current)
        if not await container.repo_authz.can_modify(e, org, user, repo_id):
            raise EditPolicyError("repo_modify_revoked")

        async def _pipeline():
            nonlocal seq
            # immutable snapshot -> artifact
            await _checkpoint(e, org, job_id, worker_id, lease_lost)     # before snapshot
            snapshot = container.repo_provider.snapshot(repo_ref, commit, target)
            snap_ref = await container.artifacts.put(e, org, AR.REPOSITORY_SNAPSHOT,
                                                     json.dumps(snapshot, sort_keys=True).encode(),
                                                     created_by=user, job_id=job_id)
            await D.add_event(e, org, job_id, seq, "RETRIEVING", "snapshot", {"commit": commit}); seq += 1

            # dual retrieval (canonical reload happens INSIDE validated_search). The retrieval policy comes
            # from the server-assigned experiment arm (M0 disables retrieval; M4 is oracle) — never client.
            await _checkpoint(e, org, job_id, worker_id, lease_lost)     # before retrieval
            rp = ev.get("retrieval_policy") or spec.get("retrieval_policy") or {}
            priv_scopes = rp.get("scopes", ["private", "shared"])
            max_inj = int(rp.get("max_injected", 2))
            slimit = int(rp.get("search_limit", 5))
            abstain = rp.get("abstain")             # P5.2 {tau_abs, tau_margin} competitive-retrieval gate
            oracle_id = rp.get("oracle_id")          # P5.2 M4 oracle: select this canonical version id
            priv = SearchResult() if "private" not in priv_scopes else await validated_search(
                e, container.index, container.embedder, PRIVATE, org, spec["instruction"],
                user_id=user, limit=slimit)
            shared = SearchResult() if "shared" not in priv_scopes else await validated_search(
                e, container.index, container.embedder, SHARED, org, spec["instruction"],
                user_id=user, limit=slimit)
            # deterministic joint ranking + REAL safe-view compilation + <=max_inj selection. `injected` is
            # set only for views actually placed in the backend payload; leakage is computed from real owners.
            rejected_audit = [a for a in (priv.audit + shared.audit) if not a.get("accepted")]
            plan = plan_injection(priv.hits, shared.hits, requester_id=str(user),
                                  repo_id=repo_id, rejected_audit=rejected_audit, max_injected=max_inj,
                                  abstain=abstain, oracle_id=oracle_id)
            for c in plan.candidates:
                await D.persist_retrieval_candidate(
                    e, org, job_id, scope=c.scope, canonical_id=c.canonical_id,
                    canonical_version_id=c.canonical_version_id, content_hash=c.content_hash,
                    private_owner_id=(c.canonical_owner_id if c.scope == "private" else None),
                    accepted=c.accepted, rejection_reason=c.rejection_reason, injected=c.injected,
                    index_owner_id=c.index_owner_id, canonical_owner_id=c.canonical_owner_id,
                    injected_view_hash=c.injected_view_hash, injected_position=c.injected_position)
            views = list(plan.memory_views)
            cross_user = plan.cross_user_private_injection_count
            injected_meta = [{"scope": c.scope, "version_id": c.canonical_version_id, "hash": c.content_hash,
                              "position": c.injected_position, "view_hash": c.injected_view_hash}
                             for c in plan.candidates if c.injected]
            await D.add_event(e, org, job_id, seq, "GENERATING", "retrieved",
                              {"priv": len(priv.hits), "shared": len(shared.hits), "injected": len(views),
                               "cross_user": cross_user}); seq += 1

            # execution backend
            await _checkpoint(e, org, job_id, worker_id, lease_lost)     # before model/harness execution
            task_ctx = {"instruction": spec["instruction"], "target_path": target,
                        "repository_reference": {"repo": repo_id, "commit": commit},
                        "edit_policy": {"editable_paths": spec["editable_paths"],
                                        "max_changed_lines": spec["maximum_changed_lines"]}}
            result: ExecutionResult = await container.backend.execute(task_ctx, snapshot, views,
                                                                      logical_request_id=lrq, org_id=org)
            for rec in result.model_call_records:
                rec.setdefault("logical_request_id", lrq)
                rec.setdefault("backend_type", result.backend_type)
                await D.persist_model_call(e, org, job_id, rec)
            # sanitized request/response artifacts
            from ..providers.redaction import sanitize
            req_blob = json.dumps({"instruction": spec["instruction"], "views": views}, sort_keys=True)
            resp_blob, _ = sanitize(result.raw_response or result.patch_text)
            await container.artifacts.put(e, org, AR.SANITIZED_MODEL_REQUEST, req_blob.encode(),
                                          created_by=user, job_id=job_id)
            await container.artifacts.put(e, org, AR.SANITIZED_MODEL_RESPONSE, resp_blob.encode(),
                                          created_by=user, job_id=job_id)
            await D.add_event(e, org, job_id, seq, "TESTING", "generated", {"backend": result.backend_type}); seq += 1

            # patch parse + edit policy. For an experiment job a rejected/unapplyable patch is a recorded
            # exec failure (Exec@1=0), NOT a job failure — the model's attempt is still a data point. For a
            # non-experiment (demo) job the original strict behaviour is preserved (policy violation -> FAIL).
            await _checkpoint(e, org, job_id, worker_id, lease_lost)     # before patch processing
            is_experiment = bool(spec.get("experiment_id"))
            new_text, meta, policy_reason = None, {}, None
            try:
                new_text, meta = validate_edit_policy(result.patch_text, spec["editable_paths"],
                                                      spec["maximum_changed_lines"], snapshot, target)
            except EditPolicyError as pe:
                if not is_experiment:
                    raise
                policy_reason = str(pe)
            await container.artifacts.put(e, org, AR.PARSED_PATCH, result.patch_text.encode(),
                                          created_by=user, job_id=job_id)
            # controlled sandbox — grade on the SERVER-OWNED hidden test (never in the model snapshot)
            await _checkpoint(e, org, job_id, worker_id, lease_lost)     # before sandbox
            hidden = getattr(container.repo_provider, "hidden_test", lambda r: None)(repo_ref)
            if new_text is not None:
                sandbox_res = container.sandbox.run(snapshot, result.patch_text, target, grading_test=hidden)
                await container.artifacts.put(e, org, AR.APPLIED_PATCH, new_text.encode(), created_by=user,
                                              job_id=job_id)
            else:
                sandbox_res = {"applied": False, "tests_passed": False, "output": "policy:%s" % policy_reason,
                               "changed_files": []}
            await container.artifacts.put(e, org, AR.SANDBOX_RESULT,
                                          json.dumps(sandbox_res, sort_keys=True).encode(), created_by=user,
                                          job_id=job_id)
            exec1 = 1 if sandbox_res.get("applied") else 0
            pass1 = 1 if sandbox_res.get("tests_passed") else 0
            if is_experiment:           # durably record raw + applied patch for adoption forensics (G7)
                await D.persist_patches(e, org, job_id, raw_patch=result.patch_text,
                                        applied_patch=(new_text or ""))
            if not is_experiment and not pass1:
                raise EditPolicyError("sandbox_tests_failed")
            await D.add_event(e, org, job_id, seq, "TESTING", "graded",
                              {"applied": bool(exec1), "passed": bool(pass1)}); seq += 1

            # build (but do NOT yet persist) the terminal evidence; the atomic finaliser writes it all in one
            # lease-owned transaction together with the SUCCEEDED transition.
            outcome = {"pass1": pass1, "exec1": exec1, "pass2": pass1, "injected": injected_meta,
                       "content_hash": D.sha(new_text or result.patch_text)}
            episode = {"task_id": spec["task_id"], "repo_id": repo_id, "commit": commit,
                       "outcome": "success", "injected_memory_ids": [m["version_id"] for m in injected_meta]}
            return cross_user, outcome, episode

        cross_user, outcome, episode = await asyncio.wait_for(_pipeline(), timeout=STAGE_DEADLINE)

        # one authoritative terminal transaction (lease-owned, evidence-verified, idempotent); a stale worker
        # or a lost race raises PermissionError and writes nothing terminal.
        await _checkpoint(e, org, job_id, worker_id, lease_lost)         # before finalisation
        episode_id = await D.finalize_success_atomic(
            e, org, job_id, worker_id, cross_user_count=cross_user, seq=seq, outcome=outcome,
            episode_canonical=episode, user_id=user, repo_id=repo_id)
        return {"job_id": job_id, "status": "SUCCEEDED", "cross_user": cross_user, "episode_id": episode_id}
    except LeaseLost as ex:
        # stale worker: abort with NO terminal write (do not mark_failed — another worker owns the job now)
        return {"job_id": job_id, "status": "LEASE_LOST", "reason": str(ex)}
    except Cancelled:
        # honour the cancellation; only the true lease owner records the terminal CANCELLED
        try:
            await D.mark_cancelled(e, org, job_id, worker_id, seq + 1)
        except Exception:
            pass
        return {"job_id": job_id, "status": "CANCELLED"}
    except PermissionError:
        # lost the finalisation race / no longer the lease owner: write nothing terminal
        return {"job_id": job_id, "status": "NOT_OWNER"}
    except Exception as ex:
        try:
            await D.mark_failed(e, org, job_id, worker_id, str(ex), seq + 1)
        except Exception:
            pass
        return {"job_id": job_id, "status": "FAILED", "error": redact(str(ex))}
    finally:
        stop.set()
        try:
            await hb
        except Exception:
            pass


async def run_once(container, worker_id, lease_seconds=30):
    ev = await claim_job(container.worker_engine, worker_id, lease_seconds=lease_seconds)
    if ev is None:
        return None
    return await process_job(container, worker_id, ev)


async def worker_loop(container, worker_id, poll_interval=0.5, max_iterations=None):
    await container.ensure_ready()
    i = 0
    while max_iterations is None or i < max_iterations:
        i += 1
        r = await run_once(container, worker_id)
        if r is None:
            await asyncio.sleep(poll_interval)


def main():
    from .ci_container import build_container
    container = build_container()
    worker_id = os.environ.get("WORKER_ID", "solve-worker-%s" % uuid.uuid4().hex[:8])
    asyncio.run(worker_loop(container, worker_id))


if __name__ == "__main__":
    main()
