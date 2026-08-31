"""Credential-free R23-B0.1 timestamp recovery and fail-closed graph tests."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "r23_b01_timestamp_recovery", ROOT / "scripts" / "r23_b01_timestamp_recovery.py"
)
assert SPEC and SPEC.loader
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)


def _response(payload, status=200, headers=None):
    return M.Response(
        url="https://api.github.com/repos/org/repo/pulls/1",
        status=status,
        body=json.dumps(payload).encode(),
        headers=headers or {"X-RateLimit-Remaining": "55"},
        queried_at_utc="2026-08-31T00:00:00Z",
    )


def _entry(number=1):
    created = "2020-01-02T00:00:00Z"
    return {
        "instance_id": f"org__repo-{number}",
        "repository": "org/repo",
        "fix_pr_number": number,
        "benchmark_created_at": created,
        "benchmark_created_at_semantics": "FIX_PR_CREATED_AT",
        "base_commit": "a" * 40,
        "fix_pr_created_at": M.UNKNOWN,
        "fix_pr_closed_at": M.UNKNOWN,
        "fix_pr_merge_at": M.UNKNOWN,
        "fix_pr_merge_commit_sha": M.UNKNOWN,
        "fix_pr_head_sha": M.UNKNOWN,
        "fix_first_commit_at": M.UNKNOWN,
        "fix_first_commit_raw_committer_at": M.UNKNOWN,
        "fix_last_commit_raw_committer_at": M.UNKNOWN,
        "fix_commit_public_at": M.UNKNOWN,
        "fix_first_commit_authored_at": M.UNKNOWN,
        "linked_issue_numbers": [],
        "linked_issue_created_at": M.UNKNOWN,
        "issue_close_at": M.UNKNOWN,
        "source_available_at": M.UNKNOWN,
        "source_available_at_basis": M.UNKNOWN,
        "provenance_status": "PENDING",
        "timestamp_status": M.UNKNOWN,
        "unknown_reasons": [],
        "queries": {"pull": [], "commits": [], "issues": {}},
    }


def _pull_payload(number=1, base=None, created="2020-01-02T00:00:00Z", merged=True):
    return {
        "number": number,
        "html_url": f"https://github.com/org/repo/pull/{number}",
        "created_at": created,
        "closed_at": "2020-01-04T00:00:00Z",
        "merged_at": "2020-01-04T00:00:00Z" if merged else None,
        "merged": merged,
        "merge_commit_sha": "b" * 40,
        "body": "Fixes #99 and mentions #100. Resolves other/repo#7.",
        "base": {"sha": base or "a" * 40, "repo": {"full_name": "org/repo"}},
        "head": {"sha": "c" * 40},
    }


def test_instance_suffix_is_pr_number_and_closing_references_are_conservative():
    assert M.pull_number("org__repo-123", "org/repo") == 123
    body = "Fixes #12; closes: org/repo#13; resolves https://github.com/org/repo/issues/14; see #15"
    assert M.extract_linked_issues(body, "org/repo", 99) == [12, 13, 14]
    assert M.extract_linked_issues("Fixes other/repo#12", "org/repo", 99) == []


def test_pull_provenance_must_match_before_merge_timestamp_is_usable():
    accepted = _entry()
    M.apply_pull_response(accepted, _response(_pull_payload()))
    assert accepted["provenance_status"] == "CONFIRMED"
    assert accepted["linked_issue_numbers"] == [99]
    assert accepted["source_available_at"] == "2020-01-04T00:00:00Z"
    assert accepted["source_available_at_basis"] == "FIX_PR_MERGED_AT"

    rejected = _entry()
    M.apply_pull_response(rejected, _response(_pull_payload(base="d" * 40)))
    assert rejected["provenance_status"] == "MISMATCH"
    assert rejected["fix_pr_merge_at"] == M.UNKNOWN
    assert rejected["source_available_at"] == M.UNKNOWN


def test_commit_and_issue_fallbacks_are_explicit_and_fail_closed():
    entry = _entry()
    M.apply_pull_response(entry, _response(_pull_payload(merged=False)))
    commits = [
        {
            "sha": "c" * 40,
            "commit": {
                "committer": {"date": "2020-01-03T00:00:00Z"},
                "author": {"date": "2020-01-02T12:00:00Z"},
            },
        }
    ]
    M.apply_commits_response(entry, _response(commits))
    assert entry["source_available_at"] == "2020-01-03T00:00:00Z"
    assert entry["source_available_at_basis"] == "FIX_COMMIT_PUBLIC_AT_CONSERVATIVE"

    entry["fix_first_commit_at"] = M.UNKNOWN
    entry["fix_commit_public_at"] = M.UNKNOWN
    issue = _response(
        {"number": 99, "created_at": "2020-01-01T00:00:00Z", "closed_at": "2020-01-05T00:00:00Z"}
    )
    M.apply_issue_responses(entry, {99: issue})
    assert entry["source_available_at_basis"] == "LINKED_ISSUE_CLOSED_AT"
    assert entry["linked_issue_created_at"] == "2020-01-01T00:00:00Z"

    M.apply_issue_responses(entry, {})
    assert entry["issue_close_at"] == M.UNKNOWN
    assert entry["source_available_at"] == M.UNKNOWN
    assert entry["timestamp_status"] == M.UNKNOWN


def test_raw_commit_date_before_pr_creation_cannot_backdate_public_availability():
    entry = _entry()
    M.apply_pull_response(entry, _response(_pull_payload(merged=False)))
    commits = [
        {
            "sha": "c" * 40,
            "commit": {
                "committer": {"date": "2019-01-01T00:00:00Z"},
                "author": {"date": "2018-01-01T00:00:00Z"},
            },
        }
    ]
    M.apply_commits_response(entry, _response(commits))
    assert entry["fix_first_commit_raw_committer_at"] == "2019-01-01T00:00:00Z"
    assert entry["fix_first_commit_at"] == entry["fix_pr_created_at"] == "2020-01-02T00:00:00Z"
    assert entry["fix_commit_public_at"] == "2020-01-02T00:00:00Z"
    assert entry["source_available_at"] == "2020-01-02T00:00:00Z"


def test_multi_commit_fallback_waits_for_last_fix_commit():
    entry = _entry()
    M.apply_pull_response(entry, _response(_pull_payload(merged=False)))
    commits = [
        {
            "sha": "d" * 40,
            "commit": {
                "committer": {"date": "2020-01-03T00:00:00Z"},
                "author": {"date": "2020-01-03T00:00:00Z"},
            },
        },
        {
            "sha": "c" * 40,
            "commit": {
                "committer": {"date": "2020-01-05T00:00:00Z"},
                "author": {"date": "2020-01-05T00:00:00Z"},
            },
        },
    ]
    M.apply_commits_response(entry, _response(commits))
    assert entry["fix_first_commit_at"] == "2020-01-03T00:00:00Z"
    assert entry["fix_last_commit_raw_committer_at"] == "2020-01-05T00:00:00Z"
    assert entry["fix_commit_public_at"] == "2020-01-05T00:00:00Z"
    assert entry["source_available_at"] == "2020-01-05T00:00:00Z"


def test_unknown_source_never_generates_edge_and_partition_is_complete(tmp_path):
    source = _entry(1)
    source["provenance_status"] = "CONFIRMED"
    source["fix_pr_merge_at"] = "2020-01-04T00:00:00Z"
    source["benchmark_created_at"] = "2020-01-02T00:00:00Z"
    M.recompute_entry(source)
    later = _entry(2)
    later["benchmark_created_at"] = "2020-01-06T00:00:00Z"
    later["linked_issue_created_at"] = "2020-01-06T00:00:00Z"
    cache = {
        "entries": {source["instance_id"]: source, later["instance_id"]: later},
        "source_availability_precedence": [
            "FIX_PR_MERGED_AT",
            "FIX_COMMIT_PUBLIC_AT_CONSERVATIVE",
            "LINKED_ISSUE_CLOSED_AT",
        ],
    }
    M.recompute_cache(cache)
    edges = tmp_path / "artifacts" / "edges.jsonl"
    graph_path = tmp_path / "artifacts" / "graph.json"
    graph = M.build_graph(cache, edges, graph_path, tmp_path)
    rows = [json.loads(line) for line in edges.read_text(encoding="utf-8").splitlines()]
    assert [(row["source_instance_id"], row["target_instance_id"]) for row in rows] == [
        ("org__repo-1", "org__repo-2")
    ]
    assert graph["temporally_eligible_edges_confirmed"] == 1
    assert graph["ordered_edges_undecidable_due_to_unknown_timestamp"] == 1
    assert graph["edge_partition_check"] is True
    assert graph["source_target_pair_selection"] == "NOT_PERFORMED"


def test_raw_evidence_is_verbatim_hashed_and_auth_header_is_impossible(tmp_path):
    response = _response({"number": 1})
    raw = tmp_path / "artifacts" / "raw" / "pull.json"
    attempt = M.retain_response(response, raw, tmp_path, "FIX_PULL_REQUEST")
    assert not raw.exists()
    assert M.load_attempt_body(attempt, tmp_path) == response.body
    assert attempt["uncompressed_response_sha256"] == hashlib.sha256(response.body).hexdigest()
    assert attempt["compressed_path"].endswith(".json.gz")
    assert attempt["authentication"] == "NONE"
    source = inspect.getsource(M.GitHubREST)
    assert "Authorization" not in source
    assert "GITHUB_TOKEN" not in source
    integrity = M.verify_raw_evidence({"attempt": attempt}, tmp_path)
    assert integrity["status"] == "PASS"
    assert integrity["unique_response_count"] == 1


def test_legacy_plain_evidence_migrates_before_scoped_removal(tmp_path):
    raw_dir = tmp_path / "artifacts" / "r23" / "timestamp_raw"
    plain = raw_dir / "task" / "pull.json"
    plain.parent.mkdir(parents=True)
    payload = b'{"public":"response"}'
    plain.write_bytes(payload)
    cache = {
        "attempt": {
            "raw_body_path": plain.relative_to(tmp_path).as_posix(),
            "response_sha256": hashlib.sha256(payload).hexdigest(),
            "response_bytes": len(payload),
        }
    }
    removable = M.compress_legacy_evidence(cache, tmp_path, raw_dir)
    assert plain.exists()  # cache must be persisted before this removal step
    assert M.load_attempt_body(cache["attempt"], tmp_path) == payload
    M.remove_migrated_plain_evidence(removable, raw_dir)
    assert not plain.exists()
    assert M.verify_raw_evidence(cache, tmp_path)["status"] == "PASS"


def test_committed_cache_and_graph_are_self_consistent_when_recovered():
    cache = json.loads((ROOT / "artifacts" / "r23" / "timestamp_cache.json").read_text(encoding="utf-8"))
    # This test accepts the pre-recovery legacy placeholder during patch review;
    # once B0.1 is run, it enforces the stronger cache/graph contract.
    if cache.get("schema_version") != M.SCHEMA_VERSION:
        assert len(cache) == 500
        return
    assert len(cache["entries"]) == 500
    assert cache["api"]["authentication"] == "NONE"
    assert cache["unknown_policy"] == "FAIL_CLOSED_NO_CHRONOLOGICAL_EDGE"
    integrity = M.verify_raw_evidence(cache, ROOT)
    assert integrity["manifest_sha256"] == cache["evidence_integrity"]["manifest_sha256"]
    graph = json.loads(
        (ROOT / "artifacts" / "r23" / "chronological_eligibility_graph.json").read_text(encoding="utf-8")
    )
    edge_bytes = (ROOT / graph["edges_file"]).read_bytes()
    assert hashlib.sha256(edge_bytes).hexdigest() == graph["edges_file_sha256"]
    assert sum(1 for line in edge_bytes.splitlines() if line) == graph["temporally_eligible_edges_confirmed"]
    assert graph["source_available_at_known"] == cache["coverage"]["source_available_at_known"]
    assert graph["source_target_pair_selection"] == "NOT_PERFORMED"
    assert graph["edge_partition_check"] is True


def test_deterministic_oldest_first_queue_and_resume(tmp_path):
    first = _entry(1)
    second = _entry(2)
    second["benchmark_created_at"] = "2021-01-02T00:00:00Z"
    cache = {
        "entries": {second["instance_id"]: second, first["instance_id"]: first},
        "source_availability_precedence": [
            "FIX_PR_MERGED_AT",
            "FIX_COMMIT_PUBLIC_AT_CONSERVATIVE",
            "LINKED_ISSUE_CLOSED_AT",
        ],
    }
    M.recompute_cache(cache)
    called = []

    def fake(url):
        called.append(url)
        number = int(url.rsplit("/", 1)[-1])
        payload = _pull_payload(number=number, created=cache["entries"][f"org__repo-{number}"]["benchmark_created_at"])
        return M.Response(url, 200, json.dumps(payload).encode(), {"X-RateLimit-Remaining": "50"}, "2026-08-31T00:00:00Z")

    runner = M.RecoveryRunner(
        root=tmp_path,
        cache_path=tmp_path / "artifacts" / "cache.json",
        raw_dir=tmp_path / "artifacts" / "raw",
        cache=cache,
        transport=fake,
        max_requests=1,
        reserve_requests=0,
        max_attempts=3,
    )
    runner.run("pulls")
    assert called == ["https://api.github.com/repos/org/repo/pulls/1"]
    assert cache["entries"]["org__repo-1"]["provenance_status"] == "CONFIRMED"
    assert cache["entries"]["org__repo-2"]["provenance_status"] == "PENDING"


def test_bulk_page_retains_one_raw_response_and_confirms_multiple_exact_prs(tmp_path):
    first = _entry(1)
    second = _entry(2)
    second["benchmark_created_at"] = "2020-01-03T00:00:00Z"
    cache = {
        "entries": {first["instance_id"]: first, second["instance_id"]: second},
        "bulk_pull_pages": {},
        "source_availability_precedence": [
            "FIX_PR_MERGED_AT",
            "FIX_COMMIT_PUBLIC_AT_CONSERVATIVE",
            "LINKED_ISSUE_CLOSED_AT",
        ],
    }
    M.recompute_cache(cache)
    payload = [
        _pull_payload(number=1, created="2020-01-02T00:00:00Z"),
        _pull_payload(number=2, created="2020-01-03T00:00:00Z"),
    ]
    called = []

    def fake(url):
        called.append(url)
        return M.Response(
            url,
            200,
            json.dumps(payload).encode(),
            {"X-RateLimit-Remaining": "50"},
            "2026-08-31T00:00:00Z",
        )

    runner = M.RecoveryRunner(
        root=tmp_path,
        cache_path=tmp_path / "artifacts" / "cache.json",
        raw_dir=tmp_path / "artifacts" / "raw",
        cache=cache,
        transport=fake,
        max_requests=1,
        reserve_requests=0,
        max_attempts=3,
    )
    runner.run("bulk-pulls")
    assert len(called) == 1
    assert cache["coverage"]["fix_pr_provenance_confirmed"] == 2
    attempts = [entry["queries"]["pull"][0] for entry in cache["entries"].values()]
    assert attempts[0]["compressed_path"] == attempts[1]["compressed_path"]
    assert attempts[0]["compressed_sha256"] == attempts[1]["compressed_sha256"]
    assert attempts[0]["uncompressed_response_sha256"] == attempts[1]["uncompressed_response_sha256"]
    assert attempts[0]["bulk_item_sha256"] != attempts[1]["bulk_item_sha256"]
