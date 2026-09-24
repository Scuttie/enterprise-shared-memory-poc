"""Project recorded L1 submission examples; no model/grader calls or prose output.

Reads the completed, hash-bound public capture and ON injection records. Code,
task text, tests, reflection prose, and model reasoning are never published.
Literal narrative keyword matches are a search aid, not semantic attribution.
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PILOT = ROOT / 'data/skhynix_lcb_002/pilot-001'
TERMS = ('trace_steps', 'source_lesson', 'finish', 'submit', 'submission', 'integer', 'format', 'schema')


class EvidenceError(ValueError):
    pass


def need(condition, reason):
    if not condition:
        raise EvidenceError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}


def checked(reference_value):
    path = Path(reference_value['path']).resolve()
    current = reference(path)
    need(current['sha256'] == reference_value['sha256'] and
         ('bytes' not in reference_value or current['bytes'] == reference_value['bytes']), 'REFERENCE_CHANGED')
    return path


def read(path, protected):
    ref = reference(path)
    value = json.loads(checked(ref).read_bytes())
    checked(ref)
    protected.append(ref)
    return value


def project_example(item, exposure, envelope):
    raw = item['exact_text'].encode()
    need(sha(raw) == item['sha256'] == exposure['injection_sha256'] and
         len(raw) == item['byte_count'] == exposure['byte_count'], 'VIEW_HASH_CHANGED')
    need(item['memory_id'] == exposure['memory_id'] and item['kind'] == exposure['kind'] == 'EPISODIC' and
         item['canonical_node_hash'] == exposure['canonical_memory_hash'], 'MEMORY_IDENTITY_CHANGED')
    view = json.loads(item['exact_text'])
    lesson = json.loads(view['summary'])
    capture, receipt = envelope['capture'], envelope['receipt']
    need(capture['task_public']['task_id'] == exposure['source_task_id'] and
         capture['task_public']['split'] == 'train' and receipt['episode_id'] == item['memory_id'] and
         receipt['episode_content_hash'] == item['canonical_node_hash'], 'TRAIN_SOURCE_CHANGED')
    need(lesson == {**capture['source_lesson'], 'provenance': 'MODEL_REFLECTION_WITH_PUBLIC_TRACE_ANCHORS',
                   'verification_scope': 'PUBLIC_EXAMPLES_ONLY_NOT_PRIVATE_GRADER'}, 'SOURCE_LESSON_CHANGED')
    steps = lesson['trace_steps']
    source_steps = {event['step_no'] for event in capture['history']}
    need(isinstance(steps, list) and bool(steps) and all(type(step) is int for step in steps) and
         steps == sorted(set(steps)) and set(steps) <= source_steps, 'INVALID_SOURCE_STEP_EXAMPLE')
    actions = [json.loads(action) for action in view['actions']]
    need([action['step_no'] for action in actions] == steps, 'ACTION_ANCHOR_CHANGED')
    narrative = ' '.join([lesson['summary'], lesson['applicability'], *lesson['procedure']]).casefold()
    return {'memory_id': item['memory_id'], 'source_task_id': exposure['source_task_id'],
        'source_family_id': exposure['source_family_id'], 'source_capture_reference': exposure['capture_reference'],
        'view_sha256': item['sha256'], 'canonical_memory_hash': item['canonical_node_hash'],
        'summary_json_keys': sorted(lesson), 'embedded_trace_steps': steps,
        'protocol_fragment': json.dumps({'trace_steps': steps}, sort_keys=True),
        'action_step_examples': [action['step_no'] for action in actions],
        'narrative_literal_substring_matches': {term: term in narrative for term in TERMS},
        'narrative_sha256': sha(canonical({key: lesson[key] for key in ('summary', 'applicability', 'procedure')})),
        'interpretation': 'STRUCTURED_SOURCE_EXAMPLE_PRESENT_NOT_PROOF_OF_MODEL_COPYING_OR_CAUSAL_USE'}


def run():
    protected = []
    analysis = read(HERE.parent / 'pilot-results-001.json', protected)
    audit = read(HERE.parent / 'pilot-exposure-audit-001.json', protected)
    summary = read(checked(analysis['summary_reference']), protected)
    need(analysis['status'] == summary['status'] == 'COMPLETE' and audit['audit_status'] == 'PASS' and
         audit['coverage'] == 'COMPLETE' and audit['summary_reference'] == analysis['summary_reference'],
         'COMPLETE_AUDITED_RUN_REQUIRED')
    frozen = read(PILOT / 'frozen-inputs.json', protected)
    for ref in frozen['implementation']:
        checked(ref)
        protected.append(ref)
    checked(audit['bank_reference'])
    protected.append(audit['bank_reference'])
    exposures = {(row['target_task_id'], row['injection_ordinal']): row for row in audit['exposures']}
    need(len(exposures) == len(audit['exposures']), 'DUPLICATE_EXPOSURE')
    memories, targets = {}, []
    for target in audit['targets']:
        state = read(checked(target['state_reference']), protected)
        solve = read(checked(target['solve_receipt_reference']), protected)
        identity = target['target_task_id']
        need(state['task']['task_id'] == solve['task_id'] == identity and state['arm'] == solve['arm'] == 'ON' and
             solve['state_sha256'] == target['state_reference']['sha256'], 'TARGET_STATE_CHANGED')
        links = []
        for ordinal, item in enumerate(state['memory_injections']):
            exposure = exposures[identity, ordinal]
            envelope = read(checked(exposure['capture_reference']), protected)
            example = project_example(item, exposure, envelope)
            key = example['memory_id']
            need(key not in memories or memories[key] == example, 'REUSED_MEMORY_DIFFERS')
            memories[key] = example
            links.append({'ordinal': ordinal, 'memory_id': key, 'source_task_id': example['source_task_id'],
                          'source_trace_steps': example['embedded_trace_steps'],
                          'active_node_id': item['active_node_id'], 'view_sha256': item['sha256']})
        targets.append({'task_id': identity, 'injection_count': len(links), 'injections': links,
                        'target_state_reference': target['state_reference']})
    need([row['task_id'] for row in targets] == frozen['enrollment']['valid'] and
         sum(row['injection_count'] for row in targets) == len(exposures) == audit['injection_count'],
         'TARGET_ENROLLMENT_OR_EXPOSURE_CHANGED')
    for ref in protected:
        checked(ref)
    report = {'schema': 'trimem/lcb-memory-format-examples/1.0', 'status': 'COMPLETE',
        'scope': 'POSTHOC_READ_ONLY_SCHEMA_PROJECTION_NOT_NEW_EXPERIMENT',
        'model': analysis['model'], 'reasoning_effort': analysis['reasoning_effort'],
        'experiment_id': analysis['experiment_id'], 'bank_sha256': audit['bank_reference']['sha256'],
        'helper_reference': reference(__file__), 'references': protected,
        'counts': {'valid_targets': len(targets), 'exposed_targets': sum(bool(t['injections']) for t in targets),
                   'injections': len(exposures), 'unique_injected_episodes': len(memories),
                   'episodes_with_numeric_trace_step_example': len(memories),
                   'episodes_with_any_narrative_literal_match': sum(any(m['narrative_literal_substring_matches'].values())
                                                                  for m in memories.values())},
        'episodes': list(memories.values()), 'targets': targets,
        'model_calls': 0, 'grader_calls': 0, 'original_writes': 0, 'references_unchanged': True,
        'prose_code_problem_test_reasoning_output': False,
        'limitations': ['Literal substring scans do not prove semantic absence of format advice.',
                       'Source step numbers identify source TRAIN history; target must cite its own history.',
                       'This projection alone does not establish delivery before a target action.',
                       'Recorded schema examples do not prove internal reasoning, copying or causal attribution.']}
    output = HERE / 'memory-examples-001.json'
    raw = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    need(not output.exists() or output.read_bytes() == raw, 'EXISTING_REPORT_DIFFERS')
    if not output.exists():
        with output.open('xb') as stream:
            stream.write(raw)
    print(json.dumps({'status': 'COMPLETE', 'counts': report['counts'], 'report_reference': reference(output)}))


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        # Never expose a source payload embedded in an exception message.
        print(json.dumps({'status': 'ERROR', 'error_type': type(exc).__name__,
                          'reason': str(exc) if isinstance(exc, EvidenceError) else 'UNEXPECTED_SOURCE_SHAPE'}))
        raise SystemExit(2)
