from __future__ import annotations

from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_grader_smoke_trigger_preflight as trigger  # noqa: E402
import trimem_evidence_inventory as inventory  # noqa: E402


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _write_json(path: Path, value: object) -> bytes:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _initialize(repository: Path, *, workflow_text: str | None = None) -> str:
    repository.mkdir()
    _git(repository, "init", "-b", "codex/trimem-coder-v1")
    _git(repository, "config", "user.name", "TriMem Test")
    _git(repository, "config", "user.email", "trimem@example.invalid")
    workflow = repository / trigger.WORKFLOW_PATH
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        workflow_text
        if workflow_text is not None
        else (ROOT / trigger.WORKFLOW_PATH).read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    # The one-time amendment is permitted to alter execution control only.
    # Copy the exact scientific baseline bytes so the fixture exercises the
    # production pin rather than manufacturing a second, synthetic baseline.
    for path in (
        trigger.FROZEN_REQUEST_PATH,
        trigger.MANIFEST_PATH,
        trigger.IMAGE_LOCK_PATH,
        trigger.CREDENTIAL_FREE_BUNDLE_PATH,
    ):
        destination = repository / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / path).read_bytes())
    historical_sentinel_path = getattr(trigger, "HISTORICAL_SENTINEL_PATH", None)
    if historical_sentinel_path is not None:
        historical = repository / historical_sentinel_path
        historical.parent.mkdir(parents=True, exist_ok=True)
        historical.write_bytes((ROOT / historical_sentinel_path).read_bytes())
    for path in (
        trigger.PREFLIGHT_PATH,
        trigger.INVENTORY_PATH,
        trigger.PROTOCOL_PATH,
    ):
        destination = repository / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / path).read_bytes())
    closure = {}
    closure_paths = [
        trigger.WORKFLOW_PATH,
        trigger.FROZEN_REQUEST_PATH,
        trigger.MANIFEST_PATH,
        trigger.IMAGE_LOCK_PATH,
        trigger.CREDENTIAL_FREE_BUNDLE_PATH,
        trigger.PREFLIGHT_PATH,
        trigger.INVENTORY_PATH,
        trigger.PROTOCOL_PATH,
    ]
    if historical_sentinel_path is not None:
        closure_paths.append(historical_sentinel_path)
    for path in closure_paths:
        raw = (repository / path).read_bytes()
        closure[path] = {
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    _write_json(
        repository / trigger.FREEZE_PATH,
        {"files": closure, "schema": "trimem/freeze/1.0"},
    )
    return _commit(repository, "base")


def _rehash(document: dict[str, object]) -> None:
    payload = {key: value for key, value in document.items() if key != "request_sha256"}
    document["request_sha256"] = trigger.sha256_prefixed(trigger.canonical_bytes(payload))


def _event(before: str, after: str) -> dict[str, object]:
    """Mirror the Actions push payload shape observed by the failed first run.

    GitHub's Actions event file retained commit identities but did not include
    the webhook-only ``added``/``modified``/``removed`` arrays.  File-set
    authority must therefore come from the checked-out Git objects.
    """

    commit = {
        "author": {"email": "trimem@example.invalid", "name": "TriMem Test"},
        "committer": {"email": "trimem@example.invalid", "name": "TriMem Test"},
        "distinct": True,
        "id": after,
        "message": "one-time grader smoke trigger",
        "timestamp": "2026-09-01T13:35:31+09:00",
        "tree_id": "f" * 40,
        "url": f"https://github.com/Scuttie/enterprise-shared-memory-poc/commit/{after}",
    }
    return {
        "after": after,
        "base_ref": None,
        "before": before,
        "commits": [commit],
        "compare": (
            "https://github.com/Scuttie/enterprise-shared-memory-poc/compare/"
            f"{before}...{after}"
        ),
        "created": False,
        "deleted": False,
        "forced": False,
        "head_commit": deepcopy(commit),
        "ref": trigger.EXPECTED_REF,
    }


def _environment(after: str) -> dict[str, str]:
    return {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": trigger.EXPECTED_REF,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": after,
    }


def _trigger_repository(
    tmp_path: Path,
    *,
    mutate: Callable[[dict[str, object]], None] | None = None,
    raw_transform: Callable[[bytes], bytes] | None = None,
    workflow_text: str | None = None,
    extra_path: bool = False,
) -> tuple[Path, Path, str, str, dict[str, str]]:
    repository = tmp_path / "repository"
    before = _initialize(repository, workflow_text=workflow_text)
    document: dict[str, object] = trigger.build_request_document(
        repository,
        source_head=before,
    )
    if mutate is not None:
        mutate(document)
        _rehash(document)
    raw = trigger.canonical_bytes(document, trailing_lf=True)
    if raw_transform is not None:
        raw = raw_transform(raw)
    sentinel = repository / trigger.SENTINEL_PATH
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_bytes(raw)
    if extra_path:
        (repository / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    after = _commit(repository, "one-time grader smoke trigger")
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(_event(before, after), sort_keys=True),
        encoding="utf-8",
    )
    return repository, event_path, before, after, _environment(after)


def _write_event(path: Path, before: str, after: str) -> Path:
    path.write_text(
        json.dumps(_event(before, after), sort_keys=True),
        encoding="utf-8",
    )
    return path


def _write_active_sentinel(
    repository: Path,
    *,
    source_head: str,
    material_commit: str | None = None,
) -> None:
    document = trigger.build_request_document(
        repository,
        source_head=source_head,
        commit=material_commit,
    )
    target = repository / trigger.SENTINEL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(trigger.canonical_bytes(document, trailing_lf=True))


def _git_contract_negative(
    tmp_path: Path, case: str
) -> tuple[Path, Path, dict[str, str]]:
    """Create one authoritative-Git/event negative while keeping file arrays absent."""

    repository = tmp_path / "repository"
    before = _initialize(repository)

    if case == "sentinel_plus_another_file":
        _write_active_sentinel(repository, source_head=before)
        (repository / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        after = _commit(repository, "sentinel plus another file")
    elif case == "sentinel_modified":
        _write_active_sentinel(repository, source_head=before)
        before = _commit(repository, "pre-existing active sentinel")
        _write_active_sentinel(repository, source_head=before)
        after = _commit(repository, "modify active sentinel")
    elif case == "old_sentinel_touched":
        historical_path = trigger.HISTORICAL_SENTINEL_PATH
        _write_active_sentinel(repository, source_head=before)
        historical = repository / historical_path
        historical.write_bytes(historical.read_bytes() + b"tampered\n")
        after = _commit(repository, "touch historical and active sentinels")
    elif case == "two_commits_between":
        (repository / "intermediate.txt").write_text("intermediate\n", encoding="utf-8")
        intermediate = _commit(repository, "intermediate commit")
        _write_active_sentinel(
            repository,
            source_head=before,
            material_commit=intermediate,
        )
        after = _commit(repository, "sentinel after intermediate commit")
    elif case == "merge_commit":
        _git(repository, "checkout", "-b", "sentinel-side")
        _write_active_sentinel(repository, source_head=before)
        _commit(repository, "sentinel side commit")
        _git(repository, "checkout", "codex/trimem-coder-v1")
        _git(repository, "merge", "--no-ff", "sentinel-side", "-m", "merge sentinel")
        after = _git(repository, "rev-parse", "HEAD")
    elif case == "wrong_parent":
        _git(repository, "checkout", "-b", "event-before")
        (repository / "event-before.txt").write_text("sibling\n", encoding="utf-8")
        event_before = _commit(repository, "event before sibling")
        _git(repository, "checkout", "codex/trimem-coder-v1")
        _write_active_sentinel(
            repository,
            source_head=event_before,
            material_commit=before,
        )
        after = _commit(repository, "sentinel with different parent")
        before = event_before
    else:
        _write_active_sentinel(repository, source_head=before)
        after = _commit(repository, "one-time grader smoke trigger")

    event_path = _write_event(tmp_path / "event.json", before, after)
    event = json.loads(event_path.read_bytes())
    environment = _environment(after)
    if case == "wrong_branch":
        event["ref"] = "refs/heads/main"
        environment["GITHUB_REF"] = "refs/heads/main"
    elif case == "forced_push":
        event["forced"] = True
    elif case == "deleted_push":
        event["deleted"] = True
    event_path.write_text(json.dumps(event, sort_keys=True), encoding="utf-8")
    return repository, event_path, environment


def test_workflow_has_exact_branch_sentinel_trigger_and_no_model_secret() -> None:
    workflow = (ROOT / trigger.WORKFLOW_PATH).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "push:" in workflow
    assert "      - codex/trimem-coder-v1" in workflow
    assert f"      - {trigger.SENTINEL_PATH}" in workflow
    assert "branch-trigger-preflight:" in workflow
    assert "needs: branch-trigger-preflight" in workflow
    assert "needs.branch-trigger-preflight.result == 'success'" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "environment: trimem-grader-smoke-exec" in workflow
    assert "ref: ${{ github.sha }}" in workflow
    assert "OPENAI_API_KEY" not in workflow
    assert workflow.index("trimem_evidence_inventory.py") < workflow.index(
        "openssl enc -aes-256-cbc"
    )
    assert "trimem-grader-smoke-evidence-inventory" in workflow
    assert "rm -f -- \"$RUNNER_TEMP/trimem-grader-smoke-evidence-inventory.json\"" in workflow
    assert set(
        re.findall(r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)", workflow)
    ) == trigger.ALLOWED_WORKFLOW_SECRETS


def test_actual_actions_payload_without_commit_file_arrays_passes(
    tmp_path: Path,
) -> None:
    repository, event_path, before, after, environment = _trigger_repository(tmp_path)
    event = json.loads(event_path.read_bytes())
    for commit in (event["commits"][0], event["head_commit"]):
        assert {"added", "modified", "removed"}.isdisjoint(commit)
    report = trigger.validate_branch_trigger(
        repository,
        event_path,
        environ=environment,
    )
    assert report == {
        "actual_execution_authorized": False,
        "freeze_sha256": json.loads(
            (repository / trigger.SENTINEL_PATH).read_text(encoding="utf-8")
        )["freeze_sha256"],
        "grader_containers": 12,
        "model_calls": 0,
        "paid_model_calls": 0,
        "phase": "GRADER_SMOKE",
        "request_id": trigger.REQUEST_ID,
        "request_sha256": json.loads(
            (repository / trigger.SENTINEL_PATH).read_text(encoding="utf-8")
        )["request_sha256"],
        "requires_external_approval": True,
        "source_head": before,
        "status": "PASS",
        "trigger_commit": after,
    }


def test_event_validator_source_never_reads_non_authoritative_file_arrays() -> None:
    source = inspect.getsource(trigger._validate_event_shape)
    assert re.findall(
        r"\.get\(\s*['\"](added|modified|removed)['\"]\s*\)", source
    ) == []


def test_rerun_attempt_two_fails_closed(tmp_path: Path) -> None:
    repository, event_path, _, _, environment = _trigger_repository(tmp_path)
    environment["GITHUB_RUN_ATTEMPT"] = "2"
    with pytest.raises(trigger.TriggerPreflightError, match="rerun attempt"):
        trigger.validate_branch_trigger(
            repository,
            event_path,
            environ=environment,
        )


@pytest.mark.parametrize(
    ("case", "message"),
    [
        pytest.param(
            "sentinel_plus_another_file", "sentinel|trigger commit", id="01-sentinel-plus-another-file"
        ),
        pytest.param(
            "sentinel_modified", "sentinel|trigger commit", id="02-sentinel-modified"
        ),
        pytest.param(
            "old_sentinel_touched", "sentinel|trigger commit", id="03-old-sentinel-touched"
        ),
        pytest.param(
            "two_commits_between", "one non-merge commit|parent", id="04-two-commits"
        ),
        pytest.param("merge_commit", "one non-merge commit|merge", id="05-merge"),
        pytest.param("wrong_parent", "one non-merge commit|parent", id="06-wrong-parent"),
        pytest.param("wrong_branch", "branch|GITHUB_REF", id="07-wrong-branch"),
        pytest.param("forced_push", "forced", id="08-forced"),
        pytest.param("deleted_push", "deletion|deleted", id="09-deleted"),
    ],
)
def test_required_negative_git_and_event_contracts_fail_closed(
    tmp_path: Path, case: str, message: str
) -> None:
    repository, event_path, environment = _git_contract_negative(tmp_path, case)
    event = json.loads(event_path.read_bytes())
    for commit in (event["commits"][0], event["head_commit"]):
        assert {"added", "modified", "removed"}.isdisjoint(commit)
    with pytest.raises(trigger.TriggerPreflightError, match=message):
        trigger.validate_branch_trigger(
            repository,
            event_path,
            environ=environment,
        )


def test_request_hash_covers_exact_canonical_content(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    source_head = _initialize(repository)
    document = trigger.build_request_document(
        repository,
        source_head=source_head,
    )
    payload = {key: value for key, value in document.items() if key != "request_sha256"}
    assert set(document) == trigger.REQUEST_FIELDS
    assert document["request_id"] == trigger.REQUEST_ID
    assert document["request_path"] == trigger.SENTINEL_PATH
    assert document["branch_ref"] == trigger.EXPECTED_REF
    assert document["workflow_path"] == trigger.WORKFLOW_PATH
    assert document["phase"] == "GRADER_SMOKE"
    assert document["hard_caps"] == trigger.HARD_CAPS
    assert document["model_secret_required"] is False
    assert document["actual_execution_authorized"] is False
    assert document["requires_external_approval"] is True
    assert document["authorization_semantics"] == trigger.AUTHORIZATION_SEMANTICS
    assert document["frozen_request_sha256"] == trigger.sha256_prefixed(
        (repository / trigger.FROZEN_REQUEST_PATH).read_bytes()
    )
    assert document["freeze_sha256"] == trigger.sha256_prefixed(
        (repository / trigger.FREEZE_PATH).read_bytes()
    )
    assert document["grader_smoke_manifest_sha256"] == trigger.sha256_prefixed(
        (repository / trigger.MANIFEST_PATH).read_bytes()
    )
    assert document["grader_image_lock_sha256"] == trigger.sha256_prefixed(
        (repository / trigger.IMAGE_LOCK_PATH).read_bytes()
    )
    assert document["credential_free_bundle_sha256"] == trigger.sha256_prefixed(
        (repository / trigger.CREDENTIAL_FREE_BUNDLE_PATH).read_bytes()
    )
    assert document["noop_baseline_patch_sha256"] == hashlib.sha256(
        trigger.NOOP_BASELINE_PATCH
    ).hexdigest()
    assert len(document["matrix_order"]) == 12
    assert document["unique_instances"] == 6
    assert document["matrix_rows"] == 12
    assert document["request_sha256"] == trigger.sha256_prefixed(
        trigger.canonical_bytes(payload)
    )
    assert trigger.canonical_bytes(document, trailing_lf=True).endswith(b"\n")


def test_frozen_image_lock_bytes_are_pinned_before_target_pair_validation(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    _initialize(repository)
    lock_path = repository / trigger.IMAGE_LOCK_PATH
    image_lock = json.loads(lock_path.read_bytes())
    image_lock["targets"][0]["target_ids"].reverse()
    lock_raw = _write_json(lock_path, image_lock)
    freeze_path = repository / trigger.FREEZE_PATH
    freeze = json.loads(freeze_path.read_bytes())
    freeze["files"][trigger.IMAGE_LOCK_PATH] = {
        "bytes": len(lock_raw),
        "sha256": hashlib.sha256(lock_raw).hexdigest(),
    }
    _write_json(freeze_path, freeze)
    changed = _commit(repository, "drift image target IDs")
    with pytest.raises(
        trigger.TriggerPreflightError,
        match="grader image lock bytes",
    ):
        trigger.build_request_document(repository, source_head=changed)


def test_event_independent_validator_reuses_the_full_contract(tmp_path: Path) -> None:
    repository, _, before, after, _ = _trigger_repository(tmp_path)
    raw = (repository / trigger.SENTINEL_PATH).read_bytes()
    value = trigger.validate_request_document(
        repository,
        raw,
        expected_source_head=before,
        material_commit=after,
    )
    assert value["request_id"] == trigger.REQUEST_ID
    assert value["source_head"] == before
    with pytest.raises(trigger.TriggerPreflightError, match="expected correction HEAD"):
        trigger.validate_request_document(
            repository,
            raw,
            expected_source_head="f" * 40,
            material_commit=after,
        )


def test_write_request_renders_only_the_fixed_untracked_sentinel(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    head = _initialize(repository)
    report = trigger.write_request(repository)
    raw = (repository / trigger.SENTINEL_PATH).read_bytes()
    document = json.loads(raw)
    assert report == {
        "bytes": len(raw),
        "path": trigger.SENTINEL_PATH,
        "payload_sha256": document["request_sha256"],
        "request_id": trigger.REQUEST_ID,
        "sentinel_bytes_sha256": trigger.sha256_prefixed(raw),
        "source_head": head,
        "status": "WROTE_ZERO_AUTHORITY_SENTINEL",
    }
    assert raw == trigger.canonical_bytes(document, trailing_lf=True)
    assert _git(
        repository, "status", "--short", "--untracked-files=all"
    ) == f"?? {trigger.SENTINEL_PATH}"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("input_tokens", 1, "input_tokens must be integer zero"),
        ("model_calls", 1, "model_calls must be integer zero"),
        ("output_tokens", 1, "output_tokens must be integer zero"),
        ("paid_model_calls", 1, "paid_model_calls must be integer zero"),
        ("task_arm_runs", 1, "task_arm_runs must be integer zero"),
        ("total_usd", 0.01, "total_usd must be float zero"),
        ("grader_containers", 11, "grader_containers must equal"),
    ],
)
def test_every_cost_authority_must_remain_zero(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    def mutate(document: dict[str, object]) -> None:
        caps = document["hard_caps"]
        assert isinstance(caps, dict)
        caps[field] = value

    repository, event_path, _, _, environment = _trigger_repository(
        tmp_path,
        mutate=mutate,
    )
    with pytest.raises(trigger.TriggerPreflightError, match=message):
        trigger.validate_branch_trigger(repository, event_path, environ=environment)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.__setitem__("phase", "DEVELOPMENT_TUNING"), "phase is not GRADER_SMOKE"),
        (lambda value: value.__setitem__("request_id", "WRONG"), "request identity mismatch"),
        (lambda value: value.__setitem__("model_secret_required", True), "must not require a model secret"),
        (lambda value: value.__setitem__("actual_execution_authorized", True), "must not authorize execution"),
        (lambda value: value.__setitem__("requires_external_approval", False), "must require external approval"),
        (lambda value: value.__setitem__("source_head", "b" * 40), "source_head differs"),
        (lambda value: value.__setitem__("frozen_request_sha256", "sha256:" + "0" * 64), "frozen request hash mismatch"),
        (lambda value: value.__setitem__("freeze_sha256", "sha256:" + "0" * 64), "freeze hash mismatch"),
        (lambda value: value.__setitem__("target_set_sha256", "0" * 64), "target-set hash mismatch"),
        (lambda value: value.__setitem__("noop_baseline_patch_sha256", "0" * 64), "NOOP_BASELINE patch hash mismatch"),
    ],
)
def test_request_identity_and_authority_fail_closed(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], None],
    message: str,
) -> None:
    repository, event_path, _, _, environment = _trigger_repository(
        tmp_path,
        mutate=mutation,
    )
    with pytest.raises(trigger.TriggerPreflightError, match=message):
        trigger.validate_branch_trigger(repository, event_path, environ=environment)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        pytest.param(
            "source_head", "source_head differs", id="10-request-source-head-mismatch"
        ),
        pytest.param(
            "request_hash", "request content hash", id="11-request-hash-mismatch"
        ),
        pytest.param("freeze_hash", "freeze hash", id="12-freeze-hash-mismatch"),
        pytest.param("target_set", "target-set hash", id="14-target-set-hash-mismatch"),
    ],
)
def test_required_negative_request_bindings_fail_closed(
    tmp_path: Path, case: str, message: str
) -> None:
    repository, _, before, after, _ = _trigger_repository(tmp_path)
    document = json.loads((repository / trigger.SENTINEL_PATH).read_bytes())
    if case == "source_head":
        document["source_head"] = "a" * 40
        _rehash(document)
    elif case == "request_hash":
        document["request_sha256"] = "sha256:" + "0" * 64
    elif case == "freeze_hash":
        document["freeze_sha256"] = "sha256:" + "0" * 64
        _rehash(document)
    elif case == "target_set":
        document["target_set_sha256"] = "0" * 64
        _rehash(document)
    else:  # pragma: no cover - parametrization is the closed case set
        raise AssertionError(case)
    raw = trigger.canonical_bytes(document, trailing_lf=True)
    with pytest.raises(trigger.TriggerPreflightError, match=message):
        trigger.validate_request_document(
            repository,
            raw,
            expected_source_head=before,
            material_commit=after,
        )


