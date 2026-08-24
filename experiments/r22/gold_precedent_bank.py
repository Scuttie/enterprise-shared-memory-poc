#!/usr/bin/env python3
"""R22 §3 — GOLD_PRECEDENT bank (deterministic; NO model calls).

Builds stage records from official source gold patches + tests. Mechanical fields are extracted from the patch/AST;
semantic fields (violated_contract / root_cause / non_applicability) are left UNKNOWN — never guessed. Only stages
with evidence get a record. GOLD_PRECEDENT is an upper-bound / schema-quality bank; USER_SUCCESS (paid) is separate.
"""
import ast
import hashlib
import json
import os
import re
from collections import defaultdict

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.environ.get("R22_SCB_DATA", "C:/Users/jewon/third_party_r22/swe-contextbench/data")
OUT = os.path.join(ROOT, "artifacts", "r22")

import sys
sys.path.insert(0, os.path.join(ROOT, "src"))
from enterprise_memory.experience.stage_schema import (  # noqa: E402
    Stage, StageTrigger, StageTransition, StageAction, StageVerification)
from enterprise_memory.experience.stage_compiler import compile_stage_record, coverage_report, UNKNOWN  # noqa: E402
from enterprise_memory.experience.stage_views import (  # noqa: E402
    episodic_precedent, semantic_recipe, search_index_view, execution_view)

UNKNOWN_FIELDS = ("violated_contract", "root_cause", "non_applicability")


def changed_files(patch):
    return re.findall(r"^\+\+\+ b/(.+)$", patch or "", flags=re.M)


def added_removed(patch):
    add = [l[1:] for l in (patch or "").splitlines() if l.startswith("+") and not l.startswith("+++")]
    rem = [l[1:] for l in (patch or "").splitlines() if l.startswith("-") and not l.startswith("---")]
    return add, rem


def py_symbols(lines):
    syms, apis = set(), set()
    for l in lines:
        for m in re.finditer(r"^\s*def\s+(\w+)", l):
            syms.add(m.group(1))
        for m in re.finditer(r"^\s*class\s+(\w+)", l):
            syms.add(m.group(1))
        for m in re.finditer(r"^\s*(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))", l):
            apis.add(m.group(1) or m.group(2))
        for m in re.finditer(r"(\w+)\s*\(", l):
            if m.group(1) not in ("if", "for", "while", "return", "print"):
                syms.add(m.group(1))
    return sorted(s for s in syms if s), sorted(a for a in apis if a)


def error_tokens(text):
    return sorted(set(re.findall(r"\b(\w*(?:Error|Exception|Warning))\b", text or "")))[:8]


def build_records(row):
    """Return a list of compiled StageMemoryRecords for one source task (only stages with evidence)."""
    iid = row["instance_id"]; repo = row["repo"]; commit = row["base_commit"]
    ts = str(row.get("created_at", "")); patch = row["patch"] or ""; test_patch = row["test_patch"] or ""
    ftp = str(row.get("FAIL_TO_PASS", "")); ptp = str(row.get("PASS_TO_PASS", ""))
    problem = str(row.get("problem_statement", ""))
    add, rem = added_removed(patch)
    files = changed_files(patch)
    syms, apis = py_symbols(add + rem)
    errs = error_tokens(problem)
    # deterministic synthetic source user (source_user != target_user is enforced downstream)
    user = "gold_" + hashlib.sha256(iid.encode()).hexdigest()[:10]
    vh = hashlib.sha256((ftp + "|" + ptp).encode()).hexdigest()
    common = dict(source_task_id=iid, source_repository=repo, source_commit=commit, source_user_id=user,
                  source_timestamp=ts, source_outcome="resolved", verifier_hash=vh,
                  patch_artifact_id="gold:" + hashlib.sha256(patch.encode()).hexdigest()[:16])
    recs = []

    def try_compile(stage, trigger, transition=None, action=None, verification=None):
        try:
            recs.append(compile_stage_record(stage=stage, trigger=trigger, transition=transition,
                                             action=action, verification=verification, **common))
        except ValueError:
            pass  # empty-core stage is skipped (no evidence)

    # COMPREHEND — issue contract (evidence: problem statement / error tokens)
    if problem:
        try_compile(Stage.COMPREHEND, StageTrigger(issue_type="bug" if errs else "task",
                    error_signature=errs[0] if errs else "", language="python", violated_contract=UNKNOWN,
                    affected_paths=files))
    # REPRODUCE — failing test signature (evidence: FAIL_TO_PASS / test patch)
    if ftp or test_patch:
        try_compile(Stage.REPRODUCE, StageTrigger(failing_test_signature=ftp[:120], language="python",
                    affected_paths=changed_files(test_patch)),
                    verification=StageVerification(command_type="run FAIL_TO_PASS", source_test_evidence="present"))
    # LOCALIZE — paths/symbols (evidence: changed files/symbols)
    if files or syms:
        try_compile(Stage.LOCALIZE, StageTrigger(affected_paths=files, affected_symbols=syms, affected_apis=apis,
                    language="python", violated_contract=UNKNOWN))
    # EDIT — the actual change (evidence: patch hunks)
    if add or rem:
        op = "add_guard" if any("if " in a for a in add) else ("api_change" if apis else "modify")
        try_compile(Stage.EDIT, StageTrigger(affected_symbols=syms, affected_paths=files, language="python",
                    error_signature=errs[0] if errs else (files[0] if files else "edit")),
                    transition=StageTransition(successful_action="apply gold change to %s" % (files[0] if files else "?")),
                    action=StageAction(operation_type=op, non_applicability=[UNKNOWN],
                                       edit_template="see gold patch (oracle-only)", target_role=syms[0] if syms else ""))
    # VERIFY — verification recipe (evidence: FAIL_TO_PASS + PASS_TO_PASS)
    if ftp:
        try_compile(Stage.VERIFY, StageTrigger(failing_test_signature=ftp[:120], language="python"),
                    verification=StageVerification(command_type="FAIL_TO_PASS then PASS_TO_PASS",
                    source_test_evidence="official", regression_scope="PASS_TO_PASS" if ptp else "targeted"))
    return recs


