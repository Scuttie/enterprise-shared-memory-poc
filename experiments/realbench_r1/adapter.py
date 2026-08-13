"""EvalPlusMBPPTaskAdapter (§5). Maps a server-owned repository fixture id to an OFFICIAL MBPP+ task. The
model-visible snapshot is only the official prompt (docstring + the single base example) as `solution.py`; the
grader is the official MBPP+ evaluator, referenced by a marker and run server-side. The coding backend never
receives the canonical solution, the augmented (plus) tests, the expected outputs, the target pairing, or the
arm. Reading the dataset (prompt/entry_point) is cross-platform; GRADING is Linux-only (CI)."""
from __future__ import annotations
import hashlib

from enterprise_memory.service.task_adapter import RepositoryTaskAdapter, _sha
from . import grader as G

GRADER_MARKER = "EVALPLUS:"


def fixture_id(task_id: str) -> str:
    return "mbpp_" + task_id.split("/")[-1]          # 'Mbpp/2' -> 'mbpp_2'


def solution_path(entry_point: str) -> str:
    return "src/solution.py"


class EvalPlusMBPPTaskAdapter(RepositoryTaskAdapter):
    """Indexes the official MBPP+ tasks by fixture id."""

    def __init__(self, task_ids=None):
        d = G._dataset()[0]
        ids = task_ids if task_ids is not None else list(d.keys())
        self._by_fixture = {}
        for tid in ids:
            self._by_fixture[fixture_id(tid)] = tid

    def _tid(self, repo_id):
        t = self._by_fixture.get(str(repo_id))
        if t is None:
            raise KeyError("no MBPP+ task for fixture %r" % (repo_id,))
        return t

    def installation_for(self, org_id) -> int:
        return int(_sha(str(org_id))[:8], 16) % 1_000_000 + 1

    def resolve_commit(self, repo_id, ref) -> str:
        return _sha("%s|%s" % (repo_id, ref))[:40]

    def resolve_tree(self, commit_sha) -> str:
        return _sha("tree|%s" % commit_sha)[:40]

    def snapshot(self, repo_id, commit_sha, target_path) -> dict:
        p = G.task(self._tid(repo_id))
        # model sees ONLY the official prompt (docstring + base example) as the file to complete
        return {"src/solution.py": p["prompt"]}

    def hidden_test(self, repo_id):
        return GRADER_MARKER + self._tid(repo_id)    # server-side marker -> official grader (never to backend)

    # convenience for the runner / policy seeding
    def task(self, repo_id):
        return G.task(self._tid(repo_id))

    def entry_point(self, repo_id):
        return G.task(self._tid(repo_id))["entry_point"]
