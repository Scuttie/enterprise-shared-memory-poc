"""Fresh ChatGPT-authenticated Codex workers with one bounded broker MCP tool.

No model API client is constructed. The trusted launcher admits the actual
thread ID observed in Codex JSONL before the worker can call the broker. Native
shell, browser, app, plugin, delegation and host-memory tools are disabled for
both arms. The MCP subprocess receives only a fixed manager-selected cell.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

SCHEMA = "skhynix/architecture-native-worker/1.0"
MAX_REQUEST_BYTES = 262_144
DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "multi_agent", "apps", "plugins",
    "browser_use", "browser_use_external", "computer_use", "image_generation",
    "view_image", "hooks", "memories", "goals", "shell_snapshot",
)
PASSIVE_ITEM_TYPES = frozenset({'agent_message', 'reasoning', 'error', 'todo_list', 'plan_update'})


def outside_broker_item(item):
    kind = item.get('type')
    if kind in PASSIVE_ITEM_TYPES:
        return None
    if kind == 'mcp_tool_call' and item.get('server') == 'benchmark' and item.get('tool') == 'action':
        return None
    return kind or 'UNKNOWN_NATIVE_ITEM'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def wsl_python(config, script, arguments):
    return ["wsl.exe", "-d", "TriMemRunner2404", "--user", "trimem-runner", "--exec",
            "env", "PYTHONDONTWRITEBYTECODE=1", "HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1",
            "LD_LIBRARY_PATH=/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib",
            "/opt/trimem-rehearsals/e932-preflight/venv/bin/python",
            config["linux_source_root"] + "/scripts/" + script, *arguments]


def manager_command(config, operation, payload):
    raw = canonical(payload)
    argv = wsl_python(config, "trimem_skhynix_architecture_run.py", [
        operation, "--cell-config", config["linux_cell_config"],
        "--request-stdin"])
    # stdin avoids Windows' ~32K command-line limit for large bounded edits.
    try:
        result = subprocess.run(argv, input=raw, capture_output=True, check=False, timeout=180)
    except Exception as exc:
        write_new(Path(config['worker_output']) / ('manager-error-' + str(uuid.uuid4()) + '.json'),
                  {'operation': operation, 'exception_type': type(exc).__name__})
        raise RuntimeError('Trusted benchmark manager transport failed: ' + operation) from None
    if result.returncode:
        write_new(Path(config['worker_output']) / ('manager-error-' + str(uuid.uuid4()) + '.json'),
                  {'operation': operation, 'returncode': result.returncode,
                   'stderr': result.stderr.decode('utf-8', errors='replace')})
        # Never pass the command or admission payload into model-visible errors.
        raise RuntimeError("Trusted benchmark manager command failed: " + operation)
    try:
        return json.loads(result.stdout)
    except (ValueError, UnicodeError):
        write_new(Path(config['worker_output']) / ('manager-error-' + str(uuid.uuid4()) + '.json'),
                  {'operation': operation, 'exception_type': 'INVALID_MANAGER_JSON'})
        raise RuntimeError('Trusted benchmark manager response failed: ' + operation) from None


def broker_action(config, request):
    if not isinstance(request, dict) or len(canonical(request)) > MAX_REQUEST_BYTES:
        raise ValueError("Expected one bounded benchmark request object")
    admission_path = Path(config["admission_path"])
    deadline = time.monotonic() + 60
    while not admission_path.is_file():
        if time.monotonic() > deadline:
            raise RuntimeError("Native worker admission did not complete")
        time.sleep(0.1)
    admission = read(admission_path)
    if admission["worker_id"] != config["worker_id"]:
        raise ValueError("Worker admission identity differs")
    # Stable ID belongs to this one MCP invocation, not a model-selected retry.
    return manager_command(config, "action", {
        "worker_id": config["worker_id"], "token": admission["token"],
        "request_id": str(uuid.uuid4()), "request": request})


def mcp_response(message, action):
    """Small stdio MCP surface. Only tools/call can access a benchmark cell."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise ValueError("Expected a JSON-RPC 2.0 object")
    if "id" not in message:
        return None
    method, params = message.get("method"), message.get("params", {})
    response = {"jsonrpc": "2.0", "id": message["id"]}
    if method == "initialize":
        response["result"] = {"protocolVersion": params.get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "skhynix-benchmark", "version": "1.0.0"}}
    elif method == "ping":
        response["result"] = {}
    elif method == "tools/list":
        response["result"] = {"tools": [{"name": "action",
            "description": "Execute exactly one public benchmark broker operation. Use the operation and repository-tool schemas in your handoff packet. All calls use the shared task budget. After handoff_required=true stop this worker immediately.",
            "inputSchema": {"type": "object", "properties": {"request": {
                "type": "object", "description": "Broker request with op and its documented arguments."}},
                "required": ["request"], "additionalProperties": False}}]}
    elif method == "tools/call":
        if params.get("name") != "action" or set(params.get("arguments", {})) != {"request"}:
            response["error"] = {"code": -32602, "message": "Only the benchmark action tool is available"}
        else:
            try:
                value = action(params["arguments"]["request"])
                response["result"] = {"content": [{"type": "text", "text": canonical(value).decode()}],
                                      "isError": False}
            except Exception as exc:
                response["result"] = {"content": [{"type": "text", "text": str(exc)[:500]}],
                                      "isError": True}
    else:
        response["error"] = {"code": -32601, "message": "Method not available"}
    return response