def test_required_negative_13_nonzero_model_token_or_usd_cap_fails_closed(
    tmp_path: Path,
) -> None:
    repository, _, before, after, _ = _trigger_repository(tmp_path)
    original = json.loads((repository / trigger.SENTINEL_PATH).read_bytes())
    for field, replacement, message in (
        ("model_calls", 1, "model_calls must be integer zero"),
        ("input_tokens", 1, "input_tokens must be integer zero"),
        ("output_tokens", 1, "output_tokens must be integer zero"),
        ("total_usd", 0.01, "total_usd must be float zero"),
    ):
        document = deepcopy(original)
        caps = document["hard_caps"]
        assert isinstance(caps, dict)
        caps[field] = replacement
        _rehash(document)
        with pytest.raises(trigger.TriggerPreflightError, match=message):
            trigger.validate_request_document(
                repository,
                trigger.canonical_bytes(document, trailing_lf=True),
                expected_source_head=before,
                material_commit=after,
            )


def test_every_repository_binding_fails_closed_on_drift(tmp_path: Path) -> None:
    repository, _, before, after, _ = _trigger_repository(tmp_path)
    original = json.loads((repository / trigger.SENTINEL_PATH).read_bytes())
    mutations: list[tuple[str, object, str]] = [
        ("request_path", "wrong.json", "request path mismatch"),
        ("frozen_request_path", "wrong.json", "frozen benchmark request path mismatch"),
        ("branch_ref", "refs/heads/main", "request branch mismatch"),
        ("workflow_path", "wrong.yml", "workflow path mismatch"),
        ("authorization_semantics", "ambiguous", "authorization semantics mismatch"),
        ("grader_smoke_manifest_sha256", "sha256:" + "0" * 64, "manifest raw hash mismatch"),
        ("grader_image_lock_sha256", "sha256:" + "0" * 64, "image-lock raw hash mismatch"),
        ("credential_free_bundle_sha256", "sha256:" + "0" * 64, "bundle raw hash mismatch"),
        ("matrix_kind", "parallel", "matrix kind mismatch"),
        ("matrix_order", list(reversed(original["matrix_order"])), "matrix order mismatch"),
        ("unique_instances", 7, "unique instance count mismatch"),
        ("matrix_rows", 11, "matrix row count mismatch"),
    ]
    for field, replacement, message in mutations:
        changed = deepcopy(original)
        changed[field] = replacement
        _rehash(changed)
        raw = trigger.canonical_bytes(changed, trailing_lf=True)
        with pytest.raises(trigger.TriggerPreflightError, match=message):
            trigger.validate_request_document(
                repository,
                raw,
                expected_source_head=before,
                material_commit=after,
            )


