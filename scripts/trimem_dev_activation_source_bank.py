"""Build a result-blind DEV diagnostic source bank from frozen public evidence.

The builder has deliberately no downloader and no API client.  In the frozen
oracle mode it consumes only a separately captured, content-addressed GitHub
evidence cache.  Legacy pinned-dataset helpers remain for audit compatibility,
but cannot satisfy an oracle plan.  UNKNOWN chronology/version/fix evidence is
rejected per candidate.  Target patches, tests, outcomes, and target-derived
memory are never projected into the builder.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = Path("configs/trimem_v1/dev_activation_source_bank_plan.json")
CHRONOLOGY_PATH = Path(
    "artifacts/trimem_v1/dev_activation_diagnostic/source_chronology_cache.json"
)
OUTPUT_MANIFEST = Path(
    "configs/trimem_v1/dev_activation_source_bank_manifest.json"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
BACKTICK_IDENTIFIER = re.compile(r"`([A-Za-z_][A-Za-z0-9_.:-]{1,127})`")
DECLARATION = re.compile(
    r"\b(?:class|def|function|fn|struct|interface|trait|enum)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)"
)
API_IDENTIFIER = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b"
)
ERROR_IDENTIFIER = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning)|"
    r"[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+)\b"
)
DJANGO_TRAC_OLD_VALUES = re.compile(
    rb"var\s+old_values\s*=\s*(\{.*?\});", re.DOTALL
)
FORBIDDEN_TARGET_KEYS = frozenset(
    {
        "gold_patch",
        "target_gold",
        "target_gold_patch",
        "target_patch",
        "target_test",
        "target_tests",
        "test_patch",
        "fail_to_pass",
        "pass_to_pass",
        "target_outcome",
        "target_resolved",
        "grader_outcome",
        "model_output",
    }
)
REQUIRED_DATASETS = (
    "swebench_verified",
    "multi_swe_bench_mini",
    "multi_swe_bench_flash",
)
DATASET_IDS = {
    "swebench_verified": "SWE-bench/SWE-bench_Verified",
    "multi_swe_bench_mini": "ByteDance-Seed/Multi-SWE-bench_mini",
    "multi_swe_bench_flash": "ByteDance-Seed/Multi-SWE-bench-flash",
}
TOP_K = 1
MAX_RANKED_SOURCES_PER_TARGET = 64
PAYLOAD_DIRECTORY = "dev_activation_source_bank_payloads"


class SourceBankError(ValueError):
    """A fail-closed source-bank contract violation."""


class CoverageError(SourceBankError):
    """No safe historical candidate exists for one or more frozen targets."""

    def __init__(self, missing_targets: Sequence[str], rejection_counts: Mapping[str, int]):
        self.missing_targets = tuple(missing_targets)
        self.rejection_counts = dict(sorted(rejection_counts.items()))
        super().__init__("SAFE_SOURCE_COVERAGE_INCOMPLETE: " + ",".join(self.missing_targets))


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceBankError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise SourceBankError(f"non-finite JSON number: {value}")


def strict_json_load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_pairs,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceBankError(f"cannot read strict JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SourceBankError(f"JSON root must be an object: {path}")
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise SourceBankError(f"{label} is not a canonical relative POSIX path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or value != relative.as_posix()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise SourceBankError(f"{label} is not a canonical relative POSIX path")
    return relative


def _confined_path(
    root: Path,
    relative_value: Any,
    *,
    label: str,
    must_exist: bool,
) -> Path:
    """Resolve a manifest-relative path while rejecting every symlink component."""

    relative = _safe_relative_path(relative_value, label)
    root_absolute = root.absolute()
    if root_absolute.is_symlink():
        raise SourceBankError(f"{label} root is a symlink")
    current = root_absolute
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise SourceBankError(f"{label} traverses a symlink: {relative.as_posix()}")
    try:
        resolved_root = root_absolute.resolve(strict=True)
    except OSError as exc:
        raise SourceBankError(f"{label} root is unavailable") from exc
    try:
        resolved = current.resolve(strict=must_exist)
    except OSError as exc:
        raise SourceBankError(f"{label} is missing: {relative.as_posix()}") from exc
    if resolved == resolved_root or resolved_root not in resolved.parents:
        raise SourceBankError(f"{label} escapes its root: {relative.as_posix()}")
    if must_exist and not resolved.is_file():
        raise SourceBankError(f"{label} is not a regular file: {relative.as_posix()}")
    return resolved


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise SourceBankError(f"{label} must be a lowercase sha256")
    return value


def _require_hex40(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX40.fullmatch(value):
        raise SourceBankError(f"{label} must be a lowercase 40-hex commit")
    return value


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not ISO_UTC.fullmatch(value):
        raise SourceBankError(f"{label} is UNKNOWN or not canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise SourceBankError(f"{label} is not a real UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise SourceBankError(f"{label} is not UTC")
    return parsed


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key).casefold()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _assert_no_forbidden_target_keys(value: Any, label: str) -> None:
    observed = sorted(set(_walk_keys(value)) & FORBIDDEN_TARGET_KEYS)
    if observed:
        raise SourceBankError(f"{label} contains target-sensitive keys: {observed}")


def validate_plan_documents(
    plan: Mapping[str, Any],
    development: Mapping[str, Any],
    grader_lock: Mapping[str, Any],
    *,
    development_raw_sha256: str,
    grader_lock_raw_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if plan.get("schema") != "trimem/dev-activation-source-bank-plan/1.0":
        raise SourceBankError("source-bank plan schema drift")
    if plan.get("status") != "FROZEN_PRE_EXEC_SOURCE_SELECTION":
        raise SourceBankError("source-bank plan is not frozen pre-result")
    if (
        plan.get("execution_authorized") is not False
        or plan.get("model_or_grader_calls_allowed") is not False
        or plan.get("public_github_capture_allowed") is not True
    ):
        raise SourceBankError("source-bank plan authorizes an execution or external call")
    if plan.get("read_only_same_snapshot_for_C1_and_C2") is not True:
        raise SourceBankError("C1/C2 source-bank snapshot is not locked equal/read-only")

    frozen = plan.get("frozen_inputs")
    if not isinstance(frozen, Mapping):
        raise SourceBankError("source-bank frozen inputs are missing")
    expected_bindings = {
        "development_manifest": (
            "configs/trimem_v1/development_manifest.json",
            development_raw_sha256,
        ),
        "grader_lock": (
            "configs/trimem_v1/grader_lock.json",
            grader_lock_raw_sha256,
        ),
    }
    for name, (path, digest) in expected_bindings.items():
        binding = frozen.get(name)
        if not isinstance(binding, Mapping):
            raise SourceBankError(f"missing frozen input binding: {name}")
        if binding.get("path") != path or binding.get("raw_sha256") != digest:
            raise SourceBankError(f"frozen input binding drift: {name}")

    if development.get("schema") != "trimem/development-manifest/1.0":
        raise SourceBankError("development manifest schema drift")
    targets = development.get("targets")
    if not isinstance(targets, list) or len(targets) != 12:
        raise SourceBankError("source bank requires the exact 12-target DEV snapshot")
    if canonical_sha256(targets) != development.get("target_set_sha256"):
        raise SourceBankError("development target-set hash mismatch")
    dev_binding = frozen["development_manifest"]
    if dev_binding.get("target_set_sha256") != development.get("target_set_sha256"):
        raise SourceBankError("plan/development target-set binding drift")
    if [row.get("order_index") for row in targets if isinstance(row, Mapping)] != list(range(12)):
        raise SourceBankError("development target order is malformed")
    target_ids = [row.get("target_id") for row in targets if isinstance(row, Mapping)]
    instance_ids = [row.get("instance_id") for row in targets if isinstance(row, Mapping)]
    if len(target_ids) != 12 or len(set(target_ids)) != 12 or len(set(instance_ids)) != 12:
        raise SourceBankError("development target identities are missing or duplicated")

    source_rule = plan.get("source_universe")
    if not isinstance(source_rule, Mapping) or any(
        source_rule.get(name) != expected
        for name, expected in {
            "mode": "FROZEN_PUBLIC_GITHUB_ORACLE_SOURCE_PRS",
            "source_instance_must_differ_from_every_dev_target": True,
            "same_repository_required": True,
            "exact_source_row_sha256_required": True,
            "source_owned_public_issue_and_merged_diff_allowed": True,
            "target_gold_patch_test_outcome_or_target_derived_memory_allowed": False,
        }.items()
    ):
        raise SourceBankError("source-universe safety rule drift")
    oracle_sources = source_rule.get("oracle_source_prs")
    if not isinstance(oracle_sources, list) or len(oracle_sources) != 12:
        raise SourceBankError("oracle source PR mapping must contain exactly 12 rows")
    if [row.get("target_id") for row in oracle_sources if isinstance(row, Mapping)] != target_ids:
        raise SourceBankError("oracle source PR target order/identity drift")
    source_pr_ids: set[tuple[str, int]] = set()
    for source, target in zip(oracle_sources, targets):
        if not isinstance(source, dict) or set(source) != {
            "target_id",
            "repository",
            "pull_number",
        }:
            raise SourceBankError("oracle source PR row field drift")
        if source["repository"] != target["repository"]:
            raise SourceBankError(f"oracle source crosses repository: {source['target_id']}")
        pull_number = source["pull_number"]
        if type(pull_number) is not int or pull_number <= 0:
            raise SourceBankError(f"oracle source PR number malformed: {source['target_id']}")
        # Benchmark instance suffixes identify target solution PRs, not target
        # problem/issue objects. This comparison is solely the target-row
        # disjointness guard for the historical source PR.
        try:
            target_solution_pr_number = int(
                str(target["instance_id"]).rsplit("-", 1)[1]
            )
        except (IndexError, ValueError) as exc:
            raise SourceBankError(
                f"target solution-PR identity malformed: {source['target_id']}"
            ) from exc
        if pull_number == target_solution_pr_number:
            raise SourceBankError(
                f"oracle source PR equals target solution PR: {source['target_id']}"
            )
        source_identity = (source["repository"], pull_number)
        if source_identity in source_pr_ids:
            raise SourceBankError(f"duplicate oracle source PR: {source_identity}")
        source_pr_ids.add(source_identity)
    problem_objects = source_rule.get("target_problem_objects")
    if not isinstance(problem_objects, list) or len(problem_objects) != 12:
        raise SourceBankError("target problem-object mapping must contain exactly 12 rows")
    if [row.get("target_id") for row in problem_objects if isinstance(row, Mapping)] != target_ids:
        raise SourceBankError("target problem-object order/identity drift")
    problem_identities: set[tuple[str, str, int]] = set()
    for problem, target in zip(problem_objects, targets):
        if not isinstance(problem, dict) or set(problem) != {
            "target_id",
            "task_projection",
            "tracker",
            "issue_number",
            "url",
        }:
            raise SourceBankError("target problem-object row field drift")
        expected_projection = (
            "SWE_BENCH_PROBLEM_STATEMENT"
            if target["benchmark_id"] == "swebench_verified"
            else "MULTI_SWE_PUBLIC_INSTRUCTION"
        )
        if problem["task_projection"] != expected_projection:
            raise SourceBankError(
                f"target public-instruction projection drift: {problem['target_id']}"
            )
        number = problem["issue_number"]
        if type(number) is not int or number <= 0:
            raise SourceBankError(f"target problem number malformed: {problem['target_id']}")
        repository = str(target["repository"])
        tracker = problem["tracker"]
        if tracker == "GITHUB_ISSUE":
            expected_url = f"https://api.github.com/repos/{repository}/issues/{number}"
        elif tracker == "DJANGO_TRAC" and repository == "django/django":
            expected_url = f"https://code.djangoproject.com/ticket/{number}"
        else:
            raise SourceBankError(f"target problem tracker malformed: {problem['target_id']}")
        if problem["url"] != expected_url:
            raise SourceBankError(f"target problem URL drift: {problem['target_id']}")
        identity = (repository, str(tracker), number)
        if identity in problem_identities:
            raise SourceBankError(f"duplicate target problem object: {identity}")
        problem_identities.add(identity)
    eligibility = plan.get("eligibility")
    if (
        not isinstance(eligibility, Mapping)
        or eligibility.get("required_source_fix_signal")
        != "PUBLIC_GITHUB_MERGED_PR_DIFF"
        or eligibility.get("required_version_signal")
        != "FIX_COMMIT_IS_ANCESTOR_OF_TARGET_BASE"
        or eligibility.get("unknown_or_missing_signal") != "REJECT"
    ):
        raise SourceBankError("source chronology/version fail-closed rule drift")
    candidate_rule = plan.get("candidate_rule")
    if (
        not isinstance(candidate_rule, Mapping)
        or candidate_rule.get("top_k_per_target") != TOP_K
        or candidate_rule.get("actual_declared_candidates_per_target") != 1
        or candidate_rule.get("minimum_verified_source_records") != 1
        or candidate_rule.get("coverage_sufficiency_target_count") != 12
        or candidate_rule.get("zero_candidate_assignment")
        != "PRESERVE_AND_RUN_AS_NO_SAFE_CANDIDATE"
        or candidate_rule.get("partial_coverage_execution_allowed") is not True
        or candidate_rule.get("coverage_shortfall_verdict")
        != "RETRIEVAL_BANK_COVERAGE_INSUFFICIENT"
    ):
        raise SourceBankError("candidate coverage/ranking rule drift")

    if plan.get("runtime_projection") != {
        "memory_kind": "ORG_SEMANTIC",
        "bank_type": "ORG_SEMANTIC",
        "permission_scope": "PUBLIC_READ",
        "tenant_scope": "BENCHMARK_ISOLATED",
        "repository_scope": "EXACT_SOURCE_AND_TARGET_REPOSITORY",
        "version_scope": "EXACT_SOURCE_COMMIT",
        "memory_record_version": "source_commit",
        "path_scope": "**",
        "changed_paths_are_reporting_features_not_path_admission_scope": True,
        "verified": True,
        "reviewed": True,
        "source_outcome": "passed",
    }:
        raise SourceBankError("runtime safe-pool projection drift")
    capture = plan.get("public_evidence_capture")
    if not isinstance(capture, Mapping) or any(
        capture.get(name) != expected
        for name, expected in {
            "network_scope": (
                "PINNED_DATASETS_PLUS_PUBLIC_GITHUB_AND_DJANGO_TRAC_"
                "NO_AUTHORIZATION_HEADER"
            ),
            "raw_response_bytes_content_addressed": True,
            "resume_without_reissuing_cached_requests": True,
            "api_failure_or_unknown_candidate": "REJECT_CANDIDATE_AND_CONTINUE_FROZEN_RANK",
            "credentials_or_response_headers_persisted": False,
            "model_calls": 0,
            "grader_containers": 0,
        }.items()
    ):
        raise SourceBankError("public evidence capture contract drift")
    if plan.get("required_materialization_inputs") != [
        "PINNED_RUNTIME_PUBLIC_INSTRUCTION_PROJECTION",
        "TRUE_TARGET_PROBLEM_CHRONOLOGY_CACHE",
        "PUBLIC_SOURCE_PR_BODY_AND_MERGED_DIFF_EVIDENCE",
        "FIX_COMMIT_TO_TARGET_BASE_ANCESTRY_EVIDENCE",
    ]:
        raise SourceBankError("source-bank materialization input inventory drift")

    if grader_lock.get("schema") != "trimem/grader-lock/1.0":
        raise SourceBankError("grader lock schema drift")
    dataset_files = grader_lock.get("dataset_files")
    if not isinstance(dataset_files, list) or len(dataset_files) != 3:
        raise SourceBankError("exactly three pinned dataset files are required")
    specs: dict[str, dict[str, Any]] = {}
    for spec in dataset_files:
        if not isinstance(spec, dict):
            raise SourceBankError("dataset lock row is malformed")
        benchmark_id = spec.get("benchmark_id")
        if benchmark_id not in REQUIRED_DATASETS or benchmark_id in specs:
            raise SourceBankError("dataset lock IDs are duplicated or unknown")
        _require_sha(spec.get("sha256"), f"dataset {benchmark_id} hash")
        if type(spec.get("bytes")) is not int or spec["bytes"] <= 0:
            raise SourceBankError(f"dataset {benchmark_id} size is invalid")
        _require_hex40(spec.get("dataset_revision"), f"dataset {benchmark_id} revision")
        specs[str(benchmark_id)] = dict(spec)
    if tuple(sorted(specs, key=REQUIRED_DATASETS.index)) != REQUIRED_DATASETS:
        raise SourceBankError("pinned dataset set is incomplete")
    for target in targets:
        if not isinstance(target, dict):
            raise SourceBankError("development target row is malformed")
        spec = specs.get(str(target.get("benchmark_id")))
        if spec is None or target.get("dataset_revision") != spec["dataset_revision"]:
            raise SourceBankError(f"target dataset revision drift: {target.get('target_id')}")
        _require_sha(target.get("source_row_sha256"), "target source-row hash")
        _require_hex40(target.get("base_commit"), "target base commit")
        if not REPOSITORY.fullmatch(str(target.get("repository", ""))):
            raise SourceBankError(f"target repository malformed: {target.get('target_id')}")
    return [dict(row) for row in targets], specs


def _source_instance_id(benchmark_id: str, row: Mapping[str, Any]) -> str:
    value = row.get("instance_id")
    if isinstance(value, str) and value:
        return value
    if benchmark_id.startswith("multi_swe_bench_"):
        org, repo, number = row.get("org"), row.get("repo"), row.get("number")
        if isinstance(org, str) and isinstance(repo, str) and type(number) is int:
            return f"{org}__{repo}-{number}"
    raise SourceBankError(f"dataset row has no canonical instance ID: {benchmark_id}")


def _source_repository(benchmark_id: str, row: Mapping[str, Any]) -> str:
    if benchmark_id == "swebench_verified":
        value = row.get("repo")
    else:
        org, repo = row.get("org"), row.get("repo")
        value = f"{org}/{repo}" if isinstance(org, str) and isinstance(repo, str) else None
    if not isinstance(value, str) or not REPOSITORY.fullmatch(value):
        raise SourceBankError(f"dataset row repository malformed: {benchmark_id}")
    return value


def _source_base_commit(benchmark_id: str, row: Mapping[str, Any]) -> str:
    if benchmark_id == "swebench_verified":
        value = row.get("base_commit")
    else:
        base = row.get("base")
        value = base.get("sha") if isinstance(base, Mapping) else row.get("base_commit")
    return _require_hex40(value, "dataset row base commit")


def public_issue_text(benchmark_id: str, row: Mapping[str, Any]) -> str:
    """Project public issue text without touching patch/test/outcome fields."""

    if benchmark_id == "swebench_verified":
        value = row.get("problem_statement")
        if not isinstance(value, str) or not value.strip():
            raise SourceBankError("SWE-bench public problem_statement is missing")
        return value.strip()
    title, body = row.get("title"), row.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        raise SourceBankError("Multi-SWE public title/body is missing")
    pieces = [title.strip(), body.strip()]
    issues = row.get("resolved_issues")
    if not isinstance(issues, list):
        raise SourceBankError("Multi-SWE resolved_issues public projection is missing")
    for issue in issues:
        if not isinstance(issue, Mapping):
            raise SourceBankError("Multi-SWE resolved issue is malformed")
        number, issue_title, issue_body = (
            issue.get("number"),
            issue.get("title"),
            issue.get("body"),
        )
        if (
            type(number) is not int
            or not isinstance(issue_title, str)
            or not (issue_body is None or isinstance(issue_body, str))
        ):
            raise SourceBankError("Multi-SWE resolved issue public fields are malformed")
        pieces.append(
            f"Resolved issue #{number}: {issue_title.strip()}\n"
            f"{issue_body.strip() if isinstance(issue_body, str) else ''}"
        )
    result = "\n\n".join(piece for piece in pieces if piece)
    if not result:
        raise SourceBankError("Multi-SWE public issue text is empty")
    return result


def _source_fix_patch(benchmark_id: str, row: Mapping[str, Any]) -> str:
    field = "patch" if benchmark_id == "swebench_verified" else "fix_patch"
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SourceBankError(f"historical source row lacks source-owned {field}")
    return value


def changed_paths_from_patch(patch: str) -> tuple[str, ...]:
    paths: set[str] = set()
    for line in patch.splitlines():
        raw: str | None = None
        if line.startswith("diff --git a/"):
            match = re.match(r"^diff --git a/(.+?) b/(.+)$", line)
            if not match or match.group(1) != match.group(2):
                raise SourceBankError("renames or malformed diff headers are not supported")
            raw = match.group(2)
        elif line.startswith("+++ b/"):
            raw = line[6:]
        if raw is None:
            continue
        pure = PurePosixPath(raw)
        if raw.startswith("/") or "\\" in raw or ".." in pure.parts or raw == "/dev/null":
            raise SourceBankError(f"unsafe changed path in source patch: {raw}")
        normalized = pure.as_posix()
        if not normalized or normalized == ".":
            raise SourceBankError("empty changed path in source patch")
        paths.add(normalized)
    if not paths:
        raise SourceBankError("source fix patch has no canonical changed paths")
    return tuple(sorted(paths))


def compile_source_features(issue_text: str, patch: str) -> dict[str, list[str]]:
    """Deterministic, source-only lexical feature projection."""

    changed_paths = changed_paths_from_patch(patch)
    combined = issue_text + "\n" + patch
    symbols = set(BACKTICK_IDENTIFIER.findall(combined))
    symbols.update(DECLARATION.findall(patch))
    apis = set(API_IDENTIFIER.findall(combined))
    errors = set(ERROR_IDENTIFIER.findall(combined))
    # Bound adversarial or unusually large rows without making ranking order-dependent.
    return {
        "changed_paths": list(changed_paths[:128]),
        "symbols": sorted(symbols)[:128],
        "apis": sorted(apis)[:128],
        "errors": sorted(errors)[:128],
    }


def _provenance_item(
    value: Any,
    label: str,
    timestamp_field: str,
    *,
    extra_fields: Sequence[str] = (),
) -> dict[str, Any]:
    expected_fields = {
        "url",
        timestamp_field,
        "observed_at",
        "raw_sha256",
        *extra_fields,
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise SourceBankError(f"{label} provenance fields are incomplete")
    url = value.get("url")
    if not isinstance(url, str) or not (
        url.startswith("https://api.github.com/")
        or url.startswith("https://github.com/")
    ):
        raise SourceBankError(f"{label} provenance URL is not a cached GitHub source")
    event_time = _timestamp(value.get(timestamp_field), f"{label}.{timestamp_field}")
    observed = _timestamp(value.get("observed_at"), f"{label}.observed_at")
    if observed < event_time:
        raise SourceBankError(f"{label} was observed before its event timestamp")
    _require_sha(value.get("raw_sha256"), f"{label}.raw_sha256")
    return dict(value)


def _chronology_indexes(cache: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if cache.get("schema") != "trimem/dev-activation-chronology-cache/1.0":
        raise SourceBankError("chronology cache schema is missing or UNKNOWN")
    if cache.get("status") not in {
        "COMPLETE_CACHED_PUBLIC_EVIDENCE",
        "FROZEN_CACHED_PUBLIC_EVIDENCE",
    }:
        raise SourceBankError("chronology cache is not frozen public evidence")
    sources, targets = cache.get("sources"), cache.get("targets")
    if not isinstance(sources, list) or not isinstance(targets, list):
        raise SourceBankError("chronology source/target entries are missing")

    def index(rows: list[Any], field: str, label: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get(field), str):
                raise SourceBankError(f"malformed chronology {label} row")
            key = row[field]
            if not key or key in result:
                raise SourceBankError(f"duplicate chronology {label}: {key}")
            result[key] = dict(row)
        return result

    return index(sources, "source_task_id", "source"), index(targets, "target_id", "target")


def evidence_blobs_from_cache(
    chronology_path: Path,
    cache: Mapping[str, Any],
) -> dict[str, bytes]:
    """Load only hash-addressed evidence referenced by a chronology cache."""

    referenced: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            if "path" in value:
                path = value["path"]
                if not isinstance(path, str) or not re.fullmatch(
                    r"github_raw/[0-9a-f]{64}\.(?:json|diff|html)", path
                ):
                    raise SourceBankError("chronology evidence path is not content-addressed")
                referenced.add(path)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(cache)
    blobs: dict[str, bytes] = {}
    for relative in sorted(referenced):
        path = _confined_path(
            chronology_path.parent,
            relative,
            label="chronology evidence",
            must_exist=True,
        )
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != PurePosixPath(relative).stem:
            raise SourceBankError(f"chronology evidence digest drift: {relative}")
        blobs[relative] = raw
    return blobs


def _write_payloads(payload_root: Path, payloads: Mapping[str, bytes]) -> None:
    payload_root.mkdir(parents=True, exist_ok=True)
    for relative, raw in payloads.items():
        path = _confined_path(
            payload_root,
            relative,
            label="payload output",
            must_exist=False,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        # A concurrent symlink swap must fail rather than redirecting the write.
        _confined_path(
            payload_root,
            relative,
            label="payload output",
            must_exist=False,
        ).write_bytes(raw)


def _validate_target_chronology(target: Mapping[str, Any], entry: Any) -> tuple[datetime, str]:
    required = {
        "target_id",
        "source_row_sha256",
        "repository",
        "base_commit",
        "issue",
    }
    if not isinstance(entry, dict) or set(entry) not in (required, required | {"public_text"}):
        raise SourceBankError(f"target chronology UNKNOWN: {target.get('target_id')}")
    for field in ("target_id", "source_row_sha256", "repository", "base_commit"):
        if entry.get(field) != target.get(field):
            raise SourceBankError(f"target chronology identity drift: {target.get('target_id')}")
    issue = _provenance_item(entry.get("issue"), "target issue", "created_at")
    if "public_text" in entry and (
        not isinstance(entry["public_text"], str) or not entry["public_text"].strip()
    ):
        raise SourceBankError(f"target public issue text UNKNOWN: {target.get('target_id')}")
    return _timestamp(issue["created_at"], "target issue.created_at"), canonical_sha256(entry)


def _validate_source_entry(
    entry: Any,
    *,
    source_task_id: str,
    source_row_sha256: str,
    source_fix_patch_sha256: str,
    repository: str,
    target: Mapping[str, Any],
    target_created_at: datetime,
) -> tuple[dict[str, Any], str, str]:
    required = {
        "source_task_id",
        "source_row_sha256",
        "repository",
        "fix_pr",
        "fix_commit",
        "source_issue",
        "patch_equivalence",
        "ancestry",
    }
    if not isinstance(entry, dict) or set(entry) != required:
        raise SourceBankError("SOURCE_CHRONOLOGY_OR_VERSION_UNKNOWN")
    if (
        entry.get("source_task_id") != source_task_id
        or entry.get("source_row_sha256") != source_row_sha256
        or entry.get("repository") != repository
    ):
        raise SourceBankError("SOURCE_CHRONOLOGY_IDENTITY_DRIFT")
    fix_pr = _provenance_item(
        entry.get("fix_pr"),
        "fix PR",
        "merged_at",
        extra_fields=("merge_commit_sha",),
    )
    fix_commit = _provenance_item(
        entry.get("fix_commit"),
        "fix commit",
        "public_timestamp",
        extra_fields=("sha",),
    )
    fix_sha = _require_hex40(fix_commit.get("sha"), "fix commit sha")
    if _require_hex40(fix_pr.get("merge_commit_sha"), "fix PR merge commit") != fix_sha:
        raise SourceBankError("FIX_PR_AND_FIX_COMMIT_IDENTITY_DRIFT")
    source_issue = _provenance_item(entry.get("source_issue"), "source issue", "closed_at")
    equivalence = entry.get("patch_equivalence")
    if not isinstance(equivalence, dict) or set(equivalence) != {
        "status",
        "observed_at",
        "evidence_sha256",
        "dataset_patch_sha256",
        "upstream_fix_diff_sha256",
    }:
        raise SourceBankError("SOURCE_FIX_PATCH_EQUIVALENCE_UNKNOWN")
    if equivalence.get("status") != "UPSTREAM_MERGED_FIX_PATCH_EQUIVALENT":
        raise SourceBankError("SOURCE_FIX_PATCH_NOT_VERIFIED")
    _timestamp(equivalence.get("observed_at"), "patch equivalence observed_at")
    if (
        _require_sha(
            equivalence.get("dataset_patch_sha256"),
            "patch equivalence dataset patch hash",
        )
        != source_fix_patch_sha256
    ):
        raise SourceBankError("SOURCE_FIX_PATCH_EQUIVALENCE_IDENTITY_DRIFT")
    _require_sha(
        equivalence.get("upstream_fix_diff_sha256"),
        "patch equivalence upstream diff hash",
    )
    verification_sha = _require_sha(
        equivalence.get("evidence_sha256"), "patch equivalence evidence"
    )
    available_at = max(
        _timestamp(fix_pr["merged_at"], "fix PR merged_at"),
        _timestamp(fix_commit["public_timestamp"], "fix commit public_timestamp"),
        _timestamp(source_issue["closed_at"], "source issue closed_at"),
    )
    if available_at >= target_created_at:
        raise SourceBankError("SOURCE_NOT_STRICTLY_BEFORE_TARGET")
    ancestry = entry.get("ancestry")
    if not isinstance(ancestry, list):
        raise SourceBankError("VERSION_ANCESTRY_UNKNOWN")
    matches = [item for item in ancestry if isinstance(item, Mapping) and item.get("target_id") == target.get("target_id")]
    if len(matches) != 1:
        raise SourceBankError("VERSION_ANCESTRY_UNKNOWN")
    proof = matches[0]
    if set(proof) != {
        "target_id",
        "target_base_commit",
        "fix_commit_sha",
        "status",
        "observed_at",
        "evidence_sha256",
    }:
        raise SourceBankError("VERSION_ANCESTRY_FIELDS_INCOMPLETE")
    if (
        proof.get("target_base_commit") != target.get("base_commit")
        or proof.get("fix_commit_sha") != fix_sha
        or proof.get("status") != "FIX_COMMIT_IS_ANCESTOR_OF_TARGET_BASE"
    ):
        raise SourceBankError("VERSION_ANCESTRY_NOT_PROVEN")
    _timestamp(proof.get("observed_at"), "ancestry observed_at")
    _require_sha(proof.get("evidence_sha256"), "ancestry evidence")
    canonical = dict(entry)
    canonical["available_at"] = available_at.isoformat().replace("+00:00", "Z")
    return canonical, fix_sha, verification_sha


def _source_tokens(text: str, features: Mapping[str, Sequence[str]]) -> set[str]:
    values = set(match.group(0).casefold() for match in TOKEN.finditer(text))
    for field in ("changed_paths", "symbols", "apis", "errors"):
        for value in features.get(field, ()):
            values.update(match.group(0).casefold() for match in TOKEN.finditer(value))
    return values


def _target_projection(text: str) -> dict[str, set[str]]:
    return {
        "tokens": {match.group(0).casefold() for match in TOKEN.finditer(text)},
        "symbols": {value.casefold() for value in BACKTICK_IDENTIFIER.findall(text)},
        "apis": {value.casefold() for value in API_IDENTIFIER.findall(text)},
        "errors": {value.casefold() for value in ERROR_IDENTIFIER.findall(text)},
        "paths": {
            value.casefold()
            for value in re.findall(
                r"(?<![A-Za-z0-9_.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+",
                text,
            )
        },
    }


def _rank_score(
    target_projection: Mapping[str, set[str]],
    issue_text: str,
    features: Mapping[str, Sequence[str]],
) -> dict[str, int]:
    source_sets = {
        "errors": {value.casefold() for value in features["errors"]},
        "apis": {value.casefold() for value in features["apis"]},
        "symbols": {value.casefold() for value in features["symbols"]},
        "paths": {value.casefold() for value in features["changed_paths"]},
        "tokens": _source_tokens(issue_text, features),
    }
    return {
        field + "_overlap": len(target_projection[field] & source_sets[field])
        for field in ("errors", "apis", "symbols", "paths", "tokens")
    }


def _rank_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    score = candidate["score"]
    return (
        -score["errors_overlap"],
        -score["apis_overlap"],
        -score["symbols_overlap"],
        -score["paths_overlap"],
        -score["tokens_overlap"],
        candidate["source_task_id"],
    )


def _memory_payload(
    *,
    source_task_id: str,
    repository: str,
    source_row_sha256: str,
    issue_text: str,
    fix_patch: str,
    features: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    payload = {
        "schema": "trimem/dev-activation-source-payload/1.0",
        "source_task_id": source_task_id,
        "source_repository": repository,
        "source_row_sha256": source_row_sha256,
        "source_public_issue": issue_text,
        "source_fix_patch": fix_patch,
        "source_fix_patch_sha256": hashlib.sha256(fix_patch.encode("utf-8")).hexdigest(),
        "features": {key: list(value) for key, value in features.items()},
    }
    _assert_no_forbidden_target_keys(payload, "source payload")
    return payload


def ranked_public_source_rows(
    *,
    target_repository: str,
    target_public_issue: str,
    forbidden_instance_ids: set[str],
    rows_by_benchmark: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Return the frozen public lexical ordering before any safety evidence.

    The identity exclusion and repository comparison precede source patch access.
    This function is the shared ordering primitive for offline construction and
    public GitHub evidence capture.
    """

    projection = _target_projection(target_public_issue)
    candidates: list[dict[str, Any]] = []
    for benchmark_id in REQUIRED_DATASETS:
        rows = rows_by_benchmark.get(benchmark_id)
        if not isinstance(rows, Sequence):
            raise SourceBankError(f"pinned dataset rows missing: {benchmark_id}")
        for row in rows:
            if not isinstance(row, Mapping):
                raise SourceBankError(f"malformed row in {benchmark_id}")
            instance_id = _source_instance_id(benchmark_id, row)
            if instance_id in forbidden_instance_ids:
                continue
            repository = _source_repository(benchmark_id, row)
            if repository != target_repository:
                continue
            issue_text = public_issue_text(benchmark_id, row)
            fix_patch = _source_fix_patch(benchmark_id, row)
            features = compile_source_features(issue_text, fix_patch)
            source_task_id = f"{benchmark_id}--{instance_id}"
            candidates.append(
                {
                    "benchmark_id": benchmark_id,
                    "instance_id": instance_id,
                    "source_task_id": source_task_id,
                    "repository": repository,
                    "row": row,
                    "source_row_sha256": canonical_sha256(row),
                    "issue_text": issue_text,
                    "fix_patch": fix_patch,
                    "features": features,
                    "score": _rank_score(projection, issue_text, features),
                }
            )
    return sorted(candidates, key=_rank_key)


