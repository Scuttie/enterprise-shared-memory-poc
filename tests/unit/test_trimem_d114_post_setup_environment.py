from __future__ import annotations

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import trimem_development_trigger_d112 as d112  # noqa: E402


WORKFLOW = ROOT / ".github/workflows/trimem-benchmark.yml"
CENTRAL_LIBRARY_PATH = d112.EXACT_PYTHON_LIBRARY_PATH
ACTIVE_EXEC_LIBRARY_PATH = (
    "/opt/trimem-d112-runners/exec/_work/_tool/"
    "Python/3.11.10/x64/lib"
)

POST_SETUP_D114_STEPS = {
    "Re-observe exact self-hosted runner before any install or materialization": (
        "--runner-host-preflight-event-path"
    ),
    "Re-observe protected runner before cache-only service creation": (
        "--protected-runner-preflight-event-path"
    ),
    "Start exact cache-only benchmark services": (
        "--start-protected-services-event-path"
    ),
    "Verify exact cache-only benchmark services": (
        "--verify-protected-services-event-path"
    ),
    "Remove exact cache-only benchmark services": (
        "--cleanup-protected-services-event-path"
    ),
}


def _workflow_text() -> str:
    raw = WORKFLOW.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\x00" not in raw
    assert b"\r" not in raw
    return raw.decode("utf-8", errors="strict")


def _step_blocks(text: str) -> dict[str, list[str]]:
    marker = "      - name: "
    blocks: dict[str, list[str]] = {}
    pieces = text.split(marker)
    for piece in pieces[1:]:
        name, _separator, _remainder = piece.partition("\n")
        body = marker + piece.split("\n      - name: ", 1)[0]
        blocks.setdefault(name, []).append(body)
    return blocks


def test_d114_workflow_routes_only_the_fresh_014_request() -> None:
    text = _workflow_text()

    assert (
        "artifacts/trimem_v1/exec_requests/"
        "DEVELOPMENT_TUNING_EXEC_REQUEST_014.json"
    ) in text
    assert "group: trimem-v1-development-tuning-exec-014" in text
    assert "scripts/trimem_development_trigger_d113.py" not in text
    assert text.count("scripts/trimem_development_trigger_d114.py") == 8


def test_every_post_setup_d114_runner_and_service_call_forces_central_library_only() -> None:
    text = _workflow_text()
    blocks = _step_blocks(text)
    exact_binding = f"          LD_LIBRARY_PATH: {CENTRAL_LIBRARY_PATH}\n"

    for name, flag in POST_SETUP_D114_STEPS.items():
        selected = blocks.get(name)
        assert selected is not None and len(selected) == 1, name
        block = selected[0]
        assert "scripts/trimem_development_trigger_d114.py" in block
        assert flag in block
        assert block.count(exact_binding) == 1
        assert block.index("        env:\n") < block.index("        run:")
        assert ACTIVE_EXEC_LIBRARY_PATH not in block
        assert f"{ACTIVE_EXEC_LIBRARY_PATH}:{CENTRAL_LIBRARY_PATH}" not in block

    # Two pre-setup probes plus the five post-setup D1.14 validation calls.
    assert text.count(exact_binding) == 7


def test_pre_setup_calls_remain_explicit_central_cache_probes() -> None:
    text = _workflow_text()
    blocks = _step_blocks(text)
    selected = blocks.get("Verify complete cached Python before setup-python")

    assert selected is not None and len(selected) == 2
    for block in selected:
        assert (
            f"          LD_LIBRARY_PATH: {CENTRAL_LIBRARY_PATH}\n" in block
        )
        assert "          RUNNER_TOOL_CACHE: ${{ runner.tool_cache }}\n" in block
        assert (
            f"          {d112.EXACT_PYTHON_ROOT}/bin/python\n" in block
        )
        assert "scripts/trimem_development_trigger_d114.py" in block
        assert "--pre-setup-cache-host-event-path" in block


@pytest.mark.parametrize(
    "value",
    [
        None,
        ACTIVE_EXEC_LIBRARY_PATH,
        f"{ACTIVE_EXEC_LIBRARY_PATH}:{CENTRAL_LIBRARY_PATH}",
        f"{CENTRAL_LIBRARY_PATH}:{ACTIVE_EXEC_LIBRARY_PATH}",
        f"{CENTRAL_LIBRARY_PATH}:/usr/local/lib",
    ],
)
def test_listener_and_persisted_env_binding_stays_single_path_fail_closed(
    value: str | None,
) -> None:
    bindings = {} if value is None else {"LD_LIBRARY_PATH": value}
    with pytest.raises(d112.DevelopmentTriggerError, match="LD_LIBRARY_PATH"):
        d112._require_exact_python_library_binding(bindings, label="listener fixture")

    assert d112._require_exact_python_library_binding(
        {"LD_LIBRARY_PATH": CENTRAL_LIBRARY_PATH},
        label="listener fixture",
    ) == CENTRAL_LIBRARY_PATH
