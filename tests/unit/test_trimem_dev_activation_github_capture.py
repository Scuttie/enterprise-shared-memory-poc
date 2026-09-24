from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_dev_activation_github_capture as capture  # noqa: E402
import trimem_dev_activation_source_bank as source_bank  # noqa: E402
import trimem_benchmark_run as benchmark  # noqa: E402


def _json_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _fake_projections(plan: dict, development: dict) -> dict[str, dict]:
    projections: dict[str, dict] = {}
    problems = plan["source_universe"]["target_problem_objects"]
    for index, (target, problem) in enumerate(zip(development["targets"], problems)):
        title = f"Target issue {index}"
        instruction = f"{title}\n\nPublic target report only."
        projections[target["target_id"]] = {
            "target_id": target["target_id"],
            "source_row_sha256": target["source_row_sha256"],
            "public_instruction": instruction,
            "public_instruction_sha256": hashlib.sha256(
                instruction.encode("utf-8")
            ).hexdigest(),
            "problem_number_from_row": (
                None
                if target["benchmark_id"] == "swebench_verified"
                else problem["issue_number"]
            ),
            "problem_title_from_row": title,
        }
    return projections


def _fake_responses(plan: dict, development: dict) -> dict[tuple[str, str], bytes]:
    responses: dict[tuple[str, str], bytes] = {}
    projections = _fake_projections(plan, development)
    for index, (target, source, problem) in enumerate(
        zip(
            development["targets"],
            plan["source_universe"]["oracle_source_prs"],
            plan["source_universe"]["target_problem_objects"],
        )
    ):
        repository = source["repository"]
        pull_number = source["pull_number"]
        merge_commit = hashlib.sha1(f"merge:{index}".encode()).hexdigest()
        source_base = hashlib.sha1(f"base:{index}".encode()).hexdigest()
        target_url = problem["url"]
        pull_url = f"https://api.github.com/repos/{repository}/pulls/{pull_number}"
        commit_url = f"https://api.github.com/repos/{repository}/commits/{merge_commit}"
        compare_url = (
            f"https://api.github.com/repos/{repository}/compare/"
            f"{merge_commit}...{target['base_commit']}"
        )
        title = projections[target["target_id"]]["problem_title_from_row"]
        if problem["tracker"] == "DJANGO_TRAC":
            responses[(target_url, capture.HTML_ACCEPT)] = (
                b"<html><script>var old_values="
                + _json_bytes(
                    {
                        "id": problem["issue_number"],
                        "summary": title,
                        "time": "2025-01-01T00:00:00Z",
                    }
                )
                + b";</script></html>"
            )
        else:
            responses[(target_url, capture.JSON_ACCEPT)] = _json_bytes(
                {
                    "number": problem["issue_number"],
                    "repository_url": f"https://api.github.com/repos/{repository}",
                    "html_url": (
                        f"https://github.com/{repository}/issues/"
                        f"{problem['issue_number']}"
                    ),
                    "title": title,
                    "body": "Public target report only.",
                    "created_at": "2025-01-01T00:00:00Z",
                }
            )
        responses[(pull_url, capture.JSON_ACCEPT)] = _json_bytes(
            {
                "number": pull_number,
                "html_url": f"https://github.com/{repository}/pull/{pull_number}",
                "title": f"Historical source {index}",
                "body": "Fix `Client.call` behavior after ValueError.",
                "base": {"sha": source_base, "repo": {"full_name": repository}},
                "merge_commit_sha": merge_commit,
                "merged_at": "2024-01-02T00:00:00Z",
                "closed_at": "2024-01-03T00:00:00Z",
            }
        )
        responses[(pull_url, capture.DIFF_ACCEPT)] = (
            "diff --git a/src/widget.py b/src/widget.py\n"
            "--- a/src/widget.py\n"
            "+++ b/src/widget.py\n"
            "@@ -1 +1 @@\n-old()\n+Client.call()\n"
        ).encode("utf-8")
        responses[(commit_url, capture.JSON_ACCEPT)] = _json_bytes(
            {
                "sha": merge_commit,
                "commit": {
                    "author": {"date": "2024-01-02T00:00:01Z"},
                    "committer": {"date": "2024-01-02T00:00:02Z"},
                },
            }
        )
        responses[(compare_url, capture.JSON_ACCEPT)] = _json_bytes(
            {
                "status": "ahead",
                "ahead_by": index + 1,
                "behind_by": 0,
                "base_commit": {"sha": merge_commit},
            }
        )
    return responses