def build_source_bank(
    plan: Mapping[str, Any],
    development: Mapping[str, Any],
    grader_lock: Mapping[str, Any],
    rows_by_benchmark: Mapping[str, Sequence[Mapping[str, Any]]],
    chronology_cache: Mapping[str, Any],
    *,
    chronology_raw_sha256: str,
    payload_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Build a frozen bank; raise CoverageError unless every DEV target is covered."""

    targets = development.get("targets")
    if not isinstance(targets, list) or len(targets) != 12:
        raise SourceBankError("development target projection is not exactly 12 rows")
    _require_sha(chronology_raw_sha256, "chronology cache raw hash")
    target_ids = {str(row.get("target_id")) for row in targets if isinstance(row, Mapping)}
    target_instance_ids = {
        str(row.get("instance_id")) for row in targets if isinstance(row, Mapping)
    }
    target_rows: dict[str, Mapping[str, Any]] = {}
    for benchmark_id in REQUIRED_DATASETS:
        rows = rows_by_benchmark.get(benchmark_id)
        if not isinstance(rows, Sequence) or not rows:
            raise SourceBankError(f"pinned dataset rows missing: {benchmark_id}")
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise SourceBankError(f"malformed row in {benchmark_id}")
            instance_id = _source_instance_id(benchmark_id, row)
            if instance_id in seen:
                raise SourceBankError(f"duplicate dataset row: {benchmark_id}--{instance_id}")
            seen.add(instance_id)
            key = f"{benchmark_id}--{instance_id}"
            if key in target_ids:
                target_rows[key] = row
    if set(target_rows) != target_ids:
        missing = sorted(target_ids - set(target_rows))
        raise SourceBankError(f"frozen target rows absent from pinned datasets: {missing}")

    source_index, target_chronology = _chronology_indexes(chronology_cache)
    target_context: dict[str, dict[str, Any]] = {}
    for target in targets:
        target_id = str(target["target_id"])
        row = target_rows[target_id]
        if canonical_sha256(row) != target.get("source_row_sha256"):
            raise SourceBankError(f"frozen target source-row hash drift: {target_id}")
        benchmark_id = str(target["benchmark_id"])
        if (
            _source_repository(benchmark_id, row) != target.get("repository")
            or _source_base_commit(benchmark_id, row) != target.get("base_commit")
        ):
            raise SourceBankError(f"frozen target identity drift: {target_id}")
        issue_text = public_issue_text(benchmark_id, row)
        created_at, target_provenance_sha = _validate_target_chronology(
            target, target_chronology.get(target_id)
        )
        target_context[target_id] = {
            "target": target,
            "issue_text": issue_text,
            "projection": _target_projection(issue_text),
            "created_at": created_at,
            "provenance_sha256": target_provenance_sha,
        }

    record_material: dict[str, dict[str, Any]] = {}
    payloads: dict[str, bytes] = {}
    rejection_counts: Counter[str] = Counter()
    assignments: list[dict[str, Any]] = []
    selected_memory_ids: set[str] = set()
    missing_targets: list[str] = []
    for target in targets:
        target_id = str(target["target_id"])
        context = target_context[target_id]
        safe_candidates: list[dict[str, Any]] = []
        try:
            ranked_universe = ranked_public_source_rows(
                target_repository=str(target["repository"]),
                target_public_issue=str(context["issue_text"]),
                forbidden_instance_ids=target_instance_ids,
                rows_by_benchmark=rows_by_benchmark,
            )[:MAX_RANKED_SOURCES_PER_TARGET]
        except SourceBankError as exc:
            rejection_counts[str(exc)] += 1
            ranked_universe = []
        for candidate in ranked_universe:
            benchmark_id = str(candidate["benchmark_id"])
            row = candidate["row"]
            source_task_id = str(candidate["source_task_id"])
            repository = str(candidate["repository"])
            source_row_sha = str(candidate["source_row_sha256"])
            issue_text = str(candidate["issue_text"])
            fix_patch = str(candidate["fix_patch"])
            features = candidate["features"]
            entry = source_index.get(source_task_id)
            if entry is None:
                rejection_counts["SOURCE_CHRONOLOGY_OR_VERSION_UNKNOWN"] += 1
                continue
            try:
                validated_entry, fix_commit, verification_sha = _validate_source_entry(
                    entry,
                    source_task_id=source_task_id,
                    source_row_sha256=source_row_sha,
                    source_fix_patch_sha256=hashlib.sha256(
                        fix_patch.encode("utf-8")
                    ).hexdigest(),
                    repository=repository,
                    target=target,
                    target_created_at=context["created_at"],
                )
            except SourceBankError as exc:
                rejection_counts[str(exc)] += 1
                continue
            payload = _memory_payload(
                source_task_id=source_task_id,
                repository=repository,
                source_row_sha256=source_row_sha,
                issue_text=issue_text,
                fix_patch=fix_patch,
                features=features,
            )
            payload_raw = canonical_bytes(payload)
            payload_sha = hashlib.sha256(payload_raw).hexdigest()
            payload_rel = f"{PAYLOAD_DIRECTORY}/{payload_sha}.json"
            payloads[payload_rel] = payload_raw
            memory_id = "dev-source-" + hashlib.sha256(
                source_task_id.encode("utf-8")
            ).hexdigest()[:24]
            provenance_sha = canonical_sha256(entry)
            record = {
                "memory_id": memory_id,
                "source_task_id": source_task_id,
                "source_dataset_id": DATASET_IDS[benchmark_id],
                "source_dataset_revision": str(
                    next(
                        spec["dataset_revision"]
                        for spec in grader_lock["dataset_files"]
                        if spec["benchmark_id"] == benchmark_id
                    )
                ),
                "source_row_sha256": source_row_sha,
                "source_repository": repository,
                "source_base_commit": _source_base_commit(benchmark_id, row),
                "source_commit": fix_commit,
                "source_timestamp": validated_entry["available_at"],
                "bank_type": "ORG_SEMANTIC",
                "changed_paths": features["changed_paths"],
                "symbols": features["symbols"],
                "apis": features["apis"],
                "errors": features["errors"],
                "verified": True,
                "reviewed": True,
                "source_outcome": "passed",
                "source_fix_verification_signal": "UPSTREAM_MERGED_FIX_PATCH_EQUIVALENT",
                "verification_evidence_sha256": verification_sha,
                "chronology_and_version_evidence_sha256": canonical_sha256(validated_entry),
                "provenance_sha256": provenance_sha,
                "payload_sha256": payload_sha,
                "payload_path": payload_rel,
                "permission_scope": "PUBLIC_READ",
                "tenant_scope": "BENCHMARK_ISOLATED",
                "repository_scope": "EXACT_SOURCE_AND_TARGET_REPOSITORY",
                "version_scope": "EXACT_SOURCE_COMMIT",
                "path_scope": "**",
                "quarantined": False,
                "target_derived": False,
            }
            existing = record_material.get(memory_id)
            if existing is not None and existing != record:
                raise SourceBankError(f"inconsistent source evidence across targets: {source_task_id}")
            record_material[memory_id] = record
            safe_candidates.append(
                {
                    "memory_id": memory_id,
                    "source_task_id": source_task_id,
                    "score": candidate["score"],
                }
            )
            if len(safe_candidates) == TOP_K:
                break
        if not safe_candidates:
            missing_targets.append(target_id)
        selected_memory_ids.update(row["memory_id"] for row in safe_candidates)
        assignments.append(
            {
                "target_id": target_id,
                "target_repository": target["repository"],
                "target_public_issue_provenance_sha256": target_context[target_id][
                    "provenance_sha256"
                ],
                "candidate_count": len(safe_candidates),
                "candidates": safe_candidates,
            }
        )
    records = sorted(
        (record_material[memory_id] for memory_id in selected_memory_ids),
        key=lambda row: row["memory_id"],
    )
    used_payloads = {
        record["payload_path"]: payloads[record["payload_path"]] for record in records
    }
    if not records:
        raise SourceBankError("NO_VERIFIED_SOURCE_RECORDS")
    covered_target_count = sum(
        1 for assignment in assignments if assignment["candidate_count"] > 0
    )
    bank = {
        "schema": "trimem/dev-activation-source-bank/1.0",
        "status": "FROZEN_VERIFIED_TARGET_DISJOINT",
        "scientific_role": "POST_DEV_DIAGNOSTIC_ORACLE_BANK_NOT_SELECTION_OR_HELDOUT_EVIDENCE",
        "read_only": True,
        "result_blind_construction": True,
        "same_logical_snapshot_for_C1_and_C2": True,
        "development_target_set_sha256": development["target_set_sha256"],
        "source_bank_plan_sha256": canonical_sha256(plan),
        "chronology_cache": {
            "path": CHRONOLOGY_PATH.as_posix(),
            "raw_sha256": chronology_raw_sha256,
        },
        "target_overlap_count": 0,
        "record_count": len(records),
        "records_sha256": canonical_sha256(records),
        "records": records,
        "covered_target_count": covered_target_count,
        "zero_candidate_target_ids": missing_targets,
        "eligibility_rejection_histogram": dict(sorted(rejection_counts.items())),
        "candidate_assignments_sha256": canonical_sha256(assignments),
        "candidate_assignments": assignments,
        "snapshot_sha256": canonical_sha256(
            {
                "records": records,
                "candidate_assignments": assignments,
                "zero_candidate_target_ids": missing_targets,
                "eligibility_rejection_histogram": dict(sorted(rejection_counts.items())),
            }
        ),
        "accounting": {
            "model_calls": 0,
            "paid_model_calls": 0,
            "grader_containers": 0,
            "official_grader_runs": 0,
        },
    }
    validate_source_bank(
        bank,
        development=development,
        payloads=used_payloads,
        plan=plan if plan.get("source_universe", {}).get("mode") else None,
    )
    if payload_root is not None:
        _write_payloads(payload_root, used_payloads)
    return bank, used_payloads


def _oracle_source_task_id(repository: str, pull_number: int) -> str:
    return f"github-pr--{repository.replace('/', '__')}--{pull_number}"


def _oracle_payload(
    *,
    source_task_id: str,
    repository: str,
    source_row_sha256: str,
    title: str,
    body: str,
    merged_diff: str,
    features: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    payload = {
        "schema": "trimem/dev-activation-github-source-payload/1.0",
        "source_task_id": source_task_id,
        "source_repository": repository,
        "source_row_sha256": source_row_sha256,
        "source_public_issue": "\n\n".join(part for part in (title.strip(), body.strip()) if part),
        "source_merged_diff": merged_diff,
        "source_merged_diff_sha256": hashlib.sha256(merged_diff.encode("utf-8")).hexdigest(),
        "features": {key: list(value) for key, value in features.items()},
    }
    _assert_no_forbidden_target_keys(payload, "GitHub source payload")
    return payload


def _strict_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SourceBankError(f"{label} raw JSON is invalid") from exc
    if not isinstance(value, dict):
        raise SourceBankError(f"{label} raw JSON root is not an object")
    return value


def parse_django_trac_ticket(raw: bytes, *, expected_number: int) -> dict[str, Any]:
    """Project identity and first-publication fields from a frozen Trac page."""

    match = DJANGO_TRAC_OLD_VALUES.search(raw)
    if match is None:
        raise SourceBankError("TARGET_TRAC_TICKET_METADATA_UNKNOWN")
    ticket = _strict_json_bytes(match.group(1), "Django Trac ticket metadata")
    if ticket.get("id") != expected_number:
        raise SourceBankError("TARGET_TRAC_TICKET_IDENTITY_DRIFT")
    created_at = ticket.get("time")
    _timestamp(created_at, "Django Trac ticket first-publication time")
    if not isinstance(ticket.get("summary"), str) or not ticket["summary"].strip():
        raise SourceBankError("TARGET_TRAC_TICKET_SUMMARY_UNKNOWN")
    return {
        "number": expected_number,
        "created_at": created_at,
        "title": ticket["summary"].strip(),
    }


def _oracle_json_provenance(
    value: Any,
    *,
    label: str,
    timestamp_field: str,
    evidence_blobs: Mapping[str, bytes],
    extra_fields: Sequence[str] = (),
    expected_url: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected = {
        "url",
        timestamp_field,
        "observed_at",
        "raw_sha256",
        "path",
        *extra_fields,
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise SourceBankError(f"{label} provenance fields are incomplete")
    url = value.get("url")
    if not isinstance(url, str) or not url.startswith("https://api.github.com/repos/"):
        raise SourceBankError(f"{label} is not a public GitHub REST URL")
    if expected_url is not None and url != expected_url:
        raise SourceBankError(f"{label} URL identity drift")
    event_time = _timestamp(value.get(timestamp_field), f"{label}.{timestamp_field}")
    observed = _timestamp(value.get("observed_at"), f"{label}.observed_at")
    if observed < event_time:
        raise SourceBankError(f"{label} was observed before its event timestamp")
    raw_sha = _require_sha(value.get("raw_sha256"), f"{label}.raw_sha256")
    expected_path = f"github_raw/{raw_sha}.json"
    if value.get("path") != expected_path:
        raise SourceBankError(f"{label} content-addressed path drift")
    raw = evidence_blobs.get(expected_path)
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != raw_sha:
        raise SourceBankError(f"{label} raw evidence missing or hash drift")
    return dict(value), _strict_json_bytes(raw, label)


def _nested(value: Mapping[str, Any], *path: str) -> Any:
    current: Any = value
    for part in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _validate_oracle_target_chronology(
    target: Mapping[str, Any],
    entry: Any,
    evidence_blobs: Mapping[str, bytes],
    problem_contract: Mapping[str, Any],
) -> tuple[datetime, str, str]:
    required = {
        "target_id",
        "source_row_sha256",
        "repository",
        "base_commit",
        "public_instruction",
        "public_instruction_sha256",
        "problem_object",
    }
    if not isinstance(entry, dict) or set(entry) != required:
        raise SourceBankError(f"target chronology UNKNOWN: {target.get('target_id')}")
    for field in ("target_id", "source_row_sha256", "repository", "base_commit"):
        if entry.get(field) != target.get(field):
            raise SourceBankError(f"target chronology identity drift: {target.get('target_id')}")
    public_instruction = entry.get("public_instruction")
    if not isinstance(public_instruction, str) or not public_instruction.strip():
        raise SourceBankError("target runtime public instruction is missing")
    instruction_sha = _require_sha(
        entry.get("public_instruction_sha256"),
        "target runtime public-instruction hash",
    )
    if hashlib.sha256(public_instruction.encode("utf-8")).hexdigest() != instruction_sha:
        raise SourceBankError("target runtime public-instruction hash drift")

    if (
        not isinstance(problem_contract, Mapping)
        or problem_contract.get("target_id") != target.get("target_id")
    ):
        raise SourceBankError("target problem-object contract missing")
    problem = entry.get("problem_object")
    expected_problem_fields = {
        "tracker",
        "issue_number",
        "url",
        "first_published_at",
        "observed_at",
        "raw_sha256",
        "path",
    }
    if not isinstance(problem, dict) or set(problem) != expected_problem_fields:
        raise SourceBankError("target problem-object provenance fields are incomplete")
    for field in ("tracker", "issue_number", "url"):
        if problem.get(field) != problem_contract.get(field):
            raise SourceBankError("target problem-object identity drift")
    first_published_at = _timestamp(
        problem.get("first_published_at"),
        "target problem first-publication timestamp",
    )
    observed_at = _timestamp(problem.get("observed_at"), "target problem observed_at")
    if observed_at < first_published_at:
        raise SourceBankError("target problem was observed before first publication")
    raw_sha = _require_sha(problem.get("raw_sha256"), "target problem raw hash")
    extension = "json" if problem["tracker"] == "GITHUB_ISSUE" else "html"
    expected_path = f"github_raw/{raw_sha}.{extension}"
    if problem.get("path") != expected_path:
        raise SourceBankError("target problem content-addressed path drift")
    raw = evidence_blobs.get(expected_path)
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != raw_sha:
        raise SourceBankError("target problem raw evidence missing or hash drift")
    issue_number = int(problem["issue_number"])
    if problem["tracker"] == "GITHUB_ISSUE":
        raw_issue = _strict_json_bytes(raw, "target GitHub issue")
        if "pull_request" in raw_issue:
            raise SourceBankError("TARGET_PROBLEM_OBJECT_IS_PULL_REQUEST")
        if (
            raw_issue.get("number") != issue_number
            or raw_issue.get("created_at") != problem["first_published_at"]
            or _nested(raw_issue, "repository_url")
            != f"https://api.github.com/repos/{target['repository']}"
            or raw_issue.get("html_url")
            != f"https://github.com/{target['repository']}/issues/{issue_number}"
        ):
            raise SourceBankError("target GitHub issue differs from raw evidence")
    elif problem["tracker"] == "DJANGO_TRAC":
        raw_issue = parse_django_trac_ticket(raw, expected_number=issue_number)
        if raw_issue["created_at"] != problem["first_published_at"]:
            raise SourceBankError("target Trac publication time differs from raw evidence")
    else:
        raise SourceBankError("target problem tracker is unsupported")
    return (
        first_published_at,
        canonical_sha256(entry),
        public_instruction,
    )


def _validate_oracle_source_entry(
    entry: Any,
    *,
    expected_repository: str,
    expected_pull_number: int,
    target: Mapping[str, Any],
    target_created_at: datetime,
    evidence_blobs: Mapping[str, bytes],
) -> tuple[dict[str, Any], str, str, str, dict[str, Any]]:
    required = {
        "source_task_id",
        "source_row_sha256",
        "repository",
        "pull_number",
        "source_public_row",
        "diff",
        "fix_pr",
        "fix_commit",
        "source_issue",
        "source_fix_verification",
        "ancestry",
    }
    if not isinstance(entry, dict) or set(entry) != required:
        raise SourceBankError("ORACLE_SOURCE_EVIDENCE_UNKNOWN")
    expected_task_id = _oracle_source_task_id(expected_repository, expected_pull_number)
    if (
        entry.get("source_task_id") != expected_task_id
        or entry.get("repository") != expected_repository
        or entry.get("pull_number") != expected_pull_number
    ):
        raise SourceBankError("ORACLE_SOURCE_IDENTITY_DRIFT")
    public_row = entry.get("source_public_row")
    expected_public_fields = {
        "schema",
        "repository",
        "pull_number",
        "html_url",
        "title",
        "body",
        "base_commit",
        "merge_commit_sha",
        "merged_at",
        "diff_sha256",
    }
    if not isinstance(public_row, dict) or set(public_row) != expected_public_fields:
        raise SourceBankError("ORACLE_SOURCE_PUBLIC_ROW_UNKNOWN")
    if (
        public_row.get("schema") != "trimem/public-github-merged-pr-source-row/1.0"
        or public_row.get("repository") != expected_repository
        or public_row.get("pull_number") != expected_pull_number
    ):
        raise SourceBankError("ORACLE_SOURCE_PUBLIC_ROW_IDENTITY_DRIFT")
    source_row_sha = canonical_sha256(public_row)
    if entry.get("source_row_sha256") != source_row_sha:
        raise SourceBankError("ORACLE_SOURCE_ROW_HASH_DRIFT")
    base_commit = _require_hex40(public_row.get("base_commit"), "oracle source base commit")
    merge_commit = _require_hex40(
        public_row.get("merge_commit_sha"), "oracle source merge commit"
    )
    _timestamp(public_row.get("merged_at"), "oracle source merged_at")
    title, body = public_row.get("title"), public_row.get("body")
    if not isinstance(title, str) or not title.strip() or not isinstance(body, str):
        raise SourceBankError("ORACLE_SOURCE_PUBLIC_TEXT_UNKNOWN")
    html_url = public_row.get("html_url")
    if not isinstance(html_url, str) or not html_url.startswith(
        f"https://github.com/{expected_repository}/pull/"
    ):
        raise SourceBankError("ORACLE_SOURCE_PUBLIC_URL_DRIFT")

    diff = entry.get("diff")
    if not isinstance(diff, dict) or set(diff) != {
        "url",
        "observed_at",
        "raw_sha256",
        "path",
    }:
        raise SourceBankError("ORACLE_SOURCE_DIFF_UNKNOWN")
    if not isinstance(diff.get("url"), str) or not diff["url"].startswith(
        f"https://api.github.com/repos/{expected_repository}/pulls/{expected_pull_number}"
    ):
        raise SourceBankError("ORACLE_SOURCE_DIFF_URL_DRIFT")
    _timestamp(diff.get("observed_at"), "oracle source diff observed_at")
    diff_sha = _require_sha(diff.get("raw_sha256"), "oracle source diff hash")
    expected_path = f"github_raw/{diff_sha}.diff"
    if diff.get("path") != expected_path:
        raise SourceBankError("ORACLE_SOURCE_DIFF_PATH_DRIFT")
    raw_diff = evidence_blobs.get(expected_path)
    if not isinstance(raw_diff, bytes) or hashlib.sha256(raw_diff).hexdigest() != diff_sha:
        raise SourceBankError("ORACLE_SOURCE_DIFF_BLOB_MISSING_OR_DRIFT")
    try:
        merged_diff = raw_diff.decode("utf-8")
    except UnicodeError as exc:
        raise SourceBankError("ORACLE_SOURCE_DIFF_NOT_UTF8") from exc
    if public_row.get("diff_sha256") != diff_sha:
        raise SourceBankError("ORACLE_SOURCE_PUBLIC_ROW_DIFF_HASH_DRIFT")

    fix_pr, raw_fix_pr = _oracle_json_provenance(
        entry.get("fix_pr"),
        label="oracle fix PR",
        timestamp_field="merged_at",
        evidence_blobs=evidence_blobs,
        extra_fields=("merge_commit_sha",),
        expected_url=(
            f"https://api.github.com/repos/{expected_repository}/pulls/"
            f"{expected_pull_number}"
        ),
    )
    fix_commit, raw_fix_commit = _oracle_json_provenance(
        entry.get("fix_commit"),
        label="oracle fix commit",
        timestamp_field="public_timestamp",
        evidence_blobs=evidence_blobs,
        extra_fields=("sha",),
        expected_url=(
            f"https://api.github.com/repos/{expected_repository}/commits/{merge_commit}"
        ),
    )
    source_issue, raw_source_issue = _oracle_json_provenance(
        entry.get("source_issue"),
        label="oracle source issue",
        timestamp_field="closed_at",
        evidence_blobs=evidence_blobs,
        expected_url=(
            f"https://api.github.com/repos/{expected_repository}/pulls/"
            f"{expected_pull_number}"
        ),
    )
    if (
        _require_hex40(fix_pr.get("merge_commit_sha"), "oracle PR merge commit")
        != merge_commit
        or _require_hex40(fix_commit.get("sha"), "oracle fix commit sha")
        != merge_commit
        or fix_pr.get("merged_at") != public_row.get("merged_at")
    ):
        raise SourceBankError("ORACLE_SOURCE_MERGE_IDENTITY_DRIFT")
    raw_base = _nested(raw_fix_pr, "base", "sha")
    if (
        raw_fix_pr.get("number") != expected_pull_number
        or raw_fix_pr.get("merged_at") != fix_pr["merged_at"]
        or raw_fix_pr.get("merge_commit_sha") != merge_commit
        or raw_fix_pr.get("title") != public_row["title"]
        or (raw_fix_pr.get("body") or "") != public_row["body"]
        or raw_fix_pr.get("html_url") != public_row["html_url"]
        or raw_base != base_commit
    ):
        raise SourceBankError("ORACLE_SOURCE_PR_PROJECTION_DIFFERS_FROM_RAW")
    raw_commit_sha = raw_fix_commit.get("sha")
    raw_commit_times = (
        _nested(raw_fix_commit, "commit", "author", "date"),
        _nested(raw_fix_commit, "commit", "committer", "date"),
    )
    if raw_commit_sha != merge_commit or any(
        not isinstance(value, str) for value in raw_commit_times
    ):
        raise SourceBankError("ORACLE_SOURCE_COMMIT_PROJECTION_DIFFERS_FROM_RAW")
    parsed_commit_times = [
        (_timestamp(value, "raw source commit public timestamp"), str(value))
        for value in raw_commit_times
    ]
    raw_public_timestamp = max(parsed_commit_times, key=lambda item: item[0])[1]
    if raw_public_timestamp != fix_commit["public_timestamp"]:
        raise SourceBankError("ORACLE_SOURCE_COMMIT_TIMESTAMP_DIFFERS_FROM_RAW")
    if (
        raw_source_issue.get("number") != expected_pull_number
        or raw_source_issue.get("closed_at") != source_issue["closed_at"]
        or _nested(raw_source_issue, "base", "repo", "full_name")
        != expected_repository
    ):
        raise SourceBankError("ORACLE_SOURCE_ISSUE_CLOSE_DIFFERS_FROM_RAW")
    verification = entry.get("source_fix_verification")
    if not isinstance(verification, dict) or set(verification) != {
        "status",
        "observed_at",
        "evidence_sha256",
        "diff_sha256",
    }:
        raise SourceBankError("ORACLE_SOURCE_FIX_VERIFICATION_UNKNOWN")
    if verification.get("status") != "PUBLIC_GITHUB_MERGED_PR_DIFF":
        raise SourceBankError("ORACLE_SOURCE_FIX_NOT_VERIFIED")
    _timestamp(verification.get("observed_at"), "oracle verification observed_at")
    if _require_sha(verification.get("diff_sha256"), "oracle verification diff") != diff_sha:
        raise SourceBankError("ORACLE_SOURCE_FIX_DIFF_IDENTITY_DRIFT")
    expected_verification = canonical_sha256(
        {
            "signal": "PUBLIC_GITHUB_MERGED_PR_DIFF",
            "source_row_sha256": source_row_sha,
            "diff_sha256": diff_sha,
            "fix_pr_raw_sha256": fix_pr["raw_sha256"],
            "fix_commit_raw_sha256": fix_commit["raw_sha256"],
        }
    )
    if verification.get("evidence_sha256") != expected_verification:
        raise SourceBankError("ORACLE_SOURCE_FIX_VERIFICATION_HASH_DRIFT")

    available_at = max(
        _timestamp(fix_pr["merged_at"], "oracle fix PR merged_at"),
        _timestamp(fix_commit["public_timestamp"], "oracle fix commit public timestamp"),
        _timestamp(source_issue["closed_at"], "oracle source issue closed_at"),
    )
    if available_at >= target_created_at:
        raise SourceBankError("ORACLE_SOURCE_NOT_STRICTLY_BEFORE_TARGET")
    ancestry = entry.get("ancestry")
    matches = [
        item
        for item in ancestry
        if isinstance(item, Mapping) and item.get("target_id") == target.get("target_id")
    ] if isinstance(ancestry, list) else []
    if len(matches) != 1:
        raise SourceBankError("ORACLE_VERSION_ANCESTRY_UNKNOWN")
    proof = matches[0]
    if set(proof) != {
        "target_id",
        "target_base_commit",
        "fix_commit_sha",
        "status",
        "ahead_by",
        "behind_by",
        "observed_at",
        "evidence_sha256",
        "url",
        "raw_sha256",
        "path",
    }:
        raise SourceBankError("ORACLE_VERSION_ANCESTRY_FIELDS_INCOMPLETE")
    if (
        proof.get("target_base_commit") != target.get("base_commit")
        or proof.get("fix_commit_sha") != merge_commit
        or proof.get("status") != "FIX_COMMIT_IS_ANCESTOR_OF_TARGET_BASE"
        or type(proof.get("ahead_by")) is not int
        or proof["ahead_by"] < 0
        or proof.get("behind_by") != 0
    ):
        raise SourceBankError("ORACLE_VERSION_ANCESTRY_NOT_PROVEN")
    expected_compare_url = (
        f"https://api.github.com/repos/{expected_repository}/compare/"
        f"{merge_commit}...{target['base_commit']}"
    )
    if proof.get("url") != expected_compare_url:
        raise SourceBankError("ORACLE_VERSION_ANCESTRY_URL_DRIFT")
    _timestamp(proof.get("observed_at"), "oracle ancestry observed_at")
    compare_sha = _require_sha(proof.get("raw_sha256"), "oracle ancestry raw hash")
    compare_path = f"github_raw/{compare_sha}.json"
    if proof.get("path") != compare_path:
        raise SourceBankError("ORACLE_VERSION_ANCESTRY_PATH_DRIFT")
    compare_raw = evidence_blobs.get(compare_path)
    if not isinstance(compare_raw, bytes) or hashlib.sha256(compare_raw).hexdigest() != compare_sha:
        raise SourceBankError("ORACLE_VERSION_ANCESTRY_RAW_MISSING_OR_DRIFT")
    raw_compare = _strict_json_bytes(compare_raw, "oracle ancestry compare")
    if (
        raw_compare.get("status") not in {"ahead", "identical"}
        or raw_compare.get("ahead_by") != proof["ahead_by"]
        or raw_compare.get("behind_by") != proof["behind_by"]
        or _nested(raw_compare, "base_commit", "sha") != merge_commit
    ):
        raise SourceBankError("ORACLE_VERSION_ANCESTRY_PROJECTION_DIFFERS_FROM_RAW")
    expected_ancestry_sha = canonical_sha256(
        {
            "target_id": target["target_id"],
            "target_base_commit": target["base_commit"],
            "fix_commit_sha": merge_commit,
            "raw_sha256": compare_sha,
            "status": proof["status"],
            "ahead_by": proof["ahead_by"],
            "behind_by": proof["behind_by"],
        }
    )
    if proof.get("evidence_sha256") != expected_ancestry_sha:
        raise SourceBankError("ORACLE_VERSION_ANCESTRY_EVIDENCE_HASH_DRIFT")
    validated = dict(entry)
    validated["available_at"] = available_at.isoformat().replace("+00:00", "Z")
    return validated, merge_commit, expected_verification, base_commit, public_row


def build_oracle_source_bank(
    plan: Mapping[str, Any],
    development: Mapping[str, Any],
    chronology_cache: Mapping[str, Any],
    evidence_blobs: Mapping[str, bytes],
    *,
    chronology_raw_sha256: str,
    payload_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Materialize the twelve frozen public-PR oracle candidates, partially if needed."""

    _require_sha(chronology_raw_sha256, "chronology cache raw hash")
    targets = development.get("targets")
    source_rule = plan.get("source_universe")
    if not isinstance(targets, list) or len(targets) != 12 or not isinstance(source_rule, Mapping):
        raise SourceBankError("oracle builder inputs are malformed")
    oracle_rows = source_rule.get("oracle_source_prs")
    if not isinstance(oracle_rows, list) or len(oracle_rows) != 12:
        raise SourceBankError("oracle source mapping is absent")
    problem_rows = source_rule.get("target_problem_objects")
    if not isinstance(problem_rows, list) or len(problem_rows) != 12:
        raise SourceBankError("target problem-object mapping is absent")
    source_index, target_index = _chronology_indexes(chronology_cache)
    records_by_id: dict[str, dict[str, Any]] = {}
    payloads: dict[str, bytes] = {}
    assignments: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()
    zero_targets: list[str] = []
    # These suffixes are solution-PR identities used solely for target-row
    # exclusion. Target problem identities come exclusively from the frozen
    # target_problem_objects mapping and pinned public task projection.
    forbidden_target_solution_prs = {
        (str(target["repository"]), int(str(target["instance_id"]).rsplit("-", 1)[1]))
        for target in targets
    }
    for target, source, problem_contract in zip(targets, oracle_rows, problem_rows):
        target_id = str(target["target_id"])
        target_provenance_sha = canonical_sha256(
            {"target_id": target_id, "status": "TARGET_PROBLEM_CHRONOLOGY_UNKNOWN"}
        )
        target_instruction_sha = canonical_sha256(
            {"target_id": target_id, "status": "TARGET_PUBLIC_INSTRUCTION_UNKNOWN"}
        )
        candidate_rows: list[dict[str, Any]] = []
        try:
            target_created_at, target_provenance_sha, target_public_instruction = (
                _validate_oracle_target_chronology(
                    target,
                    target_index.get(target_id),
                    evidence_blobs,
                    problem_contract,
                )
            )
            target_instruction_sha = hashlib.sha256(
                target_public_instruction.encode("utf-8")
            ).hexdigest()
            repository = str(source["repository"])
            pull_number = int(source["pull_number"])
            if (repository, pull_number) in forbidden_target_solution_prs:
                raise SourceBankError(
                    "ORACLE_SOURCE_EQUALS_A_FROZEN_TARGET_SOLUTION_PR"
                )
            source_task_id = _oracle_source_task_id(repository, pull_number)
            entry = source_index.get(source_task_id)
            validated, merge_commit, verification_sha, base_commit, public_row = (
                _validate_oracle_source_entry(
                    entry,
                    expected_repository=repository,
                    expected_pull_number=pull_number,
                    target=target,
                    target_created_at=target_created_at,
                    evidence_blobs=evidence_blobs,
                )
            )
            diff_ref = entry["diff"]
            merged_diff = evidence_blobs[diff_ref["path"]].decode("utf-8")
            source_text = "\n\n".join(
                part for part in (public_row["title"].strip(), public_row["body"].strip()) if part
            )
            features = compile_source_features(source_text, merged_diff)
            source_row_sha = canonical_sha256(public_row)
            payload = _oracle_payload(
                source_task_id=source_task_id,
                repository=repository,
                source_row_sha256=source_row_sha,
                title=public_row["title"],
                body=public_row["body"],
                merged_diff=merged_diff,
                features=features,
            )
            payload_raw = canonical_bytes(payload)
            payload_sha = hashlib.sha256(payload_raw).hexdigest()
            payload_path = f"{PAYLOAD_DIRECTORY}/{payload_sha}.json"
            payloads[payload_path] = payload_raw
            memory_id = "dev-oracle-pr-" + hashlib.sha256(
                source_task_id.encode("utf-8")
            ).hexdigest()[:24]
            record = {
                "memory_id": memory_id,
                "source_task_id": source_task_id,
                "source_dataset_id": "PUBLIC_GITHUB_MERGED_PR",
                "source_dataset_revision": merge_commit,
                "source_row_sha256": source_row_sha,
                "source_repository": repository,
                "source_base_commit": base_commit,
                "source_commit": merge_commit,
                "source_timestamp": validated["available_at"],
                "bank_type": "ORG_SEMANTIC",
                "changed_paths": features["changed_paths"],
                "symbols": features["symbols"],
                "apis": features["apis"],
                "errors": features["errors"],
                "verified": True,
                "reviewed": True,
                "source_outcome": "passed",
                "source_fix_verification_signal": "PUBLIC_GITHUB_MERGED_PR_DIFF",
                "verification_evidence_sha256": verification_sha,
                "chronology_and_version_evidence_sha256": canonical_sha256(validated),
                "provenance_sha256": canonical_sha256(entry),
                "payload_sha256": payload_sha,
                "payload_path": payload_path,
                "permission_scope": "PUBLIC_READ",
                "tenant_scope": "BENCHMARK_ISOLATED",
                "repository_scope": "EXACT_SOURCE_AND_TARGET_REPOSITORY",
                "version_scope": "EXACT_SOURCE_COMMIT",
                "path_scope": "**",
                "quarantined": False,
                "target_derived": False,
            }
            records_by_id[memory_id] = record
            score = _rank_score(
                _target_projection(target_public_instruction), source_text, features
            )
            candidate_rows = [
                {
                    "memory_id": memory_id,
                    "source_task_id": source_task_id,
                    "score": score,
                }
            ]
        except (KeyError, TypeError, ValueError, SourceBankError) as exc:
            reason = str(exc) if isinstance(exc, SourceBankError) else "ORACLE_EVIDENCE_MALFORMED"
            rejection_counts[reason] += 1
            zero_targets.append(target_id)
        assignments.append(
            {
                "target_id": target_id,
                "target_repository": target["repository"],
                "target_problem_provenance_sha256": target_provenance_sha,
                "target_public_instruction_sha256": target_instruction_sha,
                "candidate_count": len(candidate_rows),
                "candidates": candidate_rows,
            }
        )
    if not records_by_id:
        raise SourceBankError("NO_VERIFIED_SOURCE_RECORDS")
    records = sorted(records_by_id.values(), key=lambda row: row["memory_id"])
    used_payloads = {
        record["payload_path"]: payloads[record["payload_path"]] for record in records
    }
    snapshot_material = {
        "records": records,
        "candidate_assignments": assignments,
        "zero_candidate_target_ids": zero_targets,
        "eligibility_rejection_histogram": dict(sorted(rejection_counts.items())),
    }
    bank = {
        "schema": "trimem/dev-activation-source-bank/1.0",
        "status": "FROZEN_VERIFIED_TARGET_DISJOINT",
        "scientific_role": "POST_DEV_DIAGNOSTIC_ORACLE_BANK_NOT_SELECTION_OR_HELDOUT_EVIDENCE",
        "read_only": True,
        "result_blind_construction": True,
        "same_logical_snapshot_for_C1_and_C2": True,
        "development_target_set_sha256": development["target_set_sha256"],
        "source_bank_plan_sha256": canonical_sha256(plan),
        "chronology_cache": {
            "path": CHRONOLOGY_PATH.as_posix(),
            "raw_sha256": chronology_raw_sha256,
        },
        "target_overlap_count": 0,
        "record_count": len(records),
        "records_sha256": canonical_sha256(records),
        "records": records,
        "covered_target_count": len(records),
        "zero_candidate_target_ids": zero_targets,
        "eligibility_rejection_histogram": dict(sorted(rejection_counts.items())),
        "candidate_assignments_sha256": canonical_sha256(assignments),
        "candidate_assignments": assignments,
        "snapshot_sha256": canonical_sha256(snapshot_material),
        "accounting": {
            "model_calls": 0,
            "paid_model_calls": 0,
            "grader_containers": 0,
            "official_grader_runs": 0,
        },
    }
    validate_source_bank(
        bank,
        development=development,
        payloads=used_payloads,
        plan=plan,
    )
    if payload_root is not None:
        _write_payloads(payload_root, used_payloads)
    return bank, used_payloads


def validate_source_bank(
    bank: Mapping[str, Any],
    *,
    development: Mapping[str, Any],
    payloads: Mapping[str, bytes] | None = None,
    plan: Mapping[str, Any] | None = None,
) -> None:
    if bank.get("schema") != "trimem/dev-activation-source-bank/1.0":
        raise SourceBankError("source-bank schema drift")
    expected_flags = {
        "status": "FROZEN_VERIFIED_TARGET_DISJOINT",
        "scientific_role": "POST_DEV_DIAGNOSTIC_ORACLE_BANK_NOT_SELECTION_OR_HELDOUT_EVIDENCE",
        "read_only": True,
        "result_blind_construction": True,
        "same_logical_snapshot_for_C1_and_C2": True,
        "target_overlap_count": 0,
    }
    if any(bank.get(key) != value for key, value in expected_flags.items()):
        raise SourceBankError("source-bank frozen safety/status fields drift")
    if bank.get("development_target_set_sha256") != development.get("target_set_sha256"):
        raise SourceBankError("source bank targets a different DEV snapshot")
    oracle_plan = (
        isinstance(plan, Mapping)
        and isinstance(plan.get("source_universe"), Mapping)
        and plan["source_universe"].get("mode")
        == "FROZEN_PUBLIC_GITHUB_ORACLE_SOURCE_PRS"
    )
    if plan is not None and bank.get("source_bank_plan_sha256") != canonical_sha256(plan):
        raise SourceBankError("source bank is not bound to the frozen source plan")
    chronology_binding = bank.get("chronology_cache")
    if (
        not isinstance(chronology_binding, dict)
        or chronology_binding.get("path") != CHRONOLOGY_PATH.as_posix()
    ):
        raise SourceBankError("source-bank chronology provenance reference drift")
    _require_sha(chronology_binding.get("raw_sha256"), "chronology cache raw hash")
    _assert_no_forbidden_target_keys(bank, "source-bank manifest")
    records = bank.get("records")
    assignments = bank.get("candidate_assignments")
    if not isinstance(records, list) or not records or not isinstance(assignments, list):
        raise SourceBankError("source-bank records/assignments are missing")
    if bank.get("record_count") != len(records) or bank.get("records_sha256") != canonical_sha256(records):
        raise SourceBankError("source-bank record count/hash drift")
    if bank.get("candidate_assignments_sha256") != canonical_sha256(assignments):
        raise SourceBankError("source-bank assignment hash drift")
    if bank.get("snapshot_sha256") != canonical_sha256(
        {
            "records": records,
            "candidate_assignments": assignments,
            "zero_candidate_target_ids": bank.get("zero_candidate_target_ids"),
            "eligibility_rejection_histogram": bank.get(
                "eligibility_rejection_histogram"
            ),
        }
    ):
        raise SourceBankError("source-bank snapshot hash drift")
    expected_record_fields = {
        "memory_id",
        "source_task_id",
        "source_dataset_id",
        "source_dataset_revision",
        "source_row_sha256",
        "source_repository",
        "source_base_commit",
        "source_commit",
        "source_timestamp",
        "bank_type",
        "changed_paths",
        "symbols",
        "apis",
        "errors",
        "verified",
        "reviewed",
        "source_outcome",
        "source_fix_verification_signal",
        "verification_evidence_sha256",
        "chronology_and_version_evidence_sha256",
        "provenance_sha256",
        "payload_sha256",
        "payload_path",
        "permission_scope",
        "tenant_scope",
        "repository_scope",
        "version_scope",
        "path_scope",
        "quarantined",
        "target_derived",
    }
    target_ids = {row["target_id"] for row in development["targets"]}
    target_instances = {row["instance_id"] for row in development["targets"]}
    by_memory: dict[str, dict[str, Any]] = {}
    for position, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != expected_record_fields:
            raise SourceBankError(f"source-bank record field drift at {position}")
        memory_id, source_task_id = record["memory_id"], record["source_task_id"]
        if not isinstance(memory_id, str) or not memory_id or memory_id in by_memory:
            raise SourceBankError(f"duplicate/invalid memory ID at {position}")
        if source_task_id in target_ids or any(
            source_task_id.endswith("--" + instance_id) for instance_id in target_instances
        ):
            raise SourceBankError(f"target-derived source record: {source_task_id}")
        if (
            record["verified"] is not True
            or record["reviewed"] is not True
            or record["source_outcome"] != "passed"
            or record["quarantined"] is not False
            or record["target_derived"] is not False
            or record["repository_scope"] != "EXACT_SOURCE_AND_TARGET_REPOSITORY"
            or record["bank_type"] != "ORG_SEMANTIC"
            or record["permission_scope"] != "PUBLIC_READ"
            or record["tenant_scope"] != "BENCHMARK_ISOLATED"
            or record["version_scope"] != "EXACT_SOURCE_COMMIT"
            or record["path_scope"] != "**"
        ):
            raise SourceBankError(f"unsafe source record: {memory_id}")
        if record["source_dataset_id"] == "PUBLIC_GITHUB_MERGED_PR":
            if (
                record["source_fix_verification_signal"]
                != "PUBLIC_GITHUB_MERGED_PR_DIFF"
                or record["source_dataset_revision"] != record["source_commit"]
            ):
                raise SourceBankError(f"GitHub oracle source identity drift: {memory_id}")
        elif record["source_fix_verification_signal"] != "UPSTREAM_MERGED_FIX_PATCH_EQUIVALENT":
            raise SourceBankError(f"benchmark source verification drift: {memory_id}")
        _require_hex40(record["source_dataset_revision"], "source dataset revision")
        _require_hex40(record["source_base_commit"], "source base commit")
        _require_hex40(record["source_commit"], "source fix commit")
        _timestamp(record["source_timestamp"], "source timestamp")
        for name in (
            "source_row_sha256",
            "verification_evidence_sha256",
            "chronology_and_version_evidence_sha256",
            "provenance_sha256",
            "payload_sha256",
        ):
            _require_sha(record[name], name)
        if not REPOSITORY.fullmatch(str(record["source_repository"])):
            raise SourceBankError(f"source repository malformed: {memory_id}")
        for name in ("changed_paths", "symbols", "apis", "errors"):
            values = record[name]
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value for value in values
            ) or values != sorted(set(values)):
                raise SourceBankError(f"non-canonical source feature {name}: {memory_id}")
        if not record["changed_paths"]:
            raise SourceBankError(f"source record has no changed paths: {memory_id}")
        payload_path = record["payload_path"]
        if (
            not isinstance(payload_path, str)
            or payload_path
            != f"{PAYLOAD_DIRECTORY}/{record['payload_sha256']}.json"
        ):
            raise SourceBankError(f"payload reference is not content-addressed: {memory_id}")
        if payloads is not None:
            raw = payloads.get(payload_path)
            if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != record["payload_sha256"]:
                raise SourceBankError(f"payload bytes missing or hash drift: {memory_id}")
            try:
                payload = json.loads(
                    raw.decode("utf-8"),
                    object_pairs_hook=_strict_pairs,
                    parse_constant=_reject_constant,
                )
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise SourceBankError(f"source payload is invalid: {memory_id}") from exc
            if (
                not isinstance(payload, dict)
                or payload.get("source_task_id") != source_task_id
                or payload.get("source_row_sha256") != record["source_row_sha256"]
                or payload.get("features")
                != {name: record[name] for name in ("changed_paths", "symbols", "apis", "errors")}
            ):
                raise SourceBankError(f"source payload/record mismatch: {memory_id}")
            _assert_no_forbidden_target_keys(payload, "source payload")
        by_memory[memory_id] = record

    expected_targets = [row["target_id"] for row in development["targets"]]
    if [row.get("target_id") for row in assignments if isinstance(row, Mapping)] != expected_targets:
        raise SourceBankError("candidate assignment targets/order drift")
    referenced: set[str] = set()
    observed_covered_target_count = 0
    observed_zero_candidate_targets: list[str] = []
    for assignment, target in zip(assignments, development["targets"]):
        expected_assignment_fields = {
            "target_id",
            "target_repository",
            "target_problem_provenance_sha256",
            "target_public_instruction_sha256",
            "candidate_count",
            "candidates",
        } if oracle_plan else {
            "target_id",
            "target_repository",
            "target_public_issue_provenance_sha256",
            "candidate_count",
            "candidates",
        }
        if not isinstance(assignment, dict) or set(assignment) != expected_assignment_fields:
            raise SourceBankError("candidate assignment field drift")
        if assignment["target_repository"] != target["repository"]:
            raise SourceBankError(f"candidate target repository drift: {target['target_id']}")
        if oracle_plan:
            _require_sha(
                assignment["target_problem_provenance_sha256"],
                "target problem provenance",
            )
            _require_sha(
                assignment["target_public_instruction_sha256"],
                "target runtime public instruction",
            )
        else:
            _require_sha(
                assignment["target_public_issue_provenance_sha256"],
                "target issue provenance",
            )
        candidates = assignment["candidates"]
        if (
            not isinstance(candidates, list)
            or not 0 <= len(candidates) <= TOP_K
            or assignment["candidate_count"] != len(candidates)
        ):
            raise SourceBankError(f"candidate coverage/count invalid: {target['target_id']}")
        if candidates:
            observed_covered_target_count += 1
        else:
            observed_zero_candidate_targets.append(target["target_id"])
        if candidates != sorted(candidates, key=_rank_key):
            raise SourceBankError(f"candidate deterministic order drift: {target['target_id']}")
        candidate_ids: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, dict) or set(candidate) != {
                "memory_id",
                "source_task_id",
                "score",
            }:
                raise SourceBankError("candidate row field drift")
            memory_id = candidate["memory_id"]
            record = by_memory.get(memory_id)
            if record is None or candidate["source_task_id"] != record["source_task_id"]:
                raise SourceBankError(f"candidate references unknown source: {memory_id}")
            if record["source_repository"] != target["repository"]:
                raise SourceBankError(f"cross-repository candidate: {memory_id}")
            if memory_id in candidate_ids:
                raise SourceBankError(f"duplicate candidate in assignment: {memory_id}")
            score = candidate["score"]
            expected_score_fields = {
                "errors_overlap",
                "apis_overlap",
                "symbols_overlap",
                "paths_overlap",
                "tokens_overlap",
            }
            if not isinstance(score, dict) or set(score) != expected_score_fields or any(
                type(value) is not int or value < 0 for value in score.values()
            ):
                raise SourceBankError(f"candidate score malformed: {memory_id}")
            candidate_ids.add(memory_id)
            referenced.add(memory_id)
    if referenced != set(by_memory):
        raise SourceBankError("source bank contains unreferenced or missing records")
    if not 1 <= observed_covered_target_count <= 12:
        raise SourceBankError("source bank has no verified candidate coverage")
    if bank.get("covered_target_count") != observed_covered_target_count:
        raise SourceBankError("source-bank covered-target count drift")
    if bank.get("zero_candidate_target_ids") != observed_zero_candidate_targets:
        raise SourceBankError("source-bank zero-candidate target inventory drift")
    if oracle_plan:
        oracle_rows = plan["source_universe"].get("oracle_source_prs")
        if not isinstance(oracle_rows, list) or len(oracle_rows) != len(assignments):
            raise SourceBankError("oracle plan mapping is incomplete")
        for assignment, oracle in zip(assignments, oracle_rows):
            expected_source = _oracle_source_task_id(
                str(oracle["repository"]), int(oracle["pull_number"])
            )
            for candidate in assignment["candidates"]:
                record = by_memory[candidate["memory_id"]]
                if (
                    candidate["source_task_id"] != expected_source
                    or record["source_task_id"] != expected_source
                    or record["source_dataset_id"] != "PUBLIC_GITHUB_MERGED_PR"
                    or record["source_fix_verification_signal"]
                    != "PUBLIC_GITHUB_MERGED_PR_DIFF"
                ):
                    raise SourceBankError(
                        f"source bank substitutes the frozen oracle PR: {assignment['target_id']}"
                    )
    rejection_histogram = bank.get("eligibility_rejection_histogram")
    if not isinstance(rejection_histogram, dict) or any(
        not isinstance(key, str)
        or not key
        or type(value) is not int
        or value < 0
        for key, value in rejection_histogram.items()
    ):
        raise SourceBankError("source-bank eligibility rejection histogram is malformed")
    accounting = bank.get("accounting")
    if accounting != {
        "model_calls": 0,
        "paid_model_calls": 0,
        "grader_containers": 0,
        "official_grader_runs": 0,
    }:
        raise SourceBankError("credential-free source-bank accounting drift")