def test_noncanonical_or_wrongly_hashed_request_fails_closed(tmp_path: Path) -> None:
    repository, event_path, _, _, environment = _trigger_repository(
        tmp_path,
        raw_transform=lambda raw: b" " + raw,
    )
    with pytest.raises(trigger.TriggerPreflightError, match="bytes are not canonical"):
        trigger.validate_branch_trigger(repository, event_path, environ=environment)


def test_push_must_change_only_the_new_sentinel(tmp_path: Path) -> None:
    repository, event_path, _, _, environment = _trigger_repository(
        tmp_path,
        extra_path=True,
    )
    with pytest.raises(trigger.TriggerPreflightError, match="sentinel|trigger commit"):
        trigger.validate_branch_trigger(repository, event_path, environ=environment)


def test_exact_branch_ref_is_required(tmp_path: Path) -> None:
    repository, event_path, _, _, environment = _trigger_repository(tmp_path)
    environment["GITHUB_REF"] = "refs/heads/main"
    with pytest.raises(trigger.TriggerPreflightError, match="GITHUB_REF"):
        trigger.validate_branch_trigger(repository, event_path, environ=environment)


def test_sentinel_cannot_be_reused_after_existing_in_history(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    first = _initialize(repository)
    sentinel = repository / trigger.SENTINEL_PATH
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("{}\n", encoding="utf-8")
    _commit(repository, "historical sentinel")
    sentinel.unlink()
    before = _commit(repository, "remove historical sentinel")
    document = trigger.build_request_document(
        repository,
        source_head=before,
    )
    sentinel.write_bytes(trigger.canonical_bytes(document, trailing_lf=True))
    after = _commit(repository, "attempt to reuse sentinel")
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(_event(before, after)), encoding="utf-8")
    assert first != before
    with pytest.raises(trigger.TriggerPreflightError, match="already exists in branch history"):
        trigger.validate_branch_trigger(
            repository,
            event_path,
            environ=_environment(after),
        )