def _contracts():
    return source_bank.load_committed_contracts(ROOT)


def test_raw_github_evidence_is_git_binary_for_cross_platform_hash_stability() -> None:
    paths = [
        "artifacts/trimem_v1/dev_activation_diagnostic/github_raw/"
        + "0" * 64
        + extension
        for extension in (".json", ".diff", ".html")
    ]
    result = subprocess.run(
        ["git", "check-attr", "text", "--", *paths],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert len(rows) == 3
    assert all(row.endswith(": text: unset") for row in rows)


def test_committed_target_problem_objects_are_true_non_pr_public_objects() -> None:
    plan, development, _grader, _specs = _contracts()
    chronology_path = ROOT / source_bank.CHRONOLOGY_PATH
    chronology = source_bank.strict_json_load(chronology_path)
    evidence = source_bank.evidence_blobs_from_cache(chronology_path, chronology)
    manifest = source_bank.strict_json_load(ROOT / source_bank.OUTPUT_MANIFEST)
    assignments = {
        row["target_id"]: row for row in manifest["candidate_assignments"]
    }
    problems = {
        row["target_id"]: row
        for row in plan["source_universe"]["target_problem_objects"]
    }

    assert len(chronology["targets"]) == 12
    assert len(assignments) == 12
    assert len(problems) == 12
    github_count = 0
    trac_count = 0
    for target, entry in zip(development["targets"], chronology["targets"]):
        target_id = target["target_id"]
        problem = entry["problem_object"]
        assert problem["issue_number"] != int(target["instance_id"].rsplit("-", 1)[1])
        assert {
            key: problem[key] for key in ("tracker", "issue_number", "url")
        } == {
            key: problems[target_id][key] for key in ("tracker", "issue_number", "url")
        }
        assert assignments[target_id]["target_public_instruction_sha256"] == (
            hashlib.sha256(entry["public_instruction"].encode("utf-8")).hexdigest()
        )
        assert assignments[target_id]["target_problem_provenance_sha256"] == (
            source_bank.canonical_sha256(entry)
        )
        raw = evidence[problem["path"]]
        if problem["tracker"] == "GITHUB_ISSUE":
            github_count += 1
            issue = json.loads(raw)
            assert "pull_request" not in issue
            assert issue["number"] == problem["issue_number"]
            assert issue["created_at"] == problem["first_published_at"]
        else:
            trac_count += 1
            ticket = source_bank.parse_django_trac_ticket(
                raw, expected_number=problem["issue_number"]
            )
            assert ticket["created_at"] == problem["first_published_at"]
    assert github_count == 11
    assert trac_count == 1


def test_public_capture_and_oracle_build_cover_all_frozen_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, development, grader, specs = _contracts()
    responses = _fake_responses(plan, development)
    calls: list[tuple[str, str]] = []

    def fake_fetch(url: str, accept: str) -> bytes:
        calls.append((url, accept))
        return responses[(url, accept)]

    monkeypatch.setattr(
        capture,
        "load_committed_contracts",
        lambda _root: (plan, development, grader, specs),
    )
    monkeypatch.setattr(
        capture,
        "_load_target_problem_projections",
        lambda *_args, **_kwargs: _fake_projections(plan, development),
    )
    chronology_path = tmp_path / "chronology.json"
    chronology, invocation = capture.capture_public_evidence(
        root=ROOT,
        output_path=chronology_path,
        fetcher=fake_fetch,
        observed_at="2026-01-01T00:00:00Z",
    )
    assert invocation == {"network_requests": 60, "cache_hits": 0}
    assert len(calls) == 60
    assert chronology["coverage"] == {
        "source_entries": 12,
        "target_entries": 12,
        "frozen_target_count": 12,
    }
    assert chronology["accounting"]["public_evidence_responses"] == 60
    assert chronology["accounting"]["public_github_responses"] == 59
    assert chronology["accounting"]["public_django_trac_responses"] == 1
    evidence = source_bank.evidence_blobs_from_cache(chronology_path, chronology)
    bank, payloads = source_bank.build_oracle_source_bank(
        plan,
        development,
        chronology,
        evidence,
        chronology_raw_sha256=source_bank.file_sha256(chronology_path),
    )
    assert bank["covered_target_count"] == 12
    assert bank["zero_candidate_target_ids"] == []
    assert bank["record_count"] == 12
    assert all(row["bank_type"] == "ORG_SEMANTIC" for row in bank["records"])
    assert all(row["path_scope"] == "**" for row in bank["records"])
    assert all(
        "target_public_instruction_sha256" in row
        and "target_problem_provenance_sha256" in row
        for row in bank["candidate_assignments"]
    )
    assert all(
        target["problem_object"]["issue_number"]
        != int(target["target_id"].rsplit("-", 1)[1])
        for target in chronology["targets"]
    )
    source_bank.validate_source_bank(
        bank,
        development=development,
        payloads=payloads,
        plan=plan,
    )


def test_runtime_public_instruction_projection_is_exact_for_both_benchmarks() -> None:
    swe = {
        "problem_statement": " Public issue statement with exact whitespace. \n",
    }
    multi = {
        "title": "Public task title",
        "body": "Public task body.\r\n",
        "resolved_issues": [
            {"number": 17, "title": "Issue title", "body": "Issue body.\r\n"}
        ],
    }
    assert source_bank.public_issue_text("swebench_verified", swe) == benchmark.public_instruction(
        swe, "swebench_verified"
    )
    assert source_bank.public_issue_text(
        "multi_swe_bench_mini", multi
    ) == benchmark.public_instruction(multi, "multi_swe_bench_mini")


def test_target_issue_endpoint_with_pull_request_member_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, development, grader, specs = _contracts()
    responses = _fake_responses(plan, development)
    problem = plan["source_universe"]["target_problem_objects"][1]
    target = development["targets"][1]
    poisoned = json.loads(responses[(problem["url"], capture.JSON_ACCEPT)])
    poisoned["pull_request"] = {
        "url": f"https://api.github.com/repos/{target['repository']}/pulls/999"
    }
    responses[(problem["url"], capture.JSON_ACCEPT)] = _json_bytes(poisoned)
    monkeypatch.setattr(
        capture,
        "load_committed_contracts",
        lambda _root: (plan, development, grader, specs),
    )
    monkeypatch.setattr(
        capture,
        "_load_target_problem_projections",
        lambda *_args, **_kwargs: _fake_projections(plan, development),
    )
    chronology, _ = capture.capture_public_evidence(
        root=ROOT,
        output_path=tmp_path / "chronology.json",
        fetcher=lambda url, accept: responses[(url, accept)],
        observed_at="2026-01-01T00:00:00Z",
    )
    rejection = next(
        row
        for row in chronology["rejections"]
        if row["target_id"] == target["target_id"]
        and row["phase"] == "TARGET_PUBLIC_EVIDENCE"
    )
    assert rejection["reason_code"] == "TARGET_PROBLEM_OBJECT_IS_PULL_REQUEST"
    assert all(row["target_id"] != target["target_id"] for row in chronology["targets"])


def test_capture_resume_reuses_every_content_addressed_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, development, grader, specs = _contracts()
    responses = _fake_responses(plan, development)
    monkeypatch.setattr(
        capture,
        "load_committed_contracts",
        lambda _root: (plan, development, grader, specs),
    )
    monkeypatch.setattr(
        capture,
        "_load_target_problem_projections",
        lambda *_args, **_kwargs: _fake_projections(plan, development),
    )
    chronology_path = tmp_path / "chronology.json"
    first, _ = capture.capture_public_evidence(
        root=ROOT,
        output_path=chronology_path,
        fetcher=lambda url, accept: responses[(url, accept)],
        observed_at="2026-01-01T00:00:00Z",
    )
    frozen_bytes = chronology_path.read_bytes()

    def forbidden_fetch(_url: str, _accept: str) -> bytes:
        raise AssertionError("resume reissued an already cached public request")

    second, invocation = capture.capture_public_evidence(
        root=ROOT,
        output_path=chronology_path,
        fetcher=forbidden_fetch,
        observed_at="2026-01-02T00:00:00Z",
    )
    assert invocation == {"network_requests": 0, "cache_hits": 60}
    assert second["sources"] == first["sources"]
    assert second["targets"] == first["targets"]
    assert second["request_cache"] == first["request_cache"]
    assert chronology_path.read_bytes() == frozen_bytes


def test_failed_candidate_is_preserved_as_zero_candidate_assignment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, development, grader, specs = _contracts()
    responses = _fake_responses(plan, development)
    failed_target = development["targets"][8]
    failed_source = plan["source_universe"]["oracle_source_prs"][8]
    failed_merge = hashlib.sha1(b"merge:8").hexdigest()
    failed_compare = (
        f"https://api.github.com/repos/{failed_source['repository']}/compare/"
        f"{failed_merge}...{failed_target['base_commit']}"
    )

    def partial_fetch(url: str, accept: str) -> bytes:
        if url == failed_compare:
            raise capture.CaptureError("GITHUB_HTTP_503")
        return responses[(url, accept)]

    monkeypatch.setattr(
        capture,
        "load_committed_contracts",
        lambda _root: (plan, development, grader, specs),
    )
    monkeypatch.setattr(
        capture,
        "_load_target_problem_projections",
        lambda *_args, **_kwargs: _fake_projections(plan, development),
    )
    chronology_path = tmp_path / "chronology.json"
    chronology, _ = capture.capture_public_evidence(
        root=ROOT,
        output_path=chronology_path,
        fetcher=partial_fetch,
        observed_at="2026-01-01T00:00:00Z",
    )
    evidence = source_bank.evidence_blobs_from_cache(chronology_path, chronology)
    bank, _ = source_bank.build_oracle_source_bank(
        plan,
        development,
        chronology,
        evidence,
        chronology_raw_sha256=source_bank.file_sha256(chronology_path),
    )
    assert bank["covered_target_count"] == 11
    assert bank["zero_candidate_target_ids"] == [failed_target["target_id"]]
    failed_assignment = bank["candidate_assignments"][8]
    assert failed_assignment["candidate_count"] == 0
    assert failed_assignment["candidates"] == []


def test_oracle_plan_rejects_legacy_bank_and_payload_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, development, _grader, _specs = _contracts()
    fake_bank = {
        "source_bank_plan_sha256": source_bank.canonical_sha256(plan),
        "schema": "wrong",
    }
    with pytest.raises(source_bank.SourceBankError, match="schema drift"):
        source_bank.validate_source_bank(fake_bank, development=development, plan=plan)

    link = tmp_path / source_bank.PAYLOAD_DIRECTORY / ("a" * 64 + ".json")
    link.parent.mkdir()
    link.write_bytes(b"{}")
    path_type = type(link)
    original_is_symlink = path_type.is_symlink
    monkeypatch.setattr(
        path_type,
        "is_symlink",
        lambda self: self == link or original_is_symlink(self),
    )
    manifest = tmp_path / "manifest.json"
    bank = {
        "records": [
            {
                "payload_path": (
                    f"{source_bank.PAYLOAD_DIRECTORY}/{'a' * 64}.json"
                )
            }
        ]
    }
    with pytest.raises(source_bank.SourceBankError, match="symlink"):
        source_bank._payloads_from_manifest(manifest, bank)
