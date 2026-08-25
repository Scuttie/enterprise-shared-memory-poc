#!/usr/bin/env python3
"""R22 §6/§7/§8 — generic paid cell runner (checkpoint/resume, ledger, integrity). Offline FAKE mode drives the
harness with FakeReaderProvider + local fixtures + local grader (no Docker/credential); REAL mode (structured, not
run in credential-free work) uses the OpenAI/DeepSeek provider + the official Docker grader.

Used by reader_band.py / p1_runner.py / p2_runner.py.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)
from experiments.r22.runtime import repo_agent as RA          # noqa: E402
from experiments.r22.runtime import task_runtime as TR        # noqa: E402
from experiments.r22.runtime.provider import make_provider    # noqa: E402
from experiments.r22.runtime.accounting import Ledger         # noqa: E402
from experiments.r22.runtime.checkpoint import CheckpointStore  # noqa: E402
from experiments.r22.runtime.integrity import check_campaign  # noqa: E402


def fake_tasks(n, seed_prefix="t"):
    """n deterministic fixture tasks; each is a fresh tiny buggy repo + the fix + a frozen deranged source."""
    tasks = []
    ids = ["%s_tgt-%02d" % (seed_prefix, i) for i in range(n)]
    # sources are DISJOINT instances (different repo/number) so no target token can appear in any injection
    src_ids = ["%s_src-%02d" % (seed_prefix, i) for i in range(n)]
    deranged = src_ids[1:] + src_ids[:1]         # frozen no-fixed-point derangement over sources
    for i, tid in enumerate(ids):
        tasks.append({"target_id": tid, "source_id": src_ids[i], "shuffled_source": deranged[i],
                      "source_user": "gold_%02d" % i, "target_user": "u_%02d" % i, "stage": "EDIT",
                      "issue": "add() returns a-b; should be a+b",
                      "source_card": "prior issue: arithmetic op wrong",
                      "source_semantic": "when arithmetic result is off, verify the operator; use +",
                      "source_episodic": "tried a-b -> test failed; changed to a+b -> pass",
                      "source_full_precedent": "diff: -return a - b +return a + b",
                      "target_leak_tokens": [tid]})
    return tasks, {t["target_id"]: t["shuffled_source"] for t in tasks}


from dataclasses import dataclass


@dataclass(frozen=True)
class RunConfig:
    """Separates the two independent choices and validates the combination before any provider is built."""
    task_source: str            # "fake" | "real"
    reader_provider: str        # "fake" | "replay" | "openai" | "deepseek"
    manifest_name: str = None
    model: str = "fake-reader"
    secret_name: str = None

    def validate(self):
        assert self.task_source in ("fake", "real"), "bad task_source %r" % self.task_source
        assert self.reader_provider in ("fake", "replay", "openai", "deepseek"), \
            "bad reader_provider %r" % self.reader_provider
        if self.task_source == "fake":
            assert self.reader_provider not in ("openai", "deepseek"), \
                "task_source=fake with a paid provider is forbidden"
        if self.task_source == "real":
            assert self.reader_provider != "fake", "task_source=real must not use the fake provider"
            assert self.manifest_name, "real mode requires an explicit manifest_name"
        if self.reader_provider in ("openai", "deepseek"):
            assert self.secret_name, "paid provider requires a secret name"
        return self

    def provider_spec(self):
        return {"reader_provider": self.reader_provider, "model": self.model, "secret_name": self.secret_name}


def _fake_frozen_derangement(tasks):
    ids = [t["target_id"] for t in tasks]
    src = [t["source_id"] for t in tasks]
    return dict(zip(ids, src[1:] + src[:1]))


def _manifest_task_list(manifest_name):
    p = os.path.join(ROOT, "artifacts", "r22", manifest_name)
    return json.load(open(p, encoding="utf-8")).get("task_list", [])


def _real_derangement(manifest_name, tasks):
    """Frozen O2 derangement from the oracle manifest (target -> assigned unrelated source)."""
    d = {}
    for e in _manifest_task_list(manifest_name):
        if e["arm"] == "O2":
            d[e["target_id"]] = e.get("mem_source")
    # fall back to a deterministic rotation over target ids if the manifest lacks O2 rows
    if not d:
        ids = [t["target_id"] for t in tasks]
        d = dict(zip(ids, ids[1:] + ids[:1]))
    return d


def _source_of(manifest_name, target_id, arm, derange):
    """Exact frozen source assignment for (target, arm) from the oracle manifest."""
    for e in _manifest_task_list(manifest_name):
        if e["target_id"] == target_id and e["arm"] == arm:
            return e.get("mem_source") or (derange.get(target_id) if arm == "O2" else target_id)
    return derange.get(target_id) if arm == "O2" else target_id


def run(*, phase, arms, hard_cap, out_dir, n_tasks, task_source="fake", reader_provider="fake",
        manifest_name=None, model="fake-reader", secret_name=None, reuse_o0_from=None, task_prefix=None,
        grader_results_dir=None, provider_spec=None, mode=None):
    """task_source in {fake,real}; reader_provider in {fake,replay,openai,deepseek}. REAL task_source uses the
    frozen SWE-ContextBench loaders and NEVER touches fake_tasks/make_fixture/local_grade (guarded)."""
    from experiments.r22.runtime import loaders as LD
    os.makedirs(out_dir, exist_ok=True)
    # backward-compat: legacy callers pass provider_spec={mode:'fake'|'real'} + mode=
    if provider_spec is not None and reader_provider == "fake":
        reader_provider = provider_spec.get("reader_provider", provider_spec.get("mode", "fake"))
        model = provider_spec.get("model", model)
        secret_name = provider_spec.get("secret_name", secret_name)
    if mode is not None:
        task_source = mode
    if reader_provider == "real":
        reader_provider = "replay"          # legacy 'real' spec had no model call in CI
    cfg = RunConfig(task_source=task_source, reader_provider=reader_provider, manifest_name=manifest_name,
                    model=model, secret_name=secret_name).validate()
    provider_spec = cfg.provider_spec()

    if cfg.task_source == "real":
        task_loader = LD.RealR22TaskLoader(manifest_name)
        wsf = LD.OfficialImageWorkspaceFactory()
        mem_loader = LD.FrozenStageMemoryLoader()

        def grade_fn(t, patch):
            return LD.OfficialSWEGrader.grade_via_cli(t, patch, grader_results_dir or os.path.join(out_dir, "grade"))
    else:
        task_loader = LD.FakeTaskLoader(n_tasks, task_prefix or phase)
        wsf = LD.FakeWorkspaceFactory()
        mem_loader = LD.FakeMemorySourceLoader()

        def grade_fn(t, patch):
            return LD.LocalFixtureGrader().grade(t, patch)

    tasks = task_loader.load()
    derange = _fake_frozen_derangement(tasks) if cfg.task_source == "fake" else _real_derangement(manifest_name, tasks)
    ck = CheckpointStore(os.path.join(out_dir, "results.jsonl"))
    campaign_model = cfg.model
    ledger = Ledger(campaign_model, hard_cap)

    reused = 0
    if reuse_o0_from and os.path.isfile(reuse_o0_from):
        for line in open(reuse_o0_from, encoding="utf-8"):
            r = json.loads(line)
            if r["arm"] == "O0" and not ck.has(r["target_id"], "O0"):
                ck.append(r); reused += 1

    cells = [(t["target_id"], a) for t in tasks for a in arms]
    for (tid, arm) in ck.missing(cells):
        task = dict(next(t for t in tasks if t["target_id"] == tid))
        # exact frozen source assignment: real -> from the oracle manifest; fake -> deterministic
        if cfg.task_source == "real":
            src_id = _source_of(manifest_name, tid, arm, derange)
        else:
            src_id = derange[tid] if arm == "O2" else task["target_id"] + "_src"
        task["source_id"] = src_id
        task["source_user"] = "gold_" + hashlib.sha256(str(src_id).encode()).hexdigest()[:8]
        task["target_user"] = "u_" + hashlib.sha256(tid.encode()).hexdigest()[:8]
        wr = wsf.make(task)
        mem_rec = None
        from experiments.r22.runtime.arm_payload import MEMORY_ENABLED
        if MEMORY_ENABLED[arm]:
            mem_rec = mem_loader.load(src_id, task["stage"])
        spec = provider_spec
        if cfg.reader_provider == "fake":
            spec = {**provider_spec, "script": {"fix": task.get("_fix", {}), "stage": task["stage"]}}
        prov = make_provider(spec)
        rec = TR.run_task_arm(task=task, arm=arm, provider=prov, ledger=ledger, grade_fn=grade_fn,
                              workspace_root=wr, memory_record=mem_rec)
        ck.append(rec)

    records = ck.all()
    # campaign-level model lock: every cell must share one returned model
    models = set(r.get("returned_model") for r in records if r.get("returned_model"))
    integ = check_campaign(records, expected_cells=len(cells), o2_derangement=derange)
    if len(models) > 1:
        integ["violations"].append("campaign model drift across cells: %s" % models)
        integ["clean"] = False
    resolved = {a: sum(1 for r in records if r["arm"] == a and r["resolved"]) for a in arms}
    manifest = {"phase": phase, "arms": arms, "tasks": n_tasks, "cells": len(records),
                "reused_o0": reused, "resolved_by_arm": resolved,
                "ledger": ledger.snapshot(), "provider_mode": provider_spec.get("mode"),
                "results_sha256": hashlib.sha256(
                    json.dumps(sorted(r["cell_key"] for r in records)).encode()).hexdigest()}
    json.dump(manifest, open(os.path.join(out_dir, "evidence_manifest.json"), "w", encoding="utf-8"), indent=2)
    json.dump(integ, open(os.path.join(out_dir, "integrity_result.json"), "w", encoding="utf-8"), indent=2)
    return manifest, integ


def _spec_from_args(a):
    if a.mode == "fake":
        return {"mode": "fake", "model": "fake-reader"}
    return {"mode": "real", "provider": a.provider, "model": a.model, "secret_name": a.secret_name}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--arms", required=True)   # comma list
    ap.add_argument("--mode", choices=["fake", "real"], default="fake")
    ap.add_argument("--provider"); ap.add_argument("--model"); ap.add_argument("--secret-name")
    ap.add_argument("--hard-cap", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--reuse-o0-from")
    ap.add_argument("--task-prefix")
    a = ap.parse_args()
    manifest, integ = run(phase=a.phase, arms=a.arms.split(","), provider_spec=_spec_from_args(a),
                          hard_cap=a.hard_cap, out_dir=a.out, n_tasks=a.n, reuse_o0_from=a.reuse_o0_from, task_prefix=a.task_prefix)
    print(json.dumps({"resolved_by_arm": manifest["resolved_by_arm"], "cells": manifest["cells"],
                      "integrity_clean": integ["clean"], "violations": integ["violations"][:5]}, indent=2))
    return 0 if integ["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
