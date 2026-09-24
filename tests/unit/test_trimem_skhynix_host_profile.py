"""The host profile decides where evidence resolves and who the solver is.

These are the guarantees the port depends on: an unconfigured host still
behaves exactly like the capture host, a configured one relocates recorded
paths without touching them, and neither one lets a worker run against an
identity the controller did not declare.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"),
                str(Path(__file__).resolve().parents[2] / "scripts")]
import trimem_skhynix_host_profile as host_profile
import trimem_skhynix_architecture_native as native

CAPTURE_ROOT = "/home/trimem-runner/skhynix-architecture-scale-001"
BANK = CAPTURE_ROOT + "/pipeline-v15/bank-240/bank.json"

GLM = {
    "schema": host_profile.SCHEMA,
    "topology": host_profile.NATIVE_POSIX,
    "path_remap": [{"from": CAPTURE_ROOT, "to": "/srv/skhynix/run"}],
    "controller_python": "/usr/bin/python3.11",
    "controller_environment": {"PYTHONDONTWRITEBYTECODE": "1"},
    "solver": {"model": "glm", "reasoning_effort": "high", "authentication": host_profile.API_KEY,
               "provider": {"name": "glm", "base_url": "http://localhost:8000/v1",
                            "env_key": "GLM_API_KEY", "wire_api": "chat"}},
}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv(host_profile.ENVIRONMENT_VARIABLE, raising=False)
    host_profile.reset()
    yield
    host_profile.reset()


def install(tmp_path, monkeypatch, value):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setenv(host_profile.ENVIRONMENT_VARIABLE, str(path))
    host_profile.reset()
    return path


def test_unconfigured_host_reproduces_the_capture_host():
    assert host_profile.topology() == host_profile.WINDOWS_WSL
    assert host_profile.native_posix() is False
    assert host_profile.solver() == {"model": "gpt-6-astra", "reasoning_effort": "high",
                                     "authentication": host_profile.CHATGPT, "provider": None}
    assert host_profile.launch_authentication() == "CHATGPT_FORCED"
    # No declared remap means recorded paths are used exactly as recorded.
    assert host_profile.remap(BANK) == BANK
    assert host_profile.unmap(BANK) == BANK


def test_unconfigured_worker_argv_is_the_original_astra_command():
    config = {"model": "gpt-6-astra", "authentication": "CHATGPT", "reasoning_effort": "high",
              "codex_binary": "codex.exe", "worker_cwd": "C:/cwd", "windows_python": "py.exe"}
    command = native.worker_command(config, "C:/cell.json")
    assert command[:14] == ["codex.exe", "exec", "--ignore-user-config", "--ephemeral", "--json",
                            "--skip-git-repo-check", "--sandbox", "read-only", "-C", "C:/cwd",
                            "-m", "gpt-6-astra", "-c", 'forced_login_method="chatgpt"']
    assert native.controller_python({"linux_source_root": "/opt/src"}, "run.py", [])[:6] == [
        "wsl.exe", "-d", "TriMemRunner2404", "--user", "trimem-runner", "--exec"]


def test_declared_remap_relocates_recorded_paths_and_round_trips(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch, GLM)
    assert host_profile.remap(BANK) == "/srv/skhynix/run/pipeline-v15/bank-240/bank.json"
    assert host_profile.unmap(host_profile.remap(BANK)) == BANK
    # A path no rule mentions is left alone rather than guessed at.
    assert host_profile.remap("/srv/elsewhere/x.json") == "/srv/elsewhere/x.json"


def test_longest_declared_prefix_wins(tmp_path, monkeypatch):
    value = deepcopy(GLM)
    value["path_remap"] = [{"from": "/data", "to": "/a"},
                           {"from": "/data/bank", "to": "/b"}]
    install(tmp_path, monkeypatch, value)
    assert host_profile.remap("/data/bank/x") == "/b/x"
    assert host_profile.remap("/data/other/x") == "/a/other/x"


def test_native_topology_drops_the_wsl_hop(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch, GLM)
    command = native.controller_python({"linux_source_root": "/srv/skhynix/repo"}, "run.py", ["action"])
    assert "wsl.exe" not in command
    assert command == ["env", "PYTHONDONTWRITEBYTECODE=1", "/usr/bin/python3.11",
                       "/srv/skhynix/repo/scripts/run.py", "action"]


def test_provider_authentication_addresses_the_declared_endpoint(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch, GLM)
    arguments = native.authentication_arguments(host_profile.solver())
    assert 'forced_login_method="chatgpt"' not in arguments
    assert 'model_provider="glm"' in arguments
    assert 'model_providers.glm.base_url="http://localhost:8000/v1"' in arguments
    assert 'model_providers.glm.env_key="GLM_API_KEY"' in arguments
    assert 'model_providers.glm.wire_api="chat"' in arguments


def test_worker_cell_may_not_differ_from_the_declared_identity(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch, GLM)
    config = {"model": "gpt-6-astra", "authentication": host_profile.API_KEY,
              "reasoning_effort": "high", "codex_binary": "codex",
              "worker_cwd": "/tmp/cwd", "windows_python": "python3.11"}
    with pytest.raises(ValueError):
        native.worker_command(config, "/tmp/cell.json")


def test_chatgpt_worker_never_inherits_a_model_credential(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "leaked")
    monkeypatch.setenv("CODEX_API_KEY", "leaked")
    env = native.worker_environment(host_profile.solver())
    assert "OPENAI_API_KEY" not in env and "CODEX_API_KEY" not in env


def test_provider_worker_gets_only_its_own_credential(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch, GLM)
    monkeypatch.setenv("OPENAI_API_KEY", "leaked")
    monkeypatch.setenv("GLM_API_KEY", "declared")
    env = native.worker_environment(host_profile.solver())
    assert env["GLM_API_KEY"] == "declared"
    assert "OPENAI_API_KEY" not in env


def test_missing_declared_credential_refuses_to_launch(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch, GLM)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    with pytest.raises(ValueError):
        native.worker_environment(host_profile.solver())


@pytest.mark.parametrize("mutate", [
    lambda v: v.update(topology="SOMETHING"),
    lambda v: v.update(schema="other/1.0"),
    lambda v: v.update(path_remap=[{"from": "relative", "to": "/a"}]),
    lambda v: v.update(path_remap=[{"from": "/a/", "to": "/b"}]),
    lambda v: v["solver"].update(authentication="NONE"),
    lambda v: v["solver"].update(provider=None),
    lambda v: v["solver"]["provider"].update(wire_api="grpc"),
    lambda v: v["solver"].update(model=""),
])
def test_unusable_profiles_are_refused(tmp_path, monkeypatch, mutate):
    value = deepcopy(GLM)
    mutate(value)
    install(tmp_path, monkeypatch, value)
    with pytest.raises(host_profile.HostProfileError):
        host_profile.profile(reload=True)


def test_chatgpt_profile_may_not_declare_a_provider(tmp_path, monkeypatch):
    value = deepcopy(GLM)
    value["solver"]["authentication"] = host_profile.CHATGPT
    install(tmp_path, monkeypatch, value)
    with pytest.raises(host_profile.HostProfileError):
        host_profile.profile(reload=True)
