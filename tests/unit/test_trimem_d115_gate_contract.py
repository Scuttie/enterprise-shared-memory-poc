from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_d115_gate_contract as gate  # noqa: E402


FIXTURE = ROOT / "tests/fixtures/trimem_d115/exec_014_loader_failure.json"


def test_exec_014_failure_projection_is_exact_and_zero_scientific_work() -> None:
    result = gate.validate_fixture(gate.load_fixture(FIXTURE))

    assert result["status"] == "PASS"
    assert result["execution_run_id"] == 34147189320
    assert result["execution_run_attempt"] == 1
    assert result["dependency_installations"] == 1
    assert result["harness_materializations"] == 2
    assert result["model_api_calls"] == 0
    assert result["grader_containers"] == 0
    assert result["task_arm_runs"] == 0
    assert result["total_usd"] == 0


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("workflow_run", "run_attempt"), 2),
        (("actuals", "model_api_calls"), 1),
        (("actuals", "grader_containers"), 1),
        (("boundary", "protected_environment_entered"), True),
        (("failed_log_summary", "observed_sysconfig_libdir_exists"), True),
        (("failed_log_summary", "failure_subtype"), "UNKNOWN"),
    ],
)
def test_exec_014_failure_projection_mutations_fail_closed(
    path: tuple[str, str], replacement: object
) -> None:
    value = deepcopy(gate.load_fixture(FIXTURE))
    value[path[0]][path[1]] = replacement

    with pytest.raises(gate.D115GateContractError):
        gate.validate_fixture(value)


def test_fixture_rejects_bom(tmp_path: Path) -> None:
    target = tmp_path / "fixture.json"
    target.write_bytes(b"\xef\xbb\xbf" + FIXTURE.read_bytes())

    with pytest.raises(gate.D115GateContractError, match="BOM"):
        gate.load_fixture(target)
