"""§9 SolveOrchestrator — the real retrieval->injection->generation->test->persist pipeline, driven by
injected services so it runs identically with local fakes (Gate A local) or production adapters. Private
and shared searches stay separate until access control; invalid contracts produce NO model-facing text;
at most two views are injected; canonical IDs live only in hidden metadata, never in the execution view;
no client-supplied patch/test result is ever trusted."""
from __future__ import annotations
import hashlib

from .compiler_ir import compile_directive, ViewRefused
from .identity import IdentityContext


class SolveOrchestrator:
    def __init__(self, registry, private_index, shared_index, authz, repo_provider, model, sandbox,
                 audit, metrics, directive_builder, max_injected=2):
        self.registry = registry
        self.private_index = private_index
        self.shared_index = shared_index
        self.authz = authz
        self.repo = repo_provider
        self.model = model
        self.sandbox = sandbox
        self.audit = audit
        self.metrics = metrics
        self.directive_builder = directive_builder      # (canonical_contract, task) -> ExecutionDirective
        self.max_injected = max_injected

    def solve(self, ident: IdentityContext, task: dict, logical_request_id: str) -> dict:
        trail = []
        if not ident.has_scope("solve:submit"):
            raise PermissionError("missing scope solve:submit")
        repo_id = task["repo_id"]
        if not self.authz.can_read(ident, repo_id):
            self.audit.emit("authz_denied", ident.subject_id, repo_id, {"op": "solve"})
            raise PermissionError("repo_read_denied")
        commit = self.repo.resolve_commit(repo_id, task.get("ref", "main"))
        snapshot = self.repo.snapshot(repo_id, commit, task.get("path_allowlist", []))
        trail.append("authz+snapshot@%s" % commit)

        # 4-5 separate private / shared retrieval (canonical IDs only)
        priv = self.private_index.search("private:%s:%s" % (ident.org_id, ident.subject_id),
                                         task["query"], 5, {"org": ident.org_id})
        shared = self.shared_index.search("shared:%s" % ident.org_id, task["query"], 5, {"org": ident.org_id})
        trail.append("retrieved priv=%d shared=%d" % (len(priv), len(shared)))

        # 6-16 canonical reload + gates + compile (invalid -> no model text)
        views = []
        injected_meta = []
        for cid in shared:
            c = self.registry.get_contract(cid)
            if not c:
                continue
            directive = self.directive_builder(c, task)
            try:
                compiled = compile_directive(directive)
            except ViewRefused as e:
                self.metrics.incr("compiler.refused", tags={"reason": e.reason})
                self.audit.emit("view_refused", ident.subject_id, cid, {"reason": e.reason})
                continue
            views.append(compiled["view"])
            injected_meta.append({"contract_id": cid, "version": compiled["source_contract_version"],
                                  "hash": compiled["parent_contract_hash"]})
            if len(views) >= self.max_injected:
                break
        trail.append("views_injected=%d" % len(views))

        # 17-20 prompt + model (views carry no opaque IDs; IDs kept only in injected_meta)
        prompt = self._build_prompt(snapshot, task, views)
        gen = self.model.generate(logical_request_id, prompt)

        # 21-22 apply + sandbox (client never supplies the patch)
        from ..benchmarks.gaten_v2.harness import apply_unified_diff, PatchError
        target_file = task["target_file"]
        passed = exec_ok = 0
        parser_status = "ok"
        applied = None
        try:
            applied, _ = apply_unified_diff(snapshot["files"][target_file], gen["text"])
        except PatchError as e:
            parser_status = "malformed:%s" % e
        if applied is not None:
            res = self.sandbox.run(snapshot, {target_file: applied}, task["test_entry"], task.get("timeout_s", 20))
            passed, exec_ok = res["passed"], res["exec_ok"]
        trail.append("passed=%d exec=%d" % (passed, exec_ok))

        # 23-24 persist outcome + audit + private episode
        outcome = {"logical_request_id": logical_request_id, "job_repo": repo_id, "commit": commit,
                   "pass1": passed, "exec1": exec_ok, "parser_status": parser_status,
                   "injected_contracts": injected_meta, "model_response_sha256": gen["response_sha256"],
                   "usage": gen["usage"], "trail": trail,
                   "private_leak": False}     # views never contain another user's raw private trace
        self.audit.emit("solve_outcome", ident.subject_id, repo_id, {"pass1": passed, "lrq": logical_request_id})
        self.metrics.incr("solve.pass1" if passed else "solve.fail")
        return outcome

    @staticmethod
    def _build_prompt(snapshot, task, views):
        mem = "\n".join("- %s" % v for v in views) if views else "No internal contract is available."
        return ("Edit the fictional internal repository.\n\nFILE %s:\n```python\n%s```\n\n"
                "Authoritative internal guidance:\n%s\n\nTask: %s Return ONLY a unified diff (```diff fenced), "
                "keep the signature, change <=12 lines.\n"
                % (task["target_file"], snapshot["files"][task["target_file"]], mem, task["instruction"]))
