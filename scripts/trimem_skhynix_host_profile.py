"""Declared host topology and solver identity for the SK hynix experiment.

The experiment was captured on Windows, where the controller ran inside a WSL
distribution, the worker launcher and the agent CLI ran on the Windows side,
and every recorded reference therefore names either a /mnt/c path or a WSL
path. Moving to a native Linux server collapses that three-hop topology onto a
single operating system, so the cross-OS translations have to become
configurable rather than assumed.

Two things are declared here and nowhere else:

* the host topology and its path remapping, so evidence captured on the
  original host still resolves. Remapping happens when a path is *read*; the
  recorded files are never rewritten. Their sha256 pins are content-based, so
  they stay meaningful across the move, and rewriting them would destroy the
  evidence chain rather than port it.
* the solver identity - model, authentication and reasoning effort - which the
  controller, broker, quarantine and audit paths all check a launch against.
  Those checks stay exactly as strict; only the value being asserted moves out
  of the source and into this declaration.

With no profile configured the defaults reproduce the original Windows/WSL
capture host unchanged, so existing evidence and tests behave as before. Set
SKHYNIX_HOST_PROFILE to a JSON file to override.
"""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath

SCHEMA = "skhynix/host-profile/1.0"
ENVIRONMENT_VARIABLE = "SKHYNIX_HOST_PROFILE"

WINDOWS_WSL = "WINDOWS_WSL"
NATIVE_POSIX = "NATIVE_POSIX"
TOPOLOGIES = (WINDOWS_WSL, NATIVE_POSIX)

CHATGPT = "CHATGPT"
API_KEY = "API_KEY"
AUTHENTICATIONS = (CHATGPT, API_KEY)
# The launch receipt records how the worker was actually authenticated. The
# controller compares the receipt against the declaration, so the two spellings
# have to stay paired.
LAUNCH_AUTHENTICATION = {CHATGPT: "CHATGPT_FORCED", API_KEY: "API_KEY_FORCED"}

# Reproduces the original capture host. Changing these changes what a default
# run asserts, so they are the frozen Astra values.
DEFAULT = {
    "schema": SCHEMA,
    "topology": WINDOWS_WSL,
    "path_remap": [],
    "wsl_distribution": "TriMemRunner2404",
    "wsl_user": "trimem-runner",
    "controller_python": "/opt/trimem-rehearsals/e932-preflight/venv/bin/python",
    "run_root": "/home/trimem-runner/skhynix-architecture-scale-001",
    "staging_root": "/mnt/c/Users/jewon/AppData/Local/Temp",
    "controller_environment": {
        "PYTHONDONTWRITEBYTECODE": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "LD_LIBRARY_PATH": "/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib",
    },
    "solver": {
        "model": "gpt-6-astra",
        "reasoning_effort": "high",
        "authentication": CHATGPT,
        "provider": None,
    },
}


class HostProfileError(RuntimeError):
    pass


def _validate(value):
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise HostProfileError("host profile must declare schema " + SCHEMA)
    if value.get("topology") not in TOPOLOGIES:
        raise HostProfileError("host topology must be one of " + ", ".join(TOPOLOGIES))

    remaps = value.get("path_remap", [])
    if not isinstance(remaps, list):
        raise HostProfileError("path_remap must be a list of {from, to} objects")
    for entry in remaps:
        if (not isinstance(entry, dict) or set(entry) != {"from", "to"}
                or not all(isinstance(entry[key], str) and entry[key].startswith("/")
                           and not entry[key].endswith("/") for key in ("from", "to"))):
            raise HostProfileError(
                "each path_remap entry needs absolute 'from' and 'to' prefixes without a trailing slash")

    solver = value.get("solver")
    if not isinstance(solver, dict) or not isinstance(solver.get("model"), str) or not solver["model"]:
        raise HostProfileError("solver.model must be a non-empty string")
    if solver.get("authentication") not in AUTHENTICATIONS:
        raise HostProfileError("solver.authentication must be one of " + ", ".join(AUTHENTICATIONS))
    if not isinstance(solver.get("reasoning_effort"), str) or not solver["reasoning_effort"]:
        raise HostProfileError("solver.reasoning_effort must be a non-empty string")

    provider = solver.get("provider")
    if solver["authentication"] == API_KEY:
        if (not isinstance(provider, dict)
                or not all(isinstance(provider.get(key), str) and provider.get(key)
                           for key in ("name", "base_url", "env_key"))):
            raise HostProfileError(
                "API_KEY authentication needs solver.provider with name, base_url and env_key")
        if provider.get("wire_api", "chat") not in ("chat", "responses"):
            raise HostProfileError("solver.provider.wire_api must be 'chat' or 'responses'")
    elif provider is not None:
        raise HostProfileError("solver.provider only applies to API_KEY authentication")
    return value