def load_dataset_rows(path: Path, benchmark_id: str) -> list[dict[str, Any]]:
    if benchmark_id == "swebench_verified":
        try:
            import pyarrow.parquet as pq
        except (ImportError, ModuleNotFoundError) as exc:
            raise SourceBankError("pyarrow is required for the pinned SWE-bench parquet") from exc
        decoded = pq.read_table(path).to_pylist()
    else:
        decoded = []
        try:
            with path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    if not line.strip():
                        continue
                    row = json.loads(
                        line,
                        object_pairs_hook=_strict_pairs,
                        parse_constant=_reject_constant,
                    )
                    if not isinstance(row, dict):
                        raise SourceBankError(
                            f"dataset JSONL row is not an object: {benchmark_id}:{line_number}"
                        )
                    decoded.append(row)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SourceBankError(f"invalid pinned JSONL: {benchmark_id}") from exc
    if not decoded or any(not isinstance(row, dict) for row in decoded):
        raise SourceBankError(f"pinned dataset rows are empty/malformed: {benchmark_id}")
    return [dict(row) for row in decoded]


def verify_dataset_file(path: Path, spec: Mapping[str, Any]) -> None:
    if not path.is_file():
        raise SourceBankError(f"PINNED_DATASET_FILE_MISSING:{spec['benchmark_id']}")
    if path.stat().st_size != spec["bytes"] or file_sha256(path) != spec["sha256"]:
        raise SourceBankError(f"PINNED_DATASET_DIGEST_DRIFT:{spec['benchmark_id']}")


