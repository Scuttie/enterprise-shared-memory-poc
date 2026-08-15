"""REALBENCH-R3 §9/§10/§23 — freeze renderer + decoder manifests (code/text hashes + token budget). No model
calls. The seal (§23) verifies these hashes are unchanged post-result. Usage: python scripts/r3_build_manifests.py"""
import hashlib
import inspect
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from experiments.actionable_memory_r3 import renderers as R, decoders as D  # noqa: E402

OUT = os.path.join(REPO, "artifacts", "actionable_memory_r3")


def _h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def main():
    rman = {"tokenizer": R.TOKENIZER, "max_tokens": R.MAX_TOKENS, "bundle_order": R.BUNDLE_ORDER,
            "renderers": {b: {"code_hash": _h(inspect.getsource(R.RENDERERS[b]))} for b in R.BUNDLE_ORDER},
            "redact_hash": _h(inspect.getsource(R._redact)),
            "assemble_hash": _h(inspect.getsource(R.render))}
    dman = D.manifest()
    json.dump(rman, open(os.path.join(OUT, "renderer_manifest.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    json.dump({"decoders": dman}, open(os.path.join(OUT, "decoder_manifest.json"), "w", encoding="utf-8",
                                       newline="\n"), indent=2, sort_keys=True)
    print("renderer_manifest bundles", len(rman["renderers"]), "tokenizer", rman["tokenizer"])
    print("decoder_manifest", {k: v["hash"] for k, v in dman.items()})


if __name__ == "__main__":
    main()
