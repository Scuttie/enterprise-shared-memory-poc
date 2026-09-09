from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import trimem_development_trigger_d115 as d115  # noqa: E402
import trimem_development_trigger_d116 as d116  # noqa: E402
import trimem_d116_loader_rehearsal as d116_collector  # noqa: E402


def _previous_request() -> dict[str, object]:
    completed = subprocess.run(
        [
            "git",
            "show",
            f"{d116.PREVIOUS_EXECUTION_HEAD}:{d116.PREVIOUS_SENTINEL_PATH}",
        ],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def test_d116_exact_active_and_historical_identities() -> None:
    assert d116.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_016"
    assert d116.REQUEST_SCHEMA == "trimem/development-tuning-branch-trigger/1.16"
    assert d116.SENTINEL_PATH.endswith("DEVELOPMENT_TUNING_EXEC_REQUEST_016.json")
    assert (
        d116.REQUIRED_EXTERNAL_AUTHORIZATION
        == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_016_APPROVED_ONCE"
    )
    completed = subprocess.run(
        [
            "git",
            "rev-parse",
            f"{d116.PREVIOUS_EXECUTION_HEAD}:{d116.PREVIOUS_SENTINEL_PATH}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == d116.PREVIOUS_SENTINEL_BLOB_OID


def test_d116_immutable_record_survives_delay_but_live_validator_fails_closed() -> None:
    request = _previous_request()
    readiness = request["runner_readiness"]
    rehearsal = request["loader_rehearsal"]
    assert isinstance(readiness, dict)
    assert isinstance(rehearsal, dict)

    with d116._d116_runtime_context():
        assert d116.validate_loader_rehearsal_record(
            rehearsal,
            source_head=d116.PREVIOUS_SOURCE_HEAD,
            runner_readiness=readiness,
        ) == rehearsal
        with pytest.raises(
            d116.DevelopmentTriggerError,
            match="exact loader rehearsal is stale or from the future",
        ):
            d115.validate_loader_rehearsal(
                rehearsal,
                source_head=d116.PREVIOUS_SOURCE_HEAD,
                runner_readiness=readiness,
                now=datetime(2026, 9, 8, 1, 0, tzinfo=timezone.utc),
            )


def test_d116_context_restores_d115_bindings() -> None:
    before = {
        "request_id": d115.REQUEST_ID,
        "schema": d115.REQUEST_SCHEMA,
        "sentinel": d115.SENTINEL_PATH,
        "builder": d115._build_request_impl,
        "loader_collector": d115.LOADER_REHEARSAL_COLLECTOR_PATH,
    }
    with d116._d116_runtime_context():
        assert d115.REQUEST_ID == d116.REQUEST_ID
        assert d115.REQUEST_SCHEMA == d116.REQUEST_SCHEMA
        assert d115.SENTINEL_PATH == d116.SENTINEL_PATH
        assert d115._build_request_impl is d116._build_request_impl
        assert (
            d115.LOADER_REHEARSAL_COLLECTOR_PATH
            == d116.LOADER_REHEARSAL_COLLECTOR_PATH
        )
    assert d115.REQUEST_ID == before["request_id"]
    assert d115.REQUEST_SCHEMA == before["schema"]
    assert d115.SENTINEL_PATH == before["sentinel"]
    assert d115._build_request_impl is before["builder"]
    assert d115.LOADER_REHEARSAL_COLLECTOR_PATH == before["loader_collector"]


def test_d116_loader_subprocess_wrapper_binds_parent_collector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[object, object, object]] = []

    def parent_main(argv: object = None) -> int:
        observed.append(
            (
                argv,
                d115.RUNNER_READINESS_SCHEMA,
                d115.LOADER_REHEARSAL_COLLECTOR_PATH,
            )
        )
        return 23

    monkeypatch.setattr(d116_collector.d115_collector, "main", parent_main)
    argv = ["--synthetic"]
    assert d116_collector.main(argv) == 23
    assert observed == [
        (
            argv,
            d116.RUNNER_READINESS_SCHEMA,
            d116.LOADER_REHEARSAL_COLLECTOR_PATH,
        )
    ]


def test_d116_context_blocks_older_generation_until_full_restore() -> None:
    active_entered = threading.Event()
    release_active = threading.Event()
    historical_started = threading.Event()
    historical_entered = threading.Event()
    observed: list[str] = []

    def active() -> None:
        with d116._d116_runtime_context():
            assert d115.REQUEST_ID == d116.REQUEST_ID
            active_entered.set()
            assert release_active.wait(timeout=5)

    def historical() -> None:
        assert active_entered.wait(timeout=5)
        historical_started.set()
        with d115._d115_runtime_context():
            observed.append(d115.REQUEST_ID)
            historical_entered.set()

    active_thread = threading.Thread(target=active)
    historical_thread = threading.Thread(target=historical)
    active_thread.start()
    historical_thread.start()
    assert historical_started.wait(timeout=5)
    assert not historical_entered.wait(timeout=0.1)
    release_active.set()
    active_thread.join(timeout=5)
    historical_thread.join(timeout=5)
    assert not active_thread.is_alive()
    assert not historical_thread.is_alive()
    assert observed == ["TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_015"]


def test_d116_branch_reasserts_live_loader_freshness_before_remote_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = "a" * 40
    after = "b" * 40
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({"after": after, "before": before}), encoding="utf-8"
    )
    request = {"loader_rehearsal": {"record": True}, "runner_readiness": {}}
    events: list[object] = []

    monkeypatch.setattr(d116, "resolve_repository_root", lambda _path: tmp_path)
    monkeypatch.setattr(
        d115,
        "validate_sentinel_commit",
        lambda *_args, **_kwargs: request,
    )

    def live(*_args: object, **kwargs: object) -> dict[str, bool]:
        events.append(("live", kwargs.get("now")))
        return {"record": True}

    monkeypatch.setattr(d115, "validate_loader_rehearsal", live)
    monkeypatch.setattr(
        d115,
        "validate_branch_trigger",
        lambda *_args, **_kwargs: events.append("remote") or {"status": "PASS"},
    )
    now = datetime(2026, 9, 8, 0, 1, tzinfo=timezone.utc)
    assert d116.validate_branch_trigger(tmp_path, event_path, now=now) == {
        "status": "PASS"
    }
    assert events == [("live", now), "remote"]


def test_d116_protected_delay_does_not_reage_preregistration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        d115,
        "validate_sentinel_commit",
        lambda *_args, **_kwargs: pytest.fail("protected path re-aged the record"),
    )
    monkeypatch.setattr(
        d115,
        "validate_pre_setup_cache_host",
        lambda *_args, **_kwargs: {"status": "PASS", "live_host": True},
    )
    observed = d116.validate_pre_setup_cache_host(
        tmp_path,
        event_path,
        environ={"GITHUB_JOB": "frozen-serial-phase"},
        now=datetime(2026, 9, 8, 8, 0, tzinfo=timezone.utc),
    )
    assert observed == {"status": "PASS", "live_host": True}


