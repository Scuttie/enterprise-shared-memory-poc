"""§9/§11 async SolveOrchestrator. Server-owned TaskExecutionPolicy (never client fields) determines the
editable file, signature, tests, and budgets. Private and shared retrieval stay separate until access
control; private views pass the PrivateExecutionViewCompiler (ownership + secret/PII scan + scope);
cross-user private INJECTION must be 0 (computed, hard-fail if >0); a solve requires can_modify; invalid
contracts inject NO model-facing text; canonical IDs live only in hidden metadata; no client patch is
trusted; the outcome/audit/private-episode event are persisted."""
from __future__ import annotations

from .compiler_ir import compile_directive, ViewRefused
from .identity import IdentityContext
from .private_view import compile_private_view, PrivateViewRefused
from ..patches import apply_unified_diff, validate_bounded_edit, PatchError


class SolveOrchestrator:
    def __init__(self, registry, private_index, shared_index, authz, repo_provider, model, sandbox,
                 audit, metrics, directive_builder, policy_repo, outcome_store=None, outbox=None, max_injected=2):
        self.registry = registry
        self.private_index = private_index
        self.shared_index = shared_index
        self.authz = authz
        self.repo = repo_provider
        self.model = model
        self.sandbox = sandbox
        self.audit = audit
        self.metrics = metrics
        self.directive_builder = directive_builder
        self.policy_repo = policy_repo
        self.outcome_store = outcome_store
        self.outbox = outbox
        self.max_injected = max_injected

    async def solve(self, ident: IdentityContext, req, logical_request_id: str) -> dict:
        """`req` is a ClientTaskRequest (repo_id/task_id/instruction/desired_ref) — the ONLY client input."""
        trail = []
        if not ident.has_scope("solve:submit"):
            raise PermissionError("missing scope solve:submit")
        repo_id = req.repo_id
        can_mod = await self.authz.can_modify(ident, repo_id)     # §2.4 solve generates a patch -> modify
        if not can_mod:
            await self.audit.emit("authz_denied", ident.subject_id, repo_id, {"op": "solve"})
            raise PermissionError("repo_modify_denied")
        policy = await self.policy_repo.resolve(req, authorized_repo=can_mod)   # §2.1 server-owned
        commit = await self.repo.resolve_commit(repo_id, req.desired_ref)
        snapshot = await self.repo.snapshot(repo_id, commit, policy.editable_paths)
        trail.append("policy+snapshot@%s ignored_client_fields=%s" % (commit, req.ignored_client_fields))

        priv = await self.private_index.search("private:%s:%s" % (ident.org_id, ident.subject_id), req.instruction, 5, {"org": ident.org_id})
        shared = await self.shared_index.search("shared:%s" % ident.org_id, req.instruction, 5, {"org": ident.org_id})
        trail.append("retrieved priv=%d shared=%d" % (len(priv), len(shared)))

        views, injected_meta = [], []
        for cid in shared:
            c = await self.registry.get_contract(cid)
            if not c:
                self.metrics.incr("retrieval.canonical_missing")
                continue
            try:
                compiled = compile_directive(self.directive_builder(c, policy))
            except ViewRefused as e:
                self.metrics.incr("compiler.refused", tags={"reason": e.reason})
                await self.audit.emit("view_refused", ident.subject_id, cid, {"reason": e.reason})
                continue
            views.append(compiled["view"])
            injected_meta.append({"kind": "shared", "contract_id": cid, "version": compiled["source_contract_version"],
                                  "hash": compiled["parent_contract_hash"]})
            if len(views) >= self.max_injected:
                break

        injected_private_owners, cross_user_blocked = [], 0
        for item in priv:
            if len(views) >= self.max_injected:
                break
            try:
                pview, pmeta = compile_private_view(item, ident.subject_id, repo_id)
            except PrivateViewRefused as e:
                cross_user_blocked += 1 if e.reason == "NOT_OWNER" else 0
                self.metrics.incr("private.refused", tags={"reason": e.reason})
                continue
            views.append(pview)
            injected_private_owners.append(pmeta["owner"])
            injected_meta.append(pmeta)
        cross_user_private_injection_count = sum(1 for o in injected_private_owners if o != ident.subject_id)
        trail.append("views=%d private_owners=%s blocked=%d" % (len(views), injected_private_owners, cross_user_blocked))

        prompt = self._build_prompt(snapshot, policy, req, views)
        gen = await self.model.generate(logical_request_id, prompt)

        passed = exec_ok = 0
        parser_status = "ok"
        scope_ok = True
        applied = None
        try:
            applied, meta = apply_unified_diff(snapshot["files"][policy.target_file], gen["text"])
            viol = validate_bounded_edit(applied, policy.target_symbol, policy.exact_signature, meta)
            if viol:
                scope_ok = False
                parser_status = "scope_violation:" + ",".join(viol)
        except PatchError as e:
            parser_status = "malformed:%s" % e
        if applied is not None and scope_ok:
            res = await self.sandbox.run(snapshot, {policy.target_file: applied}, policy.test_entry, policy.timeout_s)
            passed, exec_ok = res["passed"], res["exec_ok"]
        trail.append("passed=%d exec=%d" % (passed, exec_ok))

        outcome = {"logical_request_id": logical_request_id, "repo_id": repo_id, "commit": commit,
                   "task_id": req.task_id, "pass1": passed, "exec1": exec_ok, "parser_status": parser_status,
                   "scope_ok": scope_ok, "injected_contracts": injected_meta,
                   "injected_private_owners": injected_private_owners,
                   "cross_user_private_injection_count": cross_user_private_injection_count,
                   "expected_cross_user_private_injection_count": 0, "cross_user_private_blocked": cross_user_blocked,
                   "ignored_client_fields": req.ignored_client_fields,
                   "model_response_sha256": gen["response_sha256"], "usage": gen["usage"], "trail": trail}
        if cross_user_private_injection_count != 0:
            raise AssertionError("cross-user private INJECTION detected: %d" % cross_user_private_injection_count)
        outcome["outcome_id"] = await self.outcome_store.persist(outcome) if self.outcome_store else None
        await self.audit.emit("solve_outcome", ident.subject_id, repo_id,
                              {"pass1": passed, "lrq": logical_request_id, "outcome_id": outcome.get("outcome_id")})
        if passed and self.outbox:
            self.outbox.publish("PRIVATE_EPISODE_INDEX", "%s:%s" % (ident.subject_id, logical_request_id),
                                {"owner": ident.subject_id, "repo_id": repo_id})
        self.metrics.incr("solve.pass1" if passed else "solve.fail")
        return outcome

    @staticmethod
    def _build_prompt(snapshot, policy, req, views):
        mem = "\n".join("- %s" % v for v in views) if views else "No internal contract is available."
        return ("Edit the fictional internal repository.\n\nFILE %s:\n```python\n%s```\n\n"
                "Authoritative internal guidance:\n%s\n\nTask: %s Return ONLY a unified diff (```diff fenced), "
                "keep the signature %s, change <=%d lines.\n"
                % (policy.target_file, snapshot["files"][policy.target_file], mem, req.instruction,
                   policy.exact_signature, policy.max_changed_lines))