def _load():
    location = os.environ.get(ENVIRONMENT_VARIABLE)
    if not location:
        return dict(DEFAULT)
    path = Path(location)
    if not path.is_file():
        raise HostProfileError("host profile file does not exist: " + str(path))
    try:
        value = json.loads(path.read_bytes())
    except ValueError as exc:
        raise HostProfileError("host profile is not readable JSON: " + str(path)) from exc
    return _validate(value)


_CACHE = {}


def profile(*, reload=False):
    """The active host profile. Cached, because it is read on every path check."""
    if reload or "value" not in _CACHE:
        _CACHE["value"] = _load()
    return _CACHE["value"]


def reset():
    """Drop the cached profile. Used by tests and by explicit reconfiguration."""
    _CACHE.clear()


def run_root():
    """Where pipeline state lives on this host."""
    return Path(profile().get("run_root", DEFAULT["run_root"]))


def staging_root():
    """Where frozen source snapshots are staged on this host."""
    return Path(profile().get("staging_root", DEFAULT["staging_root"]))


def topology():
    return profile()["topology"]


def native_posix():
    return topology() == NATIVE_POSIX


def solver():
    return profile()["solver"]


def launch_authentication():
    return LAUNCH_AUTHENTICATION[solver()["authentication"]]


def remap(value):
    """Map a path recorded on the capture host onto this host.

    Longest declared prefix wins, so nested roots can be remapped separately.
    A path that matches nothing is returned unchanged: absence of a rule is not
    an error, because most paths on a single-host run need no translation.
    """
    remaps = profile().get("path_remap") or []
    if not remaps:
        return value
    text = str(value).replace("\\", "/")
    best = None
    for entry in remaps:
        source = entry["from"]
        if text == source or text.startswith(source + "/"):
            if best is None or len(source) > len(best["from"]):
                best = entry
    if best is None:
        return value
    return best["to"] + text[len(best["from"]):]


def unmap(value):
    """Map a path on this host back into the capture host's namespace.

    Recorded references always name the capture host, so that evidence written
    here and evidence written during the original run can be compared directly.
    The inverse of remap(); longest declared target prefix wins.
    """
    remaps = profile().get("path_remap") or []
    if not remaps:
        return value
    text = str(value).replace("\\", "/")
    best = None
    for entry in remaps:
        target = entry["to"]
        if text == target or text.startswith(target + "/"):
            if best is None or len(target) > len(best["to"]):
                best = entry
    if best is None:
        return value
    return best["from"] + text[len(best["to"]):]


def remapped_path(value):
    return Path(remap(value))


def describe():
    """A small, printable summary. Never includes credentials."""
    active = profile()
    current = active["solver"]
    provider = current.get("provider") or {}
    return {
        "topology": active["topology"],
        "path_remap_rules": len(active.get("path_remap") or []),
        "model": current["model"],
        "reasoning_effort": current["reasoning_effort"],
        "authentication": current["authentication"],
        "provider_name": provider.get("name"),
        "provider_base_url": provider.get("base_url"),
        "provider_env_key": provider.get("env_key"),
    }