def _hf_dataset_path(spec: Mapping[str, Any]) -> Path:
    names = {
        "swebench_verified": "datasets--SWE-bench--SWE-bench_Verified",
        "multi_swe_bench_mini": "datasets--ByteDance-Seed--Multi-SWE-bench_mini",
        "multi_swe_bench_flash": "datasets--ByteDance-Seed--Multi-SWE-bench-flash",
    }
    return (
        Path.home()
        / ".cache"
        / "huggingface"
        / "hub"
        / names[str(spec["benchmark_id"])]
        / "snapshots"
        / str(spec["dataset_revision"])
        / str(spec["path"])
    )


def locate_dataset_file(spec: Mapping[str, Any], cache_roots: Sequence[Path]) -> Path | None:
    relative = Path(str(spec["path"]))
    basename = relative.name
    candidates = [_hf_dataset_path(spec)]
    for root in cache_roots:
        candidates.extend(
            [
                root / str(spec["benchmark_id"]) / str(spec["dataset_revision"]) / basename,
                root / str(spec["benchmark_id"]) / basename,
                root / relative,
            ]
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def load_committed_contracts(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    plan_path = root / PLAN_PATH
    development_path = root / "configs/trimem_v1/development_manifest.json"
    grader_path = root / "configs/trimem_v1/grader_lock.json"
    plan = strict_json_load(plan_path)
    development = strict_json_load(development_path)
    grader = strict_json_load(grader_path)
    _targets, specs = validate_plan_documents(
        plan,
        development,
        grader,
        development_raw_sha256=file_sha256(development_path),
        grader_lock_raw_sha256=file_sha256(grader_path),
    )
    return plan, development, grader, specs


def preflight(
    root: Path = ROOT,
    *,
    cache_roots: Sequence[Path] = (),
    chronology_path: Path | None = None,
) -> dict[str, Any]:
    plan, development, grader, specs = load_committed_contracts(root)
    source_mode = str(plan["source_universe"]["mode"])
    located: dict[str, str] = {}
    blockers: list[str] = []
    preview: dict[str, Any] = {}
    if source_mode != "FROZEN_PUBLIC_GITHUB_ORACLE_SOURCE_PRS":
        roots = tuple(path.resolve() for path in cache_roots) or (
            root / ".trimem-source-cache",
            Path(tempfile.gettempdir()) / "trimem-v1-source-cache",
        )
        for benchmark_id in REQUIRED_DATASETS:
            spec = specs[benchmark_id]
            path = locate_dataset_file(spec, roots)
            if path is None:
                blockers.append(f"PINNED_DATASET_FILE_MISSING:{benchmark_id}")
                continue
            try:
                verify_dataset_file(path, spec)
            except SourceBankError as exc:
                blockers.append(str(exc))
                continue
            located[benchmark_id] = str(path)
    chronology = chronology_path or root / CHRONOLOGY_PATH
    if not chronology.is_file():
        blockers.append("SOURCE_AND_TARGET_GITHUB_CHRONOLOGY_CACHE_MISSING")
    else:
        try:
            if chronology.is_symlink():
                raise SourceBankError("chronology cache must not be a symlink")
            cache = strict_json_load(chronology)
            _chronology_indexes(cache)
            evidence_blobs = evidence_blobs_from_cache(chronology, cache)
        except SourceBankError as exc:
            blockers.append(str(exc))
    if not blockers:
        try:
            if source_mode == "FROZEN_PUBLIC_GITHUB_ORACLE_SOURCE_PRS":
                bank, _payloads = build_oracle_source_bank(
                    plan,
                    development,
                    cache,
                    evidence_blobs,
                    chronology_raw_sha256=file_sha256(chronology),
                )
            else:
                rows = {
                    benchmark_id: load_dataset_rows(Path(located[benchmark_id]), benchmark_id)
                    for benchmark_id in REQUIRED_DATASETS
                }
                bank, _payloads = build_source_bank(
                    plan,
                    development,
                    grader,
                    rows,
                    cache,
                    chronology_raw_sha256=file_sha256(chronology),
                )
            preview = {
                "covered_target_count": bank["covered_target_count"],
                "zero_candidate_target_ids": bank["zero_candidate_target_ids"],
                "record_count": bank["record_count"],
                "snapshot_sha256": bank["snapshot_sha256"],
            }
        except CoverageError as exc:
            blockers.append(str(exc))
            preview = {
                "missing_targets": list(exc.missing_targets),
                "rejection_counts": exc.rejection_counts,
            }
        except SourceBankError as exc:
            blockers.append(str(exc))
    return {
        "schema": "trimem/dev-activation-source-bank-preflight/1.0",
        "status": "PASS" if not blockers else "BLOCKED_FAIL_CLOSED",
        "scientific_role": plan["scientific_role"],
        "source_mode": source_mode,
        "development_target_set_sha256": development["target_set_sha256"],
        "located_pinned_datasets": located,
        "chronology_cache_path": str(chronology),
        "blockers": sorted(set(blockers)),
        "build_preview": preview,
        "network_calls": 0,
        "model_calls": 0,
        "paid_model_calls": 0,
        "grader_containers": 0,
    }


def _parse_dataset_overrides(values: Sequence[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        benchmark_id, separator, path = value.partition("=")
        if not separator or benchmark_id not in REQUIRED_DATASETS or benchmark_id in result:
            raise SourceBankError(f"invalid/duplicate --dataset mapping: {value}")
        result[benchmark_id] = Path(path).resolve()
    return result


def _payloads_from_manifest(manifest_path: Path, bank: Mapping[str, Any]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    root = manifest_path.parent
    for record in bank.get("records", []):
        relative = record.get("payload_path") if isinstance(record, Mapping) else None
        if not isinstance(relative, str):
            raise SourceBankError("payload path missing from bank record")
        path = _confined_path(
            root,
            relative,
            label="manifest payload",
            must_exist=True,
        )
        try:
            result[relative] = path.read_bytes()
        except OSError as exc:
            raise SourceBankError(f"payload file missing: {relative}") from exc
    return result


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--cache-root", action="append", type=Path, default=[])
    preflight_parser.add_argument("--chronology-cache", type=Path)
    build = subparsers.add_parser("build")
    build.add_argument("--dataset", action="append", default=[])
    build.add_argument("--chronology-cache", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            result = preflight(
                cache_roots=args.cache_root,
                chronology_path=args.chronology_cache,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
            return 0 if result["status"] == "PASS" else 2

        plan, development, grader, specs = load_committed_contracts()
        if args.command == "validate":
            if args.manifest.is_symlink():
                raise SourceBankError("source-bank manifest must not be a symlink")
            manifest_path = args.manifest.absolute()
            bank = strict_json_load(manifest_path)
            validate_source_bank(
                bank,
                development=development,
                payloads=_payloads_from_manifest(manifest_path, bank),
                plan=plan,
            )
            result = {
                "status": "PASS",
                "record_count": bank["record_count"],
                "covered_target_count": bank["covered_target_count"],
                "snapshot_sha256": bank["snapshot_sha256"],
                "model_calls": 0,
                "paid_model_calls": 0,
                "grader_containers": 0,
            }
        else:
            source_mode = str(plan["source_universe"]["mode"])
            chronology_path = args.chronology_cache.absolute()
            if chronology_path.is_symlink():
                raise SourceBankError("chronology cache must not be a symlink")
            chronology = strict_json_load(chronology_path)
            output_path = args.output.absolute()
            if output_path.is_symlink():
                raise SourceBankError("source-bank output must not be a symlink")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if source_mode == "FROZEN_PUBLIC_GITHUB_ORACLE_SOURCE_PRS":
                if args.dataset:
                    raise SourceBankError("oracle build rejects unnecessary --dataset inputs")
                bank, _payloads = build_oracle_source_bank(
                    plan,
                    development,
                    chronology,
                    evidence_blobs_from_cache(chronology_path, chronology),
                    chronology_raw_sha256=file_sha256(chronology_path),
                    payload_root=output_path.parent,
                )
            else:
                overrides = _parse_dataset_overrides(args.dataset)
                if set(overrides) != set(REQUIRED_DATASETS):
                    raise SourceBankError(
                        "build requires one exact --dataset mapping per benchmark"
                    )
                rows: dict[str, list[dict[str, Any]]] = {}
                for benchmark_id in REQUIRED_DATASETS:
                    verify_dataset_file(overrides[benchmark_id], specs[benchmark_id])
                    rows[benchmark_id] = load_dataset_rows(
                        overrides[benchmark_id], benchmark_id
                    )
                bank, _payloads = build_source_bank(
                    plan,
                    development,
                    grader,
                    rows,
                    chronology,
                    chronology_raw_sha256=file_sha256(chronology_path),
                    payload_root=output_path.parent,
                )
            output_path.write_bytes(canonical_bytes(bank) + b"\n")
            result = {
                "status": "PASS",
                "manifest": str(output_path),
                "manifest_raw_sha256": file_sha256(output_path),
                "record_count": bank["record_count"],
                "covered_target_count": bank["covered_target_count"],
                "snapshot_sha256": bank["snapshot_sha256"],
                "model_calls": 0,
                "paid_model_calls": 0,
                "grader_containers": 0,
            }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except CoverageError as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED_FAIL_CLOSED",
                    "reason": str(exc),
                    "missing_targets": list(exc.missing_targets),
                    "rejection_counts": exc.rejection_counts,
                    "model_calls": 0,
                    "paid_model_calls": 0,
                    "grader_containers": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    except (OSError, SourceBankError) as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED_FAIL_CLOSED",
                    "reason": str(exc),
                    "model_calls": 0,
                    "paid_model_calls": 0,
                    "grader_containers": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
