#!/usr/bin/env python3
"""R22-P0.9.1 §3 — Ruff three-target forensic diagnostic.

Per the 3 frozen targets in `artifacts/r22_p09/ruff_forensic_manifest.json` (F1 astral-sh__ruff-15725,
F2 astral-sh__ruff-16445, POSITIVE_CONTROL astral-sh__ruff-15997) this diagnostic runs the *exact* official
`cargo test` command PLUS a diagnostic unfiltered collection INSIDE the pinned official per-instance image, on the
official case, and classifies why F1/F2 report "Collected 0 test results" while POSITIVE collects 9.

This is FORENSIC EVIDENCE, NOT an official score: the `cargo test -- --list` / `--no-run` outputs are diagnostics
we add on top of the byte-identical official `source $HOME/.cargo/env && cargo test`. The parse/count/map/classify
logic lives in PURE FUNCTIONS (top of file) so it is unit-testable without docker
(`tests/unit/test_r22_p09_ruff_parser.py`).

CREDENTIAL-FREE IMPORT: this module imports and py_compiles WITHOUT docker/network. Actual execution (docker) is
gated on `R22_SCB_UPSTREAM_EXEC_APPROVED=1` exactly like `scb_official_grader.grade()` — the unlicensed upstream
evaluator/image are executed only under explicit approval.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "artifacts", "r22_p09")
MANIFEST = os.path.join(OUT, "ruff_forensic_manifest.json")
RUN_DIR = os.path.join(OUT, "ruff_diag_run")
RESULTS = os.path.join(OUT, "ruff_diagnostic_results.json")

# Reuse the pinned official adapter primitives (ensure_checkout, pull_and_verify_image, _load_case, ...) so the
# diagnostic pulls the SAME frozen image by digest and reads the SAME official case JSON as the grader.
from experiments.r22.runtime import scb_official_grader as SG  # noqa: E402

RULE_CLASSES = (
    "R1_ADAPTER_INVOCATION_BUG",
    "R2_CASE_SELECTOR_BUG",
    "R3_TEST_PATCH_BUG",
    "R4_IMAGE_CASE_DRIFT",
    "R5_UPSTREAM_PARSER_BUG",
    "R6_UPSTREAM_GOLD_INVALID",
    "R7_TOOLCHAIN_INCOMPATIBILITY",
    "R8_UNKNOWN",
)

# The EXACT official command (from the harness eval.sh, byte-identical across all three targets):
#   cd /testbed && git apply /test.patch && git apply /patch.diff && source $HOME/.cargo/env && cargo test
OFFICIAL_CARGO_CMD = "source $HOME/.cargo/env && cargo test"

# ============================================================================
# PURE FUNCTIONS (no docker / no network) — unit-tested directly.
# ============================================================================

# A running cargo test line, e.g. "test rules::flake8_bugbear::tests::foo ... ok"
_TEST_LINE = re.compile(r"^\s*test\s+(?P<name>\S+)\s+\.\.\.\s+(?P<status>ok|FAILED|ignored|bench)\b")
# The cargo summary line, e.g. "test result: ok. 9 passed; 0 failed; 3 ignored; 0 measured; 0 filtered out"
_SUMMARY = re.compile(
    r"test result:\s+(?P<result>\w+)\.\s+(?P<passed>\d+)\s+passed;\s+(?P<failed>\d+)\s+failed;"
    r"\s+(?P<ignored>\d+)\s+ignored")
# A `cargo test -- --list` line, e.g. "rules::flake8_bugbear::tests::foo: test"
_LIST_LINE = re.compile(r"^\s*(?P<name>\S+):\s+test\s*$")


def extract_raw_counts(stdout: str) -> dict:
    """Extract the RAW collected test count from cargo test stdout.

    Counts individual `test <name> ... ok|FAILED|ignored` run lines AND parses every `test result:` summary line
    (there is one per test binary — they are SUMMED). Returns per-status breakdown + the summed summary totals.
    `raw_collected_count` == number of individual run lines observed (the true collected count).
    """
    stdout = stdout or ""
    test_lines = []           # list[(name, status)]
    by_status = {"ok": 0, "FAILED": 0, "ignored": 0, "bench": 0}
    for line in stdout.splitlines():
        m = _TEST_LINE.match(line)
        if m:
            name, status = m.group("name"), m.group("status")
            test_lines.append((name, status))
            by_status[status] = by_status.get(status, 0) + 1
    summaries = []
    sp = sf = si = 0
    for m in _SUMMARY.finditer(stdout):
        passed, failed, ignored = int(m.group("passed")), int(m.group("failed")), int(m.group("ignored"))
        summaries.append({"result": m.group("result"), "passed": passed, "failed": failed, "ignored": ignored})
        sp += passed
        sf += failed
        si += ignored
    return {
        "test_lines": test_lines,
        "by_status": by_status,
        "summaries": summaries,
        "summary_total": {"passed": sp, "failed": sf, "ignored": si},
        "raw_collected_count": len(test_lines),
    }


def parse_list_output(list_stdout: str) -> list:
    """Parse `cargo test -- --list` stdout into the ordered list of collected runtime test names."""
    names = []
    for line in (list_stdout or "").splitlines():
        m = _LIST_LINE.match(line)
        if m:
            names.append(m.group("name"))
    return names


def as_list(v) -> list:
    """Coerce a case FAIL_TO_PASS/PASS_TO_PASS field (list, JSON string, or scalar) into a list of str."""
    if v is None:
        return []
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("["):
            try:
                v = json.loads(s)
            except Exception:
                v = [s]
        else:
            v = [v]
    if not isinstance(v, (list, tuple)):
        v = [v]
    return [str(x) for x in v]


def selector_expected_symbol(selector: str) -> str:
    """The expected test symbol (leaf) of a `rules::<module>::tests::<name>` selector."""
    return selector.strip().split("::")[-1]


def selector_expected_source(selector: str) -> str:
    """Best-effort expected source file glob from the module path of a `rules::<module>::tests::<name>` selector."""
    parts = [p for p in selector.strip().split("::") if p]
    if "tests" in parts:
        mod = parts[:parts.index("tests")]
    else:
        mod = parts[:-1]
    if not mod:
        return None
    return "crates/**/src/" + "/".join(mod) + "/**.rs"


def _tail(name: str, n: int = 3) -> str:
    return "::".join(name.strip().split("::")[-n:])


def match_selector(selector: str, collected: list) -> tuple:
    """Map a FAIL_TO_PASS selector to a collected runtime name: (match_kind, matched_name).

    match_kind is 'exact' (string-equal), 'normalized' (equal on the trailing module::tests::name tail, or one is a
    ::-suffix of the other), or 'none'.
    """
    sel = (selector or "").strip()
    cset = [c.strip() for c in (collected or [])]
    if sel in cset:
        return "exact", sel
    st = _tail(sel)
    for c in cset:
        if _tail(c) == st or c.endswith("::" + sel) or sel.endswith("::" + c) or c.endswith(sel) or sel.endswith(c):
            return "normalized", c
    return "none", None


def map_selectors(f2p_selectors: list, collected: list) -> dict:
    """Map every FAIL_TO_PASS selector to expected source/symbol + collected-name match kind. Returns mapping +
    aggregate counts used by the classifier."""
    rows = []
    matched = 0
    for sel in f2p_selectors:
        kind, name = match_selector(sel, collected)
        if kind != "none":
            matched += 1
        rows.append({
            "selector": sel,
            "expected_source": selector_expected_source(sel),
            "expected_symbol": selector_expected_symbol(sel),
            "collected_match_kind": kind,
            "collected_match_name": name,
        })
    return {
        "rows": rows,
        "selectors_total": len(f2p_selectors),
        "selectors_matched": matched,
        "selectors_absent": len(f2p_selectors) - matched,
    }


def replicated_parser(stdout: str) -> dict:
    """REPLICATED cargo-test parser: name -> normalized status (PASSED/FAILED/SKIPPED). Fallback used only when the
    pinned upstream parser cannot be imported/invoked. Marked REPLICATED in the results so it is never mistaken for
    the official parser output."""
    out = {}
    norm = {"ok": "PASSED", "FAILED": "FAILED", "ignored": "SKIPPED", "bench": "PASSED"}
    for name, status in extract_raw_counts(stdout)["test_lines"]:
        out[name] = norm.get(status, status)
    return out


def classify_target(ev: dict) -> tuple:
    """Classify a FAILED target into exactly one R1..R8 class from the collected evidence.

    Priority follows the causal order compile -> collect -> parse -> pass/fail:
      R1 our command differs from official (never, here) ; R4 case base_commit != in-container HEAD ;
      R3 test patch git apply failed ; R7 compile/setup failed before collection ;
      R5 raw cargo collected >0 but parser yielded 0 ; R2 expected selectors absent from collected names ;
      R6 intended tests collect but fail under gold ; else R8.
    Returns (primary_class, reasons:list[str]).
    """
    reasons = []
    if ev.get("command_matches_official", True) is False:
        return "R1_ADAPTER_INVOCATION_BUG", ["our command differs from the official eval.sh cargo test"]
    if ev.get("base_commit_match") is False:
        return "R4_IMAGE_CASE_DRIFT", ["in-container HEAD != official case base_commit"]
    if ev.get("test_patch_rc") not in (0, None):
        return "R3_TEST_PATCH_BUG", ["test patch `git apply` rc=%s (intended tests not created/updated)"
                                     % ev.get("test_patch_rc")]
    if ev.get("compile_ok") is False:
        return "R7_TOOLCHAIN_INCOMPATIBILITY", ["compile/setup failed before collection "
                                                "(cargo test --no-run rc=%s)" % ev.get("no_run_rc")]
    if ev.get("raw_collected_count", 0) > 0 and ev.get("parser_output_count", 0) == 0:
        return "R5_UPSTREAM_PARSER_BUG", ["raw cargo collected %d test(s) but parser yielded 0"
                                          % ev.get("raw_collected_count", 0)]
    if ev.get("selectors_total", 0) > 0 and ev.get("selectors_matched", 0) == 0:
        return "R2_CASE_SELECTOR_BUG", ["0/%d FAIL_TO_PASS selectors present in collected --list names"
                                        % ev.get("selectors_total", 0)]
    if ev.get("selectors_matched", 0) > 0 and ev.get("gold_failed"):
        return "R6_UPSTREAM_GOLD_INVALID", ["intended test(s) collect but fail under the official gold patch"]
    return "R8_UNKNOWN", ["evidence did not discriminate R1-R7"]


# ============================================================================
# IMPURE — docker/checkout orchestration (gated).
# ============================================================================

def _sha256_file(path: str):
    if not path or not os.path.isfile(path):
        return None
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _read(path: str) -> str:
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return ""


def _read_rc(path: str):
    try:
        return int(_read(path).strip())
    except Exception:
        return None


def require_approval() -> None:
    """Gate docker execution exactly like SG.grade(): refuse without R22_SCB_UPSTREAM_EXEC_APPROVED=1."""
    if os.environ.get("R22_SCB_UPSTREAM_EXEC_APPROVED") != "1":
        raise SG.UpstreamExecutionNotApproved(
            "R22-P0.9.1 ruff forensic diagnostic executes the unlicensed upstream image + `cargo test`; it requires "
            "R22_SCB_UPSTREAM_EXEC_APPROVED=1 (see reports/R22_UPSTREAM_RIGHTS_STATUS.md). Import/py_compile do not.")


def load_upstream_parser(checkout_dir: str, repo: str):
    """Import the pinned upstream cargo-test parser from the checkout; fall back to REPLICATED if not cleanly
    importable/invocable. Returns (callable(stdout)->dict, method, detail) where method is IMPORTED or REPLICATED."""
    if checkout_dir and checkout_dir not in sys.path:
        sys.path.insert(0, checkout_dir)
    try:
        mod = importlib.import_module(SG.EVALUATOR_MODULE)
    except Exception as e:
        return replicated_parser, "REPLICATED", "upstream import failed: %r" % (e,)

    # 1) a repo->parser map (swebench MAP_REPO_TO_PARSER convention)
    fn = None
    detail = None
    mp = getattr(mod, "MAP_REPO_TO_PARSER", None)
    if isinstance(mp, dict):
        fn = mp.get(repo) or mp.get(repo.split("/")[-1]) or mp.get(repo.replace("/", "__"))
        if callable(fn):
            detail = "MAP_REPO_TO_PARSER[%s]" % repo
    # 2) a module-level log-parsing function
    if not callable(fn):
        for nm in dir(mod):
            low = nm.lower()
            if "parse" in low and ("log" in low or "test" in low or "eval" in low):
                cand = getattr(mod, nm)
                if callable(cand):
                    fn, detail = cand, "module fn %s" % nm
                    break
    if not callable(fn):
        return replicated_parser, "REPLICATED", "no parser symbol in %s" % SG.EVALUATOR_MODULE

    def _wrap(stdout: str) -> dict:
        # Upstream parsers variously take (stdout), (log_path), or (stdout, test_spec). Try in order.
        import tempfile
        try:
            r = fn(stdout)
            if isinstance(r, dict):
                return r
            if isinstance(r, (tuple, list)) and r and isinstance(r[0], dict):
                return r[0]
        except Exception:
            pass
        try:
            tf = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
            tf.write(stdout)
            tf.close()
            r = fn(tf.name)
            if isinstance(r, dict):
                return r
            if isinstance(r, (tuple, list)) and r and isinstance(r[0], dict):
                return r[0]
        except Exception:
            pass
        raise RuntimeError("imported upstream parser not invocable with (stdout) or (path)")

    return _wrap, "IMPORTED", detail


def _docker_run(image_ref: str, hostdir: str) -> dict:
    """Run the in-container diagnostic script inside the pinned image, host dir mounted rw at /host."""
    script = "\n".join([
        "#!/usr/bin/env bash",
        "set +e",
        "cd /testbed",
        "git rev-parse HEAD > /host/head.txt 2> /host/head.err",
        "git apply /host/test.patch > /host/test_patch.stdout 2> /host/test_patch.stderr; echo $? > /host/test_patch.rc",
        "git apply /host/patch.diff > /host/gold_patch.stdout 2> /host/gold_patch.stderr; echo $? > /host/gold_patch.rc",
        'source "$HOME/.cargo/env"',
        "# (a) EXACT official command — official score path",
        "cargo test > /host/official_cargo.stdout 2> /host/official_cargo.stderr; echo $? > /host/official_cargo.rc",
        "# (b) DIAGNOSTIC unfiltered collection/compile — FORENSIC EVIDENCE, NOT an official score",
        "cargo test --no-run > /host/norun.stdout 2> /host/norun.stderr; echo $? > /host/norun.rc",
        "cargo test -- --list > /host/list.stdout 2> /host/list.stderr; echo $? > /host/list.rc",
        "# enumerate test files present after the test patch (forensic)",
        'grep -rl "#\\[test\\]" crates > /host/test_files.txt 2> /host/test_files.err; echo $? > /host/test_files.rc',
    ])
    open(os.path.join(hostdir, "diag.sh"), "w", encoding="utf-8", newline="\n").write(script)
    mount = "%s:/host" % os.path.abspath(hostdir)
    cmd = ["docker", "run", "--rm", "--platform", "linux/amd64", "-v", mount, image_ref,
           "bash", "-lc", "bash /host/diag.sh"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    open(os.path.join(hostdir, "_docker.stdout"), "w", encoding="utf-8").write(proc.stdout or "")
    open(os.path.join(hostdir, "_docker.stderr"), "w", encoding="utf-8").write(proc.stderr or "")
    return {"docker_returncode": proc.returncode, "docker_cmd": " ".join(cmd)}


def run_target(role: str, target: dict, checkout: str, parser_fn, parser_method: str, parser_detail: str) -> dict:
    iid = target["instance_id"]
    hostdir = os.path.join(RUN_DIR, iid)
    os.makedirs(hostdir, exist_ok=True)

    # official case JSON (authoritative base_commit / test_patch / gold / F2P) from the pinned checkout.
    case_route = {"instance_id": iid, "case_path": target["case_path"], "case_sha256": target.get("case_sha256")}
    case = SG._load_case(checkout, case_route)
    case_base = case.get("base_commit")

    # 1) base_commit: manifest vs official case
    manifest_base = target.get("base_commit")
    base_commit_match_manifest_vs_case = (manifest_base == case_base)

    # write the official test/gold patches for the container to apply
    open(os.path.join(hostdir, "test.patch"), "w", encoding="utf-8", newline="\n").write(case.get("test_patch") or "")
    open(os.path.join(hostdir, "patch.diff"), "w", encoding="utf-8", newline="\n").write(case.get("patch") or "")

    # 2/3) pull frozen image BY DIGEST + run in-container diagnostic
    image_tag = target["image"]
    digest = target["image_digest"]
    img_info = SG.pull_and_verify_image(image_tag, digest)
    image_ref = "%s@%s" % (image_tag.split(":")[0], digest)
    dk = _docker_run(image_ref, hostdir)

    head = _read(os.path.join(hostdir, "head.txt")).strip()
    official_stdout = _read(os.path.join(hostdir, "official_cargo.stdout"))
    official_stderr = _read(os.path.join(hostdir, "official_cargo.stderr"))
    list_stdout = _read(os.path.join(hostdir, "list.stdout"))
    norun_rc = _read_rc(os.path.join(hostdir, "norun.rc"))
    official_rc = _read_rc(os.path.join(hostdir, "official_cargo.rc"))
    test_patch_rc = _read_rc(os.path.join(hostdir, "test_patch.rc"))
    gold_patch_rc = _read_rc(os.path.join(hostdir, "gold_patch.rc"))

    # base_commit match: case vs in-container HEAD (HEAD reflects pre-patch checkout of the base image)
    base_commit_match = (head == case_base) if head else None

    # 3) raw collected count from the OFFICIAL cargo stdout (the scored output)
    raw = extract_raw_counts(official_stdout)
    raw_collected_count = raw["raw_collected_count"]

    # 4) enumerate collected runtime names from the diagnostic --list
    collected_names = parse_list_output(list_stdout)

    # 5) map FAIL_TO_PASS selectors -> expected source/symbol + collected-name match
    f2p = as_list(case.get("FAIL_TO_PASS"))
    selmap = map_selectors(f2p, collected_names)

    # 6) run the pinned upstream parser SEPARATELY on the raw official output
    try:
        parsed = parser_fn(official_stdout)
        parser_output_count = len(parsed)
        parser_error = None
        used_method = parser_method
    except Exception as e:
        parsed = replicated_parser(official_stdout)
        parser_output_count = len(parsed)
        parser_error = "%r" % (e,)
        used_method = "REPLICATED_FALLBACK"

    # 7) classify
    compile_ok = (norun_rc == 0) if norun_rc is not None else None
    gold_failed = raw["summary_total"]["failed"] > 0 or (raw_collected_count > 0 and raw["by_status"]["FAILED"] > 0)
    ev = {
        "command_matches_official": True,   # R1 by construction: our command is the official eval.sh cargo test
        "base_commit_match": base_commit_match,
        "test_patch_rc": test_patch_rc,
        "gold_patch_rc": gold_patch_rc,
        "compile_ok": compile_ok,
        "no_run_rc": norun_rc,
        "raw_collected_count": raw_collected_count,
        "parser_output_count": parser_output_count,
        "selectors_total": selmap["selectors_total"],
        "selectors_matched": selmap["selectors_matched"],
        "gold_failed": gold_failed,
    }
    is_positive = (role == "POSITIVE_CONTROL")
    if is_positive:
        primary_class, reasons = None, ["positive control (not classified)"]
    else:
        primary_class, reasons = classify_target(ev)

    def _relhash(name):
        p = os.path.join(hostdir, name)
        return {"path": os.path.relpath(p, ROOT).replace("\\", "/"), "sha256": _sha256_file(p)}

    return {
        "role": role,
        "instance_id": iid,
        "official_command": OFFICIAL_CARGO_CMD,
        "command_matches_official": True,
        "base_commit_manifest": manifest_base,
        "base_commit_case": case_base,
        "base_commit_in_container_head": head or None,
        "base_commit_match_manifest_vs_case": base_commit_match_manifest_vs_case,
        "base_commit_match": base_commit_match,
        "image": image_tag,
        "image_ref": image_ref,
        "image_digest_verified": img_info.get("verified"),
        "docker_returncode": dk["docker_returncode"],
        "test_patch_apply_rc": test_patch_rc,
        "gold_patch_apply_rc": gold_patch_rc,
        "official_cargo_rc": official_rc,
        "no_run_rc": norun_rc,
        "list_rc": _read_rc(os.path.join(hostdir, "list.rc")),
        "compile_ok": compile_ok,
        "raw_collected_count": raw_collected_count,
        "raw_by_status": raw["by_status"],
        "raw_summary": raw["summaries"],
        "raw_summary_total": raw["summary_total"],
        "collected_list_count": len(collected_names),
        "parser_method": used_method,
        "parser_detail": parser_detail,
        "parser_error": parser_error,
        "parser_output_count": parser_output_count,
        "selector_mapping": selmap,
        "gold_failed": gold_failed,
        "primary_class": primary_class,
        "classification_reasons": reasons,
        "evidence": ev,
        "artifacts": {
            "official_cargo_stdout": _relhash("official_cargo.stdout"),
            "official_cargo_stderr": _relhash("official_cargo.stderr"),
            "list_stdout": _relhash("list.stdout"),
            "norun_stdout": _relhash("norun.stdout"),
            "test_files_txt": _relhash("test_files.txt"),
            "diag_sh": _relhash("diag.sh"),
            "docker_stdout": _relhash("_docker.stdout"),
            "docker_stderr": _relhash("_docker.stderr"),
        },
        "official_stderr_tail": (official_stderr or "")[-2000:],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R22-P0.9.1 §3 Ruff three-target forensic diagnostic (gated).")
    ap.add_argument("--roles", default="F1,F2,POSITIVE_CONTROL",
                    help="comma-separated roles from the manifest to run")
    args = ap.parse_args(argv)

    # GATE: refuse docker execution without explicit approval (import/py_compile never reach here).
    require_approval()

    manifest = json.load(open(MANIFEST, encoding="utf-8"))
    os.makedirs(RUN_DIR, exist_ok=True)

    checkout = os.path.abspath(SG.ensure_checkout(os.path.join(OUT, "_scb_upstream")))
    SG.verify_tree_hashes(checkout)

    # import the pinned upstream parser once (repo is shared across the three ruff targets)
    repo = manifest["targets"]["F1"].get("repo", "astral-sh/ruff")
    parser_fn, parser_method, parser_detail = load_upstream_parser(checkout, repo)

    results = {
        "experiment": "R22_P09_1_RUFF_FORENSIC_DIAGNOSTIC",
        "pinned_evaluator_commit": SG.PINNED_COMMIT,
        "official_command": OFFICIAL_CARGO_CMD,
        "parser_method": parser_method,
        "parser_detail": parser_detail,
        "rule_classes": list(RULE_CLASSES),
        "targets": {},
    }
    for role in [r.strip() for r in args.roles.split(",") if r.strip()]:
        target = manifest["targets"][role]
        print("== running", role, target["instance_id"], flush=True)
        results["targets"][role] = run_target(role, target, checkout, parser_fn, parser_method, parser_detail)
        print("   ->", results["targets"][role]["primary_class"], flush=True)

    json.dump(results, open(RESULTS, "w", encoding="utf-8"), indent=2)
    print("WROTE", os.path.relpath(RESULTS, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
