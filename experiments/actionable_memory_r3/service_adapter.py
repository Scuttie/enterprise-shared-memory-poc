"""REALBENCH-R3 — DS1000TaskAdapter: maps a server-owned repository fixture id to an OFFICIAL DS-1000 problem.
The model-visible snapshot is a task-unique one-line placeholder; the NL problem is passed to the backend as the
INSTRUCTION (from the job spec), never as the file. Grading routes to the official DS-1000 evaluator by the
server-side marker `DS1000:<problem_id>` — the backend never receives the code_context, the tests, the target
pairing, the relevance label, or the arm. Reading the dataset is cross-platform; GRADING is Linux + the official
conda env only.
"""
from __future__ import annotations

from enterprise_memory.service.task_adapter import RepositoryTaskAdapter, _sha

GRADER_MARKER = "DS1000:"


def fixture_id(problem_id) -> str:
    return "ds1000_%s" % problem_id


def pid_of(fixture: str) -> str:
    return str(fixture).split("ds1000_", 1)[-1]


class DS1000TaskAdapter(RepositoryTaskAdapter):
    def installation_for(self, org_id) -> int:
        return int(_sha(str(org_id))[:8], 16) % 1_000_000 + 1

    def resolve_commit(self, repo_id, ref) -> str:
        return _sha("%s|%s" % (repo_id, ref))[:40]

    def resolve_tree(self, commit_sha) -> str:
        return _sha("tree|%s" % commit_sha)[:40]

    def snapshot(self, repo_id, commit_sha, target_path) -> dict:
        # task-unique one-line placeholder: preserves completion semantics (the model writes the solution from
        # the NL instruction, not from a shown stub), yields a clean single-hunk diff, and keeps per-job
        # snapshot evidence unique so content-addressed artifact dedup never drops the row.
        return {target_path: "# DS-1000 problem %s\n" % pid_of(repo_id)}

    def hidden_test(self, repo_id):
        return GRADER_MARKER + pid_of(repo_id)     # server-side marker -> official grader (never to backend)
