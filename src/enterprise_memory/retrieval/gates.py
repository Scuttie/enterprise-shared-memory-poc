"""Deterministic permission / scope / validity gates (handoff §7, §8). These run BEFORE semantic
reranking and BEFORE injection. All are pure functions over UserContext + TaskContext + MemoryContract
(or PrivateEpisode), returning (pass, reason)."""
from __future__ import annotations
import fnmatch


# ---- private episode access (§7 private memory read rule) ----
def private_read_ok(user, episode) -> tuple:
    if user.org_id != episode.org_id:
        return (False, "org_mismatch")
    if user.user_id != episode.owner_user_id:
        return (False, "not_owner")
    if episode.repo_id not in user.allowed_repo_ids:
        return (False, "repo_not_allowed")
    return (True, "ok")


# ---- shared contract permission (§7 shared contract read rule) ----
def permission_gate(user, contract) -> tuple:
    sc = contract.scope
    if user.org_id != sc.org_id:
        return (False, "org_mismatch")
    if contract.governance.state != "promoted":
        return (False, "state_%s" % contract.governance.state)
    # team/repo/path permission
    if sc.team_ids and user.team_id not in sc.team_ids:
        return (False, "team_not_allowed")
    if sc.repo_ids and not (set(sc.repo_ids) & set(user.allowed_repo_ids)):
        return (False, "repo_not_allowed")
    return (True, "ok")


# ---- deterministic repo/path/version/scope gate (§8 step 4) ----
def scope_gate(task, contract) -> tuple:
    sc = contract.scope
    if sc.repo_ids and task.repo_id not in sc.repo_ids:
        return (False, "repo_out_of_scope")
    if sc.language and task.language and sc.language != task.language:
        return (False, "language_mismatch")
    if sc.path_globs:
        paths = task.path_globs or []
        if not any(fnmatch.fnmatch(p, g) for p in paths for g in sc.path_globs):
            return (False, "path_out_of_scope")
    # dependency version constraints (simple >=/pin semantics on integer-ish versions)
    for pkg, spec in (sc.dependency_version_constraints or {}).items():
        have = (task.dependency_versions or {}).get(pkg)
        if have is None:
            return (False, "missing_dep_%s" % pkg)
        if not _version_satisfies(have, spec):
            return (False, "dep_%s_%s_fails_%s" % (pkg, have, spec))
    # error-signature scope: if the contract declares signatures, at least one must match
    if sc.error_signatures and not (set(sc.error_signatures) & set(task.error_signatures or [])):
        return (False, "error_signature_mismatch")
    return (True, "ok")


# ---- validity gate: version/temporal/invalidation/supersession (§7 validity, §8) ----
def validity_gate(task, contract, now: str, successor_valid: bool = False) -> tuple:
    v = contract.validity
    if contract.governance.state in ("deprecated", "quarantined", "deleted", "candidate"):
        return (False, "state_%s" % contract.governance.state)
    if v.valid_until and now > v.valid_until:
        return (False, "expired")
    if v.superseded_by_contract_id and successor_valid:
        return (False, "superseded")
    for pkg, maxv in (v.version_constraints or {}).items():
        have = (task.dependency_versions or {}).get(pkg)
        if have is not None and not _version_satisfies(have, maxv):
            return (False, "version_invalid_%s" % pkg)
    for ev in (v.invalidation_events or []):
        if ev in (task.error_signatures or []) or ev in (task.environment_fingerprint or ""):
            return (False, "invalidation_event_%s" % ev)
    return (True, "ok")


def _version_satisfies(have, spec) -> bool:
    """Minimal semantics: '>=N', '<=N', '==N'/'N' (pin), 'range:a-b'. Versions compared as int tuples."""
    def parse(x):
        return tuple(int(p) for p in str(x).replace("v", "").split(".") if p.isdigit()) or (0,)
    h = parse(have)
    s = str(spec).strip()
    if s.startswith(">="):
        return h >= parse(s[2:])
    if s.startswith("<="):
        return h <= parse(s[2:])
    if s.startswith("=="):
        return h == parse(s[2:])
    if s.startswith("<"):
        return h < parse(s[1:])
    if s.startswith(">"):
        return h > parse(s[1:])
    return h == parse(s)
