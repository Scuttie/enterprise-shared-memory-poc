#!/usr/bin/env python3
"""Recover R23 chronology evidence from the unauthenticated GitHub REST API.

The SWE-bench instance suffix is the fix pull-request number.  This program
does not trust that convention by itself: a pull response is accepted only
when its repository, number, base commit, and created timestamp all match the
committed R23 static audit.  Every HTTP response is retained verbatim and
hashed.  Recovery is deterministic and resumable, and an unresolved or
ambiguous timestamp never creates an eligibility edge.

No Docker, model, credential, or paid endpoint is used.  In particular this
module intentionally never reads GITHUB_TOKEN or constructs an Authorization
header.  The unauthenticated core limit is normally 60 requests/hour, so pull
metadata is completed before lower-priority commit and linked-issue fallbacks.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


UNKNOWN = "UNKNOWN"
SCHEMA_VERSION = "r23-b0.1-timestamp-cache-v1"
GRAPH_SCHEMA_VERSION = "r23-b0.1-chronology-graph-v1"
API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"
USER_AGENT = "esm-r23-b0.1-credential-free"
DEFAULT_REVISION = "78f471bf655a3137b2e8a75af1501690ec009ec3"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

_CLOSING_REFERENCE = re.compile(
    r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?[ \t]+"
    r"(?:https://github\.com/(?P<url_repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/"
    r"|(?:(?P<qualified_repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#)"
    r"(?P<number>[1-9][0-9]*)"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_bytes(value))


def deterministic_gzip(payload: bytes) -> bytes:
    """Cross-run stable gzip stream (no filename, fixed mtime, level 9)."""

    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, compresslevel=9, mtime=0) as handle:
        handle.write(payload)
    return buffer.getvalue()


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or value == UNKNOWN:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def is_timestamp(value: Any) -> bool:
    return parse_timestamp(value) is not None


def pull_number(instance_id: str, repository: str) -> int:
    prefix = repository.replace("/", "__") + "-"
    if not instance_id.startswith(prefix):
        raise ValueError(f"instance/repository mismatch: {instance_id!r}, {repository!r}")
    suffix = instance_id[len(prefix) :]
    if not suffix.isdigit() or int(suffix) <= 0:
        raise ValueError(f"instance has no positive pull number: {instance_id!r}")
    return int(suffix)


def github_url(repository: str, endpoint: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError(f"unsafe GitHub repository: {repository!r}")
    if not endpoint.startswith("/") or ".." in endpoint:
        raise ValueError(f"unsafe GitHub endpoint: {endpoint!r}")
    quoted_repo = "/".join(urllib.parse.quote(part, safe="") for part in repository.split("/"))
    url = f"{API_ROOT}/repos/{quoted_repo}{endpoint}"
    if not url.startswith(API_ROOT + "/repos/"):
        raise ValueError("GitHub API allow-list failure")
    return url


def extract_linked_issues(body: Any, repository: str, fix_pr_number: int) -> list[int]:
    """Return same-repository issues named by GitHub closing-keyword syntax.

    Cross-repository references and a self-reference to the pull request are
    deliberately ignored.  Plain ``#123`` mentions are not closure evidence.
    """

    if not isinstance(body, str):
        return []
    found: set[int] = set()
    for match in _CLOSING_REFERENCE.finditer(body):
        named_repo = match.group("url_repo") or match.group("qualified_repo")
        if named_repo is not None and named_repo.casefold() != repository.casefold():
            continue
        number = int(match.group("number"))
        if number != fix_pr_number:
            found.add(number)
    return sorted(found)


def _blank_entry(instance_id: str, audit: Mapping[str, Any]) -> dict[str, Any]:
    repository = str(audit["repository"])
    number = pull_number(instance_id, repository)
    return {
        "instance_id": instance_id,
        "repository": repository,
        "fix_pr_number": number,
        "benchmark_created_at": audit.get("issue_created_at", UNKNOWN),
        "benchmark_created_at_semantics": "FIX_PR_CREATED_AT",
        "base_commit": audit["base_commit"],
        "fix_pr_created_at": UNKNOWN,
        "fix_pr_closed_at": UNKNOWN,
        "fix_pr_merge_at": UNKNOWN,
        "fix_pr_merge_commit_sha": UNKNOWN,
        "fix_pr_head_sha": UNKNOWN,
        "fix_first_commit_at": UNKNOWN,
        "fix_first_commit_raw_committer_at": UNKNOWN,
        "fix_last_commit_raw_committer_at": UNKNOWN,
        "fix_commit_public_at": UNKNOWN,
        "fix_first_commit_authored_at": UNKNOWN,
        "linked_issue_numbers": [],
        "linked_issue_created_at": UNKNOWN,
        "issue_close_at": UNKNOWN,
        "source_available_at": UNKNOWN,
        "source_available_at_basis": UNKNOWN,
        "provenance_status": "PENDING",
        "timestamp_status": UNKNOWN,
        "unknown_reasons": ["PULL_METADATA_NOT_QUERIED"],
        "queries": {"pull": [], "commits": [], "issues": {}},
    }


def initialize_cache(
    audit: Mapping[str, Any],
    benchmark: Mapping[str, Any],
    existing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    instances = audit.get("instances")
    if not isinstance(instances, Mapping) or len(instances) != 500:
        raise ValueError("R23 static audit must contain exactly 500 instances")
    expected_ids = set(instances)

    if existing and existing.get("schema_version") == SCHEMA_VERSION:
        cache = dict(existing)
        old_entries = existing.get("entries")
        if not isinstance(old_entries, Mapping) or set(old_entries) != expected_ids:
            raise ValueError("timestamp cache instance set differs from committed static audit")
        entries = {key: dict(old_entries[key]) for key in sorted(expected_ids)}
        for key, entry in entries.items():
            expected = _blank_entry(key, instances[key])
            for identity in ("instance_id", "repository", "fix_pr_number", "base_commit"):
                if entry.get(identity) != expected[identity]:
                    raise ValueError(f"timestamp cache identity drift for {key}: {identity}")
            # Migrate the first five pre-correction commit observations.  Their
            # old value was the raw committer date; retain it as provenance and
            # replace the availability field with the conservative public bound.
            if "fix_first_commit_raw_committer_at" not in entry and is_timestamp(
                entry.get("fix_first_commit_at")
            ):
                raw = entry["fix_first_commit_at"]
                entry["fix_first_commit_raw_committer_at"] = raw
                created = entry.get("fix_pr_created_at")
                entry["fix_first_commit_at"] = (
                    max((raw, created), key=lambda value: parse_timestamp(value))
                    if is_timestamp(created)
                    else UNKNOWN
                )
            for field, default in expected.items():
                entry.setdefault(field, default)
        cache["entries"] = entries
    else:
        # The B0 cache was a flat {instance: {created_at, UNKNOWN}} placeholder.
        # It carries no external evidence, so migration only reuses its known
        # benchmark timestamp after checking it against the static audit.
        if existing:
            for key in expected_ids:
                old = existing.get(key)
                if old is not None and old.get("issue_created_at") != instances[key].get("issue_created_at"):
                    raise ValueError(f"legacy timestamp cache mismatch for {key}")
        cache = {
            "schema_version": SCHEMA_VERSION,
            "experiment": "R23-B0.1 credential-free timestamp recovery",
            "entries": {key: _blank_entry(key, instances[key]) for key in sorted(expected_ids)},
        }

    cache.setdefault("bulk_pull_pages", {})
    if "last_network_run" not in cache and cache.get("last_run", {}).get("requests_made", 0) > 0:
        cache["last_network_run"] = dict(cache["last_run"])

    cache.update(
        {
            "dataset_id": benchmark.get("dataset_id"),
            "dataset_revision_sha": benchmark.get("revision_sha"),
            "row_count": len(expected_ids),
            "api": {
                "root": API_ROOT,
                "version": API_VERSION,
                "authentication": "NONE",
                "credential_environment_read": False,
            },
            "instance_identity_rule": (
                "instance_id suffix is the fix PR number; accept only after GitHub pull repository, "
                "number, base.sha, and created_at match the committed audit"
            ),
            "source_availability_precedence": [
                "FIX_PR_MERGED_AT",
                "FIX_COMMIT_PUBLIC_AT_CONSERVATIVE",
                "LINKED_ISSUE_CLOSED_AT",
            ],
            "unknown_policy": "FAIL_CLOSED_NO_CHRONOLOGICAL_EDGE",
        }
    )
    recompute_cache(cache)
    return cache


def _known_or_unknown(value: Any) -> str:
    return value if is_timestamp(value) else UNKNOWN


def recompute_entry(entry: dict[str, Any]) -> None:
    reasons: list[str] = []
    if entry.get("provenance_status") != "CONFIRMED":
        reasons.append("FIX_PR_PROVENANCE_NOT_CONFIRMED")

    merge_at = _known_or_unknown(entry.get("fix_pr_merge_at"))
    commit_at = _known_or_unknown(entry.get("fix_commit_public_at"))
    issue_at = _known_or_unknown(entry.get("issue_close_at"))
    if entry.get("provenance_status") == "CONFIRMED" and merge_at != UNKNOWN:
        entry["source_available_at"] = merge_at
        entry["source_available_at_basis"] = "FIX_PR_MERGED_AT"
    elif entry.get("provenance_status") == "CONFIRMED" and commit_at != UNKNOWN:
        entry["source_available_at"] = commit_at
        entry["source_available_at_basis"] = "FIX_COMMIT_PUBLIC_AT_CONSERVATIVE"
    elif entry.get("provenance_status") == "CONFIRMED" and issue_at != UNKNOWN:
        entry["source_available_at"] = issue_at
        entry["source_available_at_basis"] = "LINKED_ISSUE_CLOSED_AT"
    else:
        entry["source_available_at"] = UNKNOWN
        entry["source_available_at_basis"] = UNKNOWN
        reasons.append("NO_CONFIRMED_SOURCE_AVAILABILITY_TIMESTAMP")

    pull_attempts = entry.get("queries", {}).get("pull", [])
    if not pull_attempts:
        reasons.append("PULL_METADATA_NOT_QUERIED")
    elif entry.get("provenance_status") != "CONFIRMED":
        reasons.append("PULL_METADATA_INVALID_OR_UNAVAILABLE")

    entry["timestamp_status"] = (
        "CONFIRMED" if entry["source_available_at"] != UNKNOWN else UNKNOWN
    )
    entry["unknown_reasons"] = sorted(set(reasons))


def recompute_cache(cache: dict[str, Any]) -> None:
    entries = cache["entries"]
    for entry in entries.values():
        recompute_entry(entry)
    fields = (
        "benchmark_created_at",
        "fix_pr_created_at",
        "fix_pr_merge_at",
        "fix_first_commit_at",
        "fix_commit_public_at",
        "issue_close_at",
        "linked_issue_created_at",
        "source_available_at",
    )
    coverage = {f"{field}_known": sum(is_timestamp(e.get(field)) for e in entries.values()) for field in fields}
    coverage.update(
        {
            "total": len(entries),
            "fix_pr_provenance_confirmed": sum(
                e.get("provenance_status") == "CONFIRMED" for e in entries.values()
            ),
            "source_available_at_unknown": sum(
                e.get("source_available_at") == UNKNOWN for e in entries.values()
            ),
        }
    )
    cache["coverage"] = coverage
    cache["updated_at_utc"] = utc_now()


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    body: bytes
    headers: Mapping[str, str]
    queried_at_utc: str


class GitHubREST:
    """Tiny allow-listed, deliberately unauthenticated GitHub REST client."""

    def __init__(self, timeout_seconds: float = 30.0):
        self.timeout_seconds = timeout_seconds

    def __call__(self, url: str) -> Response:
        if not url.startswith(API_ROOT + "/repos/"):
            raise ValueError(f"refusing non-GitHub-REST URL: {url}")
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": USER_AGENT,
            },
            method="GET",
        )
        queried_at = utc_now()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as result:
                body = result.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise RuntimeError("GitHub response exceeded fail-closed size limit")
                final_url = result.geturl()
                if not final_url.startswith(API_ROOT + "/"):
                    raise RuntimeError(f"GitHub API redirected outside allow-list: {final_url}")
                return Response(final_url, result.status, body, dict(result.headers.items()), queried_at)
        except urllib.error.HTTPError as error:
            body = error.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                body = body[:MAX_RESPONSE_BYTES]
            return Response(error.geturl(), error.code, body, dict(error.headers.items()), queried_at)


def _selected_headers(headers: Mapping[str, str]) -> dict[str, str]:
    lowered = {key.casefold(): str(value) for key, value in headers.items()}
    allowed = (
        "content-type",
        "date",
        "etag",
        "last-modified",
        "link",
        "retry-after",
        "x-github-api-version-selected",
        "x-github-media-type",
        "x-github-request-id",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "x-ratelimit-resource",
        "x-ratelimit-used",
    )
    return {key: lowered[key] for key in allowed if key in lowered}


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raise ValueError(f"raw evidence path must be under repository root: {path}") from None


def retain_response(
    response: Response,
    raw_path: Path,
    root: Path,
    query_kind: str,
) -> dict[str, Any]:
    compressed_path = Path(str(raw_path) + ".gz") if raw_path.suffix != ".gz" else raw_path
    compressed = deterministic_gzip(response.body)
    atomic_write_bytes(compressed_path, compressed)
    return {
        "query_kind": query_kind,
        "url": response.url,
        "queried_at_utc": response.queried_at_utc,
        "http_status": response.status,
        "compressed_path": _relative(compressed_path, root),
        "compressed_sha256": sha256_bytes(compressed),
        "compressed_bytes": len(compressed),
        "uncompressed_response_sha256": sha256_bytes(response.body),
        "uncompressed_response_bytes": len(response.body),
        "compression": "gzip-level-9-mtime-0-no-filename",
        "headers": _selected_headers(response.headers),
        "authentication": "NONE",
    }


def load_attempt_body(attempt: Mapping[str, Any], root: Path) -> bytes:
    path_value = attempt.get("compressed_path")
    if not isinstance(path_value, str):
        raise ValueError("timestamp evidence has no compressed_path")
    path = (root / path_value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        raise ValueError(f"compressed evidence escaped repository root: {path_value}") from None
    compressed = path.read_bytes()
    if len(compressed) != attempt.get("compressed_bytes") or sha256_bytes(compressed) != attempt.get(
        "compressed_sha256"
    ):
        raise ValueError(f"compressed evidence integrity failure: {path_value}")
    try:
        payload = gzip.decompress(compressed)
    except (OSError, EOFError) as error:
        raise ValueError(f"compressed evidence cannot be decoded: {path_value}") from error
    if len(payload) != attempt.get("uncompressed_response_bytes") or sha256_bytes(payload) != attempt.get(
        "uncompressed_response_sha256"
    ):
        raise ValueError(f"uncompressed evidence integrity failure: {path_value}")
    return payload


def compress_legacy_evidence(cache: dict[str, Any], root: Path, raw_dir: Path) -> list[Path]:
    """Stage deterministic gzip replacements for this script's plain bodies.

    The caller persists the rewritten cache before unlinking the returned plain
    paths, so interruption cannot leave a committed reference without a body.
    """

    legacy_paths: set[Path] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            legacy = value.get("raw_body_path")
            if isinstance(legacy, str):
                path = (root / legacy).resolve()
                try:
                    path.relative_to(raw_dir.resolve())
                except ValueError:
                    raise ValueError(f"refusing to migrate evidence outside timestamp_raw: {legacy}") from None
                payload = path.read_bytes()
                if len(payload) != value.get("response_bytes") or sha256_bytes(payload) != value.get(
                    "response_sha256"
                ):
                    raise ValueError(f"legacy raw evidence integrity failure: {legacy}")
                compressed_path = Path(str(path) + ".gz")
                compressed = deterministic_gzip(payload)
                if compressed_path.exists():
                    if compressed_path.read_bytes() != compressed:
                        raise ValueError(f"deterministic gzip collision: {compressed_path}")
                else:
                    atomic_write_bytes(compressed_path, compressed)
                value.update(
                    {
                        "compressed_path": _relative(compressed_path, root),
                        "compressed_sha256": sha256_bytes(compressed),
                        "compressed_bytes": len(compressed),
                        "uncompressed_response_sha256": sha256_bytes(payload),
                        "uncompressed_response_bytes": len(payload),
                        "compression": "gzip-level-9-mtime-0-no-filename",
                    }
                )
                for old_field in ("raw_body_path", "response_sha256", "response_bytes"):
                    value.pop(old_field, None)
                legacy_paths.add(path)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(cache)
    return sorted(legacy_paths)


def remove_migrated_plain_evidence(paths: Iterable[Path], raw_dir: Path) -> None:
    """Remove only validated legacy JSON files under the dedicated raw dir."""

    for path in paths:
        resolved = path.resolve()
        try:
            resolved.relative_to(raw_dir.resolve())
        except ValueError:
            raise ValueError(f"refusing to remove evidence outside timestamp_raw: {resolved}") from None
        if resolved.suffix != ".json":
            raise ValueError(f"refusing unexpected legacy evidence extension: {resolved}")
        resolved.unlink(missing_ok=True)


def _decode_json(response: Response) -> Any:
    if response.status != 200:
        raise ValueError(f"HTTP_{response.status}")
    try:
        return json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("INVALID_JSON_RESPONSE") from error


def apply_pull_response(entry: dict[str, Any], response: Response) -> None:
    try:
        payload = _decode_json(response)
        if not isinstance(payload, Mapping):
            raise ValueError("PULL_RESPONSE_NOT_OBJECT")
        repo = entry["repository"]
        checks = {
            "number": payload.get("number") == entry["fix_pr_number"],
            "repository": str(payload.get("base", {}).get("repo", {}).get("full_name", "")).casefold()
            == repo.casefold(),
            "base_commit": payload.get("base", {}).get("sha") == entry["base_commit"],
            "created_at": payload.get("created_at") == entry["benchmark_created_at"],
            "html_url": payload.get("html_url")
            == f"https://github.com/{repo}/pull/{entry['fix_pr_number']}",
        }
        entry["provenance_checks"] = checks
        if not all(checks.values()):
            entry["provenance_status"] = "MISMATCH"
            recompute_entry(entry)
            return
        entry["provenance_status"] = "CONFIRMED"
        entry["fix_pr_created_at"] = _known_or_unknown(payload.get("created_at"))
        entry["fix_pr_closed_at"] = _known_or_unknown(payload.get("closed_at"))
        # The single-pull representation has ``merged``; list-pulls items do
        # not always carry it.  A non-null RFC3339 merged_at is authoritative
        # in either official REST representation, while an explicit false is
        # never accepted.
        entry["fix_pr_merge_at"] = (
            _known_or_unknown(payload.get("merged_at"))
            if payload.get("merged") is not False
            else UNKNOWN
        )
        merge_sha = payload.get("merge_commit_sha")
        head_sha = payload.get("head", {}).get("sha")
        entry["fix_pr_merge_commit_sha"] = (
            merge_sha if isinstance(merge_sha, str) and re.fullmatch(r"[0-9a-f]{40}", merge_sha) else UNKNOWN
        )
        entry["fix_pr_head_sha"] = (
            head_sha if isinstance(head_sha, str) and re.fullmatch(r"[0-9a-f]{40}", head_sha) else UNKNOWN
        )
        entry["linked_issue_numbers"] = extract_linked_issues(
            payload.get("body"), repo, entry["fix_pr_number"]
        )
    except (KeyError, TypeError, ValueError) as error:
        entry["provenance_status"] = "UNAVAILABLE"
        entry["pull_parse_error"] = str(error)
    recompute_entry(entry)


def apply_commits_response(entry: dict[str, Any], response: Response) -> None:
    entry["fix_first_commit_at"] = UNKNOWN
    entry["fix_first_commit_raw_committer_at"] = UNKNOWN
    entry["fix_last_commit_raw_committer_at"] = UNKNOWN
    entry["fix_commit_public_at"] = UNKNOWN
    entry["fix_first_commit_authored_at"] = UNKNOWN
    try:
        payload = _decode_json(response)
        if not isinstance(payload, list) or not payload:
            raise ValueError("PR_COMMITS_RESPONSE_EMPTY_OR_NOT_ARRAY")
        link = {key.casefold(): value for key, value in response.headers.items()}.get("link", "")
        if 'rel="next"' in link:
            raise ValueError("PR_COMMITS_RESPONSE_TRUNCATED_OVER_100")
        head_sha = entry.get("fix_pr_head_sha")
        if head_sha == UNKNOWN or not any(item.get("sha") == head_sha for item in payload):
            raise ValueError("PR_HEAD_SHA_NOT_IN_COMMITS_RESPONSE")
        committed = [item.get("commit", {}).get("committer", {}).get("date") for item in payload]
        authored = [item.get("commit", {}).get("author", {}).get("date") for item in payload]
        if not committed or not all(is_timestamp(value) for value in committed):
            raise ValueError("MISSING_COMMITTER_TIMESTAMP")
        if not authored or not all(is_timestamp(value) for value in authored):
            raise ValueError("MISSING_AUTHOR_TIMESTAMP")
        raw_committer_at = min(committed, key=lambda value: parse_timestamp(value))
        raw_last_committer_at = max(committed, key=lambda value: parse_timestamp(value))
        pr_created_at = entry.get("fix_pr_created_at")
        if not is_timestamp(pr_created_at):
            raise ValueError("FIX_PR_CREATED_AT_REQUIRED_FOR_PUBLIC_COMMIT_BOUND")
        # Git author/committer dates are user-controlled metadata, not proof of
        # when an object became public on GitHub.  The validated PR creation
        # event is the earliest public event this cache can prove, so never use
        # a raw Git timestamp earlier than it as source availability.
        entry["fix_first_commit_raw_committer_at"] = raw_committer_at
        entry["fix_last_commit_raw_committer_at"] = raw_last_committer_at
        entry["fix_first_commit_at"] = max(
            (raw_committer_at, pr_created_at), key=lambda value: parse_timestamp(value)
        )
        # A multi-commit fix is not complete at its first commit.  The source
        # fallback therefore uses the last observed fix-commit date, bounded
        # below by the validated PR-publication event.
        entry["fix_commit_public_at"] = max(
            (raw_last_committer_at, pr_created_at), key=lambda value: parse_timestamp(value)
        )
        entry["fix_first_commit_authored_at"] = min(authored, key=lambda value: parse_timestamp(value))
        entry["fix_commit_count"] = len(payload)
        entry.pop("commits_parse_error", None)
    except (KeyError, TypeError, ValueError) as error:
        entry["commits_parse_error"] = str(error)
    recompute_entry(entry)


def apply_issue_responses(entry: dict[str, Any], payloads: Mapping[int, Response]) -> None:
    entry["issue_close_at"] = UNKNOWN
    entry["linked_issue_created_at"] = UNKNOWN
    numbers = entry.get("linked_issue_numbers", [])
    if not numbers:
        entry["issue_parse_error"] = "NO_CLOSING_KEYWORD_LINKED_ISSUE"
        recompute_entry(entry)
        return
    closed: list[str] = []
    created: list[str] = []
    try:
        if set(payloads) != set(numbers):
            raise ValueError("LINKED_ISSUE_QUERIES_INCOMPLETE")
        for number in numbers:
            payload = _decode_json(payloads[number])
            if not isinstance(payload, Mapping) or payload.get("number") != number:
                raise ValueError(f"LINKED_ISSUE_IDENTITY_MISMATCH_{number}")
            if "pull_request" in payload:
                raise ValueError(f"LINKED_REFERENCE_IS_PULL_REQUEST_{number}")
            created_at = payload.get("created_at")
            if not is_timestamp(created_at):
                raise ValueError(f"LINKED_ISSUE_CREATED_UNKNOWN_{number}")
            created.append(created_at)
            closed_at = payload.get("closed_at")
            if is_timestamp(closed_at):
                closed.append(closed_at)
        # Work may begin when the earliest of multiple linked issues opens.
        # A resolution fallback, conversely, is usable only when every linked
        # issue has a known close; its latest close is conservative.
        entry["linked_issue_created_at"] = min(created, key=lambda value: parse_timestamp(value))
        if len(closed) == len(numbers):
            entry["issue_close_at"] = max(closed, key=lambda value: parse_timestamp(value))
            entry.pop("issue_parse_error", None)
        else:
            entry["issue_parse_error"] = "ONE_OR_MORE_LINKED_ISSUES_NOT_CLOSED"
    except (KeyError, TypeError, ValueError) as error:
        entry["issue_parse_error"] = str(error)
    recompute_entry(entry)


def _successful(attempts: Iterable[Mapping[str, Any]]) -> bool:
    return any(attempt.get("http_status") == 200 for attempt in attempts)


def _attemptable(attempts: Iterable[Mapping[str, Any]], max_attempts: int, refresh: bool) -> bool:
    attempts = list(attempts)
    if refresh:
        return True
    return not _successful(attempts) and len(attempts) < max_attempts


def _rate_remaining(attempt: Mapping[str, Any]) -> int | None:
    value = attempt.get("headers", {}).get("x-ratelimit-remaining")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class RecoveryRunner:
    def __init__(
        self,
        root: Path,
        cache_path: Path,
        raw_dir: Path,
        cache: dict[str, Any],
        transport: Callable[[str], Response],
        max_requests: int,
        reserve_requests: int,
        max_attempts: int,
        refresh: bool = False,
    ):
        if max_requests < 0 or reserve_requests < 0 or max_attempts < 1:
            raise ValueError("request limits must be non-negative and max_attempts positive")
        self.root = root
        self.cache_path = cache_path
        self.raw_dir = raw_dir
        self.cache = cache
        self.transport = transport
        self.max_requests = max_requests
        self.reserve_requests = reserve_requests
        self.max_attempts = max_attempts
        self.refresh = refresh
        self.requests_made = 0
        self.stop_reason = "PHASES_COMPLETE"

    def _can_request(self) -> bool:
        if self.requests_made >= self.max_requests:
            self.stop_reason = "MAX_REQUESTS_REACHED"
            return False
        return True

    def _request(self, url: str, raw_path: Path, kind: str) -> tuple[Response, dict[str, Any]] | None:
        if not self._can_request():
            return None
        response = self.transport(url)
        self.requests_made += 1
        attempt = retain_response(response, raw_path, self.root, kind)
        remaining = _rate_remaining(attempt)
        if remaining is not None and remaining <= self.reserve_requests:
            self.stop_reason = "UNAUTHENTICATED_RATE_RESERVE_REACHED"
        return response, attempt

    def _checkpoint(self) -> None:
        recompute_cache(self.cache)
        run_summary = {
            "ended_at_utc": utc_now(),
            "requests_made": self.requests_made,
            "max_requests": self.max_requests,
            "reserve_requests": self.reserve_requests,
            "stop_reason": self.stop_reason,
        }
        self.cache["last_run"] = run_summary
        if self.requests_made > 0:
            self.cache["last_network_run"] = dict(run_summary)
        atomic_write_json(self.cache_path, self.cache)

    def _ordered_entries(self) -> list[dict[str, Any]]:
        return sorted(
            self.cache["entries"].values(),
            key=lambda entry: (
                parse_timestamp(entry.get("benchmark_created_at")) or datetime.max.replace(tzinfo=timezone.utc),
                entry["instance_id"],
            ),
        )

    def recover_pulls(self) -> None:
        for entry in self._ordered_entries():
            attempts = entry["queries"]["pull"]
            if not _attemptable(attempts, self.max_attempts, self.refresh):
                continue
            if not self._can_request() or self.stop_reason == "UNAUTHENTICATED_RATE_RESERVE_REACHED":
                break
            number = entry["fix_pr_number"]
            url = github_url(entry["repository"], f"/pulls/{number}")
            raw_path = self.raw_dir / entry["instance_id"] / f"pull-attempt-{len(attempts) + 1}.json"
            result = self._request(url, raw_path, "FIX_PULL_REQUEST")
            if result is None:
                break
            response, attempt = result
            attempts.append(attempt)
            apply_pull_response(entry, response)
            self._checkpoint()

    @staticmethod
    def _last_page(attempt: Mapping[str, Any], payload_size: int, current_page: int) -> int | None:
        link = attempt.get("headers", {}).get("link", "")
        matches = re.findall(r"[?&]page=([0-9]+)>;\s*rel=\"([^\"]+)\"", link)
        for page, relation in matches:
            if relation == "last":
                return int(page)
        # A short page with no `next` relation is itself the final page.
        return current_page if payload_size < 100 else None

    @staticmethod
    def _page_observation(attempts: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
        for attempt in reversed(list(attempts)):
            if attempt.get("http_status") == 200 and "min_pr_number" in attempt:
                return attempt
        return None

    def _recover_bulk_page(self, repository: str, page: int) -> tuple[int, int, int] | None:
        """Fetch one 100-PR page and apply every exact benchmark match.

        Returns ``(minimum PR number, maximum PR number, last page)``.  The
        response itself is retained once; each matched instance points back to
        that same raw response plus an item index/hash.
        """

        pages = self.cache["bulk_pull_pages"].setdefault(repository, {})
        attempts = pages.setdefault(str(page), [])
        observation = self._page_observation(attempts)
        if observation is not None and not self.refresh:
            return (
                int(observation["min_pr_number"]),
                int(observation["max_pr_number"]),
                int(observation["last_page"]),
            )
        replay_index = next(
            (index for index in range(len(attempts) - 1, -1, -1) if attempts[index].get("http_status") == 200),
            None,
        )
        replacing_attempt = replay_index is not None and not self.refresh
        if replacing_attempt:
            old = attempts[replay_index]
            body = load_attempt_body(old, self.root)
            response = Response(old["url"], 200, body, old.get("headers", {}), old["queried_at_utc"])
            attempt = dict(old)
            for derived in (
                "parse_error",
                "page",
                "last_page",
                "item_count",
                "min_pr_number",
                "max_pr_number",
                "benchmark_items_matched",
            ):
                attempt.pop(derived, None)
        else:
            if not _attemptable(attempts, self.max_attempts, self.refresh):
                return None
            url = github_url(
                repository,
                f"/pulls?state=closed&sort=created&direction=asc&per_page=100&page={page}",
            )
            slug = repository.replace("/", "__")
            raw_path = (
                self.raw_dir
                / "bulk"
                / slug
                / f"closed-pulls-page-{page}-attempt-{len(attempts) + 1}.json"
            )
            result = self._request(url, raw_path, "FIX_PULL_REQUEST_BULK_PAGE")
            if result is None:
                return None
            response, attempt = result
        try:
            payload = _decode_json(response)
            if not isinstance(payload, list) or not payload:
                raise ValueError("BULK_PULL_PAGE_EMPTY_OR_NOT_ARRAY")
            numbered = [item.get("number") for item in payload]
            if not all(isinstance(number, int) and number > 0 for number in numbered):
                raise ValueError("BULK_PULL_PAGE_INVALID_NUMBER")
            created_values = [item.get("created_at") for item in payload]
            if not all(is_timestamp(value) for value in created_values):
                raise ValueError("BULK_PULL_PAGE_INVALID_CREATED_AT")
            last_page = self._last_page(attempt, len(payload), page)
            if last_page is None or page > last_page:
                raise ValueError("BULK_PULL_PAGE_LAST_PAGE_UNKNOWN")
            attempt.update(
                {
                    "page": page,
                    "last_page": last_page,
                    "item_count": len(payload),
                    "min_pr_number": min(numbered),
                    "max_pr_number": max(numbered),
                }
            )
            wanted = {
                entry["fix_pr_number"]: entry
                for entry in self.cache["entries"].values()
                if entry["repository"].casefold() == repository.casefold()
                and not _successful(entry["queries"]["pull"])
            }
            matched = 0
            for index, item in enumerate(payload):
                entry = wanted.get(item["number"])
                if entry is None:
                    continue
                item_bytes = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
                item_attempt = dict(attempt)
                item_attempt.update(
                    {
                        "query_kind": "FIX_PULL_REQUEST_BULK_PAGE_ITEM",
                        "bulk_page": page,
                        "bulk_item_index": index,
                        "bulk_item_sha256": sha256_bytes(item_bytes),
                    }
                )
                entry["queries"]["pull"].append(item_attempt)
                apply_pull_response(
                    entry,
                    Response(response.url, 200, item_bytes, response.headers, response.queried_at_utc),
                )
                if entry.get("provenance_status") == "CONFIRMED":
                    matched += 1
            attempt["benchmark_items_matched"] = matched
        except (KeyError, TypeError, ValueError) as error:
            attempt["parse_error"] = str(error)
            if replacing_attempt:
                attempts[replay_index] = attempt
            else:
                attempts.append(attempt)
            self._checkpoint()
            return None
        if replacing_attempt:
            attempts[replay_index] = attempt
        else:
            attempts.append(attempt)
        self._checkpoint()
        return min(numbered), max(numbered), last_page

    @staticmethod
    def _interpolated_page(
        number: int,
        observations: Mapping[int, tuple[int, int]],
        last_page: int,
    ) -> int | None:
        """Choose a not-yet-read page bracketed by monotonic PR-number ranges."""

        fetched = set(observations)
        for page, (minimum, maximum) in observations.items():
            if minimum <= number <= maximum:
                return None
        lower = [(page, maximum) for page, (_, maximum) in observations.items() if maximum < number]
        upper = [(page, minimum) for page, (minimum, _) in observations.items() if minimum > number]
        low_page, low_number = max(lower, default=(0, 0), key=lambda value: value[0])
        high_page, high_number = min(
            upper,
            default=(last_page + 1, max(number + 1, number * 2)),
            key=lambda value: value[0],
        )
        if high_page - low_page <= 1:
            return None
        if high_number > low_number:
            fraction = (number - low_number) / (high_number - low_number)
            candidate = low_page + round(fraction * (high_page - low_page))
        else:
            candidate = (low_page + high_page) // 2
        candidate = max(low_page + 1, min(high_page - 1, candidate))
        if candidate in fetched:
            choices = [page for page in range(low_page + 1, high_page) if page not in fetched]
            return choices[len(choices) // 2] if choices else None
        return candidate

    def recover_bulk_pulls(self) -> None:
        """Recover exact PRs through deterministic repository page batches.

        Repositories are prioritized by the number of missing benchmark PRs.
        Page 1 supplies GitHub's last-page bound, the last page supplies the
        upper PR-number bound, and subsequent pages use monotonic interpolation.
        A response can therefore validate many instances without either search
        heuristics or rate-limit circumvention.
        """

        pending_by_repo: dict[str, list[dict[str, Any]]] = {}
        for entry in self.cache["entries"].values():
            if not _successful(entry["queries"]["pull"]):
                pending_by_repo.setdefault(entry["repository"], []).append(entry)
        repositories = sorted(pending_by_repo, key=lambda repo: (-len(pending_by_repo[repo]), repo))

        for repository in repositories:
            if not self._can_request() or self.stop_reason == "UNAUTHENTICATED_RATE_RESERVE_REACHED":
                break
            pages = self.cache["bulk_pull_pages"].setdefault(repository, {})
            observations: dict[int, tuple[int, int]] = {}
            last_page: int | None = None
            for page_text, attempts in pages.items():
                observation = self._page_observation(attempts)
                if observation is not None:
                    page = int(page_text)
                    observations[page] = (
                        int(observation["min_pr_number"]),
                        int(observation["max_pr_number"]),
                    )
                    last_page = int(observation["last_page"])

            if 1 not in observations:
                got = self._recover_bulk_page(repository, 1)
                if got is None:
                    continue
                minimum, maximum, last_page = got
                observations[1] = (minimum, maximum)
            assert last_page is not None
            if last_page not in observations and last_page > 1:
                got = self._recover_bulk_page(repository, last_page)
                if got is None:
                    continue
                observations[last_page] = (got[0], got[1])

            while self._can_request() and self.stop_reason != "UNAUTHENTICATED_RATE_RESERVE_REACHED":
                pending = [
                    entry
                    for entry in pending_by_repo[repository]
                    if not _successful(entry["queries"]["pull"])
                ]
                if not pending:
                    break
                candidates: dict[int, int] = {}
                for entry in pending:
                    page = self._interpolated_page(entry["fix_pr_number"], observations, last_page)
                    if page is not None:
                        candidates[page] = candidates.get(page, 0) + 1
                if not candidates:
                    break
                # Most pending targets first, then stable lower page tie-break.
                page = min(candidates, key=lambda candidate: (-candidates[candidate], candidate))
                got = self._recover_bulk_page(repository, page)
                if got is None:
                    break
                observations[page] = (got[0], got[1])

    def recover_commits(self) -> None:
        for entry in self._ordered_entries():
            if entry.get("provenance_status") != "CONFIRMED":
                continue
            attempts = entry["queries"]["commits"]
            if _successful(attempts) and not self.refresh:
                latest = next(a for a in reversed(attempts) if a["http_status"] == 200)
                body = load_attempt_body(latest, self.root)
                apply_commits_response(
                    entry,
                    Response(latest["url"], 200, body, latest.get("headers", {}), latest["queried_at_utc"]),
                )
                self._checkpoint()
                continue
            if not _attemptable(attempts, self.max_attempts, self.refresh):
                continue
            if not self._can_request() or self.stop_reason == "UNAUTHENTICATED_RATE_RESERVE_REACHED":
                break
            number = entry["fix_pr_number"]
            url = github_url(entry["repository"], f"/pulls/{number}/commits?per_page=100")
            raw_path = self.raw_dir / entry["instance_id"] / f"commits-attempt-{len(attempts) + 1}.json"
            result = self._request(url, raw_path, "FIX_PULL_REQUEST_COMMITS")
            if result is None:
                break
            response, attempt = result
            attempts.append(attempt)
            apply_commits_response(entry, response)
            self._checkpoint()

    def recover_issues(self) -> None:
        for entry in self._ordered_entries():
            if entry.get("provenance_status") != "CONFIRMED":
                continue
            numbers = entry.get("linked_issue_numbers", [])
            if not numbers:
                continue
            responses: dict[int, Response] = {}
            complete = True
            for number in numbers:
                key = str(number)
                attempts = entry["queries"]["issues"].setdefault(key, [])
                if _successful(attempts) and not self.refresh:
                    latest = next(a for a in reversed(attempts) if a["http_status"] == 200)
                    body = load_attempt_body(latest, self.root)
                    responses[number] = Response(
                        latest["url"], 200, body, latest.get("headers", {}), latest["queried_at_utc"]
                    )
                    continue
                if not _attemptable(attempts, self.max_attempts, self.refresh):
                    complete = False
                    continue
                if not self._can_request() or self.stop_reason == "UNAUTHENTICATED_RATE_RESERVE_REACHED":
                    complete = False
                    break
                url = github_url(entry["repository"], f"/issues/{number}")
                raw_path = self.raw_dir / entry["instance_id"] / f"issue-{number}-attempt-{len(attempts) + 1}.json"
                result = self._request(url, raw_path, "LINKED_ISSUE")
                if result is None:
                    complete = False
                    break
                response, attempt = result
                attempts.append(attempt)
                if response.status == 200:
                    responses[number] = response
                else:
                    complete = False
                self._checkpoint()
            if complete and set(responses) == set(numbers):
                apply_issue_responses(entry, responses)
                self._checkpoint()

    def run(self, phase: str) -> None:
        if phase in ("pulls", "all"):
            self.recover_pulls()
        if phase in ("bulk-pulls",) and self.stop_reason != "UNAUTHENTICATED_RATE_RESERVE_REACHED":
            self.recover_bulk_pulls()
        if phase in ("commits", "all") and self.stop_reason != "UNAUTHENTICATED_RATE_RESERVE_REACHED":
            self.recover_commits()
        if phase in ("issues", "all") and self.stop_reason != "UNAUTHENTICATED_RATE_RESERVE_REACHED":
            self.recover_issues()
        self._checkpoint()


def build_graph(cache: Mapping[str, Any], edges_path: Path, graph_path: Path, root: Path) -> dict[str, Any]:
    entries = cache["entries"]
    lines: list[bytes] = []
    per_source: dict[str, dict[str, Any]] = {}
    eligible = 0
    ineligible = 0
    undecidable = 0
    known_targets = sum(is_timestamp(entry.get("linked_issue_created_at")) for entry in entries.values())
    pr_created_proxy_edges = 0

    for source_id in sorted(entries):
        source = entries[source_id]
        available = parse_timestamp(source.get("source_available_at"))
        source_count = 0
        if available is None:
            undecidable += len(entries) - 1
            continue
        for target_id in sorted(entries):
            if source_id == target_id:
                continue
            target = entries[target_id]
            start = parse_timestamp(target.get("linked_issue_created_at"))
            if start is None:
                undecidable += 1
                continue
            if available < start:
                edge = {
                    "source_instance_id": source_id,
                    "target_instance_id": target_id,
                    "source_available_at": source["source_available_at"],
                    "source_available_at_basis": source["source_available_at_basis"],
                    "target_start_at": target["linked_issue_created_at"],
                }
                lines.append(
                    (json.dumps(edge, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
                        "utf-8"
                    )
                )
                eligible += 1
                source_count += 1
            else:
                ineligible += 1
        per_source[source_id] = {
            "source_available_at": source["source_available_at"],
            "basis": source["source_available_at_basis"],
            "eligible_target_count": source_count,
        }

    # Preserve the former count only as a named diagnostic.  The benchmark's
    # created_at was live-verified as PR creation, not issue creation, so this
    # later timestamp cannot establish source-before-work-began eligibility.
    for source_id, source in entries.items():
        available = parse_timestamp(source.get("source_available_at"))
        if available is None:
            continue
        for target_id, target in entries.items():
            if source_id == target_id:
                continue
            proxy = parse_timestamp(target.get("benchmark_created_at"))
            if proxy is not None and available < proxy:
                pr_created_proxy_edges += 1

    payload = b"".join(lines)
    atomic_write_bytes(edges_path, payload)
    total = len(entries)
    graph = {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "experiment": "R23-X chronological eligibility",
        "generated_at_utc": utc_now(),
        "instance_count": total,
        "r23_x_chronology": "PENDING_B0_1",
        "target_start_at_field": "linked GitHub issue.created_at",
        "target_start_at_semantics": "ISSUE_CREATED_AT_FROM_VALIDATED_CLOSING_REFERENCE",
        "target_start_at_known": known_targets,
        "benchmark_created_at_semantics_correction": (
            "The committed parquet field previously labelled issue_created_at equals fix PR created_at. "
            "It is retained for provenance but is not accepted as target work start."
        ),
        "pr_created_proxy_ordered_edges": pr_created_proxy_edges,
        "pr_created_proxy_is_eligibility": False,
        "source_available_at_precedence": cache["source_availability_precedence"],
        "commit_public_timestamp_rule": (
            "max(raw last fix-commit committer date, validated fix PR created_at); raw Git dates alone "
            "do not prove historical public availability, and first commit does not prove fix completion"
        ),
        "source_available_at_known": cache["coverage"]["source_available_at_known"],
        "source_available_at_unknown": cache["coverage"]["source_available_at_unknown"],
        "unknown_policy": "FAIL_CLOSED_NO_CHRONOLOGICAL_EDGE",
        "strict_predicate": "source_instance_id != target_instance_id AND source_available_at < target_start_at",
        "temporally_eligible_edges_confirmed": eligible,
        "temporally_ineligible_edges_confirmed": ineligible,
        "ordered_edges_undecidable_due_to_unknown_timestamp": undecidable,
        "max_possible_ordered_pairs": total * (total - 1),
        "edge_partition_check": eligible + ineligible + undecidable == total * (total - 1),
        "edges_file": _relative(edges_path, root),
        "edges_file_sha256": sha256_bytes(payload),
        "edges_file_format": "canonical JSON Lines; one confirmed chronological candidate edge per line",
        "confirmed_per_source": per_source,
        "source_target_pair_selection": "NOT_PERFORMED",
        "semantic_eligibility": "PENDING_R23_A0_G0",
        "status": (
            "TIMESTAMP_COVERAGE_COMPLETE"
            if cache["coverage"]["source_available_at_known"] == total and known_targets == total
            else "PENDING_B0_1_PARTIAL_FAIL_CLOSED"
        ),
        "note": (
            "These are chronology-only candidate edges, not selected source-target pairs. "
            "UNKNOWN sources contribute zero edges. Final R23-X pairing remains prohibited until "
            "timestamp recovery and the separately gated semantic stages are complete."
        ),
    }
    atomic_write_json(graph_path, graph)
    return graph


def verify_raw_evidence(cache: Mapping[str, Any], root: Path) -> dict[str, Any]:
    """Fail closed unless compressed and uncompressed response hashes match."""

    references: dict[str, tuple[str, int, str, int]] = {}

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            path = value.get("compressed_path")
            digest = value.get("compressed_sha256")
            size = value.get("compressed_bytes")
            raw_digest = value.get("uncompressed_response_sha256")
            raw_size = value.get("uncompressed_response_bytes")
            if (
                isinstance(path, str)
                and isinstance(digest, str)
                and isinstance(size, int)
                and isinstance(raw_digest, str)
                and isinstance(raw_size, int)
            ):
                prior = references.get(path)
                current = (digest, size, raw_digest, raw_size)
                if prior is not None and prior != current:
                    raise ValueError(f"conflicting raw evidence references: {path}")
                references[path] = current
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    # Avoid recursively visiting a previous integrity summary.
    material = {key: value for key, value in cache.items() if key != "evidence_integrity"}
    visit(material)
    manifest_lines: list[bytes] = []
    compressed_bytes = 0
    uncompressed_bytes = 0
    for relative_path in sorted(references):
        digest, expected_size, raw_digest, raw_size = references[relative_path]
        raw = (root / relative_path).resolve()
        try:
            raw.relative_to(root.resolve())
        except ValueError:
            raise ValueError(f"raw evidence escaped repository root: {relative_path}") from None
        payload = raw.read_bytes()
        if len(payload) != expected_size or sha256_bytes(payload) != digest:
            raise ValueError(f"raw evidence integrity failure: {relative_path}")
        uncompressed = load_attempt_body(
            {
                "compressed_path": relative_path,
                "compressed_sha256": digest,
                "compressed_bytes": expected_size,
                "uncompressed_response_sha256": raw_digest,
                "uncompressed_response_bytes": raw_size,
            },
            root,
        )
        compressed_bytes += len(payload)
        uncompressed_bytes += len(uncompressed)
        manifest_lines.append(
            f"{digest}  {len(payload)}  {raw_digest}  {len(uncompressed)}  {relative_path}\n".encode("utf-8")
        )
    return {
        "status": "PASS",
        "unique_response_count": len(references),
        "compressed_bytes": compressed_bytes,
        "uncompressed_response_bytes": uncompressed_bytes,
        "manifest_sha256": sha256_bytes(b"".join(manifest_lines)),
        "verified_at_utc": utc_now(),
    }


def build_report(cache: Mapping[str, Any], graph: Mapping[str, Any], report_path: Path) -> dict[str, Any]:
    report = {
        "schema_version": "r23-b0.1-recovery-report-v1",
        "generated_at_utc": utc_now(),
        "status": graph["status"],
        "timestamp_coverage": cache["coverage"],
        "confirmed_chronological_edge_count": graph["temporally_eligible_edges_confirmed"],
        "pr_created_proxy_ordered_edge_count": graph["pr_created_proxy_ordered_edges"],
        "chronology_only_not_pair_selection": True,
        "source_target_pair_selection": "NOT_PERFORMED",
        "api_authentication": "NONE",
        "paid_model_calls": 0,
        "docker_executions": 0,
        "last_run": cache.get("last_run"),
        "last_network_run": cache.get("last_network_run"),
        "raw_evidence_integrity": cache.get("evidence_integrity"),
    }
    atomic_write_json(report_path, report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--benchmark", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--edges", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--phase",
        choices=("pulls", "bulk-pulls", "commits", "issues", "all", "none"),
        default="all",
    )
    parser.add_argument("--max-requests", type=int, default=55)
    parser.add_argument("--reserve-requests", type=int, default=2)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--require-complete", action="store_true")
    return parser.parse_args(argv)


def _under_root(value: Path | None, root: Path, default: str) -> Path:
    path = (value or root / default).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        raise ValueError(f"artifact path must remain under repository root: {path}") from None
    return path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    audit_path = _under_root(args.audit, root, "artifacts/r23/verified_static_audit.json")
    benchmark_path = _under_root(args.benchmark, root, "artifacts/r23/benchmark_lock.json")
    cache_path = _under_root(args.cache, root, "artifacts/r23/timestamp_cache.json")
    raw_dir = _under_root(args.raw_dir, root, "artifacts/r23/timestamp_raw")
    graph_path = _under_root(args.graph, root, "artifacts/r23/chronological_eligibility_graph.json")
    edges_path = _under_root(args.edges, root, "artifacts/r23/chronological_eligibility_edges.ndjson")
    report_path = _under_root(args.report, root, "artifacts/r23/timestamp_recovery_report.json")

    audit = load_json(audit_path)
    benchmark = load_json(benchmark_path)
    if benchmark.get("revision_sha") != DEFAULT_REVISION:
        raise ValueError("refusing timestamp recovery for an unpinned benchmark revision")
    existing = load_json(cache_path) if cache_path.exists() else None
    cache = initialize_cache(audit, benchmark, existing)
    migrated_plain_paths = compress_legacy_evidence(cache, root, raw_dir)
    atomic_write_json(cache_path, cache)
    remove_migrated_plain_evidence(migrated_plain_paths, raw_dir)

    if args.phase != "none":
        runner = RecoveryRunner(
            root=root,
            cache_path=cache_path,
            raw_dir=raw_dir,
            cache=cache,
            transport=GitHubREST(args.timeout_seconds),
            max_requests=args.max_requests,
            reserve_requests=args.reserve_requests,
            max_attempts=args.max_attempts,
            refresh=args.refresh,
        )
        runner.run(args.phase)
    else:
        cache["last_run"] = {
            "ended_at_utc": utc_now(),
            "requests_made": 0,
            "max_requests": 0,
            "reserve_requests": args.reserve_requests,
            "stop_reason": "NO_NETWORK_REBUILD",
        }
        recompute_cache(cache)
        atomic_write_json(cache_path, cache)

    cache["evidence_integrity"] = verify_raw_evidence(cache, root)
    atomic_write_json(cache_path, cache)
    graph = build_graph(cache, edges_path, graph_path, root)
    report = build_report(cache, graph, report_path)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if args.require_complete and graph["status"] != "TIMESTAMP_COVERAGE_COMPLETE":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
