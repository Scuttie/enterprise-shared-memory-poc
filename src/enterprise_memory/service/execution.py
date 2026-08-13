"""Coding execution backend (P5 §1). The worker never wires directly to a model provider; it calls a
CodingExecutionBackend that returns a common ExecutionResult. Three backends share the contract:
FakeExecutionBackend (deterministic CI), DirectModelExecutionBackend (a CodingModelProvider returns a patch),
and ExternalHarnessExecutionBackend (the boundary for a company Claude-Code-style/local-GLM harness). A
backend receives only the immutable snapshot reference, the instruction, the server-owned edit/test policy,
and governed compact views — never DB/Git/object-store/OIDC credentials — and may not override editable
paths, hidden tests, permissions, or the final verdict."""
from __future__ import annotations
import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from ..providers.base import ModelRequest


def _sha(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


@dataclass
class ExecutionResult:
    patch_text: str
    raw_response: str
    model_call_records: List[dict] = field(default_factory=list)
    harness_metadata: dict = field(default_factory=dict)
    tool_calls: List[dict] = field(default_factory=list)
    public_test_evidence: Optional[dict] = None
    returned_model: Optional[str] = None
    backend_type: str = "fake"


class CodingExecutionBackend(ABC):
    @abstractmethod
    async def execute(self, task_context: dict, repository_snapshot: dict, memory_views: list, *,
                      logical_request_id: str, org_id: str) -> ExecutionResult: ...


def _canned_patch(target_path: str) -> str:
    # deterministic minimal in-policy edit: rewrite the target function body
    return ("--- a/%s\n+++ b/%s\n@@ -1,2 +1,3 @@\n def f():\n-    return 0\n"
            "+    # governed fix applied\n+    return 1\n") % (target_path, target_path)


class FakeExecutionBackend(CodingExecutionBackend):
    """Deterministic CI backend — returns an in-policy patch for the task's target path; no model call."""
    def __init__(self, target_path="src/app.py", patch_text=None):
        self._target = target_path
        self._patch = patch_text

    async def execute(self, task_context, repository_snapshot, memory_views, *, logical_request_id, org_id):
        target = task_context.get("target_path") or self._target
        patch = self._patch if self._patch is not None else _canned_patch(target)
        return ExecutionResult(
            patch_text=patch, raw_response=patch, backend_type="fake", returned_model="fake-coder-1",
            model_call_records=[{"logical_request_id": logical_request_id, "backend_type": "fake",
                                 "final_status": "success", "attempts": 1, "requested_model": "fake-coder-1",
                                 "returned_model": "fake-coder-1", "redaction_status": "clean",
                                 "prompt_hash": _sha(json.dumps([v for v in memory_views], sort_keys=True)),
                                 "response_hash": _sha(patch)}],
            harness_metadata={"deterministic": True}, public_test_evidence=None)


class DirectModelExecutionBackend(CodingExecutionBackend):
    """Builds a coding prompt from the task + governed views, calls a CodingModelProvider, extracts the
    unified diff from the response. Sandbox remains a separate worker stage."""
    def __init__(self, provider, model_max_tokens=1024):
        self._p = provider
        self._max = model_max_tokens

    async def execute(self, task_context, repository_snapshot, memory_views, *, logical_request_id, org_id):
        from ..patches import extract_diff  # noqa
        prompt = self._build_prompt(task_context, repository_snapshot, memory_views)
        req = ModelRequest(messages=[{"role": "user", "content": prompt}], max_output_tokens=self._max)
        response, record = await self._p.generate(req, logical_request_id=logical_request_id, org_id=org_id)
        patch = extract_diff(response.text)
        return ExecutionResult(
            patch_text=patch, raw_response=response.text, returned_model=response.returned_model,
            backend_type="direct_model", model_call_records=[record.to_dict()],
            harness_metadata={"prompt_hash": _sha(prompt)})

    @staticmethod
    def _build_prompt(task_context, repository_snapshot, memory_views):
        # Governed compact views only — never raw provenance/private traces (already projected upstream).
        views = "\n\n".join("### governed view %d\n%s" % (i, json.dumps(v, sort_keys=True))
                            for i, v in enumerate(memory_views))
        files = "\n".join("# %s\n%s" % (p, c) for p, c in sorted(repository_snapshot.items()))
        return ("Task: %s\nEditable target: %s\n\n%s\n\nRepository (read-only snapshot):\n%s\n\n"
                "Return ONLY a unified diff patch." % (task_context.get("instruction", ""),
                                                       task_context.get("target_path", ""), views, files))


class WholeFileModelExecutionBackend(CodingExecutionBackend):
    """Asks the model for the COMPLETE corrected target file (not a diff) and constructs the unified diff
    server-side with difflib, so a valid rewrite always applies (robust to model diff-format variance). The
    server still owns edit-policy validation, hidden tests, and the sandbox verdict."""
    def __init__(self, provider, model_max_tokens=1024):
        self._p = provider
        self._max = model_max_tokens

    async def execute(self, task_context, repository_snapshot, memory_views, *, logical_request_id, org_id):
        import difflib
        import re
        target = task_context.get("target_path")
        original = repository_snapshot.get(target, "")
        prompt = self._build_prompt(task_context, original, memory_views)
        req = ModelRequest(messages=[{"role": "user", "content": prompt}], max_output_tokens=self._max)
        response, record = await self._p.generate(req, logical_request_id=logical_request_id, org_id=org_id)
        m = re.search(r"```(?:python)?\s*(.*?)```", response.text, re.S)
        new_file = (m.group(1) if m else response.text).strip("\n") + "\n"
        diff = "".join(difflib.unified_diff(original.splitlines(keepends=True), new_file.splitlines(keepends=True),
                                            fromfile="a/%s" % target, tofile="b/%s" % target))
        return ExecutionResult(
            patch_text=diff, raw_response=response.text, returned_model=response.returned_model,
            backend_type="direct_model_wholefile", model_call_records=[record.to_dict()],
            harness_metadata={"prompt_hash": _sha(prompt), "mode": "whole_file"})

    @staticmethod
    def _build_prompt(task_context, original, memory_views):
        views = "\n\n".join("### governed memory view %d\n%s" % (i, v) for i, v in enumerate(memory_views))
        mem = ("\n\n%s" % views) if views else ""
        return ("You are completing a Python file. Task: %s\nEditable target file: %s\n\n"
                "Current file contents:\n```python\n%s```%s\n\n"
                "Rewrite the COMPLETE file so that all of the repository's tests pass. Keep the function "
                "signature unchanged. Return ONLY the full file content in a single ```python code block."
                % (task_context.get("instruction", ""), task_context.get("target_path", ""), original, mem))


class P52WholeFileExecutionBackend(CodingExecutionBackend):
    """P5.2 backend. Like the whole-file backend but the prompt shows the FULL read-only snapshot (target file
    + the incomplete PUBLIC test), so the model fits the observable core behaviour rather than applying generic
    domain priors, and the server builds the diff with difflib. Governed memory (if any) supplies the hidden
    edge convention. Kept separate from WholeFileModelExecutionBackend so the frozen P5.1 prompt is unchanged."""
    def __init__(self, provider, model_max_tokens=1024):
        self._p = provider
        self._max = model_max_tokens

    async def execute(self, task_context, repository_snapshot, memory_views, *, logical_request_id, org_id):
        import difflib
        import re
        target = task_context.get("target_path")
        original = repository_snapshot.get(target, "")
        prompt = self._build_prompt(task_context, repository_snapshot, memory_views)
        req = ModelRequest(messages=[{"role": "user", "content": prompt}], max_output_tokens=self._max)
        response, record = await self._p.generate(req, logical_request_id=logical_request_id, org_id=org_id)
        m = re.search(r"```(?:python)?\s*(.*?)```", response.text, re.S)
        new_file = (m.group(1) if m else response.text).strip("\n") + "\n"
        diff = "".join(difflib.unified_diff(original.splitlines(keepends=True),
                                            new_file.splitlines(keepends=True),
                                            fromfile="a/%s" % target, tofile="b/%s" % target))
        return ExecutionResult(
            patch_text=diff, raw_response=response.text, returned_model=response.returned_model,
            backend_type="p52_wholefile", model_call_records=[record.to_dict()],
            harness_metadata={"prompt_hash": _sha(prompt), "mode": "p52_wholefile"})

    @staticmethod
    def _build_prompt(task_context, repository_snapshot, memory_views):
        target = task_context.get("target_path", "")
        files = "\n".join("### file: %s\n```python\n%s```" % (p, c)
                          for p, c in sorted(repository_snapshot.items()))
        views = "\n\n".join("### governed memory view %d\n%s" % (i, v) for i, v in enumerate(memory_views))
        mem = ("\n\nGoverned memory (authoritative for any documented edge-case rule):\n%s" % views) if views \
              else ""
        return ("You are editing a small Python repository. Read the read-only snapshot below, which includes "
                "the file to edit and its (incomplete) public test.\n\n%s%s\n\nRewrite the COMPLETE file `%s` "
                "so that ALL tests pass — the visible public tests AND any additional hidden tests. Make the "
                "observable public behaviour exactly match the public test. Keep the function signature "
                "unchanged. Return ONLY the full file content in one ```python code block."
                % (files, mem, target))


class ExternalHarnessExecutionBackend(CodingExecutionBackend):
    """Boundary for a company Claude-Code-style/local-GLM harness. `harness` is an injected client with an
    async `run(payload) -> dict`. It receives ONLY governed inputs and returns a patch + sanitized metadata;
    it never sees credentials and cannot override the server-owned policy or the final verdict."""
    def __init__(self, harness):
        self._h = harness

    async def execute(self, task_context, repository_snapshot, memory_views, *, logical_request_id, org_id):
        payload = {"logical_request_id": logical_request_id, "instruction": task_context.get("instruction"),
                   "target_path": task_context.get("target_path"),
                   "repository_reference": task_context.get("repository_reference"),
                   "edit_policy": task_context.get("edit_policy"), "memory_views": memory_views}
        out = await self._h.run(payload)   # credentials never included in `payload`
        return ExecutionResult(
            patch_text=out.get("patch", ""), raw_response=out.get("raw", out.get("patch", "")),
            backend_type="external_harness", returned_model=out.get("model"),
            harness_metadata={"harness_identity": out.get("harness_identity"),
                              "usage": out.get("usage"), "latency": out.get("latency")},
            tool_calls=out.get("tool_calls", []), public_test_evidence=out.get("public_test_evidence"),
            model_call_records=out.get("model_call_records", []))
