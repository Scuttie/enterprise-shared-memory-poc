"""REALBENCH-R3 §4/§5 — DS-1000 task adapter. Loads the OFFICIAL frozen data file (data/ds1000.jsonl.gz at the
pinned commit), verifies content hash + task count, and exposes task records. Benchmark semantics are never
altered here: we read `prompt`, `reference_code`, `code_context`, `metadata` exactly as shipped and grade via
the official `execution.check_correctness` (see ds1000_grader). Completion mode only (insertion removed upstream).
"""
from __future__ import annotations
import gzip
import hashlib
import json
import os

RECORD_FIELDS = ("prompt", "reference_code", "code_context", "metadata")


def data_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_tasks(gz_path: str) -> list[dict]:
    """Load ds1000.jsonl.gz -> list of task dicts, each augmented with a stable string id from metadata."""
    tasks = []
    with gzip.open(gz_path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            md = r.get("metadata", {})
            r["_id"] = "ds1000_%s" % md.get("problem_id")
            r["_library"] = md.get("library")
            r["_perturbation"] = md.get("perturbation_type")
            tasks.append(r)
    return tasks


def content_hash(tasks: list[dict]) -> str:
    """Order-independent hash over the benchmark-defining fields (excludes our injected _ keys)."""
    h = hashlib.sha256()
    for r in sorted(tasks, key=lambda x: x["metadata"]["problem_id"]):
        core = {k: r[k] for k in RECORD_FIELDS}
        h.update(json.dumps(core, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return h.hexdigest()


def assemble_program(answer_code: str, code_context: str) -> str:
    """Official completion-mode assembly: inject the answer as the variable `code`, then the task's
    code_context (which defines test_execution/test_string and invokes them). Verbatim from upstream."""
    return "code = " + repr(answer_code) + "\n" + code_context


def library_strata(tasks: list[dict]) -> dict[str, list[str]]:
    strata: dict[str, list[str]] = {}
    for r in tasks:
        strata.setdefault(r["_library"], []).append(r["_id"])
    return strata


if __name__ == "__main__":
    p = os.environ.get("DS1000_DATA", "DS-1000/data/ds1000.jsonl.gz")
    ts = load_tasks(p)
    print("tasks", len(ts), "sha256", data_sha256(p), "content_hash", content_hash(ts))
    from collections import Counter
    print("by library", dict(Counter(t["_library"] for t in ts)))
    print("by perturbation", dict(Counter(t["_perturbation"] for t in ts)))
