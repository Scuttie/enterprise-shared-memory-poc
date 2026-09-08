from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import trimem_development_trigger_d116 as d116  # noqa: E402
import trimem_development_trigger_d117 as d117  # noqa: E402


def _fixture_bytes() -> bytes:
    return (ROOT / d117.PREVIOUS_FAILURE_FIXTURE_PATH).read_bytes()


def _synthetic_rehearsal(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    adjusted: list[tuple[str, str, int, int, str]] = []
    rows: list[dict[str, object]] = []
    repositories = {
        "swebench_verified--django__django-16100": "django/django",
        "swebench_verified--sympy__sympy-23262": "sympy/sympy",
        "swebench_verified--sphinx-doc__sphinx-11445": "sphinx-doc/sphinx",
        "swebench_verified--matplotlib__matplotlib-25311": "matplotlib/matplotlib",
        "multi_swe_bench_mini--mui__material-ui-29880": "mui/material-ui",
        "multi_swe_bench_mini--ponylang__ponyc-1981": "ponylang/ponyc",
        "multi_swe_bench_mini--clap-rs__clap-3960": "clap-rs/clap",
        "multi_swe_bench_mini--facebook__zstd-938": "facebook/zstd",
        "multi_swe_bench_flash--sharkdp__bat-1276": "sharkdp/bat",
        "multi_swe_bench_flash--catchorg__Catch2-1616": "catchorg/Catch2",
        "multi_swe_bench_flash--clap-rs__clap-3394": "clap-rs/clap",
        "multi_swe_bench_flash--cli__cli-869": "cli/cli",
    }
    for index, expected in enumerate(d117.EXPECTED_CHECKOUT_MATERIALIZATION):
        target_id, commit, regular, count, expected_hash = expected
        if target_id == "multi_swe_bench_mini--ponylang__ponyc-1981":
            paths = ["make.bat"]
        elif target_id == "multi_swe_bench_mini--facebook__zstd-938":
            paths = [f"build/path-{position:02d}.vcxproj" for position in range(30)]
        else:
            paths = []
        path_hash = hashlib.sha256(d117.canonical_bytes(paths)).hexdigest()
        if path_hash != expected_hash:
            expected_hash = path_hash
        adjusted.append((target_id, commit, regular, count, expected_hash))
        rows.append(
            {
                "order_index": index,
                "target_id": target_id,
                "repository": repositories[target_id],
                "commit": commit,
                "tree_object_id": f"{index + 1:040x}",
                "regular_blob_count": regular,
                "normalized_paths": paths,
                "normalized_path_count": count,
                "normalized_paths_sha256": expected_hash,
                "strict_raw_blob_validation": "PASS",
            }
        )
    monkeypatch.setattr(d117, "EXPECTED_CHECKOUT_MATERIALIZATION", tuple(adjusted))
    return {
        "schema": d117.CHECKOUT_REHEARSAL_SCHEMA,
        "status": "PASS",
        "split": "DEVELOPMENT_TUNING",
        "credential_access": False,
        "model_calls": 0,
        "image_pulls": 0,
        "grader_containers": 0,
        "official_grader_runs": 0,
        "task_arm_runs": 0,
        "source_identity": "PINNED_GIT_BLOB_BYTES_AT_REVISION",
        "transform_rule": "COMMITTED_TEXT_SET_EOL_CRLF_ONLY",
        "target_count": 12,
        "regular_blob_count": 54544,
        "normalized_path_count": 31,
        "targets": rows,
    }


def test_d117_exact_active_and_historical_identities() -> None:
    assert d117.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_017"
    assert d117.REQUEST_SCHEMA == "trimem/development-tuning-branch-trigger/1.17"
    assert d117.SENTINEL_PATH.endswith("DEVELOPMENT_TUNING_EXEC_REQUEST_017.json")
    assert (
        d117.REQUIRED_EXTERNAL_AUTHORIZATION
        == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_017_APPROVED_ONCE"
    )
    completed = subprocess.run(
        [
            "git",
            "rev-parse",
            f"{d117.PREVIOUS_EXECUTION_HEAD}:{d117.PREVIOUS_SENTINEL_PATH}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == d117.PREVIOUS_SENTINEL_BLOB_OID
    assert d117._load_previous_request(
        ROOT, d117.PREVIOUS_EXECUTION_HEAD
    )["request_sha256"] == "sha256:" + d117.PREVIOUS_REQUEST_PAYLOAD_SHA256


def test_d117_fixture_is_exact_and_replays_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _fixture_bytes()
    assert len(raw) == d117.PREVIOUS_FAILURE_FIXTURE_BYTES
    assert hashlib.sha256(raw).hexdigest() == d117.PREVIOUS_FAILURE_FIXTURE_SHA256
    monkeypatch.setattr(d117, "commit_bytes", lambda *_args: raw)
    observed = d117._validate_previous_run_fixture(
        ROOT, d117.PREVIOUS_EXECUTION_HEAD
    )
    assert observed["performance_measured"] is False
    assert observed["pass_at_1"] is None
    assert observed["actuals"] == d117.HISTORICAL_EXECUTION_ACTUALS


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value["actuals"].__setitem__("paid_model_calls", 0),
        lambda value: value["actuals"].__setitem__("total_usd", 0.0008385),
        lambda value: value.__setitem__("performance_measured", True),
        lambda value: value.__setitem__("pass_at_1", 0.0),
        lambda value: value["root_cause"]["reproduction"].__setitem__(
            "facebook_zstd_transformed_paths", 29
        ),
        lambda value: value["approval_boundary"].__setitem__(
            "environment_secret_count_after_cleanup", 1
        ),
    ),
)
def test_d117_fixture_mutations_fail_closed(
    monkeypatch: pytest.MonkeyPatch, mutation: object
) -> None:
    value = json.loads(_fixture_bytes())
    modified = deepcopy(value)
    assert callable(mutation)
    mutation(modified)
    raw = json.dumps(modified, ensure_ascii=False, indent=2, allow_nan=False).encode() + b"\n"
    monkeypatch.setattr(d117, "commit_bytes", lambda *_args: raw)
    with pytest.raises(d117.DevelopmentTriggerError):
        d117._validate_previous_run_fixture(ROOT, d117.PREVIOUS_EXECUTION_HEAD)


def test_d117_checkout_rehearsal_is_complete_and_zero_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _synthetic_rehearsal(monkeypatch)
    assert d117.validate_checkout_rehearsal(report) == report
    for field in (
        "credential_access",
        "model_calls",
        "image_pulls",
        "grader_containers",
        "official_grader_runs",
        "task_arm_runs",
    ):
        modified = deepcopy(report)
        modified[field] = 1
        with pytest.raises(d117.DevelopmentTriggerError):
            d117.validate_checkout_rehearsal(modified)


def test_d117_checkout_rehearsal_row_mutations_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _synthetic_rehearsal(monkeypatch)
    mutations = (
        lambda row: row.__setitem__("commit", "f" * 40),
        lambda row: row.__setitem__("normalized_path_count", 29),
        lambda row: row.__setitem__("strict_raw_blob_validation", "FAIL"),
        lambda row: row["normalized_paths"].append("unbound.txt"),
    )
    for mutation in mutations:
        modified = deepcopy(report)
        mutation(modified["targets"][7])
        with pytest.raises(d117.DevelopmentTriggerError):
            d117.validate_checkout_rehearsal(modified)


def test_d117_context_restores_d116_bindings() -> None:
    before = {
        "request_id": d116.REQUEST_ID,
        "schema": d116.REQUEST_SCHEMA,
        "sentinel": d116.SENTINEL_PATH,
        "builder": d116._build_request_impl,
    }
    with d117._d117_runtime_context():
        assert d116.REQUEST_ID == d117.REQUEST_ID
        assert d116.REQUEST_SCHEMA == d117.REQUEST_SCHEMA
        assert d116.SENTINEL_PATH == d117.SENTINEL_PATH
        assert d116._build_request_impl is d117._build_request_impl
    assert d116.REQUEST_ID == before["request_id"]
    assert d116.REQUEST_SCHEMA == before["schema"]
    assert d116.SENTINEL_PATH == before["sentinel"]
    assert d116._build_request_impl is before["builder"]


def test_d117_recovery_scope_excludes_science_and_historical_d116() -> None:
    forbidden = {
        ".gitattributes",
        "configs/trimem_v1/arms.json",
        "configs/trimem_v1/cost_plan.json",
        "configs/trimem_v1/development_manifest.json",
        "configs/trimem_v1/grader_lock.json",
        "configs/trimem_v1/model_lock.json",
        d116.AMENDMENT_PATH,
        d116.INVENTORY_PATH,
        d116.PREVIOUS_FAILURE_FIXTURE_PATH,
        d116.TRIGGER_PATH,
    }
    assert forbidden.isdisjoint(d117.ALLOWED_RECOVERY_PATHS)


@pytest.mark.parametrize("filter_name", ("paths", "paths-ignore"))
def test_d117_exact_head_dev_toolchain_gate_rejects_path_filters(
    monkeypatch: pytest.MonkeyPatch, filter_name: str
) -> None:
    workflow = (ROOT / d117.EXACT_HEAD_GATE_WORKFLOW_PATH).read_text(
        encoding="utf-8"
    )
    trigger = (
        "on:\n"
        "  push:\n"
        "    branches:\n"
        f"      - {d117.EXPECTED_BRANCH}\n"
    )
    assert trigger in workflow
    monkeypatch.setattr(
        d117,
        "commit_bytes",
        lambda *_args: workflow.encode("utf-8"),
    )
    d117._validate_exact_head_gate_workflow(ROOT, "a" * 40)

    filtered = workflow.replace(
        trigger,
        trigger + f"    {filter_name}:\n      - scripts/**\n",
        1,
    )
    assert filtered != workflow
    monkeypatch.setattr(
        d117,
        "commit_bytes",
        lambda *_args: filtered.encode("utf-8"),
    )
    with pytest.raises(
        d117.DevelopmentTriggerError,
        match="exact-head DEV toolchain push gate is filtered or misbound",
    ):
        d117._validate_exact_head_gate_workflow(ROOT, "a" * 40)


def test_d117_current_records_separate_consumed_and_current_actuals() -> None:
    failure = d117.current_failure_record()
    recovery = d117.current_recovery_record()
    assert failure["pass_at_1"] is None
    assert failure["performance_measured"] is False
    assert failure["observed_execution_actuals"] == d117.HISTORICAL_EXECUTION_ACTUALS
    assert recovery["consumed_exec_016_actuals"] == d117.HISTORICAL_EXECUTION_ACTUALS
    assert all(value == 0 for value in recovery["current_execution_actuals"].values())
    assert recovery["actual_execution_authorized"] is False


def test_d117_build_request_hash_binds_checkout_rehearsal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = _synthetic_rehearsal(monkeypatch)
    previous = {
        "control_plane": {"one_time_workflow_runs": 1},
        "exact_model": {"model_id": d117.MODEL_ID},
        "scientific_workload": {"task_arm_runs": 72},
    }
    bindings = {
        "checkout_rehearsal_sha256": "sha256:" + "a" * 64,
    }
    monkeypatch.setattr(
        d117,
        "_validate_source_impl",
        lambda *_args: {
            "previous_request": previous,
            "bindings": bindings,
            "hard_cap": {"total_usd": 50.0},
        },
    )
    monkeypatch.setattr(
        d117.d115,
        "_validate_remote_gate_evidence",
        lambda value, **_kwargs: value,
    )
    monkeypatch.setattr(
        d117.d115,
        "_validate_runner_readiness",
        lambda value, **_kwargs: value,
    )
    monkeypatch.setattr(
        d117,
        "validate_loader_rehearsal_record",
        lambda value, **_kwargs: value,
    )
    monkeypatch.setattr(
        d117,
        "_request_execution_contracts",
        lambda _bindings: {"git_blob_checkout_portability": True},
    )
    request = d117._build_request_impl(
        ROOT,
        source_head="a" * 40,
        remote_gate_evidence={"gates": True},
        runner_readiness={"runner": True},
        loader_rehearsal={"loader": True},
        checkout_rehearsal=checkout,
    )
    expected = hashlib.sha256(d117.canonical_bytes(checkout)).hexdigest()
    assert request["checkout_rehearsal"] == checkout
    assert request["checkout_rehearsal_sha256"] == "sha256:" + expected
    assert request["request_sha256"].startswith("sha256:")


def _install_checkout_collector_fakes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    observed_head: str | None = None,
    observed_status: bytes = b"",
) -> tuple[str, dict[str, object], list[dict[str, object]]]:
    source_head = "a" * 40
    report = _synthetic_rehearsal(monkeypatch)
    events: list[dict[str, object]] = []

    monkeypatch.setattr(d117, "resolve_repository_root", lambda _path: tmp_path)

    def fake_git(repository: Path, *arguments: str) -> str:
        events.append(
            {"kind": "host-git-read", "cwd": repository, "argv": arguments}
        )
        assert arguments == ("rev-parse", "HEAD")
        return source_head + "\n"

    monkeypatch.setattr(d117, "git", fake_git)
    monkeypatch.setattr(
        d117.d115,
        "_system_wsl_path",
        lambda: r"C:\Windows\System32\wsl.exe",
    )
    monkeypatch.setattr(
        d117.d115,
        "_wsl_collector_host_environment",
        lambda _environment, *, system_root: {"SystemRoot": system_root},
    )

    def fake_host_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        events.append(
            {
                "kind": "host-bundle",
                "argv": tuple(argv),
                "cwd": kwargs.get("cwd"),
                "environment": kwargs.get("env"),
            }
        )
        assert argv[-3] == "create"
        bundle = Path(argv[-2])
        bundle.write_bytes(b"synthetic exact Git bundle")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(d117.subprocess, "run", fake_host_run)

    outputs = {
        "D1.17 source bundle path translation": b"/mnt/c/external/source.bundle\n",
        "D1.17 checkout rehearsal temporary root": (
            b"/tmp/trimem-d117-writer-ABC123\n"
        ),
        "D1.17 exact source bundle clone": b"",
        "D1.17 exact source checkout": b"",
        "D1.17 exact source HEAD verification": (
            ((observed_head or source_head) + "\n").encode("ascii")
        ),
        "D1.17 exact source cleanliness verification": observed_status,
        "exact twelve-target checkout rehearsal": (
            b"TRIMEM_DEVELOPMENT_TASK_CHECKOUT_REHEARSAL_PASS\n"
        ),
        "D1.17 checkout rehearsal evidence read": d117.canonical_bytes(
            report, trailing_lf=True
        ),
        "D1.17 checkout rehearsal temporary cleanup": b"",
    }

    def fake_wsl_run(
        argv: list[str],
        *,
        environment: dict[str, str],
        label: str,
        timeout: float,
    ) -> bytes:
        events.append(
            {
                "kind": "wsl",
                "argv": tuple(argv),
                "environment": environment,
                "label": label,
                "timeout": timeout,
            }
        )
        return outputs[label]

    monkeypatch.setattr(
        d117.d115, "_run_wsl_collector_command", fake_wsl_run
    )
    return source_head, report, events


