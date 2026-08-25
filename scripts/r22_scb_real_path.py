#!/usr/bin/env python3
"""R22-P0.8 §8 — credential-free REAL-path E2E through the OFFICIAL SCB grader.

frozen target -> RealR22TaskLoader (official case route + official image) -> OfficialImageWorkspaceFactory (real
repo checkout) -> ReplayReaderProvider (no / non-solving patch) -> SCBOfficialGrader (pinned upstream evaluator +
official image) -> unresolved -> durable evidence. Also grades the OFFICIAL gold patch (expect resolved).

Hard guarantees enforced here: the fake task loader, fake fixture, local-fixture grader, and generic swebench
grader all RAISE if reached. No secret, no network model call, paid API = 0. Requires Docker at runtime and
R22_SCB_UPSTREAM_EXEC_APPROVED=1 (compliance gate)."""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
ART = os.path.join(ROOT, "artifacts", "r22")

from experiments.r22.runtime import loaders as LD                # noqa: E402
from experiments.r22.runtime import task_runtime as TR           # noqa: E402
from experiments.r22.runtime import repo_agent as RA             # noqa: E402
from experiments.r22.runtime import scb_official_grader as SG    # noqa: E402
from experiments.r22.runtime.provider import make_provider       # noqa: E402
from experiments.r22.runtime.accounting import Ledger            # noqa: E402


def _boom(name):
    def f(*a, **k):
        raise AssertionError("FAKE/GENERIC path reached on the REAL path: %s" % name)
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-id", required=True)
    ap.add_argument("--manifest", default="oracle_dev_manifest.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--results-dir", default=os.path.join(ART, "_scb_realpath_run"))
    a = ap.parse_args()

    # tripwires: any fake/generic path is a hard failure on the real path
    RA.make_fixture = _boom("repo_agent.make_fixture")
    RA.local_grade = _boom("repo_agent.local_grade")
    LD.FakeTaskLoader.load = _boom("FakeTaskLoader.load")
    LD.LocalFixtureGrader.grade = _boom("LocalFixtureGrader.grade")

    iid = a.instance_id
    tasks = LD.RealR22TaskLoader(a.manifest).load()
    task = next(t for t in tasks if t["target_id"] == iid)
    assert task["image"] and task["image"].startswith("jiayuanz3/swecontextbench:"), "no official image on task"
    assert task.get("case_route"), "no official case route on task"

    wsf = LD.OfficialImageWorkspaceFactory()
    wr = wsf.make(dict(task))
    assert task.get("workspace_method") or os.path.isdir(wr)

    prov = make_provider({"reader_provider": "replay", "model": "replay-no-patch"})
    rec = TR.run_task_arm(task=dict(task), arm="O0", provider=prov, ledger=Ledger("replay-no-patch", 0.0),
                          grade_fn=lambda t, p: LD.SCBOfficialGrader.grade_via_cli(t, p, os.path.join(a.results_dir, iid, "replay")),
                          workspace_root=wr, memory_record=None)

    # reader never saw the gold/test content
    prompt_blob = json.dumps(rec.get("messages", []))
    leak = bool(task.get("_gold_patch")) and (str(task["_gold_patch"])[:40] in prompt_blob)

    # official gold patch must resolve the same target
    checkout = SG.ensure_checkout(os.path.join(a.results_dir, "_scb_upstream"))
    case = json.loads(open(os.path.join(checkout, task["case_route"]["case_path"]), encoding="utf-8").read())
    route = dict(task["case_route"]); route["instance_id"] = iid; route["image_digest"] = task.get("image_digest")
    gold = SG.grade(route, case.get("patch") or "", os.path.join(a.results_dir, iid, "gold"))

    out = {"instance_id": iid, "pinned_commit": SG.PINNED_COMMIT,
           "image": task["image"], "image_digest": task.get("image_digest"),
           "workspace_method": task.get("workspace_method"),
           "case_path": task["case_route"]["case_path"],
           "replay_patch_sha256": rec.get("patch_sha256"),
           "replay_resolved": bool(rec.get("resolved")),
           "replay_grader": (rec.get("grader") or {}),
           "replay_infra_ok": (rec.get("grader") or {}).get("infra_ok") if isinstance(rec.get("grader"), dict) else None,
           "gold_resolved": bool(gold.get("resolved")), "gold_infra_ok": gold.get("infra_ok"),
           "gold_report": gold.get("report_path"),
           "reader_saw_gold": leak,
           "pass": (not rec.get("resolved")) and bool(gold.get("resolved")) and not leak}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=2)
    print(json.dumps({k: out[k] for k in ("instance_id", "replay_resolved", "gold_resolved",
                                          "reader_saw_gold", "pass")}, indent=2))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
