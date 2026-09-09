"""Capture frozen public issue/PR evidence for the DEV activation oracle bank.

This utility is deliberately credential-free: it never reads a token, never
sends an Authorization header, and never invokes a model, benchmark reader, or
grader.  Successful response bodies are stored byte-for-byte under their SHA256
and reused on resume.  A failed/UNKNOWN candidate is recorded and capture
continues in the already-frozen target order.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence
import urllib.error
import urllib.request

from trimem_dev_activation_source_bank import (
    CHRONOLOGY_PATH,
    HEX40,
    ROOT,
    SourceBankError,
    _confined_path,
    _oracle_source_task_id,
    _source_base_commit,
    _source_instance_id,
    _source_repository,
    _strict_json_bytes,
    _timestamp,
    canonical_bytes,
    canonical_sha256,
    file_sha256,
    load_dataset_rows,
    load_committed_contracts,
    locate_dataset_file,
    parse_django_trac_ticket,
    public_issue_text,
    strict_json_load,
    verify_dataset_file,
)


JSON_ACCEPT = "application/vnd.github+json"
DIFF_ACCEPT = "application/vnd.github.v3.diff"
HTML_ACCEPT = "text/html"
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_DIFF_BYTES = 64 * 1024 * 1024
MAX_HTML_BYTES = 8 * 1024 * 1024
Fetch = Callable[[str, str], bytes]


class CaptureError(SourceBankError):
    """A public evidence response cannot satisfy the frozen contract."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _public_fetch(url: str, accept: str) -> bytes:
    github = url.startswith("https://api.github.com/repos/")
    django_trac = url.startswith("https://code.djangoproject.com/ticket/")
    if not (
        (github and accept in {JSON_ACCEPT, DIFF_ACCEPT})
        or (django_trac and accept == HTML_ACCEPT)
    ):
        raise CaptureError("NON_PUBLIC_GITHUB_URL")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": "trimem-dev-activation-public-evidence/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    # Deliberately use no Authorization header and read no environment variable.
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read(MAX_DIFF_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise CaptureError(f"GITHUB_HTTP_{exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CaptureError("GITHUB_NETWORK_FAILURE") from exc
    limit = (
        MAX_DIFF_BYTES
        if accept == DIFF_ACCEPT
        else MAX_HTML_BYTES
        if accept == HTML_ACCEPT
        else MAX_JSON_BYTES
    )
    if not raw or len(raw) > limit:
        raise CaptureError("GITHUB_RESPONSE_EMPTY_OR_OVERSIZE")
    return raw


def _max_timestamp(*values: Any) -> str:
    parsed = [(_timestamp(value, "captured GitHub timestamp"), str(value)) for value in values]
    return max(parsed, key=lambda item: item[0])[1]


def _reason(exc: BaseException) -> str:
    value = str(exc) if isinstance(exc, SourceBankError) else "CAPTURE_INTERNAL_FAILURE"
    normalized = re.sub(r"[^A-Z0-9_:-]", "_", value.upper())[:160]
    return normalized or "CAPTURE_UNKNOWN_FAILURE"


class _RawStore:
    def __init__(
        self,
        *,
        output_root: Path,
        previous: Mapping[str, Any] | None,
        fetcher: Fetch,
        observed_at: str,
    ) -> None:
        self.output_root = output_root
        self.fetcher = fetcher
        self.observed_at = observed_at
        self.network_requests = 0
        self.cache_hits = 0
        self._entries: dict[tuple[str, str], dict[str, Any]] = {}
        self._used: set[tuple[str, str]] = set()
        rows = previous.get("request_cache", []) if isinstance(previous, Mapping) else []
        if not isinstance(rows, list):
            raise CaptureError("PREVIOUS_REQUEST_CACHE_MALFORMED")
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "url",
                "accept",
                "observed_at",
                "raw_sha256",
                "path",
            }:
                raise CaptureError("PREVIOUS_REQUEST_CACHE_MALFORMED")
            key = (row["url"], row["accept"])
            if key in self._entries:
                raise CaptureError("PREVIOUS_REQUEST_CACHE_DUPLICATE")
            _timestamp(row["observed_at"], "cached request observed_at")
            sha = row["raw_sha256"]
            extension = (
                "diff"
                if row["accept"] == DIFF_ACCEPT
                else "html"
                if row["accept"] == HTML_ACCEPT
                else "json"
            )
            if (
                not isinstance(sha, str)
                or not re.fullmatch(r"[0-9a-f]{64}", sha)
                or row["path"] != f"github_raw/{sha}.{extension}"
            ):
                raise CaptureError("PREVIOUS_REQUEST_CACHE_HASH_DRIFT")
            path = _confined_path(
                output_root,
                row["path"],
                label="cached GitHub response",
                must_exist=True,
            )
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise CaptureError("PREVIOUS_REQUEST_CACHE_BYTES_DRIFT")
            self._entries[key] = dict(row)

    def get(self, url: str, accept: str) -> tuple[bytes, dict[str, Any]]:
        key = (url, accept)
        cached = self._entries.get(key)
        if cached is not None:
            path = _confined_path(
                self.output_root,
                cached["path"],
                label="cached GitHub response",
                must_exist=True,
            )
            self.cache_hits += 1
            self._used.add(key)
            return path.read_bytes(), dict(cached)
        raw = self.fetcher(url, accept)
        limit = (
            MAX_DIFF_BYTES
            if accept == DIFF_ACCEPT
            else MAX_HTML_BYTES
            if accept == HTML_ACCEPT
            else MAX_JSON_BYTES
        )
        if not isinstance(raw, bytes) or not raw or len(raw) > limit:
            raise CaptureError("GITHUB_RESPONSE_EMPTY_OR_OVERSIZE")
        if accept == JSON_ACCEPT:
            _strict_json_bytes(raw, "captured GitHub JSON")
        sha = hashlib.sha256(raw).hexdigest()
        extension = (
            "diff" if accept == DIFF_ACCEPT else "html" if accept == HTML_ACCEPT else "json"
        )
        relative = f"github_raw/{sha}.{extension}"
        path = _confined_path(
            self.output_root,
            relative,
            label="captured GitHub response",
            must_exist=False,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.is_symlink() or path.read_bytes() != raw:
                raise CaptureError("CONTENT_ADDRESSED_RESPONSE_COLLISION")
        else:
            _confined_path(
                self.output_root,
                relative,
                label="captured GitHub response",
                must_exist=False,
            ).write_bytes(raw)
        row = {
            "url": url,
            "accept": accept,
            "observed_at": self.observed_at,
            "raw_sha256": sha,
            "path": relative,
        }
        self._entries[key] = row
        self._used.add(key)
        self.network_requests += 1
        return raw, dict(row)

    def rows(self) -> list[dict[str, Any]]:
        return [self._entries[key] for key in sorted(self._used)]


def _json(store: _RawStore, url: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, reference = store.get(url, JSON_ACCEPT)
    return _strict_json_bytes(raw, url), reference


def _load_target_problem_projections(
    development: Mapping[str, Any],
    specs: Mapping[str, Mapping[str, Any]],
    dataset_paths: Mapping[str, Path],
) -> dict[str, dict[str, Any]]:
    """Load only the exact model-visible target instruction from pinned rows."""

    selected_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for benchmark_id, spec in specs.items():
        path = dataset_paths.get(benchmark_id) or locate_dataset_file(spec, ())
        if path is None:
            raise CaptureError(f"PINNED_DATASET_FILE_MISSING:{benchmark_id}")
        verify_dataset_file(path, spec)
        wanted = {
            str(target["instance_id"])
            for target in development["targets"]
            if target["benchmark_id"] == benchmark_id
        }
        for row in load_dataset_rows(path, benchmark_id):
            instance_id = _source_instance_id(benchmark_id, row)
            if instance_id not in wanted:
                continue
            key = (benchmark_id, instance_id)
            if key in selected_rows:
                raise CaptureError(f"DUPLICATE_PINNED_TARGET_ROW:{instance_id}")
            selected_rows[key] = row

    projections: dict[str, dict[str, Any]] = {}
    for target in development["targets"]:
        benchmark_id = str(target["benchmark_id"])
        instance_id = str(target["instance_id"])
        row = selected_rows.get((benchmark_id, instance_id))
        if row is None:
            raise CaptureError(f"PINNED_TARGET_ROW_MISSING:{instance_id}")
        if canonical_sha256(row) != target["source_row_sha256"]:
            raise CaptureError(f"PINNED_TARGET_ROW_HASH_DRIFT:{instance_id}")
        if (
            _source_repository(benchmark_id, row) != target["repository"]
            or _source_base_commit(benchmark_id, row) != target["base_commit"]
        ):
            raise CaptureError(f"PINNED_TARGET_ROW_IDENTITY_DRIFT:{instance_id}")
        instruction = public_issue_text(benchmark_id, row)
        if benchmark_id == "swebench_verified":
            problem_number = None
            problem_title = instruction.splitlines()[0].strip()
        else:
            issues = row.get("resolved_issues")
            if not isinstance(issues, list) or len(issues) != 1:
                raise CaptureError(f"TARGET_RESOLVED_ISSUE_CARDINALITY_UNKNOWN:{instance_id}")
            issue = issues[0]
            if not isinstance(issue, Mapping):
                raise CaptureError(f"TARGET_RESOLVED_ISSUE_MALFORMED:{instance_id}")
            problem_number = issue.get("number")
            problem_title = issue.get("title")
            if type(problem_number) is not int or not isinstance(problem_title, str):
                raise CaptureError(f"TARGET_RESOLVED_ISSUE_MALFORMED:{instance_id}")
        projection = {
            "target_id": target["target_id"],
            "source_row_sha256": target["source_row_sha256"],
            "public_instruction": instruction,
            "public_instruction_sha256": hashlib.sha256(
                instruction.encode("utf-8")
            ).hexdigest(),
            "problem_number_from_row": problem_number,
            "problem_title_from_row": problem_title,
        }
        projections[str(target["target_id"])] = projection
    if len(projections) != 12:
        raise CaptureError("PINNED_TARGET_PROJECTION_SET_INCOMPLETE")
    return projections


def _target_entry(
    store: _RawStore,
    target: Mapping[str, Any],
    projection: Mapping[str, Any],
    problem_contract: Mapping[str, Any],
) -> dict[str, Any]:
    repository = str(target["repository"])
    if (
        projection.get("target_id") != target.get("target_id")
        or projection.get("source_row_sha256") != target.get("source_row_sha256")
    ):
        raise CaptureError("TARGET_PUBLIC_INSTRUCTION_IDENTITY_DRIFT")
    instruction = projection.get("public_instruction")
    instruction_sha = projection.get("public_instruction_sha256")
    if (
        not isinstance(instruction, str)
        or not instruction.strip()
        or not isinstance(instruction_sha, str)
        or hashlib.sha256(instruction.encode("utf-8")).hexdigest() != instruction_sha
    ):
        raise CaptureError("TARGET_PUBLIC_INSTRUCTION_HASH_DRIFT")
    if problem_contract.get("target_id") != target.get("target_id"):
        raise CaptureError("TARGET_PROBLEM_CONTRACT_IDENTITY_DRIFT")
    tracker = problem_contract.get("tracker")
    number = problem_contract.get("issue_number")
    url = problem_contract.get("url")
    if type(number) is not int or not isinstance(url, str):
        raise CaptureError("TARGET_PROBLEM_CONTRACT_MALFORMED")
    if projection.get("problem_number_from_row") not in {None, number}:
        raise CaptureError("TARGET_PROBLEM_NUMBER_DIFFERS_FROM_PINNED_ROW")

    if tracker == "GITHUB_ISSUE":
        issue, ref = _json(store, url)
        if "pull_request" in issue:
            raise CaptureError("TARGET_PROBLEM_OBJECT_IS_PULL_REQUEST")
        if (
            issue.get("number") != number
            or issue.get("repository_url")
            != f"https://api.github.com/repos/{repository}"
            or issue.get("html_url")
            != f"https://github.com/{repository}/issues/{number}"
        ):
            raise CaptureError("TARGET_ISSUE_IDENTITY_DRIFT")
        created_at = issue.get("created_at")
        _timestamp(created_at, "target issue created_at")
        title, body = issue.get("title"), issue.get("body")
        if not isinstance(title, str) or not title.strip() or not (
            body is None or isinstance(body, str)
        ):
            raise CaptureError("TARGET_ISSUE_PUBLIC_TEXT_UNKNOWN")
        if title.strip() != projection.get("problem_title_from_row"):
            raise CaptureError("TARGET_ISSUE_TITLE_DIFFERS_FROM_PINNED_ROW")
    elif tracker == "DJANGO_TRAC":
        raw, ref = store.get(url, HTML_ACCEPT)
        issue = parse_django_trac_ticket(raw, expected_number=number)
        created_at = issue["created_at"]
        if issue["title"] != projection.get("problem_title_from_row"):
            raise CaptureError("TARGET_TRAC_TITLE_DIFFERS_FROM_PINNED_ROW")
    else:
        raise CaptureError("TARGET_PROBLEM_TRACKER_UNSUPPORTED")
    return {
        "target_id": target["target_id"],
        "source_row_sha256": target["source_row_sha256"],
        "repository": repository,
        "base_commit": target["base_commit"],
        "public_instruction": instruction,
        "public_instruction_sha256": instruction_sha,
        "problem_object": {
            "tracker": tracker,
            "issue_number": number,
            "url": url,
            "first_published_at": created_at,
            "observed_at": ref["observed_at"],
            "raw_sha256": ref["raw_sha256"],
            "path": ref["path"],
        },
    }


def _source_entry(
    store: _RawStore,
    *,
    source: Mapping[str, Any],
    target: Mapping[str, Any],
) -> dict[str, Any]:
    repository = str(source["repository"])
    pull_number = int(source["pull_number"])
    pull_url = f"https://api.github.com/repos/{repository}/pulls/{pull_number}"
    pull, pull_ref = _json(store, pull_url)
    if (
        pull.get("number") != pull_number
        or not isinstance(pull.get("title"), str)
        or not pull["title"].strip()
        or not (pull.get("body") is None or isinstance(pull.get("body"), str))
        or not isinstance(pull.get("html_url"), str)
        or pull["html_url"] != f"https://github.com/{repository}/pull/{pull_number}"
        or not isinstance(pull.get("base"), Mapping)
        or not isinstance(pull["base"].get("repo"), Mapping)
        or pull["base"]["repo"].get("full_name") != repository
    ):
        raise CaptureError("SOURCE_PR_IDENTITY_DRIFT")
    base_commit = pull["base"].get("sha")
    merge_commit = pull.get("merge_commit_sha")
    if not isinstance(base_commit, str) or not HEX40.fullmatch(base_commit):
        raise CaptureError("SOURCE_BASE_COMMIT_UNKNOWN")
    if not isinstance(merge_commit, str) or not HEX40.fullmatch(merge_commit):
        raise CaptureError("SOURCE_MERGE_COMMIT_UNKNOWN")
    merged_at, closed_at = pull.get("merged_at"), pull.get("closed_at")
    _timestamp(merged_at, "source PR merged_at")
    _timestamp(closed_at, "source PR closed_at")

    diff_raw, diff_ref = store.get(pull_url, DIFF_ACCEPT)
    try:
        diff_raw.decode("utf-8")
    except UnicodeError as exc:
        raise CaptureError("SOURCE_DIFF_NOT_UTF8") from exc
    commit_url = f"https://api.github.com/repos/{repository}/commits/{merge_commit}"
    commit, commit_ref = _json(store, commit_url)
    if commit.get("sha") != merge_commit:
        raise CaptureError("SOURCE_COMMIT_IDENTITY_DRIFT")
    author_at = commit.get("commit", {}).get("author", {}).get("date")
    committer_at = commit.get("commit", {}).get("committer", {}).get("date")
    public_timestamp = _max_timestamp(author_at, committer_at)

    target_base = str(target["base_commit"])
    compare_url = (
        f"https://api.github.com/repos/{repository}/compare/"
        f"{merge_commit}...{target_base}"
    )
    compare, compare_ref = _json(store, compare_url)
    if (
        compare.get("status") not in {"ahead", "identical"}
        or type(compare.get("ahead_by")) is not int
        or compare["ahead_by"] < 0
        or compare.get("behind_by") != 0
        or compare.get("base_commit", {}).get("sha") != merge_commit
    ):
        raise CaptureError("FIX_COMMIT_NOT_ANCESTOR_OF_TARGET_BASE")

    public_row = {
        "schema": "trimem/public-github-merged-pr-source-row/1.0",
        "repository": repository,
        "pull_number": pull_number,
        "html_url": pull["html_url"],
        "title": pull["title"],
        "body": pull.get("body") or "",
        "base_commit": base_commit,
        "merge_commit_sha": merge_commit,
        "merged_at": merged_at,
        "diff_sha256": diff_ref["raw_sha256"],
    }
    row_sha = canonical_sha256(public_row)
    verification_sha = canonical_sha256(
        {
            "signal": "PUBLIC_GITHUB_MERGED_PR_DIFF",
            "source_row_sha256": row_sha,
            "diff_sha256": diff_ref["raw_sha256"],
            "fix_pr_raw_sha256": pull_ref["raw_sha256"],
            "fix_commit_raw_sha256": commit_ref["raw_sha256"],
        }
    )
    ancestry_sha = canonical_sha256(
        {
            "target_id": target["target_id"],
            "target_base_commit": target_base,
            "fix_commit_sha": merge_commit,
            "raw_sha256": compare_ref["raw_sha256"],
            "status": "FIX_COMMIT_IS_ANCESTOR_OF_TARGET_BASE",
            "ahead_by": compare["ahead_by"],
            "behind_by": compare["behind_by"],
        }
    )
    verification_observed = _max_timestamp(
        pull_ref["observed_at"], diff_ref["observed_at"], commit_ref["observed_at"]
    )
    source_task_id = _oracle_source_task_id(repository, pull_number)
    return {
        "source_task_id": source_task_id,
        "source_row_sha256": row_sha,
        "repository": repository,
        "pull_number": pull_number,
        "source_public_row": public_row,
        "diff": {
            "url": pull_url,
            "observed_at": diff_ref["observed_at"],
            "raw_sha256": diff_ref["raw_sha256"],
            "path": diff_ref["path"],
        },
        "fix_pr": {
            "url": pull_url,
            "merged_at": merged_at,
            "observed_at": pull_ref["observed_at"],
            "raw_sha256": pull_ref["raw_sha256"],
            "path": pull_ref["path"],
            "merge_commit_sha": merge_commit,
        },
        # A pull request is also the source issue; the same immutable raw PR JSON
        # supplies its independently checked closed_at field without an extra call.
        "source_issue": {
            "url": pull_url,
            "closed_at": closed_at,
            "observed_at": pull_ref["observed_at"],
            "raw_sha256": pull_ref["raw_sha256"],
            "path": pull_ref["path"],
        },
        "fix_commit": {
            "url": commit_url,
            "public_timestamp": public_timestamp,
            "observed_at": commit_ref["observed_at"],
            "raw_sha256": commit_ref["raw_sha256"],
            "path": commit_ref["path"],
            "sha": merge_commit,
        },
        "source_fix_verification": {
            "status": "PUBLIC_GITHUB_MERGED_PR_DIFF",
            "observed_at": verification_observed,
            "evidence_sha256": verification_sha,
            "diff_sha256": diff_ref["raw_sha256"],
        },
        "ancestry": [
            {
                "target_id": target["target_id"],
                "target_base_commit": target_base,
                "fix_commit_sha": merge_commit,
                "status": "FIX_COMMIT_IS_ANCESTOR_OF_TARGET_BASE",
                "ahead_by": compare["ahead_by"],
                "behind_by": compare["behind_by"],
                "observed_at": compare_ref["observed_at"],
                "evidence_sha256": ancestry_sha,
                "url": compare_url,
                "raw_sha256": compare_ref["raw_sha256"],
                "path": compare_ref["path"],
            }
        ],
    }


def capture_public_evidence(
    *,
    root: Path = ROOT,
    output_path: Path | None = None,
    dataset_paths: Mapping[str, Path] | None = None,
    fetcher: Fetch = _public_fetch,
    observed_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    plan, development, _grader, specs = load_committed_contracts(root)
    if plan["source_universe"]["mode"] != "FROZEN_PUBLIC_GITHUB_ORACLE_SOURCE_PRS":
        raise CaptureError("PUBLIC_ORACLE_CAPTURE_PLAN_NOT_ACTIVE")
    if dataset_paths is not None and not set(dataset_paths).issubset(specs):
        raise CaptureError("DATASET_OVERRIDE_BENCHMARK_UNKNOWN")
    target_projections = _load_target_problem_projections(
        development,
        specs,
        dataset_paths or {},
    )
    output = (output_path or root / CHRONOLOGY_PATH).absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink() or output.parent.is_symlink():
        raise CaptureError("CAPTURE_OUTPUT_SYMLINK_REJECTED")
    previous: dict[str, Any] | None = None
    if output.is_file():
        previous = strict_json_load(output)
        if (
            previous.get("schema")
            != "trimem/dev-activation-chronology-cache/1.0"
            or previous.get("status") != "FROZEN_CACHED_PUBLIC_EVIDENCE"
            or previous.get("capture_policy")
            != (
                "PINNED_DATASETS_PLUS_PUBLIC_GITHUB_AND_DJANGO_TRAC_"
                "NO_AUTHORIZATION_HEADER"
            )
            or previous.get("source_bank_plan_sha256") != canonical_sha256(plan)
            or previous.get("development_target_set_sha256")
            != development["target_set_sha256"]
        ):
            raise CaptureError("PREVIOUS_CAPTURE_FROZEN_BINDING_DRIFT")
    timestamp = observed_at or _utc_now()
    _timestamp(timestamp, "capture observed_at")
    store = _RawStore(
        output_root=output.parent,
        previous=previous,
        fetcher=fetcher,
        observed_at=timestamp,
    )
    targets: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    rejections: list[dict[str, str]] = []
    oracle_rows = plan["source_universe"]["oracle_source_prs"]
    problem_rows = plan["source_universe"]["target_problem_objects"]
    for target, source, problem_contract in zip(
        development["targets"], oracle_rows, problem_rows
    ):
        target_id = str(target["target_id"])
        source_task_id = _oracle_source_task_id(
            str(source["repository"]), int(source["pull_number"])
        )
        try:
            targets.append(
                _target_entry(
                    store,
                    target,
                    target_projections[target_id],
                    problem_contract,
                )
            )
        except (KeyError, TypeError, ValueError, SourceBankError) as exc:
            rejections.append(
                {
                    "target_id": target_id,
                    "source_task_id": source_task_id,
                    "phase": "TARGET_PUBLIC_EVIDENCE",
                    "reason_code": _reason(exc),
                }
            )
        try:
            sources.append(_source_entry(store, source=source, target=target))
        except (KeyError, TypeError, ValueError, SourceBankError) as exc:
            rejections.append(
                {
                    "target_id": target_id,
                    "source_task_id": source_task_id,
                    "phase": "SOURCE_PUBLIC_EVIDENCE",
                    "reason_code": _reason(exc),
                }
            )
    cache = {
        "schema": "trimem/dev-activation-chronology-cache/1.0",
        "status": "FROZEN_CACHED_PUBLIC_EVIDENCE",
        "diagnostic_id": plan["diagnostic_id"],
        "scientific_role": plan["scientific_role"],
        "source_bank_plan_sha256": canonical_sha256(plan),
        "development_target_set_sha256": development["target_set_sha256"],
        "capture_policy": (
            "PINNED_DATASETS_PLUS_PUBLIC_GITHUB_AND_DJANGO_TRAC_"
            "NO_AUTHORIZATION_HEADER"
        ),
        "request_cache": store.rows(),
        "sources": sources,
        "targets": targets,
        "rejections": rejections,
        "coverage": {
            "source_entries": len(sources),
            "target_entries": len(targets),
            "frozen_target_count": 12,
        },
        "accounting": {
            "public_evidence_responses": len(store.rows()),
            "public_github_responses": sum(
                1
                for row in store.rows()
                if row["url"].startswith("https://api.github.com/repos/")
            ),
            "public_django_trac_responses": sum(
                1
                for row in store.rows()
                if row["url"].startswith("https://code.djangoproject.com/ticket/")
            ),
            "capture_rejections": len(rejections),
            "model_calls": 0,
            "paid_model_calls": 0,
            "grader_containers": 0,
            "official_grader_runs": 0,
        },
    }
    temporary = output.with_name(output.name + ".tmp")
    if temporary.is_symlink():
        raise CaptureError("CAPTURE_TEMP_SYMLINK_REJECTED")
    temporary.write_bytes(canonical_bytes(cache) + b"\n")
    temporary.replace(output)
    return cache, {
        "network_requests": store.network_requests,
        "cache_hits": store.cache_hits,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / CHRONOLOGY_PATH)
    parser.add_argument(
        "--dataset",
        action="append",
        default=[],
        help="optional benchmark_id=/exact/pinned/file override",
    )
    args = parser.parse_args(argv)
    try:
        dataset_paths: dict[str, Path] = {}
        for value in args.dataset:
            benchmark_id, separator, path = value.partition("=")
            if (
                not separator
                or not benchmark_id
                or benchmark_id in dataset_paths
                or not path
            ):
                raise CaptureError("DATASET_OVERRIDE_MALFORMED_OR_DUPLICATED")
            dataset_paths[benchmark_id] = Path(path).resolve()
        cache, invocation = capture_public_evidence(
            output_path=args.output,
            dataset_paths=dataset_paths,
        )
    except (OSError, SourceBankError) as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED_FAIL_CLOSED",
                    "reason": _reason(exc),
                    "model_calls": 0,
                    "paid_model_calls": 0,
                    "grader_containers": 0,
                },
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "status": cache["status"],
                "source_entries": len(cache["sources"]),
                "target_entries": len(cache["targets"]),
                "rejections": len(cache["rejections"]),
                **invocation,
                "model_calls": 0,
                "paid_model_calls": 0,
                "grader_containers": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
