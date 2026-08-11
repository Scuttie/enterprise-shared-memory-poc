"""§6 durable job state machine + an in-memory reference JobRepository (the production impl is Postgres
row-leasing with SELECT ... FOR UPDATE SKIP LOCKED). Retries are attempts of ONE logical job — never new
jobs/outcomes. Duplicate submission with the same idempotency key returns the existing job."""
from __future__ import annotations
import itertools

STATES = ("QUEUED", "RETRIEVING", "GENERATING", "TESTING", "REPAIRING", "SUCCEEDED", "FAILED",
          "CANCELLED", "DEAD_LETTER")
_ALLOWED = {
    "QUEUED": {"RETRIEVING", "CANCELLED"},
    "RETRIEVING": {"GENERATING", "FAILED", "QUEUED", "CANCELLED"},
    "GENERATING": {"TESTING", "FAILED", "QUEUED", "CANCELLED"},
    "TESTING": {"REPAIRING", "SUCCEEDED", "FAILED", "QUEUED", "CANCELLED"},
    "REPAIRING": {"TESTING", "SUCCEEDED", "FAILED", "CANCELLED"},
    "SUCCEEDED": set(), "FAILED": {"QUEUED", "DEAD_LETTER"}, "CANCELLED": set(), "DEAD_LETTER": set(),
}
MAX_ATTEMPTS = 3


class JobError(Exception):
    pass


def can_transition(a: str, b: str) -> bool:
    return b in _ALLOWED.get(a, set())


class InMemoryJobRepository:
    """Reference implementation for test/local. Production = Postgres FOR UPDATE SKIP LOCKED leasing."""

    def __init__(self, clock=None):
        self._jobs = {}
        self._by_idem = {}
        self._seq = itertools.count(1)
        self._t = 0
        self._clock = clock

    def _now(self):
        if self._clock:
            return self._clock()
        self._t += 1
        return self._t

    async def create(self, spec: dict, idempotency_key: str | None = None) -> dict:
        if idempotency_key and idempotency_key in self._by_idem:
            return self._jobs[self._by_idem[idempotency_key]]           # duplicate -> existing job
        jid = "job_%06d" % next(self._seq)
        job = {"job_id": jid, "state": "QUEUED", "spec": spec, "attempts": 0, "lease_owner": None,
               "lease_expiry": None, "logical_request_id": "lrq_%s" % jid, "events": [("QUEUED", self._now())],
               "idempotency_key": idempotency_key}
        self._jobs[jid] = job
        if idempotency_key:
            self._by_idem[idempotency_key] = jid
        return job

    async def claim(self, worker_id: str, lease_s: int = 30) -> dict | None:
        now = self._now()
        for job in self._jobs.values():
            leaseable = job["state"] in ("QUEUED",) or (
                job["lease_expiry"] is not None and job["lease_expiry"] <= now and job["state"] not in
                ("SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER"))
            if leaseable:
                job["lease_owner"] = worker_id
                job["lease_expiry"] = now + lease_s
                job["attempts"] += 1
                if job["state"] == "QUEUED":
                    self._set(job, "RETRIEVING")
                return job
        return None

    async def transition(self, job_id: str, to_state: str, detail: dict | None = None) -> dict:
        job = self._jobs[job_id]
        if not can_transition(job["state"], to_state):
            raise JobError("illegal transition %s -> %s" % (job["state"], to_state))
        if to_state == "FAILED" and job["attempts"] >= MAX_ATTEMPTS:
            self._set(job, "DEAD_LETTER")
            return job
        self._set(job, to_state, detail)
        return job

    def _set(self, job, state, detail=None):
        job["state"] = state
        job["events"].append((state, self._now(), detail))

    async def get(self, job_id: str) -> dict | None:
        return self._jobs.get(job_id)

    async def heartbeat(self, job_id: str, worker_id: str, lease_s: int = 30):
        job = self._jobs[job_id]
        if job["lease_owner"] != worker_id:
            raise JobError("not lease owner")
        job["lease_expiry"] = self._now() + lease_s
