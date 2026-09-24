"""Evaluation-only paired LCB run with an inherited immutable training bank.

The additive native adapter supplies identical explicit submission rules. All
48 fresh solves are sealed before diagnostic selection or private grading.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import sys
import time

# Install the deliberate process-local hooks before using the original manager.
import lcb_explicit_format_native as native
import trimem_lcb_experiment as exp
import trimem_lcb_memory as memory

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'lcb-explicit-format-experiment/1'
COLLECTION_SCHEMA = 'lcb-explicit-format-collection/1'


class ExplicitExperimentError(exp.ExperimentError):
    pass


def require(ok, code):
    if not ok:
        raise ExplicitExperimentError(code)


def checked(ref):
    require(isinstance(ref, dict) and set(ref) >= {'path', 'sha256', 'bytes'}, 'INVALID_ABSOLUTE_REFERENCE')
    path = Path(ref['path']).resolve()
    require(exp.reference(path) == ref, 'REFERENCED_SOURCE_CHANGED')
    return path


def unique_references(refs):
    result = {}
    for ref in refs:
        key = str(Path(ref['path']).resolve())
        require(key not in result or result[key] == ref, 'CONFLICTING_SOURCE_REFERENCE')
        result[key] = ref
    return [result[key] for key in sorted(result)]


def schedule(valid_ids):
    require(len(valid_ids) == len(set(valid_ids)) == 24, 'VALID_COHORT_MUST_HAVE_24_IDS')
    return [(identity, arm) for i, identity in enumerate(valid_ids)
            for arm in (('OFF', 'ON') if i % 2 == 0 else ('ON', 'OFF'))]


def validate_source_bank(config, runtime, tasks, split):
    bank_ref = config['source_bank_reference']
    bank_path = checked(bank_ref)
    bank_receipt_ref = config.get('source_bank_receipt_reference', config.get('source_bank_receipt'))
    bank_receipt = exp.read(checked(bank_receipt_ref))
    summary_ref = config['source_summary_reference']
    summary = exp.read(checked(summary_ref))
    old_frozen_ref = config['source_frozen_inputs_reference']
    old_frozen = exp.read(checked(old_frozen_ref))
    exp.verify_frozen(old_frozen)
    require(old_frozen['model'] == runtime['native']['model'] == 'gpt-5.6-luna' and
            old_frozen['reasoning_effort'] == runtime['native']['reasoning_effort'] == 'low', 'SOURCE_MODEL_DIFFERS')
    require(old_frozen['enrollment']['valid'] == split['pilot_ids'] and
            old_frozen['enrollment']['train'] == split['train_pilot_ids'], 'SOURCE_SPLIT_DIFFERS')
    require(Path(bank_receipt['path']).resolve() == bank_path and bank_receipt['sha256'] == bank_ref['sha256'], 'SOURCE_BANK_RECEIPT_DIFFERS')
    require(summary['status'] == 'COMPLETE' and summary['bank'] == bank_receipt, 'SOURCE_SUMMARY_BANK_DIFFERS')
    training = [row for row in summary['cells'] if row['arm'] == 'TRAIN']
    require(len(training) == 24 and {r['task_id'] for r in training} == set(split['train_pilot_ids']), 'SOURCE_TRAIN_COHORT_DIFFERS')
    refs = [bank_ref, bank_receipt_ref, summary_ref, old_frozen_ref, *old_frozen['references']]
    for row in training:
        if row.get('capture_status') != 'CAPTURED':
            continue
        solve_path = checked(row['solve_reference'])
        solve = exp.read(solve_path)
        require(solve['task_id'] == row['task_id'] and solve['arm'] == 'TRAIN' and solve['status'] == 'SUBMITTED' and
                solve['candidate_sha256'] == row['candidate_sha256'], 'SOURCE_TRAIN_SOLVE_DIFFERS')
        state_ref = exp.reference(solve_path.parent / 'state.json')
        require(state_ref['sha256'] == solve['state_sha256'], 'SOURCE_TRAIN_STATE_DIFFERS')
        checked(row['capture_reference'])
        refs.extend([row['solve_reference'], state_ref, row['capture_reference']])
    bank = {key: bank_receipt[key] for key in ('path', 'sha256', 'layer_counts')}
    exp.verify_bank_cohort(bank, training, runtime)
    with memory.load_frozen_bank(bank['path'], bank['sha256']) as frozen:
        scope = frozen.manifest['scope']
        require(scope['org_id'] == config['org_id'] and scope['owner_user_id'] == config['owner_user_id'], 'SOURCE_BANK_OWNER_DIFFERS')
        require(all(memory._descriptor(tasks[identity]) in scope['tasks'] for identity in split['pilot_ids']), 'TARGET_OUTSIDE_SOURCE_BANK_SCOPE')
        refs.append(exp.reference(exp.checked_reference(frozen.root, frozen.manifest['authority'])))
        for kind in ('captures', 'observations'):
            for ref in frozen.manifest['catalog'][kind].values():
                refs.append(exp.reference(exp.checked_reference(frozen.root, ref)))
    return bank, unique_references(refs)


def _prepare(config_path, runtime_path, dataset_root, output):
    config, runtime, split, public_manifest, tasks, frozen = exp.load_inputs(config_path, runtime_path, dataset_root)
    require(config.get('workers', 2) == 2 and config['requested_model'] == 'gpt-5.6-luna' and config['reasoning_effort'] == 'low', 'EXPLICIT_RUN_CONTRACT_CHANGED')
    require(type(config.get('repeats')) is int and config['repeats'] == 1 and
            type(config.get('new_training_cells')) is int and config['new_training_cells'] == 0,
            'EXPLICIT_RUN_COUNTS_CHANGED')
    jobs = schedule(split['pilot_ids'])
    require(config.get('launch_order') == [{'task_id': identity, 'arm': arm} for identity, arm in jobs],
            'DECLARED_LAUNCH_ORDER_CHANGED')
    bank, bank_refs = validate_source_bank(config, runtime, tasks, split)
    auxiliary = importlib.import_module('lcb_explicit_format_diagnostic')
    extra = [exp.reference(__file__), exp.reference(native.__file__), exp.reference(auxiliary.__file__),
             exp.reference(runtime['native']['codex_executable'])]
    frozen = deepcopy(frozen)
    frozen['schema'] = SCHEMA
    frozen['references'] = unique_references([*frozen['references'], *extra, *bank_refs])
    frozen['evaluation_only'] = True
    frozen['new_training_cells'] = 0
    frozen['source_bank_reference'] = config['source_bank_reference']
    frozen['schedule'] = [{'ordinal': i, 'task_id': identity, 'arm': arm} for i, (identity, arm) in enumerate(jobs, 1)]
    frozen['schedule_semantics'] = 'BALANCED_PAIR_SCHEDULING_ORDER_NOT_NATIVE_COMPLETION_ORDER'
    path = output / 'frozen-inputs.json'
    if path.exists():
        require(exp.read(path) == frozen, 'RESUMED_EXPLICIT_INPUTS_DIFFER')
    else:
        require(all(p.name == 'experiment.lock' for p in output.iterdir()), 'OUTPUT_NOT_FRESH')
        native.write(path, frozen, fresh=True)
    exp.verify_frozen(frozen)
    preparation = {'schema': SCHEMA, 'status': 'PREPARED', 'planned_evaluation_cells': 48,
                   'new_training_cells': 0, 'model_calls': 0, 'private_grader_calls': 0,
                   'source_bank': bank, 'frozen_inputs_reference': exp.reference(path),
                   'schedule': frozen['schedule']}
    prepared_path = output / 'preparation.json'
    if prepared_path.exists():
        require(exp.read(prepared_path) == preparation, 'PREPARATION_RECEIPT_CHANGED')
    else:
        native.write(prepared_path, preparation, fresh=True)
    return {'config': config, 'runtime': runtime, 'split': split, 'public_manifest': public_manifest,
            'tasks': tasks, 'frozen': frozen, 'bank': bank, 'auxiliary': auxiliary,
            'jobs': jobs, 'preparation': preparation}


def prepare(config_path, runtime_path, dataset_root, output):
    output = Path(output).resolve()
    with exp.exclusive_lock(output):
        return _prepare(config_path, runtime_path, Path(dataset_root).resolve(), output)['preparation']


def generation_row(row):
    excluded = {'grade_reference', 'grader_seconds', 'grade_error_type', 'resolved', 'outcome'}
    result = {k: deepcopy(v) for k, v in row.items() if k not in excluded}
    result['passed'] = None
    result['grade_status'] = 'PENDING' if result['status'] == 'SUBMITTED' else 'GENERATION_ERROR'
    return result


def _scheduled_start(output, frozen, ordinal, task_id, arm):
    folder = output / 'collection-starts'
    folder.mkdir(exist_ok=True)
    path = folder / ('%03d.json' % ordinal)
    identity = {'schema': SCHEMA, 'scheduled_ordinal': ordinal, 'task_id': task_id, 'arm': arm,
                'frozen_inputs_reference': exp.reference(output / 'frozen-inputs.json')}
    if path.exists():
        previous = exp.read(path)
        require(all(previous.get(k) == value for k, value in identity.items()), 'SCHEDULED_START_CHANGED')
    else:
        require(not (output / 'cells' / exp.cell_name(task_id, arm)).exists(), 'MISSING_PREEXISTING_START_EVIDENCE')
        native.write(path, {**identity, 'recorded_at': datetime.now(timezone.utc).isoformat()}, fresh=True)
    return exp.reference(path)


def seal_collection(output, rows, frozen, tasks):
    output = Path(output).resolve()
    expected = [(r['task_id'], r['arm']) for r in frozen['schedule']]
    require(len(expected) == 48 and len(rows) == 48 and [(r['task_id'], r['arm']) for r in rows] == expected, 'COLLECTION_COHORT_INCOMPLETE')
    require(all(r['status'] in ('SUBMITTED', 'GENERATION_ERROR') and 'solve_reference' in r for r in rows), 'UNSEALED_OR_HELD_NATIVE_ATTEMPT')
    refs, sessions, generation = [exp.reference(output / 'frozen-inputs.json')], 0, []
    for ordinal, row in enumerate(rows, 1):
        cell = output / 'cells' / exp.cell_name(row['task_id'], row['arm'])
        solve_path = checked(row['solve_reference'])
        require(solve_path == cell / 'solve-receipt.json', 'SOLVE_PATH_CHANGED')
        solve, state = exp.read(solve_path), exp.read(cell / 'state.json')
        rebuilt = exp._cell_result(cell, tasks[row['task_id']], row['arm'], solve, state)
        require(generation_row(row) == generation_row(rebuilt), 'COLLECTION_GENERATION_ROW_CHANGED')
        generation.append(generation_row(rebuilt))
        refs.extend(exp.reference(cell / name) for name in ('solve-receipt.json', 'state.json', 'attempt.json'))
        require((output / 'collection-starts' / ('%03d.json' % ordinal)).is_file(), 'MISSING_SCHEDULE_START_EVIDENCE')
        refs.append(_scheduled_start(output, frozen, ordinal, row['task_id'], row['arm']))
        for i, session in enumerate(solve['sessions'], 1):
            require(session['session'] == i, 'SESSION_SEQUENCE_CHANGED')
            folder = cell / ('session-%02d' % i)
            require(exp.read(folder / 'receipt.json') == session, 'SESSION_RECEIPT_CHANGED')
            require(exp.file_hash(folder / 'events.jsonl') == session['events_sha256'] and
                    exp.file_hash(folder / 'stderr.log') == session['stderr_sha256'], 'SESSION_OUTPUT_HASH_CHANGED')
            prompt = exp.read(folder / 'prompt-receipt.json')
            require(prompt['task_id'] == row['task_id'] and prompt['arm'] == row['arm'] and prompt['session'] == i,
                    'PROMPT_IDENTITY_CHANGED')
            require(prompt['prompt_sha256'] == exp.file_hash(folder / 'prompt.txt') and
                    prompt['prompt_bytes'] == (folder / 'prompt.txt').stat().st_size and
                    prompt['contract_sha256'] == exp.sha(native.CONTRACT.encode()), 'PROMPT_CONTRACT_CHANGED')
            command_state = {**state, 'session': i}
            require(prompt['command_sha256'] == exp.sha(native.canonical(native.worker_command(cell, command_state))), 'PROMPT_LAUNCH_COMMAND_CHANGED')
            refs.extend(exp.reference(folder / name) for name in ('receipt.json', 'prompt-receipt.json', 'prompt.txt', 'events.jsonl', 'stderr.log'))
            sessions += 1
    collection = {'schema': COLLECTION_SCHEMA, 'status': 'COMPLETE', 'planned_cells': 48,
                  'completed_cells': 48, 'native_sessions': sessions, 'rows': generation,
                  'frozen_inputs_reference': exp.reference(output / 'frozen-inputs.json'),
                  'source_references': unique_references(refs), 'new_training_cells': 0,
                  'private_grading_started': False, 'diagnostic_selection_started': False}
    path = output / 'collection.json'
    if path.exists():
        require(exp.read(path) == collection, 'COLLECTION_SEAL_CHANGED')
    else:
        native.write(path, collection, fresh=True)
    return exp.reference(path)


def verify_collection(output, expected_reference):
    output = Path(output).resolve()
    require(checked(expected_reference) == output / 'collection.json', 'COLLECTION_REFERENCE_OUTSIDE_OUTPUT')
    collection = exp.read(output / 'collection.json')
    require(collection['schema'] == COLLECTION_SCHEMA and collection['status'] == 'COMPLETE' and
            collection['planned_cells'] == collection['completed_cells'] == len(collection['rows']) == 48, 'COLLECTION_NOT_COMPLETE')
    frozen = exp.read(checked(collection['frozen_inputs_reference']))
    exp.verify_frozen(frozen)
    expected = [(r['task_id'], r['arm']) for r in frozen['schedule']]
    require([(r['task_id'], r['arm']) for r in collection['rows']] == expected, 'COLLECTION_IDENTITY_CHANGED')
    for ref in collection['source_references']:
        checked(ref)
    return collection


def summarize(context, rows, *, phase, elapsed, private_ready=False):
    # Original summarize divides by a zero TRAIN denominator. Retain the real
    # source split internally, remove its unexecuted arm, and recompute status.
    value = exp.summarize(context['config'], context['split'], deepcopy(rows), context['bank'],
                          private_ready=private_ready, manager_seconds=elapsed)
    value['arms'].pop('TRAIN')
    value['schema'] = SCHEMA
    value['phase'] = phase
    value['new_training_cells'] = 0
    value['source_training_tasks'] = context['bank']['layer_counts']['training_tasks']
    value['evaluation_cells_planned'] = 48
    value['evaluation_cells_recorded'] = len(rows)
    complete = all(v['resolved_outcomes'] == v['planned'] for v in value['arms'].values())
    value['status'] = 'COMPLETE' if phase == 'COMPLETE' and complete else ('HELD' if phase == 'HELD' else 'INCOMPLETE')
    value['source_bank_reference'] = context['config']['source_bank_reference']
    return value


def grade_primary(output, row, manifest, dataset_root, runtime, config, collection_reference):
    """Retain the original grader while rejecting interrupted attempts as retries."""
    if row['status'] == 'SUBMITTED':
        name = exp.cell_name(row['task_id'], row['arm'])
        directory = Path(output) / 'private-grades' / name
        folder = Path(output) / 'primary-grade-starts'
        folder.mkdir(exist_ok=True)
        path = folder / (name + '.json')
        authority = {'schema': SCHEMA, 'task_id': row['task_id'], 'arm': row['arm'],
                     'collection_reference': collection_reference,
                     'generation_row_sha256': exp.sha(native.canonical(generation_row(row)))}
        if path.exists():
            previous = exp.read(path)
            require(all(previous.get(k) == v for k, v in authority.items()), 'PRIMARY_GRADE_START_CHANGED')
            require(row.get('grade_status') != 'PENDING' or (directory / 'report.json').is_file(),
                    'PARTIAL_PRIMARY_GRADING_NO_RETRY')
        else:
            require(row.get('grade_status') == 'PENDING' and not directory.exists(),
                    'MISSING_PRIMARY_GRADE_START_EVIDENCE')
            native.write(path, {**authority, 'recorded_at': datetime.now(timezone.utc).isoformat()}, fresh=True)
    return exp.grade_cell(output, row['task_id'], row['arm'], row, manifest, dataset_root, runtime, config)


def run_experiment(config_path, runtime_path, dataset_root, output, *, collect_only=False):
    output, dataset_root = Path(output).resolve(), Path(dataset_root).resolve()
    started = time.monotonic()
    with exp.exclusive_lock(output):
        context = _prepare(config_path, runtime_path, dataset_root, output)
        frozen, rows = context['frozen'], []

        def checkpoint(phase, private_ready=False):
            value = summarize(context, rows, phase=phase, elapsed=time.monotonic() - started, private_ready=private_ready)
            exp.write(output / 'summary.json', value)
            return value

        checkpoint('COLLECTING')
        for offset in range(0, 48, 2):
            exp.verify_frozen(frozen)
            jobs = context['jobs'][offset:offset + 2]
            for ordinal, (task_id, arm) in enumerate(jobs, offset + 1):
                _scheduled_start(output, frozen, ordinal, task_id, arm)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(exp.collect_cell, output, context['tasks'][task_id], arm,
                                       context['runtime'], context['bank'] if arm == 'ON' else None, frozen)
                           for task_id, arm in jobs]
                rows.extend(f.result() for f in futures)
            checkpoint('COLLECTING')
            if any(row['status'] == 'HELD' for row in rows):
                exp.verify_frozen(frozen)
                return checkpoint('HELD')
        exp.verify_frozen(frozen)
        collection_ref = seal_collection(output, rows, frozen, context['tasks'])
        verify = lambda: verify_collection(output, collection_ref)
        verify()
        checkpoint('COLLECTED')
        if collect_only:
            return checkpoint('COLLECTED')
        diagnostic = context['auxiliary']
        # Seal diagnostic choices for all 48 BEFORE any private evaluation.
        selection_ref = diagnostic.prepare_diagnostics(output, verify()['rows'],
                            collection_reference=collection_ref, verify_collection=verify)
        verify()
        manifest = exp.final_manifest(context['config'], context['split'], context['public_manifest'], dataset_root, output)
        if manifest is None:
            return checkpoint('WAITING_FOR_PRIVATE_DATA')
        for i, row in enumerate(rows):
            verify()
            rows[i] = grade_primary(output, row, manifest, dataset_root, context['runtime'],
                                    context['config'], collection_ref)
            checkpoint('GRADING_PRIMARY', private_ready=True)
        verify()
        auxiliary_summary = diagnostic.grade_diagnostics(output, selection_ref, manifest,
            dataset_root, context['runtime'], context['config'], rows,
            collection_reference=collection_ref, verify_collection=verify)
        verify()
        result = checkpoint('COMPLETE', private_ready=True)
        result['collection_reference'] = collection_ref
        result['diagnostic_selection_reference'] = selection_ref
        result['diagnostic_summary_reference'] = exp.reference(output / 'diagnostic-summary.json')
        result['diagnostic_status'] = auxiliary_summary.get('status')
        exp.write(output / 'summary.json', result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'run'))
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--dataset-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--collect-only', action='store_true')
    args = parser.parse_args()
    if args.mode == 'prepare':
        result = prepare(args.config, args.runtime, args.dataset_root, args.output)
        print(json.dumps({k: result[k] for k in ('status', 'planned_evaluation_cells', 'new_training_cells')}))
    else:
        result = run_experiment(args.config, args.runtime, args.dataset_root, args.output, collect_only=args.collect_only)
        print(json.dumps({k: result[k] for k in ('status', 'phase', 'evaluation_cells_recorded', 'new_training_cells')}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Paths/payload-bearing exception strings are never printed.
        print(json.dumps({'status': 'ERROR', 'error_type': type(exc).__name__,
                          'error_code': str(exc) if isinstance(exc, ExplicitExperimentError) else 'EXPLICIT_RUN_FAILED'}))
        raise SystemExit(1) from None
