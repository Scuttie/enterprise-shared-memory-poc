from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_dev_activation_source_bank as source_bank  # noqa: E402


def _row(benchmark_id: str, instance_id: str, repository: str, commit: str, *, source: bool) -> dict:
    issue = f"Fix `Widget{instance_id[-1]}` when Client.call raises ValueError in src/file{instance_id[-1]}.py"
    patch = (
        f"diff --git a/src/file{instance_id[-1]}.py b/src/file{instance_id[-1]}.py\n"
        f"--- a/src/file{instance_id[-1]}.py\n"
        f"+++ b/src/file{instance_id[-1]}.py\n"
        "@@ -1 +1 @@\n"
        "-def old(): pass\n"
        "+def WidgetFix(): return Client.call()\n"
    )
    if benchmark_id == "swebench_verified":
        row = {
            "instance_id": instance_id,
            "repo": repository,
            "base_commit": commit,
            "problem_statement": issue,
            # Target rows deliberately have no patch.  A target exclusion bug would fail.
        }
        if source:
            row["patch"] = patch
        return row
    org, repo = repository.split("/", 1)
    row = {
        "instance_id": instance_id,
        "org": org,
        "repo": repo,
        "base": {"sha": commit},
        "title": issue,
        "body": "Public reproduction only.",
        "resolved_issues": [],
    }
    if source:
        row["fix_patch"] = patch
    return row


def _github_item(repository: str, kind: str, timestamp_key: str, timestamp: str) -> dict:
    return {
        "url": f"https://api.github.com/repos/{repository}/{kind}/1",
        timestamp_key: timestamp,
        "observed_at": "2026-01-01T00:00:00Z",
        "raw_sha256": hashlib.sha256(f"{repository}:{kind}".encode()).hexdigest(),
    }


