#!/usr/bin/env python3
"""R22-P0.9.2 §4 — Ruff SELECTOR-LEVEL diagnostic (scores each intended FAIL_TO_PASS test directly).

P0.9.1 (`artifacts/r22_p09/ruff_root_cause.json`) proved that for the 2 failed ruff targets the code COMPILES,
base_commit matches, and 500-592 tests collect+run via the identical `cargo test` — so R1(adapter)/R4(drift)/
R7(toolchain)/TRUE_ZERO are EXCLUDED. What it could NOT answer: do the SPECIFIC FAIL_TO_PASS selector tests PASS
under the official gold patch? The prior classifier wrongly leaned on the GLOBAL `cargo test` exit code (rc 101),
which the RESOLVED positive control ALSO shows. This §4 diagnostic scores each intended selector DIRECTLY with
`cargo test "<selector>" -- --exact` inside the frozen official image, then classifies from the per-selector
pass/fail — never from the global exit code.

Structure mirrors `scripts/r22_p09_ruff_forensics.py`: PURE parse/membership/status/agreement/classify functions at
the top (unit-tested without docker via `tests/unit/test_r22_p092_selector.py`), gated docker orchestration below.

CREDENTIAL-FREE IMPORT: imports + py_compile WITHOUT docker/network. Docker execution is gated on
`R22_SCB_UPSTREAM_EXEC_APPROVED=1` exactly like `scb_official_grader.grade()`.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
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
RUN_DIR = os.path.join(OUT, "ruff_sel_run")
RESULTS_V2 = os.path.join(OUT, "ruff_diagnostic_results_v2.json")
ROOTCAUSE_V2 = os.path.join(OUT, "ruff_root_cause_v2.json")

# Reuse the pinned official adapter primitives (ensure_checkout, verify_tree_hashes, _load_case,
# pull_and_verify_image, derive_image_tag, PINNED_COMMIT, UpstreamExecutionNotApproved) so this diagnostic pulls the
# SAME frozen image by digest and reads the SAME authoritative case JSON as the grader.
from experiments.r22.runtime import scb_official_grader as SG  # noqa: E402

# The EXACT per-selector direct command form (fully-qualified `rules::mod::tests::name` is unambiguous across the
# test binaries, so the aggregate parse of a single unqualified `cargo test <sel> -- --exact` yields the one true
# result — `-p <pkg>` is recorded as metadata but not required; see run_target()).
PER_SELECTOR_CMD_FORM = 'cargo test "<selector>" -- --exact --nocapture'
# The official score command (byte-identical to eval.sh) — recorded for provenance; NOT used for per-selector status.
OFFICIAL_CARGO_CMD = "source $HOME/.cargo/env && cargo test"

PRIMARY_CLASSES = (
    "R2_CASE_SELECTOR_BUG",
    "R5_UPSTREAM_PARSER_BUG",
    "R6_UPSTREAM_GOLD_INVALID",
    "MIXED",
    "R8_UNKNOWN",
)

# ============================================================================
# PURE FUNCTIONS (no docker / no network) — unit-tested directly.
# ============================================================================

# A running cargo test line, e.g. "test rules::pyupgrade::tests::foo ... ok"
_TEST_LINE = re.compile(r"^\s*test\s+(?P<name>\S+)\s+\.\.\.\s+(?P<status>ok|FAILED|ignored|bench)\b")
# The cargo per-binary summary, e.g. "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out"
_SUMMARY = re.compile(
    r"test result:\s+(?P<result>\w+)\.\s+(?P<passed>\d+)\s+passed;\s+(?P<failed>\d+)\s+failed;"
    r"\s+(?P<ignored>\d+)\s+ignored")
# A `cargo test -- --list` name line, e.g. "rules::pyupgrade::tests::foo: test"
_LIST_LINE = re.compile(r"^\s*(?P<name>\S+):\s+test\s*$")
# A cargo "Running ... deps/<pkg>-<hash>" header (used to attribute listed names to a package/binary).
_RUNNING = re.compile(r"Running\s+.*?target/debug/deps/(?P<pkg>[A-Za-z0-9_]+)-[0-9a-f]+")


def parse_f2p(v) -> list:
    """Coerce a case FAIL_TO_PASS field into a list[str]. Handles a real list, a JSON string, and a PYTHON-REPR
    string (single quotes) via an ast.literal_eval fallback — mirroring the case-audit `canon()` helper."""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("[") or s.startswith("("):
            for loader in (json.loads, ast.literal_eval):
                try:
                    parsed = loader(s)
                    if isinstance(parsed, (list, tuple)):
                        return [str(x) for x in parsed]
                except Exception:
                    pass
        return [v]
    return [str(v)]


def parse_list_output(list_stdout: str) -> list:
    """Parse `cargo test -- --list` stdout into the ordered list of collected runtime test names."""
    names = []
    for line in (list_stdout or "").splitlines():
        m = _LIST_LINE.match(line)
        if m:
            names.append(m.group("name"))
    return names


def parse_list_with_packages(list_merged: str):
    """Parse a MERGED (`--list 2>&1`) capture into (names, {name: package}). Each name is attributed to the most
    recent `Running ... deps/<pkg>-<hash>` header. Best-effort: package is None when no header preceded the name."""
    names, name_to_pkg, cur = [], {}, None
    for line in (list_merged or "").splitlines():
        rm = _RUNNING.search(line)
        if rm:
            cur = rm.group("pkg")
            continue
        m = _LIST_LINE.match(line)
        if m:
            nm = m.group("name")
            names.append(nm)
            name_to_pkg.setdefault(nm, cur)
    return names, name_to_pkg


def selector_leaf(sel: str) -> str:
    """Trailing `::` segment (leaf symbol) of a selector, e.g. rules::mod::tests::foo -> foo."""
    return (sel or "").strip().split("::")[-1]


def list_membership(selector: str, collected: list) -> dict:
    """Is `selector` present in the `cargo test -- --list` names? Returns listed_exact / listed_normalized /
    matched_name. Normalized = same leaf symbol OR one is a ::-suffix of the other (exact implies normalized)."""
    sel = (selector or "").strip()
    cset = [c.strip() for c in (collected or [])]
    if sel in cset:
        return {"listed_exact": True, "listed_normalized": True, "matched_name": sel}
    leaf = selector_leaf(sel)
    for c in cset:
        if selector_leaf(c) == leaf or c.endswith("::" + sel) or sel.endswith("::" + c) \
                or c.endswith(sel) or sel.endswith(c):
            return {"listed_exact": False, "listed_normalized": True, "matched_name": c}
    return {"listed_exact": False, "listed_normalized": False, "matched_name": None}


def parse_selector_status(stdout: str) -> dict:
    """Status of ONE `cargo test "<sel>" -- --exact` run, from its `test result:` summaries + `test ... ok|FAILED|
    ignored` run lines (summed across binaries). Precedence fail>pass>ignored>absent; absent == nothing ran (the
    selector was filtered out of every binary => not collected / impossible test)."""
    stdout = stdout or ""
    run = {"ok": 0, "FAILED": 0, "ignored": 0, "bench": 0}
    ran = 0
    for line in stdout.splitlines():
        m = _TEST_LINE.match(line)
        if m:
            run[m.group("status")] = run.get(m.group("status"), 0) + 1
            ran += 1
    sp = sf = si = 0
    for m in _SUMMARY.finditer(stdout):
        sp += int(m.group("passed"))
        sf += int(m.group("failed"))
        si += int(m.group("ignored"))
    if run["FAILED"] > 0 or sf > 0:
        status = "fail"
    elif run["ok"] > 0 or sp > 0:
        status = "pass"
    elif run["ignored"] > 0 or si > 0:
        status = "ignored"
    else:
        status = "absent"
    return {"status": status, "passed": sp, "failed": sf, "ignored": si, "ran": ran}


def agreement(direct_status: str, official_status: str) -> str:
    """Agreement of the DIRECT per-selector result with the OFFICIAL baseline. official_status is 'not_passed' for
    the failed targets (campaign F2P 0/N) or 'passed' for the resolved control. Only a direct 'pass' counts as
    passed; ignored/absent/fail all did NOT pass. => direct-pass vs official-not_passed == DISAGREE."""
    direct_passed = (direct_status == "pass")
    official_passed = (official_status == "passed")
    return "AGREE" if direct_passed == official_passed else "DISAGREE"


def compute_counts(rows: list) -> dict:
    """Aggregate per-selector rows into {total, present, absent, pass, fail, ignored, agree, disagree}."""
    by = {"pass": 0, "fail": 0, "ignored": 0, "absent": 0}
    present = agree = disagree = 0
    for r in rows:
        st = r.get("status", "absent")
        by[st] = by.get(st, 0) + 1
        if r.get("listed_exact") or r.get("listed_normalized"):
            present += 1
        ag = r.get("agreement")
        if ag == "AGREE":
            agree += 1
        elif ag == "DISAGREE":
            disagree += 1
    return {"total": len(rows), "present": present, "absent": by["absent"],
            "pass": by["pass"], "fail": by["fail"], "ignored": by["ignored"],
            "agree": agree, "disagree": disagree}


def classify(rows: list):
    """Classify a FAILED target from the PER-SELECTOR direct results (never the global cargo exit code).

    Priority (deterministic):
      MIXED  if some intended selectors pass AND some fail (do not force one global class);
      R2     elif >=1 intended selector is ABSENT (did not execute / not in --list / impossible test);
      R6     elif selectors execute and ALL FAIL directly under gold  (AGREE with official not_passed);
      R5     elif selectors execute and ALL PASS directly under gold   (DISAGREE with official not_passed);
      R8     else indistinguishable.
    Returns (primary_class, reason:str, counts:dict).
    """
    c = compute_counts(rows)
    p, f, absent = c["pass"], c["fail"], c["absent"]
    if p > 0 and f > 0:
        return ("MIXED",
                "some intended selectors pass and some fail under gold "
                "(pass=%d fail=%d ignored=%d absent=%d)" % (p, f, c["ignored"], absent), c)
    if absent > 0:
        return ("R2_CASE_SELECTOR_BUG",
                "%d/%d intended selector(s) ABSENT from `cargo test -- --list` (not collected / impossible test)"
                % (absent, c["total"]), c)
    if f > 0 and p == 0:
        return ("R6_UPSTREAM_GOLD_INVALID",
                "all %d executing selector(s) FAIL directly under the official gold patch "
                "(AGREE with official not_passed)" % f, c)
    if p > 0 and f == 0:
        return ("R5_UPSTREAM_PARSER_BUG",
                "all %d executing selector(s) PASS directly under gold but the official evaluator marked them "
                "not_passed (direct-pass vs official-not_passed DISAGREE)" % p, c)
    return ("R8_UNKNOWN",
            "per-selector evidence did not discriminate (present=%d absent=%d pass=%d fail=%d ignored=%d)"
            % (c["present"], absent, p, f, c["ignored"]), c)


def official_status_for(campaign_result: dict) -> str:
    """Official per-F2P-selector baseline derived from the campaign: 'passed' iff the campaign marked the gold F2P
    set complete (the resolved control), else 'not_passed' (the failed targets graded FAIL_TO_PASS 0/N)."""
    return "passed" if (campaign_result or {}).get("gold_f2p_complete") else "not_passed"


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
            "R22-P0.9.2 ruff SELECTOR diagnostic executes the unlicensed upstream image + `cargo test`; it requires "
            "R22_SCB_UPSTREAM_EXEC_APPROVED=1 (see reports/R22_UPSTREAM_RIGHTS_STATUS.md). Import/py_compile do not.")


def _build_sel_script() -> str:
    """In-container script: HEAD, apply test.patch then gold patch.diff, collect --list, then run EACH intended
    selector directly with `cargo test "<sel>" -- --exact --nocapture` (selectors read from /host/selectors.txt in
    order; index i -> sel_<i>.*). Does NOT edit the case or the tests."""
    return "\n".join([
        "#!/usr/bin/env bash",
        "set +e",
        "cd /testbed",
        "git rev-parse HEAD > /host/head.txt 2> /host/head.err",
        "git apply /host/test.patch > /host/test_patch.stdout 2> /host/test_patch.stderr; echo $? > /host/test_patch.rc",
        "git apply /host/patch.diff > /host/gold_patch.stdout 2> /host/gold_patch.stderr; echo $? > /host/gold_patch.rc",
        'source "$HOME/.cargo/env"',
        "# collected runtime names (clean stdout) + a merged capture for package/binary attribution",
        "cargo test -- --list > /host/list.stdout 2> /host/list.stderr; echo $? > /host/list.rc",
        "cargo test -- --list > /host/list.merged 2>&1",
        "# score EACH intended FAIL_TO_PASS selector DIRECTLY (per-selector, --exact) — NOT the global exit code",
        "i=0",
        "while IFS= read -r sel; do",
        '  [ -z "$sel" ] && { i=$((i+1)); continue; }',
        '  cargo test "$sel" -- --exact --nocapture > "/host/sel_${i}.stdout" 2> "/host/sel_${i}.stderr"',
        '  echo $? > "/host/sel_${i}.rc"',
        "  i=$((i+1))",
        "done < /host/selectors.txt",
    ])


def _docker_run_selectors(image_ref: str, hostdir: str) -> dict:
    """Run the in-container per-selector script inside the pinned image, host dir mounted rw at /host."""
    open(os.path.join(hostdir, "sel.sh"), "w", encoding="utf-8", newline="\n").write(_build_sel_script())
    mount = "%s:/host" % os.path.abspath(hostdir)
    cmd = ["docker", "run", "--rm", "--platform", "linux/amd64", "-v", mount, image_ref,
           "bash", "-lc", "bash /host/sel.sh"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    open(os.path.join(hostdir, "_docker.stdout"), "w", encoding="utf-8").write(proc.stdout or "")
    open(os.path.join(hostdir, "_docker.stderr"), "w", encoding="utf-8").write(proc.stderr or "")
    return {"docker_returncode": proc.returncode, "docker_cmd": " ".join(cmd)}


def run_target(role: str, target: dict, checkout: str) -> dict:
    iid = target["instance_id"]
    hostdir = os.path.join(RUN_DIR, iid)
    os.makedirs(hostdir, exist_ok=True)

    # authoritative case JSON (base_commit / test_patch / gold / FAIL_TO_PASS) from the pinned checkout
    case_route = {"instance_id": iid, "case_path": target["case_path"], "case_sha256": target.get("case_sha256")}
    case = SG._load_case(checkout, case_route)
    case_base = case.get("base_commit")
    selectors = parse_f2p(case.get("FAIL_TO_PASS"))
    official_status = official_status_for(target.get("campaign_result"))

    # materialize container inputs
    open(os.path.join(hostdir, "test.patch"), "w", encoding="utf-8", newline="\n").write(case.get("test_patch") or "")
    open(os.path.join(hostdir, "patch.diff"), "w", encoding="utf-8", newline="\n").write(case.get("patch") or "")
    open(os.path.join(hostdir, "selectors.txt"), "w", encoding="utf-8", newline="\n").write(
        "\n".join(selectors) + ("\n" if selectors else ""))

    # pull the frozen image BY DIGEST + verify once, then run the per-selector diagnostic in one container
    image_tag = target["image"]
    digest = target["image_digest"]
    img_info = SG.pull_and_verify_image(image_tag, digest)
    image_ref = "%s@%s" % (image_tag.split(":")[0], digest)
    dk = _docker_run_selectors(image_ref, hostdir)

    head = _read(os.path.join(hostdir, "head.txt")).strip()
    base_commit_match = (head == case_base) if head else None
    test_patch_rc = _read_rc(os.path.join(hostdir, "test_patch.rc"))
    gold_patch_rc = _read_rc(os.path.join(hostdir, "gold_patch.rc"))
    list_rc = _read_rc(os.path.join(hostdir, "list.rc"))

    collected = parse_list_output(_read(os.path.join(hostdir, "list.stdout")))
    _, name_to_pkg = parse_list_with_packages(_read(os.path.join(hostdir, "list.merged")))

    def _relhash(name):
        p = os.path.join(hostdir, name)
        return {"path": os.path.relpath(p, ROOT).replace("\\", "/"), "sha256": _sha256_file(p)}

    rows = []
    for i, sel in enumerate(selectors):
        mem = list_membership(sel, collected)
        so = os.path.join(hostdir, "sel_%d.stdout" % i)
        se = os.path.join(hostdir, "sel_%d.stderr" % i)
        st = parse_selector_status(_read(so))
        status = st["status"]
        ag = agreement(status, official_status)
        pkg = name_to_pkg.get(sel) or (name_to_pkg.get(mem["matched_name"]) if mem["matched_name"] else None)
        rows.append({
            "selector": sel,
            "listed_exact": mem["listed_exact"],
            "listed_normalized": mem["listed_normalized"],
            "matched_list_name": mem["matched_name"],
            "package": pkg,
            "direct_command": 'cargo test "%s" -- --exact --nocapture' % sel,
            "return_code": _read_rc(os.path.join(hostdir, "sel_%d.rc" % i)),
            "status": status,
            "status_detail": {k: st[k] for k in ("passed", "failed", "ignored", "ran")},
            "official_status": official_status,
            "agreement": ag,
            "stdout": _relhash("sel_%d.stdout" % i),
            "stderr": _relhash("sel_%d.stderr" % i),
        })

    is_failed = role in ("F1", "F2")
    if is_failed:
        primary_class, reason, counts = classify(rows)
    else:
        counts = compute_counts(rows)
        primary_class, reason = None, "POSITIVE_CONTROL (method validation; not classified)"

    return {
        "role": role,
        "instance_id": iid,
        "per_selector_command_form": PER_SELECTOR_CMD_FORM,
        "official_command": OFFICIAL_CARGO_CMD,
        "image": image_tag,
        "image_ref": image_ref,
        "image_digest_verified": img_info.get("verified"),
        "docker_returncode": dk["docker_returncode"],
        "base_commit_case": case_base,
        "base_commit_in_container_head": head or None,
        "base_commit_match": base_commit_match,
        "test_patch_apply_rc": test_patch_rc,
        "gold_patch_apply_rc": gold_patch_rc,
        "list_rc": list_rc,
        "collected_list_count": len(collected),
        "official_status_baseline": official_status,
        "selectors_total": len(selectors),
        "per_selector": rows,
        "counts": counts,
        "primary_class": primary_class,
        "classification_reason": reason,
        "artifacts": {
            "sel_sh": _relhash("sel.sh"),
            "selectors_txt": _relhash("selectors.txt"),
            "test_patch": _relhash("test.patch"),
            "gold_patch": _relhash("patch.diff"),
            "list_stdout": _relhash("list.stdout"),
            "list_merged": _relhash("list.merged"),
            "head_txt": _relhash("head.txt"),
            "test_patch_stderr": _relhash("test_patch.stderr"),
            "gold_patch_stderr": _relhash("gold_patch.stderr"),
            "docker_stdout": _relhash("_docker.stdout"),
            "docker_stderr": _relhash("_docker.stderr"),
        },
    }


def build_root_cause(results: dict) -> dict:
    """Per FAILED target: primary_class + evidence + the classes EXCLUDED by P0.9.1 (R1/R4/R7/TRUE_ZERO)."""
    tcs = {}
    for role in ("F1", "F2"):
        t = results["targets"].get(role)
        if not t:
            continue
        base_ok = t.get("base_commit_match")
        list_ok = (t.get("list_rc") == 0) or (t.get("collected_list_count", 0) > 0)
        tcs[t["instance_id"]] = {
            "role": role,
            "primary_class": t["primary_class"],
            "classification_reason": t["classification_reason"],
            "counts": t["counts"],
            "official_status_baseline": t["official_status_baseline"],
            "evidence": {
                "base_commit_match": base_ok,
                "test_patch_apply_rc": t["test_patch_apply_rc"],
                "gold_patch_apply_rc": t["gold_patch_apply_rc"],
                "collected_list_count": t["collected_list_count"],
                "selectors_total": t["selectors_total"],
                "per_selector_command_form": t["per_selector_command_form"],
                "scored_from": "per-selector DIRECT `cargo test <sel> -- --exact` results (NOT the global exit code)",
            },
            "excluded_classes": {
                "R1_ADAPTER_INVOCATION_BUG":
                    "per-selector uses `cargo test <sel> -- --exact` on the official FAIL_TO_PASS selectors from the "
                    "authoritative case JSON; the score command is the byte-identical official `cargo test`",
                "R4_IMAGE_CASE_DRIFT":
                    "in-container HEAD == case base_commit (base_commit_match=%s)" % base_ok,
                "R7_TOOLCHAIN_INCOMPATIBILITY":
                    "compiles + tests execute: `cargo test -- --list` rc=%s collected %d tests"
                    % (t.get("list_rc"), t.get("collected_list_count", 0)),
                "TRUE_ZERO_COLLECTION":
                    "%d tests collect via --list and the intended selectors execute directly (not a true zero)"
                    % t.get("collected_list_count", 0),
            },
        }
    return {
        "experiment": "R22_P09_2_RUFF_SELECTOR_ROOT_CAUSE",
        "pinned_evaluator_commit": SG.PINNED_COMMIT,
        "method": "score each intended FAIL_TO_PASS selector DIRECTLY under the official gold patch; classify from "
                  "the per-selector pass/fail, never from the global `cargo test` exit code",
        "official_baseline_note": "official_status per FAIL_TO_PASS selector derives from the campaign result: the "
                                  "failed targets graded FAIL_TO_PASS 0/N => 'not_passed'.",
        "excluded_by_p091": ["R1_ADAPTER_INVOCATION_BUG", "R4_IMAGE_CASE_DRIFT",
                             "R7_TOOLCHAIN_INCOMPATIBILITY", "TRUE_ZERO_COLLECTION"],
        "targets": tcs,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R22-P0.9.2 §4 Ruff SELECTOR-LEVEL diagnostic (gated).")
    ap.add_argument("--roles", default="F1,F2,POSITIVE_CONTROL",
                    help="comma-separated roles from the manifest to run")
    args = ap.parse_args(argv)

    # GATE: refuse docker execution without explicit approval (import/py_compile never reach here).
    require_approval()

    manifest = json.load(open(MANIFEST, encoding="utf-8"))
    os.makedirs(RUN_DIR, exist_ok=True)

    checkout = os.path.abspath(SG.ensure_checkout(os.path.join(OUT, "_scb_upstream")))
    SG.verify_tree_hashes(checkout)

    results = {
        "experiment": "R22_P09_2_RUFF_SELECTOR_DIAGNOSTIC",
        "pinned_evaluator_commit": SG.PINNED_COMMIT,
        "per_selector_command_form": PER_SELECTOR_CMD_FORM,
        "official_command": OFFICIAL_CARGO_CMD,
        "primary_classes": list(PRIMARY_CLASSES),
        "official_baseline_note": "official_status per FAIL_TO_PASS selector = 'not_passed' for the failed targets "
                                  "(campaign FAIL_TO_PASS 0/N: all F2P selectors reported NOT passing / uncollected); "
                                  "'passed' for the resolved positive control. DIRECT-pass vs official-not_passed = "
                                  "DISAGREE; DIRECT-fail vs official-not_passed = AGREE.",
        "targets": {},
    }
    for role in [r.strip() for r in args.roles.split(",") if r.strip()]:
        target = manifest["targets"][role]
        print("== running", role, target["instance_id"], flush=True)
        results["targets"][role] = run_target(role, target, checkout)
        print("   ->", results["targets"][role]["primary_class"],
              results["targets"][role]["counts"], flush=True)

    json.dump(results, open(RESULTS_V2, "w", encoding="utf-8"), indent=2)
    json.dump(build_root_cause(results), open(ROOTCAUSE_V2, "w", encoding="utf-8"), indent=2)
    print("WROTE", os.path.relpath(RESULTS_V2, ROOT))
    print("WROTE", os.path.relpath(ROOTCAUSE_V2, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
