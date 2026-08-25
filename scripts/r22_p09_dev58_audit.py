#!/usr/bin/env python3
"""R22-P0.9 §7 — static case+image audit for all 58 development-pool TARGETS (40 ORIGINAL_P2 + 18 DEV_RESERVE).

Credential-free: GitHub raw (official case JSON at the pinned SCB commit) + Docker Hub registry API (image digest).
No docker, no model, no secret. Produces the metadata freeze consumed by the dev58 gradeability manifest; it does
NOT run the evaluator (that is the gated §8 execution)."""
import ast
import hashlib
import json
import os
import sys
import time
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts", "r22")
OUT = os.path.join(ROOT, "artifacts", "r22_p09")
COMMIT = "31bb04155f52b184bf31b220e3cff0607ac9c953"
RAW = "https://raw.githubusercontent.com/jiayuanz3/SWEContextBench/" + COMMIT
IMG_REPO = "jiayuanz3/swecontextbench"
REG = "https://registry-1.docker.io/v2/" + IMG_REPO
ACCEPT = ("application/vnd.oci.image.index.v1+json,"
          "application/vnd.docker.distribution.manifest.list.v2+json,"
          "application/vnd.docker.distribution.manifest.v2+json,"
          "application/vnd.oci.image.manifest.v1+json")
NARROW = ["SWEContextBench Verified", "SWEContextBench Lite", "SWEContextBench Multilingual"]
LANG = {"astropy": "python", "sympy": "python", "xarray": "python", "seaborn": "python",
        "lucene": "java", "gson": "java", "ruff": "rust", "rubocop": "ruby", "caddy": "go",
        "prometheus": "go", "laravel": "php", "php-cs-fixer": "php"}


def sha256(b):
    return hashlib.sha256(b.encode() if isinstance(b, str) else b).hexdigest()


def http(url, headers=None, retries=4):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=60) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 500, 502, 503) and i < retries - 1:
                time.sleep(2 * (i + 1)); continue
            return e.code, dict(e.headers or {}), b""
        except Exception:
            if i < retries - 1:
                time.sleep(2); continue
            raise


def canon(v):
    if isinstance(v, str):
        s = v.strip()
        try:
            v = ast.literal_eval(s) if s.startswith("[") else [v]
        except Exception:
            try:
                v = json.loads(s)
            except Exception:
                v = [v]
    if not isinstance(v, list):
        v = [v]
    return sha256(json.dumps(sorted(str(x) for x in v)))


def reg_token():
    with urllib.request.urlopen(
            "https://auth.docker.io/token?service=registry.docker.io&scope=repository:%s:pull" % IMG_REPO,
            timeout=60) as r:
        return json.load(r)["token"]


def main():
    os.makedirs(OUT, exist_ok=True)
    pairs = json.load(open(os.path.join(ART, "dev_manifest_v2.json"), encoding="utf-8"))["pairs"]
    orig40 = set()
    m = json.load(open(os.path.join(ART, "oracle_dev_manifest.json"), encoding="utf-8"))
    for t in m["task_list"]:
        orig40.add(t["target_id"])
    tree = json.load(open(os.path.join(
        r"C:/Users/jewon/AppData/Local/Temp/claude/g-----------PC----2026-1-------/3ac33feb-5c89-4bf4-84af-fb1563bea476/scratchpad",
        "scb_tree.json"), encoding="utf-8"))
    case_blobs = [t["path"] for t in tree["tree"] if t["path"].startswith("cases/") and t["type"] == "blob"]
    noop_sha = sha256(__import__("importlib").import_module(
        "experiments.r22.runtime.scb_official_grader").NOOP_BASELINE_PATCH)

    def find_case(iid):
        hits = [p for p in case_blobs if p.endswith("/%s.json" % iid)]
        narrow = [p for p in hits if any(("/%s/" % s) in p for s in NARROW)]
        full = [p for p in hits if "SWEContextBench Full/" in p]
        return (sorted(narrow) or sorted(full) or sorted(hits))

    tok = reg_token()
    out = {}
    seen = []
    for pr in pairs:
        iid = pr["target_id"]
        if iid in out:
            continue
        seen.append(iid)
        rec = {"target_id": iid, "source_id": pr["source_id"], "source_repo": pr["source_repo"],
               "target_repo": pr["target_repo"], "relation_class": pr["class"],
               "repository_cluster": pr["target_repo"],
               "language": LANG.get(pr["target_repo"].split("/")[-1], "unknown"),
               "original_status": "ORIGINAL_P2" if iid in orig40 else "DEV_RESERVE",
               "noop_patch_sha256": noop_sha}
        paths = find_case(iid)
        if not paths:
            rec["case_error"] = "no official case"; out[iid] = rec; print("NOCASE", iid); continue
        import urllib.parse
        st, _, body = http(RAW + "/" + urllib.parse.quote(paths[0]))
        if st != 200:
            rec["case_error"] = "case fetch %d" % st; out[iid] = rec; print("CASEHTTP", iid, st); continue
        d = json.loads(body)
        rec.update({"case_path": paths[0], "subset": paths[0].split("/")[1], "case_sha256": sha256(body),
                    "base_commit": d.get("base_commit"),
                    "issue_sha256": sha256(d.get("problem_statement") or ""),
                    "gold_patch_sha256": sha256(d.get("patch") or ""),
                    "test_patch_sha256": sha256(d.get("test_patch") or ""),
                    "f2p_canon": canon(d.get("FAIL_TO_PASS")), "p2p_canon": canon(d.get("PASS_TO_PASS"))})
        tag = iid.replace("__", ".").lower()
        st2, hdr2, body2 = http(REG + "/manifests/" + tag,
                                {"Authorization": "Bearer " + tok, "Accept": ACCEPT})
        rec["image"] = "%s:%s" % (IMG_REPO, tag)
        rec["image_http"] = st2
        rec["image_digest"] = hdr2.get("Docker-Content-Digest") or (
            ("sha256:" + hashlib.sha256(body2).hexdigest()) if st2 == 200 else None)
        rec["linux_amd64"] = None
        if st2 == 200:
            try:
                man = json.loads(body2)
                plats = ["%s/%s" % (x.get("platform", {}).get("os"), x.get("platform", {}).get("architecture"))
                         for x in man.get("manifests", [])]
                rec["linux_amd64"] = "linux/amd64" in plats
            except Exception:
                pass
        out[iid] = rec
        print("OK", iid, rec["original_status"], rec.get("subset"), "img", st2, rec["language"])
        sys.stdout.flush()

    summary = {"pinned_commit": COMMIT, "targets": len(out),
               "original_p2": sum(1 for r in out.values() if r["original_status"] == "ORIGINAL_P2"),
               "dev_reserve": sum(1 for r in out.values() if r["original_status"] == "DEV_RESERVE"),
               "cases_found": sum(1 for r in out.values() if "case_sha256" in r),
               "images_found": sum(1 for r in out.values() if r.get("image_http") == 200),
               "linux_amd64": sum(1 for r in out.values() if r.get("linux_amd64")),
               "records": out}
    json.dump(summary, open(os.path.join(OUT, "dev58_case_image.json"), "w", encoding="utf-8"), indent=2)
    print("DEV58 AUDIT: targets=%d orig40=%d reserve18=%d cases=%d images=%d amd64=%d"
          % (summary["targets"], summary["original_p2"], summary["dev_reserve"],
             summary["cases_found"], summary["images_found"], summary["linux_amd64"]))


if __name__ == "__main__":
    sys.path.insert(0, ROOT)
    raise SystemExit(main())