def serve_mcp(config):
    for raw in iter(lambda: sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1), b""):
        try:
            if len(raw) > MAX_REQUEST_BYTES:
                raise ValueError("MCP request exceeds byte limit")
            response = mcp_response(json.loads(raw), lambda req: broker_action(config, req))
        except Exception:
            response = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "Invalid bounded JSON-RPC request"}}
        if response is not None:
            sys.stdout.buffer.write(canonical(response) + b"\n")
            sys.stdout.buffer.flush()


def worker_command(config, config_path):
    if config.get("model") != "gpt-6-astra" or config.get("authentication") != "CHATGPT":
        raise ValueError("This experiment requires the declared Astra model and ChatGPT login")
    command = [config["codex_binary"], "exec", "--ignore-user-config", "--ephemeral", "--json",
        "--skip-git-repo-check", "--sandbox", "read-only", "-C", config["worker_cwd"],
        "-m", config["model"], "-c", 'forced_login_method="chatgpt"',
        "-c", "model_reasoning_effort=" + json.dumps(config["reasoning_effort"]),
        "-c", 'web_search="disabled"', "--enable", "skip_host_skill_discovery"]
    for feature in DISABLED_FEATURES:
        command += ["--disable", feature]
    # Only this task's MCP server is loaded; no user-config MCP servers or apps.
    overrides = {
        "mcp_servers.benchmark.command": config["windows_python"],
        "mcp_servers.benchmark.args": [str(Path(__file__).resolve()), "mcp", "--config", str(config_path)],
        "mcp_servers.benchmark.required": True,
        "mcp_servers.benchmark.startup_timeout_sec": 60,
        "mcp_servers.benchmark.tool_timeout_sec": 180,
        "mcp_servers.benchmark.default_tools_approval_mode": "auto",
        "mcp_servers.benchmark.enabled_tools": ["action"],
        "mcp_servers.benchmark.tools.action.approval_mode": "approve",
    }
    for key, value in overrides.items():
        command += ["-c", key + "=" + json.dumps(value, ensure_ascii=False)]
    return command + ["-"]


