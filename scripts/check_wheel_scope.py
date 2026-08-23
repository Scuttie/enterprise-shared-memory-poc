#!/usr/bin/env python3
"""OSS release gate (§3) — the product wheel ships ONLY enterprise_memory + license files, and NO research
code/artifacts. Builds the wheel if none is present, then inspects it. Non-zero exit on violation."""
import glob
import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    os.chdir(ROOT)
    whls = glob.glob("dist/*.whl")
    if not whls:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "setuptools>=77", "build"], check=False)
        subprocess.run([sys.executable, "-m", "build", "--wheel"], check=False)
        whls = glob.glob("dist/*.whl")
    if not whls:
        print("WHEEL SCOPE: FAIL — no wheel built")
        return 1
    whl = sorted(whls)[-1]
    names = zipfile.ZipFile(whl).namelist()
    fails = []
    if not any(n.startswith("enterprise_memory/") for n in names):
        fails.append("enterprise_memory package missing from wheel")
    forbidden = [n for n in names if n.split("/")[0] in ("benchmarks", "experiments", "artifacts", "reports",
                                                          "scripts", "tests", "migrations")]
    if forbidden:
        fails.append("research/non-product paths leaked into wheel: %s" % sorted(set(f.split('/')[0] for f in forbidden)))
    lic = [n for n in names if n.endswith(("LICENSE", "NOTICE.md", "THIRD_PARTY_NOTICES.md"))]
    if len(lic) < 3:
        fails.append("license files missing from wheel dist-info/licenses: %s" % lic)
    if fails:
        print("WHEEL SCOPE: FAIL (%s)" % os.path.basename(whl))
        for f in fails:
            print("  - " + f)
        return 1
    print("WHEEL SCOPE: PASS (%s) — enterprise_memory only + LICENSE/NOTICE/THIRD_PARTY; no research code" % os.path.basename(whl))
    return 0


if __name__ == "__main__":
    sys.exit(main())
