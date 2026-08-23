"""Controlled local sandbox for P5/P5.1 CI (§13). In-process, deterministic apply + compile + test evaluation
of the patched target. Grading runs a SERVER-OWNED test (the hidden test for experiment tasks, passed in by
the worker and never present in the model-visible snapshot); if none is supplied it falls back to the
snapshot's public test. This is NOT OS isolation; production/staging must refuse it (the container never
constructs it outside ci/local)."""
from __future__ import annotations
import sys
import types


class SandboxError(Exception):
    pass


class SandboxTimeout(SandboxError):
    pass


def _module_name(target_path: str) -> str:
    # src/foo.py -> src.foo ; tests never map here
    p = target_path[:-3] if target_path.endswith(".py") else target_path
    return p.replace("/", ".").strip(".")


class ControlledLocalSandbox:
    def __init__(self, environment="ci", timeout_s=20):
        if environment in ("staging", "production"):
            raise SandboxError("local sandbox is refused in %s" % environment)
        self._env = environment
        self._timeout = timeout_s

    def run(self, snapshot: dict, patch_text: str, target_path: str, grading_test: str = None) -> dict:
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
        # REALBENCH-R1: an "EVALPLUS:<task_id>" grading marker routes to the OFFICIAL MBPP+ evaluator (Linux/CI)
        if grading_test is not None and grading_test.startswith("EVALPLUS:"):
            from experiments.realbench_r1 import grader as _G
            r = _G.grade(grading_test[len("EVALPLUS:"):], new_text)
            return {"applied": True, "tests_passed": bool(r["mbpp_plus_pass"]),
                    "output": ("ok" if r["mbpp_plus_pass"] else "mbpp_plus_fail"),
                    "base_pass": r["base_pass"], "plus_pass": r["plus_pass"], "exec_ok": r["exec_ok"],
                    "changed_files": [target_path], "meta": meta, "patched_text": new_text}
        # REALBENCH-R2: a "BIGCODE:<task_id>" grading marker routes to the OFFICIAL BigCodeBench evaluator
        # (Linux + official eval image only).
        if grading_test is not None and grading_test.startswith("BIGCODE:"):
            from experiments.bigcode_r2 import grader as _BG
            r = _BG.grade(grading_test[len("BIGCODE:"):], new_text)
            return {"applied": True, "tests_passed": bool(r["bigcodebench_pass"]),
                    "output": ("ok" if r["bigcodebench_pass"] else "bigcode_fail"),
                    "base_pass": r["base_pass"], "status": r["status"], "exec_ok": r["exec_ok"],
                    "changed_files": [target_path], "meta": meta, "patched_text": new_text}
        # REALBENCH-R3: a "DS1000:<problem_id>" grading marker routes to the OFFICIAL DS-1000 evaluator
        # (Linux + official conda env only). new_text is the already-extracted completion snippet.
        if grading_test is not None and grading_test.startswith("DS1000:"):
            from experiments.actionable_memory_r3 import ds1000_grader as _DS
            r = _DS.grade_by_id(grading_test[len("DS1000:"):], new_text, already_extracted=True)
            return {"applied": True, "tests_passed": bool(r["passed"]),
                    "output": ("ok" if r["passed"] else "ds1000_fail"), "exec_ok": True,
                    "changed_files": [target_path], "meta": meta, "patched_text": new_text}
        # grade on the server-owned test (hidden for experiment tasks); fall back to the snapshot public test
        test_src = grading_test if grading_test is not None else snapshot.get("tests/test_app.py", "")
        passed = _run_test(new_text, target_path, test_src)
        return {"applied": True, "tests_passed": passed, "output": ("ok" if passed else "test_failed"),
                "changed_files": [target_path], "meta": meta, "patched_text": new_text}


def _run_test(patched_src: str, target_path: str, test_src: str) -> bool:
    modname = _module_name(target_path)
    ns = {}
    try:
        exec(compile(patched_src, target_path, "exec"), ns)
    except Exception:
        return False
    mod = types.ModuleType(modname)
    mod.__dict__.update(ns)
    saved_mod = sys.modules.get(modname)
    saved_src = sys.modules.get("src")
    sys.modules[modname] = mod
    if "src" not in sys.modules:
        srcpkg = types.ModuleType("src"); srcpkg.__path__ = []
        sys.modules["src"] = srcpkg
    # also expose as an attribute of the src package (supports `from src.x import y`)
    short = modname.split(".", 1)[1] if modname.startswith("src.") else modname
    setattr(sys.modules["src"], short, mod)
    try:
        tns = {}
        exec(compile(test_src or "", target_path + ".test", "exec"), tns)
        ran = False
        for name, fn in tns.items():
            if name.startswith("test_") and callable(fn):
                fn()
                ran = True
        return ran
    except Exception:
        return False
    finally:
        if saved_mod is not None:
            sys.modules[modname] = saved_mod
        else:
            sys.modules.pop(modname, None)
        if saved_src is None:
            sys.modules.pop("src", None)