def _fixture() -> tuple[dict, dict, dict, dict[str, list[dict]], dict]:
    benchmark_ids = list(source_bank.REQUIRED_DATASETS)
    revisions = {
        benchmark_id: hashlib.sha1((benchmark_id + ":revision").encode()).hexdigest()
        for benchmark_id in benchmark_ids
    }
    rows: dict[str, list[dict]] = {benchmark_id: [] for benchmark_id in benchmark_ids}
    targets = []
    sources = []
    target_cache = []
    for index in range(12):
        benchmark_id = benchmark_ids[index // 4]
        repository = f"owner{index}/repo{index}"
        target_iid = f"owner{index}__repo{index}-target"
        source_iid = f"owner{index}__repo{index}-source"
        target_commit = hashlib.sha1(f"target:{index}".encode()).hexdigest()
        source_base = hashlib.sha1(f"base:{index}".encode()).hexdigest()
        fix_commit = hashlib.sha1(f"fix:{index}".encode()).hexdigest()
        target_row = _row(
            benchmark_id,
            target_iid,
            repository,
            target_commit,
            source=False,
        )
        historical_row = _row(
            benchmark_id,
            source_iid,
            repository,
            source_base,
            source=True,
        )
        rows[benchmark_id].extend([target_row, historical_row])
        target_id = f"{benchmark_id}--{target_iid}"
        source_task_id = f"{benchmark_id}--{source_iid}"
        target_row_sha = source_bank.canonical_sha256(target_row)
        source_row_sha = source_bank.canonical_sha256(historical_row)
        targets.append(
            {
                "target_id": target_id,
                "instance_id": target_iid,
                "benchmark_id": benchmark_id,
                "dataset_revision": revisions[benchmark_id],
                "source_row_sha256": target_row_sha,
                "base_commit": target_commit,
                "repository": repository,
                "language": "python",
                "order_index": index,
            }
        )
        target_cache.append(
            {
                "target_id": target_id,
                "source_row_sha256": target_row_sha,
                "repository": repository,
                "base_commit": target_commit,
                "issue": _github_item(
                    repository, "issues", "created_at", "2025-01-01T00:00:00Z"
                ),
            }
        )
        fix_commit_item = _github_item(
            repository, "commits", "public_timestamp", "2024-01-02T00:00:00Z"
        )
        fix_commit_item["sha"] = fix_commit
        fix_pr_item = _github_item(
            repository, "pulls", "merged_at", "2024-01-01T00:00:00Z"
        )
        fix_pr_item["merge_commit_sha"] = fix_commit
        source_patch = (
            historical_row["patch"]
            if benchmark_id == "swebench_verified"
            else historical_row["fix_patch"]
        )
        sources.append(
            {
                "source_task_id": source_task_id,
                "source_row_sha256": source_row_sha,
                "repository": repository,
                "fix_pr": fix_pr_item,
                "fix_commit": fix_commit_item,
                "source_issue": _github_item(
                    repository, "issues", "closed_at", "2024-01-03T00:00:00Z"
                ),
                "patch_equivalence": {
                    "status": "UPSTREAM_MERGED_FIX_PATCH_EQUIVALENT",
                    "observed_at": "2026-01-01T00:00:00Z",
                    "evidence_sha256": hashlib.sha256(
                        f"patch-equivalence:{index}".encode()
                    ).hexdigest(),
                    "dataset_patch_sha256": hashlib.sha256(
                        source_patch.encode("utf-8")
                    ).hexdigest(),
                    "upstream_fix_diff_sha256": hashlib.sha256(
                        ("upstream:" + source_patch).encode("utf-8")
                    ).hexdigest(),
                },
                "ancestry": [
                    {
                        "target_id": target_id,
                        "target_base_commit": target_commit,
                        "fix_commit_sha": fix_commit,
                        "status": "FIX_COMMIT_IS_ANCESTOR_OF_TARGET_BASE",
                        "observed_at": "2026-01-01T00:00:00Z",
                        "evidence_sha256": hashlib.sha256(
                            f"ancestry:{index}".encode()
                        ).hexdigest(),
                    }
                ],
            }
        )
    development = {
        "schema": "trimem/development-manifest/1.0",
        "targets": targets,
    }
    development["target_set_sha256"] = source_bank.canonical_sha256(targets)
    grader = {
        "schema": "trimem/grader-lock/1.0",
        "dataset_files": [
            {
                "benchmark_id": benchmark_id,
                "dataset_revision": revisions[benchmark_id],
                "path": f"{benchmark_id}.jsonl",
                "bytes": 1,
                "sha256": "a" * 64,
            }
            for benchmark_id in benchmark_ids
        ],
    }
    plan = {
        "schema": "trimem/dev-activation-source-bank-plan/1.0",
        "scientific_role": "POST_DEV_DIAGNOSTIC_ORACLE_BANK_NOT_SELECTION_OR_HELDOUT_EVIDENCE",
    }
    chronology = {
        "schema": "trimem/dev-activation-chronology-cache/1.0",
        "status": "COMPLETE_CACHED_PUBLIC_EVIDENCE",
        "sources": sources,
        "targets": target_cache,
    }
    return plan, development, grader, rows, chronology


def _build(*, payload_root: Path | None = None):
    plan, development, grader, rows, chronology = _fixture()
    bank, payloads = source_bank.build_source_bank(
        plan,
        development,
        grader,
        rows,
        chronology,
        chronology_raw_sha256=source_bank.canonical_sha256(chronology),
        payload_root=payload_root,
    )
    return bank, payloads, development


def test_builder_produces_twelve_target_disjoint_verified_assignments(tmp_path: Path) -> None:
    bank, payloads, development = _build(payload_root=tmp_path)
    assert bank["status"] == "FROZEN_VERIFIED_TARGET_DISJOINT"
    assert bank["scientific_role"] == (
        "POST_DEV_DIAGNOSTIC_ORACLE_BANK_NOT_SELECTION_OR_HELDOUT_EVIDENCE"
    )
    assert bank["covered_target_count"] == 12
    assert len(bank["candidate_assignments"]) == 12
    assert bank["record_count"] == 12
    assert all(row["candidate_count"] == 1 for row in bank["candidate_assignments"])
    assert all(row["changed_paths"] for row in bank["records"])
    assert all(row["source_row_sha256"] for row in bank["records"])
    assert all(row["source_fix_verification_signal"] == "UPSTREAM_MERGED_FIX_PATCH_EQUIVALENT" for row in bank["records"])
    assert all(row["target_derived"] is False for row in bank["records"])
    assert bank["accounting"] == {
        "model_calls": 0,
        "paid_model_calls": 0,
        "grader_containers": 0,
        "official_grader_runs": 0,
    }
    source_bank.validate_source_bank(bank, development=development, payloads=payloads)
    assert all((tmp_path / relative).read_bytes() == raw for relative, raw in payloads.items())


def test_target_rows_are_excluded_before_source_patch_access() -> None:
    # Fixture target rows intentionally omit patch/fix_patch.  Successful build proves
    # those fields were never used for target-derived feature or payload construction.
    bank, payloads, development = _build()
    target_instances = {row["instance_id"] for row in development["targets"]}
    assert all(
        not any(record["source_task_id"].endswith("--" + target) for target in target_instances)
        for record in bank["records"]
    )
    combined_payload = b"\n".join(payloads.values())
    assert b"target_gold" not in combined_payload
    assert b"test_patch" not in combined_payload


def test_public_target_projection_ignores_patch_tests_and_outcomes() -> None:
    row = {
        "problem_statement": "Public issue text",
        "patch": "SECRET GOLD A",
        "test_patch": "SECRET TEST A",
        "FAIL_TO_PASS": ["secret"],
    }
    changed = deepcopy(row)
    changed.update(
        {
            "patch": "SECRET GOLD B",
            "test_patch": "SECRET TEST B",
            "FAIL_TO_PASS": ["different"],
        }
    )
    assert source_bank.public_issue_text("swebench_verified", row) == "Public issue text"
    assert source_bank.public_issue_text("swebench_verified", changed) == "Public issue text"
    assert source_bank._target_projection(  # noqa: SLF001 - contract-level unit test
        source_bank.public_issue_text("swebench_verified", row)
    ) == source_bank._target_projection(  # noqa: SLF001
        source_bank.public_issue_text("swebench_verified", changed)
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing_source_cache", "SOURCE_CHRONOLOGY_OR_VERSION_UNKNOWN"),
        ("unknown_ancestry", "VERSION_ANCESTRY_NOT_PROVEN"),
        ("late_source", "SOURCE_NOT_STRICTLY_BEFORE_TARGET"),
        ("unverified_patch", "SOURCE_FIX_PATCH_NOT_VERIFIED"),
    ],
)
def test_unknown_or_failed_chronology_version_and_fix_evidence_fail_coverage(
    mutation: str, reason: str
) -> None:
    plan, development, grader, rows, chronology = _fixture()
    if mutation == "missing_source_cache":
        chronology["sources"].pop(0)
    elif mutation == "unknown_ancestry":
        chronology["sources"][0]["ancestry"][0]["status"] = "UNKNOWN"
    elif mutation == "late_source":
        chronology["sources"][0]["source_issue"]["closed_at"] = "2025-01-01T00:00:00Z"
    else:
        chronology["sources"][0]["patch_equivalence"]["status"] = "UNKNOWN"
    bank, payloads = source_bank.build_source_bank(
        plan,
        development,
        grader,
        rows,
        chronology,
        chronology_raw_sha256=source_bank.canonical_sha256(chronology),
    )
    assert bank["covered_target_count"] == 11
    assert bank["zero_candidate_target_ids"] == [development["targets"][0]["target_id"]]
    assert any(reason in key for key in bank["eligibility_rejection_histogram"])
    source_bank.validate_source_bank(bank, development=development, payloads=payloads)