def test_d116_recovery_scope_excludes_every_scientific_input() -> None:
    forbidden = {
        "configs/trimem_v1/arms.json",
        "configs/trimem_v1/cost_plan.json",
        "configs/trimem_v1/development_manifest.json",
        "configs/trimem_v1/grader_lock.json",
        "configs/trimem_v1/model_lock.json",
        "configs/trimem_v1/m2_candidates/baseline.json",
    }
    assert forbidden.isdisjoint(d116.ALLOWED_RECOVERY_PATHS)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.__setitem__("observed_actuals", {}),
        lambda value: value.pop("root_cause"),
        lambda value: value["approval_boundary"].__setitem__(
            "environment_secret_count", True
        ),
        lambda value: value["root_cause"].__setitem__(
            "maximum_age_seconds", 3599
        ),
    ),
)
def test_d116_previous_run_fixture_mutations_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    mutation: object,
) -> None:
    fixture = json.loads(
        (ROOT / d116.PREVIOUS_FAILURE_FIXTURE_PATH).read_text(encoding="utf-8")
    )
    modified = deepcopy(fixture)
    assert callable(mutation)
    mutation(modified)
    monkeypatch.setattr(d116, "commit_bytes", lambda *_args: d116.canonical_bytes(modified, trailing_lf=True))
    with pytest.raises(d116.DevelopmentTriggerError):
        d116._validate_previous_run_fixture(ROOT, d116.PREVIOUS_EXECUTION_HEAD)