def test_d117_checkout_collector_bundles_exact_head_into_wsl_owned_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_head, report, events = _install_checkout_collector_fakes(
        tmp_path, monkeypatch
    )

    assert d117.collect_exact_checkout_rehearsal(tmp_path, source_head) == report

    assert events[0] == {
        "kind": "host-git-read",
        "cwd": tmp_path,
        "argv": ("rev-parse", "HEAD"),
    }
    bundle_event = events[1]
    assert bundle_event["kind"] == "host-bundle"
    bundle_argv = bundle_event["argv"]
    assert isinstance(bundle_argv, tuple)
    assert bundle_argv[-3:] == (
        "create",
        bundle_argv[-2],
        "HEAD",
    )
    assert bundle_event["cwd"] == tmp_path
    assert "safe.directory" not in " ".join(bundle_argv)

    wsl_events = [event for event in events if event["kind"] == "wsl"]
    labels = [event["label"] for event in wsl_events]
    assert labels == [
        "D1.17 source bundle path translation",
        "D1.17 checkout rehearsal temporary root",
        "D1.17 exact source bundle clone",
        "D1.17 exact source checkout",
        "D1.17 exact source HEAD verification",
        "D1.17 exact source cleanliness verification",
        "exact twelve-target checkout rehearsal",
        "D1.17 checkout rehearsal evidence read",
        "D1.17 checkout rehearsal temporary cleanup",
    ]

    clone = wsl_events[2]["argv"]
    checkout = wsl_events[3]["argv"]
    head_check = wsl_events[4]["argv"]
    status_check = wsl_events[5]["argv"]
    rehearsal = wsl_events[6]["argv"]
    assert isinstance(clone, tuple)
    assert clone[-7:] == (
        "/usr/bin/git",
        "clone",
        "--quiet",
        "--no-checkout",
        "--",
        "/mnt/c/external/source.bundle",
        "/tmp/trimem-d117-writer-ABC123/source",
    )
    assert isinstance(checkout, tuple)
    assert checkout[-7:] == (
        "/usr/bin/git",
        "-C",
        "/tmp/trimem-d117-writer-ABC123/source",
        "checkout",
        "--quiet",
        "--detach",
        source_head,
    )
    assert isinstance(head_check, tuple)
    assert head_check[-5:] == (
        "/usr/bin/git",
        "-C",
        "/tmp/trimem-d117-writer-ABC123/source",
        "rev-parse",
        "HEAD",
    )
    assert isinstance(status_check, tuple)
    assert status_check[-6:] == (
        "/usr/bin/git",
        "-C",
        "/tmp/trimem-d117-writer-ABC123/source",
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    assert isinstance(rehearsal, tuple)
    assert rehearsal[rehearsal.index("-C") + 1] == (
        "/tmp/trimem-d117-writer-ABC123/source"
    )
    assert str(tmp_path) not in "\n".join(
        " ".join(str(item) for item in event["argv"])
        for event in wsl_events[2:]
    )


@pytest.mark.parametrize(
    ("observed_head", "observed_status"),
    (("b" * 40, b""), (None, b"1 .M N... tracked.py\n")),
)
def test_d117_checkout_collector_rejects_nonexact_wsl_source_before_rehearsal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    observed_head: str | None,
    observed_status: bytes,
) -> None:
    source_head, _report, events = _install_checkout_collector_fakes(
        tmp_path,
        monkeypatch,
        observed_head=observed_head,
        observed_status=observed_status,
    )
    with pytest.raises(
        d117.DevelopmentTriggerError,
        match="WSL source checkout is not exact and clean",
    ):
        d117.collect_exact_checkout_rehearsal(tmp_path, source_head)
    labels = [event["label"] for event in events if event["kind"] == "wsl"]
    assert "exact twelve-target checkout rehearsal" not in labels
    assert labels[-1] == "D1.17 checkout rehearsal temporary cleanup"


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr", "write_bundle"),
    (
        (1, b"", b"", True),
        (0, b"unexpected", b"", True),
        (0, b"", b"diagnostic", True),
        (0, b"", b"", False),
    ),
)
def test_d117_checkout_collector_rejects_inexact_host_bundle_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: bytes,
    stderr: bytes,
    write_bundle: bool,
) -> None:
    source_head, _report, events = _install_checkout_collector_fakes(
        tmp_path, monkeypatch
    )

    def failing_bundle(
        argv: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        if write_bundle:
            Path(argv[-2]).write_bytes(b"bundle")
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    monkeypatch.setattr(d117.subprocess, "run", failing_bundle)
    with pytest.raises(
        d117.DevelopmentTriggerError,
        match="exact source bundle creation failed",
    ):
        d117.collect_exact_checkout_rehearsal(tmp_path, source_head)
    assert not any(event["kind"] == "wsl" for event in events)
