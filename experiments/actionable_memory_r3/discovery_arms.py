"""REALBENCH-R3 §12 — discovery arm constants (pure; no service deps). Kept separate so both the service-side
seeding (discovery.py) and the light aggregation/combine (discovery_analysis.py) can import them without pulling
enterprise_memory."""
from experiments.actionable_memory_r3 import renderers as R

BUNDLES = R.BUNDLE_ORDER                       # B0..B9
ARMS = ["D0", "D1"] + ["D%d" % (i + 2) for i in range(len(BUNDLES))]   # D0,D1,D2..D11
ARM_BUNDLE = {"D%d" % (i + 2): b for i, b in enumerate(BUNDLES)}       # D2->B0 ... D11->B9
BASELINE_BUNDLE = "B0"
