#!/usr/bin/env python3
"""R22 §7.3 — which source information survives in each view (O3 full vs O4/O5/O6 compressed). No model calls."""
import re
from collections import defaultdict

FIELDS = ("file", "symbol", "api", "operation", "precondition", "validation", "raw_diff")


def _signals(text):
    text = text or ""
    return {
        "file": bool(re.search(r"\.\w+\b|/", text)),
        "symbol": bool(re.search(r"\b[a-z_]+\(", text)),
        "api": "import" in text or "api" in text.lower(),
        "operation": any(w in text.lower() for w in ("guard", "copy", "return", "add", "fix", "change")),
        "precondition": "when" in text.lower() or "if" in text.lower(),
        "validation": any(w in text.lower() for w in ("test", "pass", "verify", "assert")),
        "raw_diff": "diff:" in text.lower() or text.strip().startswith(("+", "-")),
        "tokens": max(len(text.split()), len(text) // 4),
    }


def retention(records):
    by_arm_text = defaultdict(list)
    for r in records:
        inj = r.get("injection") or {}
        if inj.get("text"):
            by_arm_text[r["arm"]].append(inj["text"])
    out = {}
    for arm in ("O3", "O4", "O5", "O6"):
        texts = by_arm_text.get(arm, [])
        if not texts:
            out[arm] = {"n": 0}
            continue
        agg = {f: 0 for f in FIELDS}
        toks = 0
        for t in texts:
            s = _signals(t)
            for f in FIELDS:
                agg[f] += int(s[f])
            toks += s["tokens"]
        out[arm] = {"n": len(texts), "mean_tokens": round(toks / len(texts), 1),
                    **{f: round(agg[f] / len(texts), 3) for f in FIELDS}}
    return out
