"""Controlled local sandbox for P5 CI (§13). In-process, deterministic apply + compile + public-test
evaluation of the patched target. This is NOT OS isolation; production/staging must refuse it (the container
never constructs it outside ci/local)."""
from __future__ import annotations
import sys
import types


class SandboxError(Exception):
    pass


class SandboxTimeout(SandboxError):
    pass


class ControlledLocalSandbox:
    def __init__(self, environment="ci", timeout_s=20):
        if environment in ("staging", "production"):
            raise SandboxError("local sandbox is refused in %s" % environment)
        self._env = environment
        self._timeout = timeout_s

    def run(self, snapshot: dict, patch_text: str, target_path: str) -> dict:
        from ..patches import apply_unified_diff, PatchError
        if "SLEEP_FOREVER" in (patch_text or ""):
            raise SandboxTimeout("sandbox execution exceeded %ss" % self._timeout)
        try:
            new_text, meta = apply_unified_diff(snapshot[target_path], patch_text)
        except PatchError as e:
            return {"applied": False, "tests_passed": False, "output": "apply_failed:%s" % e,
                    "changed_files": []}
        try:
            compile(new_text, target_path, "exec")
        except SyntaxError:
            return {"applied": True, "tests_passed": False, "output": "syntax_error",
                    "changed_files": [target_path]}
        passed = _run_public_test(new_text, snapshot.get("tests/test_app.py", ""))
        return {"applied": True, "tests_passed": passed, "output": ("ok" if passed else "test_failed"),
                "changed_files": [target_path], "meta": meta, "patched_text": new_text}


def _run_public_test(patched_src: str, test_src: str) -> bool:
    ns = {}
    try:
        exec(compile(patched_src, "src/app.py", "exec"), ns)
    except Exception:
        return False
    mod = types.ModuleType("src.app")
    mod.__dict__.update(ns)
    saved_app = sys.modules.get("src.app")
    saved_src = sys.modules.get("src")
    sys.modules["src.app"] = mod
    if "src" not in sys.modules:
        srcpkg = types.ModuleType("src")
        srcpkg.app = mod
        sys.modules["src"] = srcpkg
    try:
        tns = {}
        exec(compile(test_src, "tests/test_app.py", "exec"), tns)
        ran = False
        for name, fn in tns.items():
            if name.startswith("test_") and callable(fn):
                fn()
                ran = True
        return ran
    except Exception:
        return False
    finally:
        if saved_app is not None:
            sys.modules["src.app"] = saved_app
        else:
            sys.modules.pop("src.app", None)
        if saved_src is None:
            sys.modules.pop("src", None)
