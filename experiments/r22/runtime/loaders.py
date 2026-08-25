"""R22 §1-§5 — hard-separated FAKE vs REAL task loading / workspaces / grading / memory. REAL implementations load
the frozen SWE-ContextBench targets, official images, official grader, and frozen stage-memory records; they never
touch the fake fixtures. FAKE implementations are the offline local-fixture path (renamed LOCAL_FIXTURE_HARNESS).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ART = os.path.join(ROOT, "artifacts", "r22")
ENRICHED = {
    "SWE-bench Verified": ("SWE-bench/SWE-bench_Verified", "78f471bf655a3137b2e8a75af1501690ec009ec3"),
    "SWE-bench Lite": ("SWE-bench/SWE-bench_Lite", "b0dde1093fe417d83b7184254edf8199c1f0dff5"),
    "SWE-bench Multilingual": ("SWE-bench/SWE-bench_Multilingual", "846e647b9f33c0b51b739d005d13d85493c9af09"),
}


# ---- interfaces --------------------------------------------------------------
class TaskLoader:
    def load(self) -> List[dict]:
        raise NotImplementedError


class WorkspaceFactory:
    def make(self, task: dict) -> str:
        raise NotImplementedError


class Grader:
    def grade(self, task: dict, model_patch: str) -> dict:
        raise NotImplementedError


class MemorySourceLoader:
    def load(self, source_id: str, stage: str) -> dict:
        raise NotImplementedError


class RealModeViolation(Exception):
    pass


# ---- FAKE (local fixture) ----------------------------------------------------
class FakeTaskLoader(TaskLoader):
    def __init__(self, n, prefix):
        from experiments.r22.paid_runner import fake_tasks
        self.n, self.prefix = n, prefix
        self._fake_tasks = fake_tasks

    def load(self):
        tasks, _ = self._fake_tasks(self.n, seed_prefix=self.prefix)
        return tasks


class FakeWorkspaceFactory(WorkspaceFactory):
    def make(self, task):
        from experiments.r22.runtime import repo_agent as RA
        wr = tempfile.mkdtemp()                 # build the fixture directly in the workspace (no copytree race)
        task["_fix"] = RA.make_fixture(wr)
        return wr


class LocalFixtureGrader(Grader):
    def grade(self, task, model_patch):
        from experiments.r22.runtime import repo_agent as RA
        return {"resolved": bool(model_patch.strip()) and RA.local_grade(task["_workspace"]),
                "grader": "local_fixture"}


# ---- REAL (frozen SWE-ContextBench) ------------------------------------------
def _frozen_ids(manifest_name):
    m = json.load(open(os.path.join(ART, manifest_name), encoding="utf-8"))
    ids = []
    for t in m["task_list"]:
        if t.get("target_id") not in ids:
            ids.append(t["target_id"])
    return ids


SCB_DATASET = "jiayuanz3/SWEContextBench"
SCB_GH_COMMIT = "31bb04155f52b184bf31b220e3cff0607ac9c953"


def _load_case_route_manifest():
    p = os.path.join(ART, "scb_case_route_manifest.json")
    return json.load(open(p, encoding="utf-8"))["cases"] if os.path.isfile(p) else {}


def _load_image_manifest():
    p = os.path.join(ART, "scb_image_manifest.json")
    return json.load(open(p, encoding="utf-8"))["images"] if os.path.isfile(p) else {}


class RealR22TaskLoader(TaskLoader):
    """Loads the frozen oracle TARGET rows and attaches the OFFICIAL SWE-ContextBench grading route (P0.8).

    The reader-facing fields (issue/base_commit/repo) come from the MIT SCB dataset row; the grading route
    (official case JSON path+hash, official prebuilt image tag `jiayuanz3/swecontextbench:<tag>` + digest) comes
    from the frozen P0.8 audits. There is NO `image=None`: SCB Related targets ARE graded by the benchmark's own
    evaluator against prebuilt per-instance images. Gold patch / test_patch / F2P / P2P are withheld from the
    reader (grading reads them from the official case inside the pinned checkout). Credential-free load."""

    def __init__(self, manifest_name: str, scb_data: Optional[str] = None):
        self.manifest_name = manifest_name
        self.scb_data = scb_data or os.environ.get("R22_SCB_DATA", os.path.join(ART, "_scb_data"))

    def load(self):
        import pandas as pd
        target_ids = _frozen_ids(self.manifest_name)
        rel = pd.read_parquet(os.path.join(self.scb_data, "SWEContextBench_Related.parquet"))
        exp = pd.read_parquet(os.path.join(self.scb_data, "SWEContextBench_Experience.parquet"))
        by = {}
        for df in (rel, exp):
            for _, r in df.iterrows():
                by.setdefault(r["instance_id"], r)
        routes = _load_case_route_manifest()
        images = _load_image_manifest()
        tasks = []
        for tid in target_ids:
            if tid not in by:
                raise RealModeViolation("frozen target %s not in the SWE-ContextBench dataset" % tid)
            if tid not in routes:
                raise RealModeViolation("no OFFICIAL case route for %s (run the P0.8 case audit)" % tid)
            r = by[tid]
            route = dict(routes[tid])
            img = images.get(tid, {})
            route["image_digest"] = img.get("digest")
            tasks.append({
                "target_id": tid, "subset": route.get("subset_used"), "dataset_name": SCB_DATASET,
                "dataset_revision": SCB_GH_COMMIT,
                "repository": r["repo"], "base_commit": r["base_commit"],
                "problem_statement": r["problem_statement"], "issue": r["problem_statement"],
                "image": img.get("image"),          # OFFICIAL prebuilt image tag jiayuanz3/swecontextbench:<tag>
                "image_digest": img.get("digest"),
                "case_route": route,                 # official case path + hashes (no gold content in cleartext)
                "environment_setup_commit": r.get("environment_setup_commit"), "version": str(r.get("version")),
                "repo_cluster": r["repo"],
                "_gold_patch": r["patch"], "_test_patch": r["test_patch"],   # withheld from the reader
                "stage": "COMPREHEND",
            })
        return tasks


class OfficialImageWorkspaceFactory(WorkspaceFactory):
    """Editable READER workspace for a REAL SCB target. Grading always uses the OFFICIAL SCB image separately
    (see SCBOfficialGrader); this only produces a repo tree the reader edits. Two methods (§7):
      B) git checkout base_commit (default; credential-free, no image pull), or
      A) extract /testbed from the official SCB image (R22_WORKSPACE_METHOD=image; requires Docker).
    Records task['workspace_method']. Never creates the fake-fixture files."""

    def make(self, task):
        image = task.get("image")
        if not image:
            raise RealModeViolation("no official image tag for %s (run the P0.8 image audit)" % task["target_id"])
        method = os.environ.get("R22_WORKSPACE_METHOD", "git")
        wr = tempfile.mkdtemp()
        if method == "image":
            subprocess.run(["docker", "pull", image], check=True, capture_output=True)
            digest = subprocess.run(["docker", "inspect", "--format", "{{index .RepoDigests 0}}", image],
                                    capture_output=True, text=True).stdout.strip()
            task["image_pulled_digest"] = digest
            cid = subprocess.run(["docker", "create", image], capture_output=True, text=True).stdout.strip()
            try:
                subprocess.run(["docker", "cp", "%s:/testbed/." % cid, wr], check=True, capture_output=True)
            finally:
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
        else:
            repo = task["repository"]
            subprocess.run(["git", "init", "-q"], cwd=wr, check=True, capture_output=True)
            subprocess.run(["git", "remote", "add", "origin", "https://github.com/%s.git" % repo],
                           cwd=wr, capture_output=True)
            subprocess.run(["git", "fetch", "--depth", "1", "origin", task["base_commit"]],
                           cwd=wr, check=True, capture_output=True)
            subprocess.run(["git", "checkout", "-q", task["base_commit"]], cwd=wr, check=True, capture_output=True)
        task["workspace_method"] = method
        # the real path must never create the fixture files
        if os.path.exists(os.path.join(wr, "bug.py")) or os.path.exists(os.path.join(wr, "test_bug.py")):
            raise RealModeViolation("fixture files present in a REAL workspace")
        return wr


class SCBOfficialGrader(Grader):
    """Grade a REAL SCB target with the BENCHMARK-SPECIFIC official evaluator (pinned ephemeral checkout of
    swebench_memory.harness.run_evaluation + official per-instance image). Never generic swebench, never
    local_grade. Requires task['case_route'] from the P0.8 case audit."""

    def grade(self, task, model_patch):
        return SCBOfficialGrader.grade_via_cli(task, model_patch,
                                               os.environ.get("R22_GRADER_RESULTS", tempfile.mkdtemp()))

    @staticmethod
    def grade_via_cli(task, model_patch, results_dir):
        from experiments.r22.runtime import scb_official_grader as SG
        route = task.get("case_route")
        if not route:
            raise RealModeViolation("no official case_route for %s; cannot grade with the SCB evaluator"
                                    % task["target_id"])
        route = dict(route)
        route.setdefault("instance_id", task["target_id"])
        route.setdefault("image_digest", task.get("image_digest"))
        return SG.grade(route, model_patch, results_dir, model_name="r22-reader")


# Back-compat alias: the previous (WRONG, generic-swebench) grader name now routes to the SCB official grader.
OfficialSWEGrader = SCBOfficialGrader


class FrozenStageMemoryLoader(MemorySourceLoader):
    """Loads the exact (source_id, stage) record from the frozen GOLD_PRECEDENT bank."""

    def __init__(self):
        bank = json.load(open(os.path.join(ART, "gold_precedent_bank.json"), encoding="utf-8"))
        self.index = {}
        for e in bank["records"]:
            rec = e["record"]
            self.index[(rec["identity"]["source_task_id"], rec["stage"])] = e

    def load(self, source_id, stage):
        e = self.index.get((source_id, stage))
        if e is None:
            return None
        v = e["views"]
        return {"card": v["episodic"].get("attempted_action", ""),
                "semantic": json.dumps(v["semantic"]),
                "episodic": json.dumps(v["episodic"]),
                "full_precedent": json.dumps(v.get("oracle_raw_diff", {})),
                "execution_view": v["execution"]}


class FakeMemorySourceLoader(MemorySourceLoader):
    def load(self, source_id, stage):
        return {"card": "prior issue: arithmetic op wrong",
                "semantic": "when arithmetic result is off, verify the operator; use +",
                "episodic": "tried a-b -> failed; changed to a+b -> pass",
                "full_precedent": "diff: -return a - b +return a + b", "execution_view": {"approx_tokens": 20}}
