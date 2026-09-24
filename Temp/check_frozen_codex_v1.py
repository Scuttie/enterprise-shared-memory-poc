"""One fresh tool-free transport probe, separate from all benchmark attempts."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

repo = Path('C:/Users/jewon/esm-r23-d115-writer')
art = repo / 'artifacts/skhynix_v1/architecture_scale_001'
prior = Path('C:/Users/jewon/AppData/Local/Temp/skhynix-codex-quota-health-20260915T070932Z-e4cd0f6a')
root = Path('C:/Users/jewon/AppData/Local/Temp/skhynix-frozen-codex-health-001')
root.mkdir(exist_ok=False)
(root / 'empty-workspace').mkdir()
binary = Path('C:/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-codex-v1/codex.exe')
assert hashlib.sha256(binary.read_bytes()).hexdigest() == '2271526227b06ca13ab2b975b88546460fc61b2a29225b6dda0fdc803024ccc9'
command = json.loads((prior / 'command.json').read_text())
command[0] = str(binary)
command[command.index('-C') + 1] = str(root / 'empty-workspace')
command[command.index('-o') + 1] = str(root / 'response.txt')
prompt = b'Reply with exactly OK and nothing else. Do not call any tools.\n'
def retain(path, value):
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n')
def ref(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
retain(root / 'command.json', command)
(root / 'prompt.txt').write_bytes(prompt)
started = datetime.now(timezone.utc).isoformat()
retain(root / 'intent.json', {'operation': 'ONE_FRESH_TOOL_FREE_SESSION', 'started_at': started,
    'requested_model': 'gpt-6-astra', 'reasoning_effort': 'high', 'benchmark_solves': 0,
    'official_grader_runs': 0, 'automatic_retry': False, 'binary_reference': ref(binary)})
env = dict(os.environ)
env.pop('OPENAI_API_KEY', None)
env.pop('CODEX_API_KEY', None)
timeout = False
with (root / 'events.jsonl').open('xb') as out, (root / 'stderr.log').open('xb') as err:
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=out, stderr=err, env=env)
    try:
        proc.communicate(prompt, timeout=90)
    except subprocess.TimeoutExpired:
        timeout = True
        proc.kill()
        proc.wait(timeout=15)
events = [json.loads(line) for line in (root / 'events.jsonl').read_bytes().splitlines()]
response = (root / 'response.txt').read_text().strip() if (root / 'response.txt').exists() else ''
tools = [event for event in events if event.get('item', {}).get('type') in
         {'mcp_tool_call', 'command_execution', 'web_search', 'file_change'}]
result = {'schema': 'skhynix/frozen-native-transport-health/1.0', 'started_at': started,
    'finished_at': datetime.now(timezone.utc).isoformat(), 'exit_code': proc.returncode,
    'timed_out': timeout, 'requested_model': 'gpt-6-astra', 'reasoning_effort': 'high',
    'model_session_attempts': 1, 'benchmark_solves': 0, 'official_grader_runs': 0,
    'separate_api_client_calls': 0, 'automatic_retry': False, 'tool_event_count': len(tools),
    'response_is_exact_OK': response == 'OK',
    'turn_completed_count': sum(row.get('type') == 'turn.completed' for row in events),
    'binary_reference': ref(binary), 'source_reference': ref(Path(__file__)),
    'logs': {path.name: ref(path) for path in root.iterdir() if path.is_file()}}
result['status'] = 'PASS' if proc.returncode == 0 and not timeout and not tools and response == 'OK' else 'FAIL'
retain(art / 'frozen-native-transport-health-001.json', result)
print(json.dumps({key: result[key] for key in ('status', 'exit_code', 'timed_out', 'response_is_exact_OK', 'tool_event_count')}))