def test_same_repository_gate_never_falls_back_cross_repository() -> None:
    plan, development, grader, rows, chronology = _fixture()
    first_source = rows[source_bank.REQUIRED_DATASETS[0]][1]
    first_source["repo"] = "different/repository"
    chronology["sources"][0]["repository"] = "different/repository"
    chronology["sources"][0]["source_row_sha256"] = source_bank.canonical_sha256(first_source)
    bank, payloads = source_bank.build_source_bank(
        plan,
        development,
        grader,
        rows,
        chronology,
        chronology_raw_sha256=source_bank.canonical_sha256(chronology),
    )
    assert bank["covered_target_count"] == 11
    assert bank["zero_candidate_target_ids"] == [development["targets"][0]["target_id"]]
    source_bank.validate_source_bank(bank, development=development, payloads=payloads)


def test_source_feature_compiler_is_deterministic_and_rejects_unsafe_paths() -> None:
    patch = (
        "diff --git a/src/client.py b/src/client.py\n"
        "--- a/src/client.py\n+++ b/src/client.py\n"
        "@@ -1 +1 @@\n-def old(): pass\n+def parse_value(): return Client.call()\n"
    )
    first = source_bank.compile_source_features(
        "`parse_value` handles Client.call ValueError", patch
    )
    second = source_bank.compile_source_features(
        "`parse_value` handles Client.call ValueError", patch
    )
    assert first == second
    assert first["changed_paths"] == ["src/client.py"]
    assert "parse_value" in first["symbols"]
    assert "Client.call" in first["apis"]
    assert "ValueError" in first["errors"]
    with pytest.raises(source_bank.SourceBankError, match="unsafe changed path"):
        source_bank.changed_paths_from_patch("+++ b/../../secret\n")


