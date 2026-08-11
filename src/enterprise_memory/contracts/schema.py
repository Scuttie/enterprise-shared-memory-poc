"""Enterprise Shared Memory — typed, versioned core schemas (handoff §5).

The authoritative object is the MemoryContract in the structured registry; embedding records are NOT
the source of truth. All objects carry a deterministic content_hash. Mem0 is a replaceable retrieval
substrate behind the MemoryBackend adapter (see backends/base.py)."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field, asdict

SCHEMA_VERSION = "enterprise_memory/1.0.0"
CONTRACT_STATES = ("candidate", "promoted", "deprecated", "quarantined", "deleted")
VISIBILITY = ("private", "shared")
VARIANT_TYPES = ("APPLICABLE", "OUT_OF_SCOPE", "EXPIRED", "IRRELEVANT")


def _canon(o) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True, ensure_ascii=True, default=str).encode()).hexdigest()


def content_hash(o) -> str:
    d = asdict(o) if hasattr(o, "__dataclass_fields__") else dict(o)
    d = {k: v for k, v in d.items() if k not in ("content_hash",)}
    return "sha256:" + _canon(d)[:32]


# ---------------------------------------------------------------- 5.1 UserContext
@dataclass
class UserContext:
    org_id: str
    team_id: str
    user_id: str
    agent_id: str
    allowed_repo_ids: list
    allowed_path_globs: list
    role: str
    request_id: str


# ---------------------------------------------------------------- 5.2 TaskContext
@dataclass
class TaskContext:
    task_id: str
    org_id: str
    user_id: str
    repo_id: str
    repository_commit: str
    branch: str
    language: str
    framework: str
    dependency_versions: dict
    path_globs: list
    task_text: str
    error_signatures: list
    environment_fingerprint: str
    created_at: str
    content_hash: str = ""

    def stamp(self):
        self.content_hash = content_hash(self)
        return self


# ---------------------------------------------------------------- 5.3 PrivateEpisode
@dataclass
class PrivateEpisode:
    episode_id: str
    owner_user_id: str
    org_id: str
    repo_id: str
    task_id: str
    source_commit: str
    request: dict
    retrieved_memory_ids: list
    injected_memory_ids: list
    generated_patch: str
    tool_events: list
    test_commands: list
    test_results: dict
    execution_outcome: str
    model_request_hashes: list
    dependency_lock_hash: str
    created_at: str
    visibility: str = "private"       # ALWAYS private; never returned to another user
    content_hash: str = ""

    def stamp(self):
        assert self.visibility == "private", "PrivateEpisode must stay private"
        self.content_hash = content_hash(self)
        return self


# ---------------------------------------------------------------- 5.4 MemoryContract (nested blocks)
@dataclass
class ContractScope:
    org_id: str
    team_ids: list
    repo_ids: list
    path_globs: list
    language: str
    framework: str
    dependency_version_constraints: dict     # {package: spec} e.g. {"api":">=2"}
    branch_or_release_constraints: list
    error_signatures: list
    applies_when: list
    does_not_apply_when: list


@dataclass
class ContractAction:
    ordered_steps: list
    code_pattern: str
    forbidden_patterns: list
    required_inputs: list
    operation_order: list


@dataclass
class ContractValidity:
    valid_from: str
    valid_until: str                          # "" = open-ended
    environment_constraints: dict
    version_constraints: dict                 # {package: max_version or pin}
    invalidation_events: list
    supersedes_contract_ids: list
    superseded_by_contract_id: str


@dataclass
class ContractVerification:
    test_commands: list
    expected_observations: list
    regression_checks: list
    failure_observations: list


@dataclass
class ContractProvenance:
    source_episode_ids: list
    contributor_user_ids_pseudonymized: list
    source_commit_shas: list
    source_test_results: list
    extractor_version: str


@dataclass
class ContractEvidence:
    source_success_count: int = 0
    replay_success_count: int = 0
    replay_failure_count: int = 0
    successful_reuse_count: int = 0
    failed_reuse_count: int = 0
    distinct_users_helped: int = 0
    causal_shadow_observations: list = field(default_factory=list)   # only shadow-ablation updates this


@dataclass
class ContractGovernance:
    visibility: str = "shared"
    state: str = "candidate"                  # one of CONTRACT_STATES
    promotion_policy_version: str = ""
    security_scan_status: str = "unscanned"
    reviewer: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class MemoryContract:
    contract_id: str
    schema_version: str
    title: str
    canonical_summary: str
    scope: ContractScope
    action: ContractAction
    validity: ContractValidity
    verification: ContractVerification
    provenance: ContractProvenance
    evidence: ContractEvidence
    governance: ContractGovernance
    parent_hashes: list = field(default_factory=list)
    content_hash: str = ""

    def stamp(self):
        self.content_hash = content_hash(self)
        return self

    def retrieval_view(self) -> dict:
        """Deterministic, target-FREE rendering indexed in Mem0. Never the source of truth. Contains
        no raw private trace, no target value, no answer."""
        return {
            "contract_id": self.contract_id,
            "title": self.title,
            "summary": self.canonical_summary,
            "language": self.scope.language,
            "framework": self.scope.framework,
            "repo_ids": self.scope.repo_ids,
            "path_globs": self.scope.path_globs,
            "applies_when": self.scope.applies_when,
            "does_not_apply_when": self.scope.does_not_apply_when,
            "error_signatures": self.scope.error_signatures,
            "steps": self.action.ordered_steps,
            "state": self.governance.state,
        }

    def validate(self) -> list:
        errs = []
        if self.governance.state not in CONTRACT_STATES:
            errs.append("bad state %s" % self.governance.state)
        if not self.scope.applies_when:
            errs.append("empty applies_when")
        if not self.scope.does_not_apply_when:
            errs.append("empty does_not_apply_when")
        if not self.verification.test_commands:
            errs.append("no verification test_commands")
        if not (self.scope.repo_ids or self.scope.org_id):
            errs.append("no repo/org scope")
        if not self.provenance.source_episode_ids:
            errs.append("no provenance")
        return errs


# ---------------------------------------------------------------- 5.5 RetrievalDecision
@dataclass
class RetrievalDecision:
    query_id: str
    user_context: dict
    task_context_hash: str
    candidate_memory_ids: list
    permission_pass_ids: list
    scope_pass_ids: list
    validity_pass_ids: list
    reranked_ids: list
    injected_ids: list
    rejection_reasons: dict           # memory_id -> reason
    latency_ms_by_stage: dict
    content_hash: str = ""

    def stamp(self):
        self.content_hash = content_hash(self)
        return self


# ---------------------------------------------------------------- 5.6 OutcomeObservation
@dataclass
class OutcomeObservation:
    task_id: str
    condition: str                    # M0..M6
    memory_ids: list
    test_success: bool
    exec_success: bool
    pass_at_1: bool
    regression_success: bool
    input_tokens: int
    output_tokens: int
    memory_tokens: int
    model_calls: int
    test_executions: int
    wall_time: float
    retrieval_latency: float
    malformed_output: bool
    content_hash: str = ""

    def stamp(self):
        self.content_hash = content_hash(self)
        return self