def main():
    exp = pd.read_parquet(os.path.join(DATA, "SWEContextBench_Experience.parquet")).drop_duplicates("instance_id")
    clean = json.load(open(os.path.join(OUT, "dev_manifest_v2.json")))["pairs"] + \
        json.load(open(os.path.join(OUT, "main_manifest_v2.json")))["pairs"]
    source_ids = sorted(set(p["source_id"] for p in clean))
    exp_by = {r["instance_id"]: r for _, r in exp.iterrows()}

    bank = []
    per_source = {}
    ext = defaultdict(int)
    for sid in source_ids:
        row = exp_by.get(sid)
        if row is None:
            continue
        recs = build_records(row)
        per_source[sid] = len(recs)
        for rec in recs:
            d = rec.to_dict()
            views = {"episodic": episodic_precedent(rec), "semantic": semantic_recipe(rec),
                     "search_index": search_index_view(rec), "execution": execution_view(rec)}
            # OracleRawDiffView (O3-only): a reference id, never the raw diff inline in retrieval
            views["oracle_raw_diff"] = {"kind": "OracleRawDiffView", "patch_ref": rec.raw_evidence.patch_artifact_id,
                                        "restricted": "O3_ONLY"}
            bank.append({"record": d, "views": views})
            if rec.trigger.affected_symbols:
                ext["symbol"] += 1
            if rec.trigger.affected_apis:
                ext["api"] += 1
            if rec.action.operation_type and rec.action.operation_type != UNKNOWN:
                ext["operation"] += 1
            if rec.verification.command_type:
                ext["verification"] += 1

    records = [type("R", (), {"stage": Stage(b["record"]["stage"]),
                              "action": type("A", (), {"operation_type": b["record"]["action"]["operation_type"]})})()
               for b in bank]
    cov = coverage_report([__import__("enterprise_memory.experience.stage_schema", fromlist=["StageMemoryRecord"])
                           .StageMemoryRecord.from_dict(b["record"]) for b in bank])
    total = len(bank)
    unknown_fraction = sum(1 for b in bank for f in UNKNOWN_FIELDS
                           if str(b["record"]["trigger"].get(f, "")) == UNKNOWN
                           or str(b["record"]["action"].get(f, "")) == UNKNOWN) / max(1, total)

    manifest = {"schema": "r22/gold_precedent_manifest/1.0.0", "sources": len(source_ids),
                "sources_with_records": sum(1 for v in per_source.values() if v),
                "stage_records": total, "by_stage": cov["by_stage"],
                "symbol_extraction_coverage": round(ext["symbol"] / max(1, total), 3),
                "api_extraction_coverage": round(ext["api"] / max(1, total), 3),
                "operation_extraction_coverage": round(ext["operation"] / max(1, total), 3),
                "verification_coverage": round(ext["verification"] / max(1, total), 3),
                "unknown_field_fraction": round(unknown_fraction, 3),
                "leakage_sentinel": "PASS (compiler asserts no target keys per record)",
                "bank_sha256": hashlib.sha256(json.dumps(bank, sort_keys=True, default=str).encode()).hexdigest()}
    json.dump({"schema": "r22/gold_precedent_bank/1.0.0", "records": bank},
              open(os.path.join(OUT, "gold_precedent_bank.json"), "w", encoding="utf-8"), indent=2, default=str)
    json.dump(manifest, open(os.path.join(OUT, "gold_precedent_manifest.json"), "w", encoding="utf-8"),
              indent=2, default=str)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
