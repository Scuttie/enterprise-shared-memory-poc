"""Sequential discovery, private-procedure verification, VALID and TEST.

All cohorts are preregistered. Missing readiness skips later model calls, rather
than expanding training or claiming absent L3 exposure as an L3 experiment.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import lcb_transfer_native as native
import lcb_transfer_plan as planner
import lcb_personal_memory as memory
import trimem_lcb_experiment as base

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'lcb-transfer-experiment/1'
PHASES = ('DISCOVERY', 'VERIFICATION', 'VALID', 'TEST')
MODEL_FAILURES = {'TaskTimeout', 'SessionBudgetExhausted', 'MissingSubmission',
                  'UnexpectedNativeTool', 'ActionCallBudgetExceeded'}


class TransferError(ValueError):
    pass


def require(value, code):
    if not value:
        raise TransferError(code)


def checked(ref):
    require(base.reference(ref['path']) == ref, 'REFERENCED_BYTES_CHANGED')
    return Path(ref['path'])


def fresh(path, value):
    path = Path(path)
    if path.exists():
        require(base.read(path) == value, 'IMMUTABLE_RECEIPT_CHANGED')
    else:
        native.write(path, value, fresh=True)


def load(plan_path, runtime_path, dataset_root, output):
    plan = base.read(plan_path)
    planner.verify_references(plan['source_references'])
    sources = plan['source_references']
    rebuilt = planner.from_files(ROOT / sources['split']['path'], ROOT / sources['public_split']['path'],
                                 ROOT / sources['exclusion_config']['path'], seed=plan['selection_seed'])
    require(plan == rebuilt, 'PLAN_DERIVATION_CHANGED')
    require(plan['schema'] == planner.SCHEMA and plan['schedule_sha256'] == planner.digest(planner.canonical(planner.schedule(plan))), 'PLAN_CHANGED')
    config_path = ROOT / plan['source_references']['exclusion_config']['path']
    config, runtime, split, public_manifest, tasks, frozen = base.load_inputs(config_path, runtime_path, dataset_root)
    require(runtime['native']['model'] == plan['requested_model'] and runtime['native']['reasoning_effort'] == plan['reasoning_effort'], 'MODEL_SETTINGS_CHANGED')
    frozen = deepcopy(frozen)
    extra = [base.reference(path) for path in (plan_path, __file__, native.__file__, memory.__file__, planner.__file__,
             ROOT / 'scripts/lcb_explicit_format_native.py', runtime['native']['codex_executable'])]
    refs = {ref['path']: ref for ref in frozen['references'] + extra}
    frozen.update(schema=SCHEMA, references=[refs[k] for k in sorted(refs)],
        enrollment={name: value['task_ids'] for name, value in plan['cohorts'].items()},
        schedule=planner.schedule(plan), shared_test_budget=4,
        memory_scope='PRIVATE_OWNER', organisation_shared_promotion=False,
        private_grades_used_for_memory=False, repeated_attempts=1)
    fresh(output / 'frozen-inputs.json', frozen)
    base.verify_frozen(frozen)
    return {'plan': plan, 'config': config, 'runtime': runtime, 'split': split,
            'public_manifest': public_manifest, 'tasks': tasks, 'frozen': frozen,
            'dataset_root': Path(dataset_root).resolve(), 'output': output}


def condition(job):
    return job['condition'] if 'condition' in job else job['arm']


def native_arm(job):
    if 'native_arm' in job:
        return job['native_arm']
    return 'ON' if job['arm'] == 'L1ONLY' else job['arm']


def cell_paths(output, job):
    folder = output / job['phase'] / condition(job)
    return folder, folder / 'cells' / base.cell_name(job['task_id'], native_arm(job))


def verify(context):
    base.verify_frozen(context['frozen'])
    planner.verify_references(context['plan']['source_references'])


def collect(context, job, bank, selected_id):
    verify(context)
    output, task = context['output'], context['tasks'][job['task_id']]
    folder, cell = cell_paths(output, job)
    start_path = output / 'starts' / ('%04d.json' % job['ordinal'])
    identity = {'schema': SCHEMA, **job, 'native_arm': native_arm(job), 'condition': condition(job),
                'frozen_inputs_reference': base.reference(output / 'frozen-inputs.json'),
                'bank': bank, 'selected_procedure_id': selected_id}
    if start_path.exists():
        require(all(base.read(start_path).get(k) == v for k, v in identity.items()), 'CELL_START_CHANGED')
    else:
        require(not cell.exists(), 'MISSING_PREEXISTING_CELL_START')
        fresh(start_path, {**identity, 'started_at': datetime.now(timezone.utc).isoformat()})
    row_path = cell / 'cell-receipt.json'
    if (cell / 'solve-receipt.json').exists():
        solve, state = base.read(cell / 'solve-receipt.json'), base.read(cell / 'state.json')
        require(state['phase'] == job['phase'] and state['bank'] == bank and
                state['runtime'] == context['runtime'] and state.get('selected_procedure_id') == selected_id and
                state.get('owner_user_id') == context['config']['owner_user_id'] and
                state.get('org_id') == context['config']['org_id'] and
                state.get('enabled_layers') == (['L1'] if condition(job) == 'L1ONLY' else ['L3', 'L2', 'L1']),
                'RESUMED_CELL_SCOPE_CHANGED')
        row = base._cell_result(cell, task, native_arm(job), solve, state)
        if row_path.exists():
            old = base.read(row_path)
            require(old['solve_reference'] == row['solve_reference'] and old['candidate_sha256'] == row['candidate_sha256'], 'RESUMED_SOLVE_CHANGED')
            if 'grade_reference' in old:
                grade_path = checked(old['grade_reference'])
                require(grade_path.resolve() == (folder / 'private-grades' / cell.name / 'report.json').resolve(), 'CACHED_GRADE_PATH_CHANGED')
                report = base.read(grade_path)
                outcomes = report.get('results', [])
                require(len(outcomes) == 1 and outcomes[0].get('question_id') == task['task_id'] and
                    outcomes[0].get('status') == old.get('grade_status') and outcomes[0].get('passed') is old.get('passed') and
                    (old.get('grade_status') != 'GRADED' or outcomes[0].get('extracted_code_sha256') == row['candidate_sha256']),
                    'CACHED_GRADE_VERDICT_CHANGED')
                settings = context['config'].get('private_grading', {})
                require(report.get('provenance', {}).get('upstream_commit') == base.UPSTREAM_COMMIT and
                    report.get('settings', {}).get('timeout_seconds') == settings.get('timeout_seconds_per_case', 6) and
                    report.get('settings', {}).get('workers') == settings.get('workers_per_cell', 1), 'CACHED_GRADER_SETTINGS_CHANGED')
                for key in ('grade_status', 'passed', 'grade_reference', 'grader_seconds', 'grade_error_type'):
                    if key in old: row[key] = old[key]
    elif cell.exists():
        row = {'task_id': task['task_id'], 'arm': native_arm(job), 'status': 'HELD',
               'error_type': 'InterruptedNativeAttempt', 'grade_status': 'NOT_GRADED', 'passed': None}
    else:
        native.initialize_cell(cell, task, native_arm(job), context['runtime'], bank=bank,
            phase=job['phase'], owner_user_id=context['config']['owner_user_id'], org_id=context['config']['org_id'],
            selected_procedure_id=selected_id,
            enabled_layers=('L1',) if condition(job) == 'L1ONLY' else ('L3', 'L2', 'L1'))
        fresh(cell / 'attempt.json', {**identity, 'started_at': datetime.now(timezone.utc).isoformat()})
        try:
            solve = native.solve_cell(cell, before_model_call=lambda: verify(context))
            row = base._cell_result(cell, task, native_arm(job), solve, base.read(cell / 'state.json'))
        except base.FrozenInputChanged:
            raise
        except Exception as exc:
            row = {'task_id': task['task_id'], 'arm': native_arm(job), 'status': 'HELD',
                   'error_type': type(exc).__name__, 'grade_status': 'NOT_GRADED', 'passed': None}
    row.update(phase=job['phase'], condition=condition(job), ordinal=job['ordinal'])
    if (cell / 'state.json').exists():
        state = base.read(cell / 'state.json')
        row['generated_test_runs'] = state.get('generated_test_runs', 0)
        row['procedure_applications'] = sum(bool(e.get('procedure_id')) for e in state.get('procedure_events', []))
    base.write(row_path, row)
    return row


def primary(row):
    if row.get('grade_status') == 'GRADED' and type(row.get('passed')) is bool:
        return row['passed']
    if row.get('status') == 'GENERATION_ERROR' and row.get('error_type') in MODEL_FAILURES:
        return False
    return None


def checkpoint(context, rows, phase, status, started, *, bank=None, reason=None):
    plan = context['plan']
    arms = {}
    for stage in PHASES:
        jobs = [j for j in context['frozen']['schedule'] if j['phase'] == stage]
        for arm in sorted({condition(j) for j in jobs}):
            selected = [r for r in rows if r['phase'] == stage and r['condition'] == arm]
            values = [primary(r) for r in selected]
            total = sum(condition(j) == arm for j in jobs)
            arms[stage + '/' + arm] = {'planned': total, 'recorded': len(selected),
                'submitted': sum(r['status'] == 'SUBMITTED' for r in selected),
                'graded': sum(r.get('grade_status') == 'GRADED' for r in selected),
                'passed': sum(v is True for v in values), 'failed': sum(v is False for v in values),
                'unresolved_or_unexecuted': total - sum(type(v) is bool for v in values),
                'rate': sum(v is True for v in values) / total if len(values) == total and all(type(v) is bool for v in values) else None,
                'solve_seconds': sum(r.get('wall_seconds', 0) for r in selected),
                'memory_injections': sum(r.get('memory_injection_count', 0) for r in selected),
                'procedure_applications': sum(r.get('procedure_applications', 0) for r in selected)}
    value = {'schema': SCHEMA, 'experiment_id': plan['experiment_id'], 'phase': phase,
        'status': status, 'reason': reason, 'recorded_at': datetime.now(timezone.utc).isoformat(),
        'manager_seconds': time.monotonic() - started, 'planned_cells': len(context['frozen']['schedule']),
        'recorded_cells': len(rows), 'arms': arms, 'bank': bank, 'cells': rows,
        'hidden_feedback_to_model': False, 'bank_updates_on_evaluation': False,
        'organisation_shared_skill_claim': False, 'memory_scope': 'PRIVATE_OWNER'}
    base.write(context['output'] / 'summary.json', value)
    return value


def seal_phase(context, phase, rows):
    verify(context)
    selected = [r for r in rows if r['phase'] == phase]
    expected = [j for j in context['frozen']['schedule'] if j['phase'] == phase]
    require(len(selected) == len(expected) and all('solve_reference' in r for r in selected), 'PHASE_NOT_COMPLETE')
    refs = [base.reference(context['output'] / 'frozen-inputs.json')]
    snapshots = []
    for row, job in zip(selected, expected):
        require(row['ordinal'] == job['ordinal'], 'PHASE_ORDER_CHANGED')
        _, cell = cell_paths(context['output'], job)
        solve = base.read(checked(row['solve_reference']))
        state = base.read(cell / 'state.json')
        base._cell_result(cell, context['tasks'][job['task_id']], native_arm(job), solve, state)
        refs += [base.reference(cell / p) for p in ('state.json', 'solve-receipt.json', 'attempt.json')]
        refs.append(base.reference(context['output'] / 'starts' / ('%04d.json' % job['ordinal'])))
        for number, receipt in enumerate(solve['sessions'], 1):
            folder = cell / ('session-%02d' % number)
            require(base.read(folder / 'receipt.json') == receipt and base.file_hash(folder / 'events.jsonl') == receipt['events_sha256']
                and base.file_hash(folder / 'stderr.log') == receipt['stderr_sha256'], 'SESSION_OUTPUT_CHANGED')
            prompt = base.read(folder / 'prompt-receipt.json')
            require(prompt['prompt_sha256'] == base.file_hash(folder / 'prompt.txt') and
                prompt['state_before_call_sha256'] == base.file_hash(folder / 'initial-state.json'), 'SESSION_INPUT_CHANGED')
            refs += [base.reference(folder / p) for p in ('receipt.json', 'prompt-receipt.json', 'prompt.txt',
                                                        'initial-state.json', 'events.jsonl', 'stderr.log')]
        snapshots.append({k: v for k, v in row.items() if k not in ('grade_status', 'passed', 'grade_reference', 'grader_seconds', 'grade_error_type')})
    path = context['output'] / phase / 'collection.json'
    fresh(path, {'schema': 'lcb-transfer-collection/1', 'phase': phase, 'status': 'SEALED',
                'rows': snapshots, 'references': refs, 'cells': len(selected), 'private_grader_started': False})
    return base.reference(path)


def verify_collection(reference):
    value = base.read(checked(reference))
    for ref in value['references']:
        checked(ref)
    return value


def frozen_bank(store, output, stage):
    path = output / ('bank-' + stage.lower() + '.json')
    if not path.exists():
        return memory.freeze(store, path, stage=stage)
    reference = base.reference(path)
    with memory.load_bank(reference['path'], reference['sha256']) as bank:
        require(bank.manifest['stage'] == stage and
                bank.manifest['scope_reference'] == base.reference(store / 'scope.json'), 'RESUMED_BANK_SCOPE_CHANGED')
        return {**reference, 'status': bank.manifest['status'], 'layer_counts': bank.manifest['layer_counts']}


def grade_phase(context, phase, rows, collection_ref, started, bank):
    stage_root = context['output'] / phase
    manifest = base.final_manifest(context['config'], context['split'], context['public_manifest'],
                                   context['dataset_root'], stage_root)
    require(manifest is not None, 'PRIVATE_GRADING_NOT_READY')
    verify_collection(collection_ref)
    for i, row in enumerate(rows):
        if row['phase'] != phase or row['status'] != 'SUBMITTED':
            continue
        verify(context)
        checked(collection_ref)
        job = context['frozen']['schedule'][row['ordinal'] - 1]
        folder, cell = cell_paths(context['output'], job)
        receipt_path = cell / 'grade-start.json'
        authority = {'collection_reference': collection_ref, 'solve_reference': row['solve_reference']}
        grade_dir = folder / 'private-grades' / cell.name
        if receipt_path.exists():
            old = base.read(receipt_path)
            require(all(old.get(k) == v for k, v in authority.items()), 'GRADE_START_CHANGED')
            if row.get('grade_status') == 'PENDING' and not (grade_dir / 'report.json').exists():
                rows[i] = {**row, 'grade_status': 'INFRA_ERROR', 'passed': None, 'grade_error_type': 'InterruptedGradeNoRetry'}
                base.write(cell / 'cell-receipt.json', rows[i])
                continue
        else:
            require(not grade_dir.exists(), 'UNBOUND_PRIOR_GRADE')
            fresh(receipt_path, {**authority, 'started_at': datetime.now(timezone.utc).isoformat()})
        rows[i] = base.grade_cell(folder, row['task_id'], row['arm'], row, manifest,
                                  context['dataset_root'], context['runtime'], context['config'])
        checkpoint(context, rows, phase, 'GRADING', started, bank=bank)
    verify_collection(collection_ref)


def run(plan_path, runtime_path, dataset_root, output, *, prepare_only=False):
    output = Path(output).resolve()
    started = time.monotonic()
    with base.exclusive_lock(output):
        context = load(plan_path, runtime_path, dataset_root, output)
        if prepare_only:
            return {'status': 'PREPARED', 'planned_cells': len(context['frozen']['schedule']), 'model_calls': 0}
        scope = context['plan']['cohorts']
        store = output / 'personal-memory'
        enrolled_ids = [identity for name in ('discovery', 'verification', 'validation', 'test')
                        for identity in scope[name]['task_ids']]
        memory.initialize(store, org_id=context['config']['org_id'], owner_user_id=context['config']['owner_user_id'],
            tasks=[context['tasks'][identity] for identity in enrolled_ids], discovery_ids=scope['discovery']['task_ids'],
            verification_ids=scope['verification']['task_ids'], validation_ids=scope['validation']['task_ids'],
            test_ids=scope['test']['task_ids'], source_references=[base.reference(output / 'frozen-inputs.json')])
        rows, bank, candidates = [], None, []
        for phase in PHASES:
            jobs = [job for job in context['frozen']['schedule'] if job['phase'] == phase]
            checkpoint(context, rows, phase, 'COLLECTING', started, bank=bank)
            for offset in range(0, len(jobs), 2):
                batch = jobs[offset:offset + 2]
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = []
                    for index, job in enumerate(batch, offset):
                        selected = candidates[index % len(candidates)] if phase == 'VERIFICATION' else None
                        active_bank = bank if native_arm(job) == 'ON' else None
                        futures.append(pool.submit(collect, context, job, active_bank, selected))
                    rows.extend(future.result() for future in futures)
                checkpoint(context, rows, phase, 'COLLECTING', started, bank=bank)
                if any(row['status'] == 'HELD' for row in rows):
                    return checkpoint(context, rows, phase, 'HELD', started, bank=bank, reason='NO_AUTOMATIC_PARTIAL_MODEL_RETRY')
            collection_ref = seal_phase(context, phase, rows)
            if phase in ('DISCOVERY', 'VERIFICATION'):
                for job in jobs:
                    _, cell = cell_paths(output, job)
                    memory.ingest_cell(store, phase=phase, state_path=cell / 'state.json',
                        solve_reference=base.reference(cell / 'solve-receipt.json'))
                stage = 'PROVISIONAL' if phase == 'DISCOVERY' else 'FINAL'
                bank = frozen_bank(store, output, stage)
                with memory.load_bank(bank['path'], bank['sha256']) as loaded:
                    candidates = sorted(loaded.candidate_ids())
                base.write(output / ('bank-' + stage.lower() + '-receipt.json'), bank)
                if phase == 'DISCOVERY' and not candidates:
                    grade_phase(context, phase, rows, collection_ref, started, bank)
                    verify(context)
                    return checkpoint(context, rows, phase, 'NOT_READY', started, bank=bank, reason='NO_PROVISIONAL_PROCEDURES')
                if phase == 'VERIFICATION' and bank['status'] == 'NOT_READY':
                    grade_phase(context, 'DISCOVERY', rows, base.reference(output / 'DISCOVERY/collection.json'), started, bank)
                    grade_phase(context, phase, rows, collection_ref, started, bank)
                    verify(context)
                    return checkpoint(context, rows, phase, 'NOT_READY', started, bank=bank, reason='NO_PROMOTED_PRIVATE_L3')
            else:
                grade_phase(context, phase, rows, collection_ref, started, bank)
            verify(context)
        # Training correctness is descriptive and never used to select or promote memory.
        for phase in ('DISCOVERY', 'VERIFICATION'):
            grade_phase(context, phase, rows, base.reference(output / phase / 'collection.json'), started, bank)
        verify(context)
        return checkpoint(context, rows, 'COMPLETE', 'COMPLETE', started, bank=bank)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'run'))
    parser.add_argument('--plan', type=Path, default=ROOT / 'configs/skhynix_v1/lcb_004_transfer_plan.json')
    parser.add_argument('--runtime', type=Path, default=ROOT / 'data/skhynix_lcb_002/runtime.local.json')
    parser.add_argument('--dataset-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/skhynix_lcb_004/run-001')
    args = parser.parse_args()
    try:
        result = run(args.plan, args.runtime, args.dataset_root, args.output, prepare_only=args.mode == 'prepare')
        print(json.dumps({key: result[key] for key in ('status', 'phase', 'planned_cells', 'recorded_cells', 'reason') if key in result}))
    except Exception as exc:
        print(json.dumps({'status': 'ERROR', 'error_type': type(exc).__name__,
                          'error_code': str(exc) if isinstance(exc, TransferError) else 'TRANSFER_RUN_FAILED'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
