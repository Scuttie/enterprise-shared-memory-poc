from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/trimem_d114_gate_contract.py"
FIXTURE = ROOT / "tests/fixtures/trimem_d114/exec_013_post_setup_failure.json"
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_d114_gate_contract as contract  # noqa: E402


def _document() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _sha(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def test_exact_exec_013_post_setup_failure_validates() -> None:
    result = contract.validate_fixture(contract.load_fixture(FIXTURE))
    assert result == {
        "benchmark_image_pulls": 0,
        "dependency_installations": 0,
        "execution_head": "35bfa338915d731dab499f2dfee08b38741bfe8d",
        "execution_run_attempt": 1,
        "execution_run_id": 34_138_918_074,
        "grader_containers": 0,
        "harness_materializations": 0,
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "protected_environment_entered": False,
        "self_hosted_job_assignments": 1,
        "source_head": "cb17ceae0fbc951dff34213de977a73b5405fefc",
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def test_projection_digests_are_independently_recomputed() -> None:
    document = _document()
    assert document["digests"]["failed_log_summary_sha256"] == _sha(
        document["failed_log_summary"]
    )
    assert document["digests"]["jobs_projection_sha256"] == _sha(document["jobs"])
    assert document["digests"]["workflow_run_projection_sha256"] == _sha(
        document["workflow_run"]
    )
    assert document["digests"]["evidence_bundle_sha256"] == _sha(
        {key: value for key, value in document.items() if key != "digests"}
    )


@pytest.mark.parametrize("counter", sorted(contract.EXPECTED_ZERO_COUNTERS))
def test_every_actual_counter_is_exact_zero(counter: str) -> None:
    document = _document()
    document["actuals"][counter] = 1
    with pytest.raises(contract.D114GateContractError, match="actuals"):
        contract.validate_fixture(document)


def test_bool_is_not_accepted_as_numeric_zero() -> None:
    document = _document()
    document["actuals"]["model_api_calls"] = False
    with pytest.raises(contract.D114GateContractError, match="model_api_calls"):
        contract.validate_fixture(document)


@pytest.mark.parametrize(
    ("name", "job_id", "conclusion"),
    [
        ("branch-trigger-preflight", 101_796_222_373, "success"),
        ("bounded-context-preflight", 101_796_314_944, "failure"),
        ("frozen-serial-phase", 101_796_404_674, "skipped"),
    ],
)
def test_job_funnel_is_literal(name: str, job_id: int, conclusion: str) -> None:
    rows = {row["name"]: row for row in _document()["jobs"]}
    assert rows[name]["id"] == job_id
    assert rows[name]["conclusion"] == conclusion


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("failed_job", "frozen-serial-phase"),
        ("failed_step", "Install hash-locked environment"),
        ("process_exit_code", 0),
        ("observed_ld_library_path", contract.EXPECTED_LIBRARY_PATH),
        ("expected_ld_library_path", contract.OBSERVED_LIBRARY_PATH),
    ],
)
def test_failure_location_and_environment_shape_fail_closed(
    field: str, value: object
) -> None:
    document = _document()
    document["failed_log_summary"][field] = value
    with pytest.raises(contract.D114GateContractError, match="failed_log_summary"):
        contract.validate_fixture(document)


def test_boundary_proves_no_install_materialization_or_protected_entry() -> None:
    boundary = _document()["boundary"]
    assert boundary["pre_setup_cache_host_passed"] is True
    assert boundary["setup_python_passed"] is True
    assert boundary["post_setup_runner_reobservation_entered"] is True
    assert boundary["dependency_install_started"] is False
    assert boundary["harness_materialization_started"] is False
    assert boundary["protected_environment_approval_requested"] is False
    assert boundary["protected_environment_entered"] is False


@pytest.mark.parametrize(
    "mutation",
    ["missing-job", "reordered-jobs", "extra-step", "entered-protected"],
)
def test_job_and_boundary_shape_fail_closed(mutation: str) -> None:
    document = deepcopy(_document())
    if mutation == "missing-job":
        document["jobs"].pop()
    elif mutation == "reordered-jobs":
        document["jobs"][0], document["jobs"][1] = (
            document["jobs"][1],
            document["jobs"][0],
        )
    elif mutation == "extra-step":
        document["jobs"][1]["steps"]["install"] = "success"
    else:
        document["boundary"]["protected_environment_entered"] = True
    with pytest.raises(contract.D114GateContractError):
        contract.validate_fixture(document)


def test_projection_digest_cannot_be_repaired_only_inside_fixture() -> None:
    document = _document()
    document["jobs"][1]["conclusion"] = "success"
    document["digests"]["jobs_projection_sha256"] = _sha(document["jobs"])
    document["digests"]["evidence_bundle_sha256"] = _sha(
        {key: value for key, value in document.items() if key != "digests"}
    )
    with pytest.raises(contract.D114GateContractError):
        contract.validate_fixture(document)


def test_strict_json_rejects_bom_nul_duplicates_and_nonfinite() -> None:
    samples = (
        b'\xef\xbb\xbf{"a":1}',
        b'{"a":"\x00"}',
        b'{"a":1,"a":2}',
        b'{"a":NaN}',
    )
    for raw in samples:
        with pytest.raises(contract.D114GateContractError):
            contract.strict_json_bytes(raw)


def test_fixture_is_pretty_lf_only_and_has_no_raw_secret_material() -> None:
    raw = FIXTURE.read_bytes()
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert b"\r" not in raw and b"\x00" not in raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    for forbidden in (b"OPENAI_API_KEY", b"TRIMEM_EXEC_APPROVAL_B64", b"Bearer "):
        assert forbidden not in raw


def test_cli_validates_fixture_under_isolated_python() -> None:
    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPT), "--fixture", str(FIXTURE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert json.loads(completed.stdout)["status"] == "PASS"
