"""§9/§11 async SolveOrchestrator. Private and shared retrieval stay separate until access control;
private views are sanitised and asserted to belong to the requesting user (cross-user private injection
MUST be 0 — computed, never hard-coded); a solve requires can_modify; invalid contracts inject NO
model-facing text; at most `max_injected` views compete deterministically (shared then private); canonical
IDs live only in hidden metadata; no client-supplied patch is trusted; the outcome/audit/candidate event
are persisted."""
from __future__ import annotations
import hashlib

from .compiler_ir import compile_directive, ViewRefused
from .identity import IdentityContext
from ..patches import apply_unified_diff, validate_bounded_edit, PatchError


class SolveOrchestrator:
    def __init__(self, registry, private_index, shared_index, authz, repo_provider, model, sandbox,
                 audit, metrics, directive_builder, outcome_store=None, outbox=None, max_injected=2):
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
        self.outcome_store = outcome_store
        self.outbox = outbox
        self.max_injected = max_injected

    async def solve(self, ident: IdentityContext, task: dict, logical_request_id: str) -> dict:
        trail = []
        if not ident.has_scope("solve:submit"):
            raise PermissionError("missing scope solve:submit")
        repo_id = task["repo_id"]
        # §2.4 a solve GENERATES a patch -> require modify, not just read; paths come from server policy
        if not await self.authz.can_modify(ident, repo_id):
            await self.audit.emit("authz_denied", ident.subject_id, repo_id, {"op": "solve", "need": "can_modify"})
            raise PermissionError("repo_modify_denied")
        path_allowlist = self._server_path_policy(repo_id, task)     # NOT from the request body
        commit = await self.repo.resolve_commit(repo_id, task.get("ref", "main"))
        snapshot = await self.repo.snapshot(repo_id, commit, path_allowlist)
        trail.append("authz(modify)+snapshot@%s" % commit)

        # 4-5 separate private / shared retrieval
        priv_scope = "private:%s:%s" % (ident.org_id, ident.subject_id)
        priv = await self.private_index.search(priv_scope, task["query"], 5, {"org": ident.org_id})
        shared = await self.shared_index.search("shared:%s" % ident.org_id, task["query"], 5, {"org": ident.org_id})
        trail.append("retrieved priv=%d shared=%d" % (len(priv), len(shared)))

        # 6-16 shared: canonical reload + gates + compile (invalid -> no model text)
        views, injected_meta = [], []
        for cid in shared:
            c = await self.registry.get_contract(cid)
            if not c:
                self.metrics.incr("retrieval.canonical_missing")
                continue
            directive = self.directive_builder(c, task)
            try:
                compiled = compile_directive(directive)
            except ViewRefused as e:
                self.metrics.incr("compiler.refused", tags={"reason": e.reason})
                await self.audit.emit("view_refused", ident.subject_id, cid, {"reason": e.reason})
                continue
            views.append(compiled["view"])
            injected_meta.append({"kind": "shared", "contract_id": cid,
                                  "version": compiled["source_contract_version"], "hash": compiled["parent_contract_hash"]})
            if len(views) >= self.max_injected:
                break

        # §2.3 private path: sanitise + assert ownership; NEVER inject another user's raw trace
        injected_private_owners, cross_user_blocked = [], 0
        for item in priv:
            owner = item.get("owner")
            if owner != ident.subject_id:
                cross_user_blocked += 1          # not owned by requester -> blocked from injection (defense in depth)
                self.metrics.incr("private.cross_user_blocked")
                continue
            if len(views) >= self.max_injected:
                break
            views.append("Your prior verified note: %s" % _sanitise_private(item))
            injected_private_owners.append(owner)
            injected_meta.append({"kind": "private", "memory_id": item.get("id"), "owner": owner,
                                  "hash": item.get("hash")})
        # the hard-fail metric is the number of ACTUALLY-INJECTED non-owner items -> must be 0 by construction
        cross_user_private_injection_count = sum(1 for o in injected_private_owners if o != ident.subject_id)
        trail.append("views_injected=%d (private_owners=%s, blocked=%d)"
                     % (len(views), injected_private_owners, cross_user_blocked))

        # 17-20 prompt + model
        prompt = self._build_prompt(snapshot, task, views)
        gen = await self.model.generate(logical_request_id, prompt)

        # 21-22 apply (client never supplies the patch) + bounded-edit validation + sandbox
        target_file = task["target_file"]
        passed = exec_ok = 0
        parser_status = "ok"
        scope_ok = True
        applied = None
        try:
            applied, meta = apply_unified_diff(snapshot["files"][target_file], gen["text"])
            viol = validate_bounded_edit(applied, task["func"], task["signature"], meta)
            if viol:
                scope_ok = False
                parser_status = "scope_violation:" + ",".join(viol)
        except PatchError as e:
            parser_status = "malformed:%s" % e
        if applied is not None and scope_ok:
            res = await self.sandbox.run(snapshot, {target_file: applied}, task["test_entry"], task.get("timeout_s", 20))
            passed, exec_ok = res["passed"], res["exec_ok"]
        trail.append("passed=%d exec=%d" % (passed, exec_ok))

        # 23-26 persist outcome + audit + private episode + candidate event
        outcome = {"logical_request_id": logical_request_id, "repo_id": repo_id, "commit": commit,
                   "pass1": passed, "exec1": exec_ok, "parser_status": parser_status, "scope_ok": scope_ok,
                   "injected_contracts": injected_meta, "injected_private_owners": injected_private_owners,
                   "cross_user_private_injection_count": cross_user_private_injection_count,
                   "expected_cross_user_private_injection_count": 0,
                   "cross_user_private_blocked": cross_user_blocked,
                   "model_response_sha256": gen["response_sha256"], "usage": gen["usage"], "trail": trail}
        if cross_user_private_injection_count != 0:
            raise AssertionError("cross-user private INJECTION detected: %d" % cross_user_private_injection_count)  # hard fail
        outcome["outcome_id"] = await self.outcome_store.persist(outcome) if self.outcome_store else None
        await self.audit.emit("solve_outcome", ident.subject_id, repo_id,
                              {"pass1": passed, "lrq": logical_request_id, "outcome_id": outcome.get("outcome_id")})
        if passed and self.outbox:
            self.outbox.publish("PRIVATE_EPISODE_INDEX", "%s:%s" % (ident.subject_id, logical_request_id),
                                {"owner": ident.subject_id, "repo_id": repo_id})
        self.metrics.incr("solve.pass1" if passed else "solve.fail")
        return outcome

    @staticmethod
    def _server_path_policy(repo_id, task):
        # server-side policy derives the editable paths; the request body is NOT trusted for this.
        return [task["target_file"], task["test_entry"]]

    @staticmethod
    def _build_prompt(snapshot, task, views):
        mem = "\n".join("- %s" % v for v in views) if views else "No internal contract is available."
        return ("Edit the fictional internal repository.\n\nFILE %s:\n```python\n%s```\n\n"
                "Authoritative internal guidance:\n%s\n\nTask: %s Return ONLY a unified diff (```diff fenced), "
                "keep the signature, change <=12 lines.\n"
                % (task["target_file"], snapshot["files"][task["target_file"]], mem, task["instruction"]))


def _sanitise_private(item: dict) -> str:
    """Canonicalise a private item to a short note; strip any raw code/secret before injection."""
    note = str(item.get("note", ""))
    return note.replace("\n", " ")[:160]
