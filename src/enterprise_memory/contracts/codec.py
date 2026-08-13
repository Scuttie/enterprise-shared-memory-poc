"""Versioned canonical codec (P3.1 §1). Production serving decodes canonical JSON through this typed codec —
never ad-hoc `.get()` chains. It enforces the released schema `enterprise_memory/1.0.0`, rejects absent/
unknown versions, malformed nested blocks, mismatched content hashes, and (for shared contracts) missing
scope/action/validity/governance. Path scope is read from `contract.scope.path_globs`, never a synthetic
top-level field. Old simplified test fixtures are handled ONLY by the explicit legacy adapters below."""
from __future__ import annotations
import json
from dataclasses import asdict
from . import schema as S

SUPPORTED_SCHEMAS = (S.SCHEMA_VERSION,)   # "enterprise_memory/1.0.0"


class CodecError(Exception):
    pass


def _as_dict(canonical_json):
    if isinstance(canonical_json, dict):
        return canonical_json
    if isinstance(canonical_json, str):
        try:
            return json.loads(canonical_json)
        except Exception:
            raise CodecError("canonical_json is not valid JSON")
    raise CodecError("canonical_json must be an object")


def _check_version(schema_version):
    if not schema_version:
        raise CodecError("absent schema_version")
    if schema_version not in SUPPORTED_SCHEMAS:
        raise CodecError("unknown schema_version %r" % (schema_version,))


def _req(d, key, where):
    if key not in d or d[key] is None:
        raise CodecError("missing '%s' in %s" % (key, where))
    return d[key]


def _nested(cls, d, key):
    block = _req(d, key, "contract")
    if not isinstance(block, dict):
        raise CodecError("malformed block '%s' (not an object)" % key)
    try:
        return cls(**block)
    except TypeError as e:
        raise CodecError("malformed block '%s': %s" % (key, e))


def decode_memory_contract(canonical_json, schema_version) -> S.MemoryContract:
    _check_version(schema_version)
    d = _as_dict(canonical_json)
    if d.get("schema_version") not in (None, schema_version):
        raise CodecError("schema_version mismatch: doc=%r arg=%r" % (d.get("schema_version"), schema_version))
    scope = _nested(S.ContractScope, d, "scope")
    action = _nested(S.ContractAction, d, "action")
    validity = _nested(S.ContractValidity, d, "validity")
    verification = _nested(S.ContractVerification, d, "verification")
    provenance = _nested(S.ContractProvenance, d, "provenance")
    try:
        evidence = S.ContractEvidence(**d.get("evidence", {}))
        governance = S.ContractGovernance(**d.get("governance", {}))
    except TypeError as e:
        raise CodecError("malformed evidence/governance: %s" % e)
    contract = S.MemoryContract(
        contract_id=_req(d, "contract_id", "contract"), schema_version=schema_version,
        title=_req(d, "title", "contract"), canonical_summary=d.get("canonical_summary", ""),
        scope=scope, action=action, validity=validity, verification=verification,
        provenance=provenance, evidence=evidence, governance=governance,
        parent_hashes=list(d.get("parent_hashes", [])), content_hash=d.get("content_hash", ""))
    if governance.visibility == "shared":
        if not (scope.path_globs or scope.repo_ids or scope.org_id):
            raise CodecError("shared contract missing scope")
        if not action.ordered_steps:
            raise CodecError("shared contract missing action steps")
        if governance.state not in S.CONTRACT_STATES:
            raise CodecError("shared contract bad governance state %r" % governance.state)
        if validity.valid_from is None:
            raise CodecError("shared contract missing validity.valid_from")
    return contract


def encode_memory_contract(contract: S.MemoryContract) -> dict:
    d = asdict(contract)
    d["schema_version"] = contract.schema_version or S.SCHEMA_VERSION
    return d


def decode_private_episode(canonical_json, schema_version) -> S.PrivateEpisode:
    _check_version(schema_version)
    d = _as_dict(canonical_json)
    fields = [f for f in S.PrivateEpisode.__dataclass_fields__ if f not in ("content_hash", "visibility")]
    for f in ("episode_id", "owner_user_id", "org_id"):
        _req(d, f, "private_episode")
    kw = {f: d.get(f) for f in fields}
    try:
        ep = S.PrivateEpisode(visibility=d.get("visibility", "private"),
                              content_hash=d.get("content_hash", ""), **kw)
    except TypeError as e:
        raise CodecError("malformed private_episode: %s" % e)
    if ep.visibility != "private":
        raise CodecError("private_episode must be private")
    return ep


def validate_content_hash(obj, expected=None) -> bool:
    """Recompute the typed content hash and compare. `expected` overrides obj.content_hash when given."""
    recomputed = S.content_hash(obj)
    target = expected if expected is not None else getattr(obj, "content_hash", None)
    if target is None:
        raise CodecError("no content hash to validate against")
    if recomputed != target:
        raise CodecError("content hash mismatch: computed=%s expected=%s" % (recomputed, target))
    return True


def build_retrieval_projection(contract: S.MemoryContract) -> dict:
    """Target-free retrieval projection — exactly MemoryContract.retrieval_view(): no provenance, no private
    traces, no reviewer identity, no target values."""
    return contract.retrieval_view()


def extract_execution_scope(contract: S.MemoryContract) -> dict:
    s = contract.scope
    return {"org_id": s.org_id, "repo_ids": list(s.repo_ids), "path_globs": list(s.path_globs),
            "language": s.language, "framework": s.framework,
            "branch_or_release_constraints": list(s.branch_or_release_constraints),
            "applies_when": list(s.applies_when), "does_not_apply_when": list(s.does_not_apply_when)}


# ---------------------------------------------------------------- legacy/test compatibility (explicit)
def is_typed_contract(canonical) -> bool:
    return isinstance(canonical, dict) and canonical.get("schema_version") == S.SCHEMA_VERSION


def retrieval_text(canonical) -> str:
    return retrieval_text_and_path_scope(canonical)[0]


def path_scope(canonical):
    return retrieval_text_and_path_scope(canonical)[1]


def retrieval_text_and_path_scope(canonical):
    """Serving helper: for a typed contract, embed the SAFE retrieval projection and read path scope from
    scope.path_globs. For a legacy/simplified fixture, fall back to the compact JSON + synthetic path_scope.
    This is the only sanctioned legacy path and it never leaks provenance for typed contracts."""
    if is_typed_contract(canonical):
        c = decode_memory_contract(canonical, canonical["schema_version"])
        text = json.dumps(build_retrieval_projection(c), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return text, list(c.scope.path_globs)
    # legacy fixture
    if isinstance(canonical, str):
        return canonical, None
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    ps = canonical.get("path_scope") if isinstance(canonical, dict) else None
    return text, (list(ps) if isinstance(ps, list) else None)
