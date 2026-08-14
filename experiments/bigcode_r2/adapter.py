"""BigCodeBenchTaskAdapter (§3/§5). Maps a server-owned repository fixture id to an OFFICIAL BigCodeBench
task. The model-visible snapshot is ONLY the official BigCodeBench-Instruct natural-language prompt as
`solution.py`; the grader is the official BigCodeBench evaluator, referenced by a server-side marker. The
coding backend never receives the canonical solution, the unit tests, the target pairing, the relevance
label, or the arm. Reading the dataset (instruct_prompt/entry_point) is cross-platform; GRADING is Linux +
the official eval image only."""
from __future__ import annotations

from enterprise_memory.service.task_adapter import RepositoryTaskAdapter, _sha
from . import grader as G

GRADER_MARKER = "BIGCODE:"


def fixture_id(task_id: str) -> str:
    return "bigcode_" + task_id.split("/")[-1]          # 'BigCodeBench/0' -> 'bigcode_0'


class BigCodeBenchTaskAdapter(RepositoryTaskAdapter):
    """Indexes the official BigCodeBench tasks by fixture id. Instruct variant (§3)."""

    def __init__(self, task_ids=None):
        d = G._dataset()
        ids = task_ids if task_ids is not None else list(d.keys())
        self._by_fixture = {fixture_id(tid): tid for tid in ids}

    def _tid(self, repo_id):
        t = self._by_fixture.get(str(repo_id))
        if t is None:
            raise KeyError("no BigCodeBench task for fixture %r" % (repo_id,))
        return t

    def installation_for(self, org_id) -> int:
        return int(_sha(str(org_id))[:8], 16) % 1_000_000 + 1

    def resolve_commit(self, repo_id, ref) -> str:
        return _sha("%s|%s" % (repo_id, ref))[:40]

    def resolve_tree(self, commit_sha) -> str:
        return _sha("tree|%s" % commit_sha)[:40]

    # A minimal placeholder file. Instruct semantics are preserved because the model writes the whole
    # solution from the NATURAL-LANGUAGE instruct_prompt, which the worker passes as the INSTRUCTION (not as
    # the file). Using a code stub here would turn this into BigCodeBench-Complete (a semantics change, §21) —
    # so the file is a neutral placeholder that carries no signature/docstring. It also makes the whole-file
    # model output diff cleanly against a tiny context (a prose instruct_prompt as the file does not).
    PLACEHOLDER = "# Implement the required solution in this file.\n"

    def snapshot(self, repo_id, commit_sha, target_path) -> dict:
        self._tid(repo_id)                                 # validate the fixture maps to a task
        return {"src/solution.py": self.PLACEHOLDER}

    def hidden_test(self, repo_id):
        return GRADER_MARKER + self._tid(repo_id)      # server-side marker -> official grader (never to backend)

    def task(self, repo_id):
        return G.task(self._tid(repo_id))

    def entry_point(self, repo_id):
        return G.task(self._tid(repo_id))["entry_point"]