def test_rank_tie_break_is_source_identity_and_partial_coverage_is_valid() -> None:
    candidates = [
        {
            "memory_id": "b",
            "source_task_id": "source-b",
            "score": {name: 0 for name in (
                "errors_overlap", "apis_overlap", "symbols_overlap", "paths_overlap", "tokens_overlap"
            )},
        },
        {
            "memory_id": "a",
            "source_task_id": "source-a",
            "score": {name: 0 for name in (
                "errors_overlap", "apis_overlap", "symbols_overlap", "paths_overlap", "tokens_overlap"
            )},
        },
    ]
    assert [row["source_task_id"] for row in sorted(candidates, key=source_bank._rank_key)] == [  # noqa: SLF001
        "source-a",
        "source-b",
    ]

    plan, development, grader, rows, chronology = _fixture()
    chronology["sources"].pop(0)
    bank, payloads = source_bank.build_source_bank(
        plan,
        development,
        grader,
        rows,
        chronology,
        chronology_raw_sha256=source_bank.canonical_sha256(chronology),
    )
    assert bank["covered_target_count"] == 11
    assert bank["candidate_assignments"][0]["candidate_count"] == 0
    source_bank.validate_source_bank(bank, development=development, payloads=payloads)
    drifted = deepcopy(bank)
    drifted["covered_target_count"] = 12
    with pytest.raises(source_bank.SourceBankError, match="covered-target count drift"):
        source_bank.validate_source_bank(drifted, development=development, payloads=payloads)


def test_pinned_dataset_hash_drift_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "dataset.jsonl"
    path.write_bytes(b"{}\n")
    spec = {
        "benchmark_id": "multi_swe_bench_mini",
        "bytes": 3,
        "sha256": "0" * 64,
    }
    with pytest.raises(source_bank.SourceBankError, match="PINNED_DATASET_DIGEST_DRIFT"):
        source_bank.verify_dataset_file(path, spec)


def test_committed_plan_is_bound_and_preflight_reports_only_zero_call_blockers(
    tmp_path: Path,
) -> None:
    plan, development, grader, specs = source_bank.load_committed_contracts(ROOT)
    assert plan["source_universe"]["same_repository_required"] is True
    assert plan["eligibility"]["unknown_or_missing_signal"] == "REJECT"
    assert plan["candidate_rule"]["coverage_sufficiency_target_count"] == 12
    assert plan["candidate_rule"]["partial_coverage_execution_allowed"] is True
    assert set(specs) == set(source_bank.REQUIRED_DATASETS)
    result = source_bank.preflight(
        ROOT,
        cache_roots=(tmp_path,),
        chronology_path=tmp_path / "missing-chronology.json",
    )
    assert result["status"] == "BLOCKED_FAIL_CLOSED"
    assert "SOURCE_AND_TARGET_GITHUB_CHRONOLOGY_CACHE_MISSING" in result["blockers"]
    assert result["network_calls"] == 0
    assert result["model_calls"] == 0
    assert result["paid_model_calls"] == 0
    assert result["grader_containers"] == 0