def launch(config_path):
    config_path = Path(config_path).resolve(strict=True)
    config = read(config_path)
    output = Path(config["worker_output"])
    output.mkdir(parents=True, exist_ok=False)
    Path(config["worker_cwd"]).mkdir(parents=True, exist_ok=True)
    prompt = Path(config["prompt_path"]).read_bytes()
    if digest(prompt) != config["prompt_sha256"]:
        raise ValueError("Frozen worker prompt changed")
    command = worker_command(config, config_path)
    env = dict(os.environ)
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY"):
        env.pop(key, None)
    start = time.time()
    receipt = {"schema": SCHEMA, "worker_id": config["worker_id"], "requested_model": config["model"],
        "reasoning_effort": config["reasoning_effort"], "authentication": "CHATGPT_FORCED",
        "prompt_sha256": digest(prompt), "prompt_bytes": len(prompt),
        "packet_sha256": config["packet_sha256"], "fresh_session": True,
        "resume_or_fork_used": False, "separate_model_api_client_calls": 0,
        "command_sha256": digest(canonical(command)), "started_at": start}
    write_new(output / "launch.json", receipt)
    events, errors = [], []
    result = {"thread_id": None, "admitted": False, "usage": None,
              "transport_errors": [],
              "outside_broker_tool_events": [], "timed_out": False}
    with (output / "stderr.log").open("xb") as err, (output / "events.jsonl").open("xb") as event_file:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=err, env=env)
        def consume():
            try:
                for line in process.stdout:
                    event_file.write(line)
                    event_file.flush()
                    event = json.loads(line)
                    events.append(event)
                    if event.get("type") == "thread.started":
                        if result["thread_id"] is not None:
                            raise ValueError("A native launch emitted more than one thread identity")
                        result["thread_id"] = event["thread_id"]
                        admission = manager_command(config, "admit", {
                            "worker_id": config["worker_id"], "packet_sha256": config["packet_sha256"],
                            "launch_receipt": {"thread_id": event["thread_id"], "fresh_session": True,
                                "fork_turns": "none", "requested_model": config["model"],
                                "launch_evidence_sha256": digest(canonical(receipt)),
                                "prompt_sha256": digest(prompt)}})
                        write_new(config["admission_path"], {"worker_id": config["worker_id"], **admission})
                        result["admitted"] = True
                    if event.get("type") == "turn.completed":
                        result["usage"] = event.get("usage")
                    item = event.get("item", {})
                    if (event.get('type') == 'item.completed' and
                            item.get('type') == 'mcp_tool_call' and item.get('error')):
                        result['transport_errors'].append(item['error'])
                    violation = outside_broker_item(item) if item else None
                    if violation:
                        result["outside_broker_tool_events"].append(violation)
                        if process.poll() is None:
                            process.terminate()
            except Exception as exc:
                errors.append(type(exc).__name__ + ": " + str(exc))
                if process.poll() is None:
                    process.terminate()
        reader = threading.Thread(target=consume, daemon=True)
        reader.start()
        process.stdin.write(prompt)
        process.stdin.close()
        try:
            process.wait(timeout=config["worker_timeout_seconds"])
        except subprocess.TimeoutExpired:
            result["timed_out"] = True
            process.kill()
            process.wait(timeout=30)
        reader.join(timeout=190)
        if reader.is_alive():
            raise RuntimeError("Native worker event reader did not terminate")
    result.update(exit_code=process.returncode, ended_at=time.time(),
                  wall_seconds=time.time()-start, errors=errors,
                  events_sha256=digest((output/"events.jsonl").read_bytes()))
    for path in sorted(output.glob('manager-error-*.json')):
        result['transport_errors'].append({'manager_error_file': path.name,
                                         'sha256': digest(path.read_bytes())})
    write_new(output/"completion.json", result)
    print(canonical({k:v for k,v in result.items() if k != "errors"}).decode())
    return 0 if (result["admitted"] and not errors and process.returncode == 0
                 and not result['transport_errors']
                 and not result["timed_out"] and not result["outside_broker_tool_events"]) else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("launch", "mcp"))
    parser.add_argument("--config", required=True)
    args=parser.parse_args()
    if args.command == "mcp":
        serve_mcp(read(args.config))
        return 0
    return launch(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
