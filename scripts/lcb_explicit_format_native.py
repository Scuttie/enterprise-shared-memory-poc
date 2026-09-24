"""Common explicit submission contract over the unchanged native solver core.

The adapter is used in both manager and MCP processes. No bank writes, private
grading, automatic correction, or validator changes are introduced here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import trimem_lcb_native as core

_original_context = core.context
_original_prompt = core.prompt_for
_original_worker = core.worker_command
_original_solve = core.solve_cell

CONTRACT = '''COMMON SUBMISSION CONTRACT (identical for memory OFF and ON):
The benchmark.action MCP arguments must be exactly {"request":{"tool":OP,"arguments":{...}}}.
For finish, the request must be exactly {"tool":"finish","arguments":{"code":STRING,"source_lesson":OBJECT}}.
The code must be the complete nonempty Python source, without Markdown fences, at most 65536 UTF-8 bytes.
source_lesson must contain EXACTLY these four keys, with no additional keys:
  summary: a nonblank string, at most 6000 UTF-8 bytes.
  applicability: a nonblank string, at most 3000 UTF-8 bytes.
  procedure: an array of 1 through 12 nonblank strings, each at most 1500 UTF-8 bytes.
  trace_steps: a NONEMPTY JSON ARRAY OF INTEGERS, sorted increasingly with NO DUPLICATES.
Each trace_steps integer MUST occur in context.submission_contract.available_trace_steps for THIS target task.
Use numeric JSON values such as 2, not "2", booleans, descriptions, or objects such as {"step_no":2}.
All successful non-finish operations in this target's history are eligible, including successful graph edits,
public-test operations, and completed subtasks. Rejected operations are not eligible.
The available_trace_steps list is refreshed after every action and at each new session. At the start it is empty.
A new successful action's step_no is added to that list. At least one real run_public_tests attempt is separately
required before finish; public tests need not all pass. Cite actual evidence and never claim unseen tests passed.
The compact JSON encoding of the complete source_lesson (UTF-8, non-ASCII unescaped, plus final newline) must fit in 8000 bytes.
Prefer a concise lesson well below this limit. Do not add extra metadata keys to the lesson.

SYNTHETIC SYNTAX EXAMPLE ONLY: suppose a DIFFERENT example task has a completed successful history step 2.
Its valid finish arguments could look like:
{"request":{"tool":"finish","arguments":{"code":"<complete final Python source>","source_lesson":{"summary":"State the method learned from this attempt.","applicability":"State when this method applies.","procedure":["Describe a concrete step supported by the public history."],"trace_steps":[2]}}}}
This example provides the syntax, not a valid trace ID for your task. Use your current available_trace_steps.
Likewise, numbers in TRAIN memories belong to those SOURCE tasks. Never cite a source task's number unless that
number independently exists in your target's available_trace_steps and supports your target's lesson.
Before finish, check the four keys, string/list types, integer IDs, sorted uniqueness, and full candidate code.
Use the existing action/test/session/time budgets; a rejected submission is not automatically repaired.
'''


def context(state, *, recall=True):
    value = _original_context(state, recall=recall)
    value['submission_contract'] = {
        'available_trace_steps': sorted(event['step_no'] for event in state['history']),
        'public_test_attempts': state['public_test_runs'],
        'trace_steps_type': 'nonempty_sorted_unique_array_of_target_history_integers',
    }
    return value


def prompt_for(state):
    original = _original_prompt(state)
    prefix, packet = original.split('TASK_PACKET:\n', 1)
    # Remove the old underspecified placeholder instead of showing conflicting examples.
    prefix = prefix.replace('"trace_steps":[ACTUAL_PUBLIC_TRACE_STEP]', '"trace_steps":[2]')
    value = prefix + CONTRACT + '\nTASK_PACKET:\n' + packet
    if len(value.encode('utf8')) > state['limits']['prompt_bytes']:
        raise ValueError('Explicit task packet exceeds declared context byte cap')
    return value


def worker_command(cell, state):
    command = _original_worker(cell, state)
    setting = 'mcp_servers.benchmark.args='
    matches = [i for i, arg in enumerate(command) if arg.startswith(setting)]
    if len(matches) != 1:
        raise ValueError('Native broker argument setting differs')
    index = matches[0]
    args = json.loads(command[index][len(setting):])
    if Path(args[0]).resolve() != Path(core.__file__).resolve():
        raise ValueError('Unexpected base broker script')
    args[0] = str(Path(__file__).resolve())
    command[index] = setting + json.dumps(args)
    return command


def solve_cell(cell, *, before_model_call=None):
    cell = Path(cell).resolve()

    def seal_prompt():
        if before_model_call:
            before_model_call()
        state = core.read(cell / 'state.json')
        folder = cell / ('session-%02d' % state['session'])
        raw = (folder / 'prompt.txt').read_bytes()
        core.write(folder / 'prompt-receipt.json', {
            'schema': 'lcb-explicit-format-prompt/1',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'task_id': state['task']['task_id'], 'arm': state['arm'], 'session': state['session'],
            'prompt_sha256': hashlib.sha256(raw).hexdigest(), 'prompt_bytes': len(raw),
            'contract_sha256': hashlib.sha256(CONTRACT.encode()).hexdigest(),
            'state_before_call_sha256': hashlib.sha256((cell / 'state.json').read_bytes()).hexdigest(),
            'command_sha256': hashlib.sha256(core.canonical(worker_command(cell, state))).hexdigest(),
        }, fresh=True)

    return _original_solve(cell, before_model_call=seal_prompt)


# Deliberate process-local adapter hooks: unchanged files and original validator.
core.context = context
core.prompt_for = prompt_for
core.worker_command = worker_command
core.solve_cell = solve_cell


def __getattr__(name):
    return getattr(core, name)


if __name__ == '__main__':
    # The original main uses binary stdin/stdout for MCP JSON, independent of the
    # Windows text-stream code page. Its validation and action budgets are kept.
    core.main()