def test_model_secret_reference_or_exposure_fails_closed(tmp_path: Path) -> None:
    workflow = (ROOT / trigger.WORKFLOW_PATH).read_text(encoding="utf-8")
    workflow += "\n# forbidden: ${{ secrets.OPENAI_API_KEY }}\n"
    repository, event_path, _, _, environment = _trigger_repository(
        tmp_path,
        workflow_text=workflow,
    )
    with pytest.raises(trigger.TriggerPreflightError, match="non-control secret"):
        trigger.validate_branch_trigger(repository, event_path, environ=environment)

    clean_root = tmp_path / "clean"
    clean_root.mkdir()
    repository, event_path, _, _, environment = _trigger_repository(clean_root)
    environment["OPENAI_API_KEY"] = "must-not-reach-preflight"
    with pytest.raises(trigger.TriggerPreflightError, match="execution secret is exposed"):
        trigger.validate_branch_trigger(repository, event_path, environ=environment)


def test_restricted_evidence_inventory_is_deterministic_and_content_free(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "restricted"
    (evidence / "nested").mkdir(parents=True)
    (evidence / "z-last.txt").write_bytes(b"last\n")
    (evidence / "nested/a-first.bin").write_bytes(b"\x00secret bytes\xff")
    output = tmp_path / "inventory.json"
    value = inventory.write_inventory(
        evidence,
        output,
        root_label="grader_smoke_exec",
    )
    assert value["schema"] == inventory.SCHEMA
    assert value["root"] == "grader_smoke_exec"
    assert value["files"] == [
        {
            "bytes": len(b"\x00secret bytes\xff"),
            "path": "nested/a-first.bin",
            "sha256": hashlib.sha256(b"\x00secret bytes\xff").hexdigest(),
        },
        {
            "bytes": len(b"last\n"),
            "path": "z-last.txt",
            "sha256": hashlib.sha256(b"last\n").hexdigest(),
        },
    ]
    assert value["total_files"] == 2
    assert value["total_bytes"] == len(b"\x00secret bytes\xff") + len(b"last\n")
    payload = {key: item for key, item in value.items() if key != "inventory_sha256"}
    assert value["inventory_sha256"] == hashlib.sha256(
        inventory._canonical(payload)
    ).hexdigest()
    raw = output.read_bytes()
    assert raw == inventory._canonical(value) + b"\n"
    assert b"secret bytes" not in raw
    with pytest.raises(inventory.EvidenceInventoryError, match="refusing to overwrite"):
        inventory.write_inventory(evidence, output, root_label="grader_smoke_exec")


def test_restricted_inventory_rejects_self_inclusion_and_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = tmp_path / "restricted"
    evidence.mkdir()
    (evidence / "evidence.txt").write_text("evidence\n", encoding="utf-8")
    with pytest.raises(inventory.EvidenceInventoryError, match="outside restricted"):
        inventory.write_inventory(
            evidence,
            evidence / "inventory.json",
            root_label="grader_smoke_exec",
        )

    target = tmp_path / "target.txt"
    target.write_text("target\n", encoding="utf-8")
    link = evidence / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        link.write_text("synthetic link placeholder\n", encoding="utf-8")
        original_is_symlink_mode = inventory.stat.S_ISLNK
        regular_file_calls = 0

        def synthetic_symlink_mode(mode: int) -> bool:
            nonlocal regular_file_calls
            if original_is_symlink_mode(mode):
                return True
            regular_file_calls += 1
            return regular_file_calls == 2

        monkeypatch.setattr(inventory.stat, "S_ISLNK", synthetic_symlink_mode)
    with pytest.raises(inventory.EvidenceInventoryError, match="contains a symlink"):
        inventory.build_inventory(evidence, root_label="grader_smoke_exec")
