"""Retain authenticated native service quota stops as unscored evaluation cells.

This orchestration amendment preserves the frozen solver and enrolled schedule.
It never retries a native attempt or grader, edits an original audit, or converts
an infrastructure stop into an official solver failure.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import math
import sys
import time

import trimem_skhynix_architecture_pipeline as core
from enterprise_memory.trimem.grader import GraderInvocationFailure

SCHEMA = 'skhynix/evaluation-quota-continuation-pipeline/1.0'
AMENDMENT_SCHEMA = 'skhynix/evaluation-native-quota-amendment/1.0'
POLICY = 'RETAIN_NATIVE_SERVICE_USAGE_LIMIT_UNSCORED_AND_CONTINUE_FIXED_SCHEDULE'
HOLD_SCHEMA = 'skhynix/evaluation-native-quota-undetermined/1.0'
CLASSIFICATION = 'NATIVE_SERVICE_USAGE_LIMIT'


class NativeQuotaPaused(core.PipelineError):
    """A newly encountered quota stop is retained before pausing the controller."""


def fail(message):
    raise core.PipelineError(message)


def load_bound(reference):
    path = core.check(reference, decode=False)
    name = 'skhynix_bound_quota_predecessor_' + reference['sha256']
    if name in sys.modules:
        module = sys.modules[name]
        if core.ref(module.__file__) != reference:
            fail('Bound predecessor controller source changed')
        return module
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def quota_hold_path(root, runner, row):
    identity = core.digest(core.canonical_bytes([
        runner.manifest['experiment_reference'], row['task_id'], row['arm']]))
    return Path(root) / 'native-quota-unscored' / (identity + '.json')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _service_quota_lines(raw):
    """Classify only the two terminal top-level service events, never item text."""
    lines = raw.splitlines()
    events = [json.loads(line) for line in lines]
    terminal = [(i, event) for i, event in enumerate(events)
                if event.get('type') in ('error', 'turn.failed')]
    if ([event.get('type') for _, event in terminal] != ['error', 'turn.failed']
            or [i for i, _ in terminal] != [len(events)-2, len(events)-1]
            or any(event.get('type') == 'turn.completed' for event in events)):
        fail('Native failure is not an exact terminal service quota event pair')
    first, last = terminal[0][1], terminal[1][1]
    if (set(first) != {'type', 'message'} or set(last) != {'type', 'error'}
            or not isinstance(last['error'], dict)
            or set(last['error']) not in ({'message'}, {'type', 'message'})
            or last['error'].get('type', 'usage_limit_reached') != 'usage_limit_reached'):
        fail('Native terminal quota service event fields differ')
    message = first['message']
    prefix = "You've hit your usage limit."
    advice = ' Visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at '
    if (not isinstance(message, str) or last['error'].get('message') != message
            or not (message == prefix or message.startswith(prefix + advice))):
        fail('Native service error is not the supported usage-limit classification')
    return events, [{'line': i+1, 'type': event['type'], 'sha256': core.digest(lines[i])}
                    for i, event in terminal]


def retain_quota_hold(root, runner, row, *, amendment_reference, create=False):
    """Authenticate an immutable failed native attempt without reexecuting it."""
    proof_path = quota_hold_path(root, runner, row)
    existing = core.read(proof_path) if proof_path.exists() else None
    path = Path(row['cell_config'])
    folder = path.parent
    if existing is None and (not create or not (folder/'native-execution-failure.json').is_file()):
        return None
    events = runner._cell_events(row)
    stages = {event['stage'] for event in events}
    if (runner.manifest.get('phase') != 'EVALUATION'
            or row['arm'] not in ('BASELINE', 'PDF_MEMORY')
            or not {'PREPARED', 'SOLVE_STARTED', 'INFRA_ERROR'} <= stages
            or stages & {'SOLVE_COMPLETE', 'GRADE_STARTED', 'GRADED', 'GRADE_UNDETERMINED',
                         'CELL_COMPLETE', 'LEARN_STARTED', 'LEARNED', 'CLEANED'}):
        fail('Native quota hold requires an ungraded, terminal evaluation attempt')
    failures = [event for event in events if event['stage'] == 'INFRA_ERROR']
    failed_event = failures[-1]
    if (failed_event['details'].get('error_type') != 'RuntimeError'
            or failed_event['details'].get('automatic_retry') is not False):
        fail('Native quota hold requires its original terminal infrastructure error')
    if any((folder/name).exists() for name in
           ('public-result.json', 'grader-private.json', 'grader-pending.json', 'training-grade-undetermined.json')):
        fail('Native quota hold conflicts with a started or recorded grade')
    cell = runner._validate_cell(row)
    if not isinstance(cell, dict):
        cell = core.read(path)
    config = runner._row_config(row)
    broker_root = Path(cell['broker_root'])
    if (broker_root/'pending.json').exists():
        fail('Native quota hold cannot recover unfinished broker work')
    if (cell.get('phase') != 'EVALUATION' or cell.get('arm') != row['arm']
            or cell.get('task_public', {}).get('task_id') != row['task_id']
            or path != Path(config['run_root'])/'cells/EVALUATION'/row['task_id']/row['arm']/'cell.json'
            or broker_root != folder/'broker'):
        fail('Native quota hold differs from its original enrolled cell')
    references = {'cell': core.ref(path), 'audit': core.ref(folder/'execution-audit.json'),
        'native_failure': core.ref(folder/'native-execution-failure.json'),
        'submission': core.ref(broker_root/'submission.json'), 'patch': core.ref(broker_root/'submission.diff'),
        'failed_event': core.ref(runner.root/'events'/f"{failed_event['sequence']:08d}.json")}
    for key, name in (('broker_manifest', 'manifest.json'), ('broker_manifest_checksum', 'manifest.sha256'),
                      ('broker_initial_state', 'initial-state.json'), ('broker_state', 'state.json'),
                      ('broker_events', 'events.jsonl')):
        references[key] = core.ref(broker_root/name)
    audit = core.check(references['audit'])
    failure = core.check(references['native_failure'])
    submission = core.check(references['submission'])
    status = runner._broker_status(path)
    state = core.check(references['broker_state'])
    configuration_sha = core.digest(core.canonical_bytes(config))
    number = status['workers_issued']
    if (status['status'] != 'SUBMITTED' or status['unfinished_actions'] != 0
            or type(number) is not int or number < 1 or status['workers_admitted'] != number
            or state.get('status') != 'SUBMITTED' or state.get('submission') != submission
            or status['submission'] != submission or len(state.get('workers', {})) != number
            or submission.get('task_id') != row['task_id'] or submission.get('arm') != row['arm']
            or submission.get('configuration_sha256') != configuration_sha
            or submission.get('bank_sha256') != cell['bank_sha256']
            or submission.get('reason') != 'NATIVE_WORKER_INFRASTRUCTURE_FAILURE'
            or submission.get('agent_completed') is not False
            or submission.get('actions') != state.get('actions')
            or submission.get('patch_sha256') != references['patch']['sha256']
            or submission.get('patch_utf8_bytes') != Path(references['patch']['path']).stat().st_size
            or not _finite(submission.get('submitted_at'))
            or audit.get('schema') != 'skhynix/architecture-execution-audit/1.0'
            or audit.get('passed') is not False or audit.get('task_id') != row['task_id']
            or audit.get('arm') != row['arm'] or audit.get('configuration_sha256') != configuration_sha
            or audit.get('patch_sha256') != references['patch']['sha256']
            or audit.get('event_tail_sha256') != status['event_tail_sha256']
            or type(failure.get('launcher_returncode')) is not int or failure['launcher_returncode'] != 1
            or failure.get('worker_id') != row['arm'].lower()+'-'+cell['target']['instance_id']+'-'+str(number)):
        fail('Native quota hold does not bind its sealed broker, patch and failed audit')
    expected_errors = [
        {'reason': 'Trusted launcher failure persisted', 'failure_sha256': references['native_failure']['sha256']},
        {'worker_number': number, 'reason': 'RuntimeError: Native process failed; sealed patch retained for explicit review'}]
    if audit.get('errors') != expected_errors:
        fail('Native quota hold cannot hide any additional audit failure')
    native_root = Path(config['native_control_root'])/'EVALUATION'/cell['target']['instance_id']/row['arm']
    native_workers, prior_workers, threads = [], [], set()
    service_lines = None
    for index in range(1, number+1):
        worker_folder = native_root/f'worker-{index:03d}'
        output = worker_folder/'output'
        local = {}
        for key, name in (('config', 'config.json'), ('packet', 'packet.json'), ('prompt', 'prompt.txt'),
                          ('admission', 'admission.json'), ('launch', 'output/launch.json'),
                          ('completion', 'output/completion.json'), ('events', 'output/events.jsonl')):
            local[key] = core.ref(worker_folder/name)
            references[f'worker_{index:03d}_{key}'] = local[key]
        completion, launch = core.check(local['completion']), core.check(local['launch'])
        native_config, admission = core.check(local['config']), core.check(local['admission'])
        worker_id = row['arm'].lower()+'-'+cell['target']['instance_id']+'-'+str(index)
        issued = state['workers'].get(worker_id, {})
        thread = completion.get('thread_id')
        if (not isinstance(thread, str) or not thread or thread in threads
                or issued.get('thread_id') != thread
                or issued.get('launch_receipt') != {'thread_id': thread, 'fork_turns': 'none',
                    'fresh_session': True, 'requested_model': config['model'],
                    'launch_evidence_sha256': core.digest(core.canonical_bytes(launch))}
                or native_config.get('worker_id') != worker_id or native_config.get('linux_cell_config') != str(path)
                or native_config.get('model') != config['model']
                or native_config.get('reasoning_effort') != config['reasoning_effort']
                or native_config.get('authentication') != 'CHATGPT'
                or native_config.get('packet_sha256') != issued.get('packet_sha256')
                or native_config.get('prompt_sha256') != local['prompt']['sha256']
                or launch.get('worker_id') != worker_id or launch.get('requested_model') != config['model']
                or launch.get('reasoning_effort') != config['reasoning_effort']
                or launch.get('authentication') != 'CHATGPT_FORCED' or launch.get('fresh_session') is not True
                or launch.get('resume_or_fork_used') is not False or launch.get('separate_model_api_client_calls') != 0
                or launch.get('packet_sha256') != issued.get('packet_sha256')
                or launch.get('prompt_sha256') != local['prompt']['sha256']
                or admission.get('admitted') is not True or admission.get('worker_id') != worker_id
                or admission.get('thread_id') != thread or admission.get('packet_sha256') != issued.get('packet_sha256')
                or not isinstance(admission.get('token'), str)
                or core.digest(admission['token'].encode()) != issued.get('admission_token_sha256')
                or completion.get('admitted') is not True or completion.get('timed_out') is not False
                or type(completion.get('exit_code')) is not int or completion['exit_code'] != (1 if index == number else 0)
                or any(completion.get(key) != [] for key in ('errors', 'transport_errors', 'outside_broker_tool_events'))
                or completion.get('events_sha256') != local['events']['sha256']
                or not _finite(completion.get('ended_at')) or completion['ended_at'] > submission['submitted_at']
                or list(output.glob('manager-error-*.json'))):
            fail('Native quota worker lineage or completion is not authentic')
        threads.add(thread)
        packet = core.check(local['packet'])
        packet_ref = core.ref(broker_root/'packets'/issued['packet_file'])
        references[f'worker_{index:03d}_broker_packet'] = packet_ref
        if packet != core.check(packet_ref) or packet.get('sha256') != issued['packet_sha256']:
            fail('Native quota worker packet differs from its original broker handoff')
        raw = Path(local['events']['path']).read_bytes()
        if index == number:
            native_events, service_lines = _service_quota_lines(raw)
            if failure.get('completion_sha256') != local['completion']['sha256']:
                fail('Native quota failure references a different completion')
        else:
            native_events = [json.loads(line) for line in raw.splitlines()]
            if any(event.get('type') in ('error', 'turn.failed') for event in native_events):
                fail('Earlier native worker has a service failure')
        if [event.get('thread_id') for event in native_events if event.get('type') == 'thread.started'] != [thread]:
            fail('Native quota stream belongs to a different thread')
        worker = {'number': index, 'thread_id': thread, 'completion_sha256': local['completion']['sha256'],
            'events_sha256': local['events']['sha256'], 'outcome': CLASSIFICATION if index == number else 'COMPLETE'}
        native_workers.append({**worker, 'completion_reference': local['completion'], 'events_reference': local['events']})
        if index != number:
            prior_workers.append(worker)
    if audit.get('workers') != prior_workers:
        fail('Native quota audit does not preserve all successful preceding workers')
    # Re-run only the frozen pure audit; it must retain the SAME original failed
    # audit. No missing audit can be generated because its reference was required.
    try:
        runner.operations.execution_audit(path)
    except RuntimeError as exc:
        if str(exc) != 'Native execution audit failed; no solve-rate result may be emitted':
            raise
    else:
        fail('Native quota audit unexpectedly passed')
    value = {'schema': HOLD_SCHEMA, 'policy': POLICY, 'amendment_reference': amendment_reference,
        'experiment_reference': runner._row_experiment_reference(row),
        'cohort_reference': core.ref(runner.root/'cohort.json'), 'task_id': row['task_id'], 'arm': row['arm'],
        'phase': 'EVALUATION', 'official': False, 'resolved': None, 'grader_status': 'not_invoked',
        'native_status': 'usage_limit', 'classification': CLASSIFICATION,
        'reason': 'Terminal native service usage limit; original failed attempt retained without retry',
        'references': references, 'service_error_lines': service_lines, 'native_workers': native_workers,
        'broker_event_tail_sha256': status['event_tail_sha256'], 'memory_injections': status['memory_injections'],
        'resources_retained': True, 'model_calls': 0, 'official_grader_runs': 0,
        'native_retries': False, 'official_grader_retries': False, 'training_memory_writes': 0}
    if existing is not None and existing != value:
        fail('Retained native quota evidence changed')
    for reference in references.values():
        core.check(reference, decode=False)
    return value, core.retain(proof_path, value)


def quota_held_task_ids(root, amendment_reference):
    tasks = set()
    for path in sorted((Path(root)/'native-quota-unscored').glob('*.json')):
        proof = core.read(path)
        identity = core.digest(core.canonical_bytes([proof['experiment_reference'], proof['task_id'], proof['arm']]))
        if (proof.get('schema') != HOLD_SCHEMA or proof.get('policy') != POLICY
                or proof.get('amendment_reference') != amendment_reference or proof.get('phase') != 'EVALUATION'
                or proof.get('classification') != CLASSIFICATION or proof.get('official') is not False
                or proof.get('resolved') is not None or path.name != identity+'.json'):
            fail('Invalid retained cross-arm native quota hold')
        for reference in proof['references'].values():
            core.check(reference, decode=False)
        tasks.add(proof['task_id'])
    return tasks


def _grader_hold(grader_module, grader_roots, runner, row, amendment_reference, *, create=False):
    found = None
    for root in grader_roots:
        proof = grader_module.retain_hold(root, runner, row, amendment_reference=amendment_reference)
        if proof:
            if found is not None:
                fail('Duplicate retained grader hold roots')
            found = proof
    if found is None and create:
        found = grader_module.retain_hold(grader_roots[-1], runner, row,
                                         amendment_reference=amendment_reference, create=True)
    return found


def advance_one(runner, *, root, amendment_reference, grader_module, grader_amendment_reference, grader_roots):
    held_tasks = quota_held_task_ids(root, amendment_reference)
    for hold_root in grader_roots:
        held_tasks.update(grader_module.held_task_ids(hold_root, grader_amendment_reference))
    with core.locked(runner.root/'run.lock'), runner._journal_snapshot():
        runner.operations.load_experiment(runner.manifest['experiment_reference']['path'])
        runner._check_execution_api()
        core.check(runner.manifest['experiment_reference'])
        runner._check_controller_source()
        if runner.manifest['bank_reference'] is not None:
            core.check(runner.manifest['bank_reference'])
        for row in runner.schedule:
            quota = retain_quota_hold(root, runner, row, amendment_reference=amendment_reference)
            grade = _grader_hold(grader_module, grader_roots, runner, row, grader_amendment_reference)
            if quota or grade:
                held_tasks.add(row['task_id'])
        for row in runner.schedule:
            stages = {event['stage'] for event in runner._cell_events(row)}
            if 'CELL_COMPLETE' in stages:
                if row['task_id'] not in held_tasks:
                    runner._cleanup(row)
                runner._validate_result(row)
                continue
            if quota_hold_path(root, runner, row).exists() or any(
                    grader_module.hold_path(hold_root, runner, row).exists() for hold_root in grader_roots):
                continue
            proof = retain_quota_hold(root, runner, row, amendment_reference=amendment_reference, create=True)
            classification = CLASSIFICATION
            if proof is None and 'GRADE_STARTED' in stages:
                proof = _grader_hold(grader_module, grader_roots, runner, row, grader_amendment_reference, create=True)
                classification = 'GRADER_UNDETERMINED'
            if proof:
                return {'kind': 'HELD', 'classification': classification, 'task_id': row['task_id'],
                        'arm': row['arm'], 'reference': proof[1]}
            storage = Path(runner.config['run_root'])
            while not storage.exists():
                storage = storage.parent
            free = runner.disk_free(storage)
            if free < runner.manifest['min_free_bytes']:
                runner._record('DISK_BLOCK', row, {'free_bytes': free, 'minimum_bytes': runner.manifest['min_free_bytes'], 'operation_started': False})
                fail('Insufficient storage; no solve or grade started')
            try:
                runner._advance(row)
            except Exception as exc:
                runner._record('INFRA_ERROR', row, {'error_type': type(exc).__name__, 'error': str(exc)[:2000],
                    'automatic_retry': False, 'result_is_not_a_solver_failure': True})
                if isinstance(exc, GraderInvocationFailure):
                    proof = _grader_hold(grader_module, grader_roots, runner, row, grader_amendment_reference, create=True)
                    classification = 'GRADER_UNDETERMINED'
                else:
                    proof = retain_quota_hold(root, runner, row, amendment_reference=amendment_reference, create=True)
                    classification = CLASSIFICATION
                if proof:
                    if classification == CLASSIFICATION:
                        raise NativeQuotaPaused('New native service quota stop retained unscored; '
                                                'controller paused before the next enrolled task') from exc
                    return {'kind': 'HELD', 'classification': classification, 'task_id': row['task_id'],
                            'arm': row['arm'], 'reference': proof[1]}
                raise
            if row['task_id'] not in held_tasks:
                try:
                    runner._cleanup(row)
                except Exception as exc:
                    runner._record('INFRA_ERROR', row, {'operation': 'CLEANUP', 'error_type': type(exc).__name__,
                        'error': str(exc)[:2000], 'solver_retry': False})
                    raise
            return {'kind': 'OFFICIAL', 'task_id': row['task_id'], 'arm': row['arm']}
    return {'kind': 'EXHAUSTED'}


class EvaluationQuotaContinuation(core.Pipeline):
    def __init__(self, path):
        self.path, self.clock = core.absolute(path), time.time
        self.reference, self.config = core.ref(self.path), core.read(self.path)
        if core.digest(core.canonical_bytes(self.config)) != self.path.with_suffix('.sha256').read_text().strip():
            fail('Native quota continuation configuration checksum differs')
        if self.config.get('schema') != SCHEMA or core.ref(Path(__file__).resolve()) != self.config['pipeline_source_reference']:
            fail('Native quota controller source is not the frozen revision')
        self.v16_config = core.check(self.config['supersedes_configuration_reference'])
        allowed = {'schema', 'pipeline_root', 'progress_root', 'evaluation_native_root', 'pipeline_source_reference',
                   'supersedes_configuration_reference', 'revision_reason', 'native_quota_continuation_reference'}
        if ({k: v for k, v in self.config.items() if k not in allowed} !=
                {k: v for k, v in self.v16_config.items() if k not in allowed}):
            fail('Native quota continuation cannot change solver, bank, grader policy or task protocol')
        for key in ('pipeline_root', 'progress_root', 'evaluation_native_root'):
            a, b = core.absolute(self.config[key]), core.absolute(self.v16_config[key])
            if a == b or a in b.parents or b in a.parents:
                fail('Native quota continuation requires distinct orchestration and native roots')
        self.quota_amendment = core.check(self.config['native_quota_continuation_reference'])
        receipt = self.quota_amendment
        if (receipt.get('schema') != AMENDMENT_SCHEMA or receipt.get('policy') != POLICY
                or receipt.get('previous_configuration_reference') != self.config['supersedes_configuration_reference']
                or receipt.get('applies_to') != ['BASELINE', 'PDF_MEMORY']
                or receipt.get('pause_on_new_native_quota') is not True
                or any(receipt.get(key) is not False for key in
                       ('native_outcome_retries', 'official_grading_retries', 'undetermined_as_failure', 'training_memory_updates'))):
            fail('Native quota amendment must be explicit, symmetric, unscored and without retries')
        self.grader_module = load_bound(self.v16_config['pipeline_source_reference'])
        self.v16 = self.grader_module.EvaluationContinuation(self.config['supersedes_configuration_reference']['path'])
        # These aliases are the exact v16 runtime dependencies expected by its
        # unchanged runner, bank validation and run orchestration methods.
        self.previous, self.previous_module, self.prior = self.v16.previous, self.v16.previous_module, self.v16.prior
        self.operations, self.scale, self.amendment = self.v16.operations, self.v16.scale, self.v16.amendment
        self.root = Path(self.config['pipeline_root'])
        self.root.mkdir(parents=True, exist_ok=True)
        core.retain(self.root/'pipeline-binding.json', {'schema': SCHEMA, 'configuration_reference': self.reference})
        (self.root/'events').mkdir(exist_ok=True)
        self.grader_roots = [Path(self.v16_config['pipeline_root']), self.root]
        self.validate_predecessor()

    def validate_predecessor(self):
        self.v16.validate_predecessor()
        receipt = self.quota_amendment
        tail = receipt['previous_pipeline_event_tail_reference']
        self.scale._event_reference(tail, self.v16_config['pipeline_root'], tail=True)
        if core.check(tail)['stage'] != 'PIPELINE_BLOCKED':
            fail('Native quota predecessor must remain the blocked v16 controller')
        if receipt['baseline_cohort_reference'] != self.amendment['baseline_cohort_reference']:
            fail('Native quota continuation changed the original baseline cohort')
        manifest = core.check(receipt['baseline_cohort_reference'])
        root = Path(receipt['baseline_cohort_reference']['path']).parent
        events = self.operations.modules['cohort']._event_chain(root)
        initial = core.check(receipt['baseline_event_tail_reference'])
        if (events[initial['sequence']-1] != initial or initial['stage'] != 'INFRA_ERROR'
                or initial['task_id'] != receipt['initial_held_task_id'] or initial['arm'] != receipt['initial_held_arm']
                or receipt['initial_held_arm'] != 'BASELINE' or manifest['arms'] != ['BASELINE']
                or manifest['experiment_reference'] != self.amendment['baseline_experiment_reference']
                or len(manifest['schedule']) != 60):
            fail('Native quota continuation changed the retained baseline prefix')
        for reference in receipt['initial_held_evidence_references'].values():
            core.check(reference, decode=False)

    def progress(self):
        return self.v16.progress.__func__(self)

    def status(self):
        value = self.v16.status.__func__(self)
        return {**value, 'schema': SCHEMA, 'native_quota_continuation_reference': self.config['native_quota_continuation_reference'],
                'pause_on_new_native_quota': True}

    def runner(self, purpose, stage, bank_reference, name):
        return self.v16.runner.__func__(self, purpose, stage, bank_reference, name)

    def evaluation(self, purpose, stage, bank_reference, name):
        runner, experiment = self.runner(purpose, stage, bank_reference, name)
        while True:
            self.record('COHORT_ADVANCE_STARTED', {'cohort_root': str(runner.root), 'planned_cells': len(runner.schedule)}, job=name)
            change = advance_one(runner, root=self.root,
                amendment_reference=self.config['native_quota_continuation_reference'], grader_module=self.grader_module,
                grader_amendment_reference=self.config['evaluation_continuation_reference'], grader_roots=self.grader_roots)
            self.record('COHORT_PROGRESS', {'cohort_root': str(runner.root), 'change': change}, job=name)
            self.progress()
            if change['kind'] == 'EXHAUSTED':
                break
        rows = []
        with core.locked(runner.root/'run.lock'), runner._journal_snapshot():
            runner.full_audit()
            for row in runner.schedule:
                held = retain_quota_hold(self.root, runner, row, amendment_reference=self.config['native_quota_continuation_reference'])
                classification = CLASSIFICATION
                if held is None:
                    held = _grader_hold(self.grader_module, self.grader_roots, runner, row, self.config['evaluation_continuation_reference'])
                    classification = 'GRADER_UNDETERMINED'
                if held:
                    value, reference = held
                    rows.append({'task_id': row['task_id'], 'arm': row['arm'], 'official': False, 'resolved': None,
                        'classification': classification, 'reference': reference, 'memory_injections': value['memory_injections']})
                else:
                    value, reference = runner._validate_result(row, full_audit=True)
                    rows.append({'task_id': row['task_id'], 'arm': row['arm'], 'official': True, 'resolved': value['resolved'],
                        'reference': reference, 'memory_injections': value['broker_status']['memory_injections']})
        by_arm = {}
        for arm in runner.manifest['arms']:
            arm_rows = [row for row in rows if row['arm'] == arm]
            counts = self.grader_module.result_counts(arm_rows, sum(row['arm'] == arm for row in runner.schedule))
            counts['native_service_usage_limit'] = sum(row.get('classification') == CLASSIFICATION for row in arm_rows)
            counts['grader_undetermined'] = sum(row.get('classification') == 'GRADER_UNDETERMINED' for row in arm_rows)
            by_arm[arm] = counts
        report = {'scope': 'FINAL' if purpose == 'FINAL_EVALUATION' else 'DEVELOPMENT', 'rows': rows,
            'planned': len(rows), 'by_arm': by_arm, 'experiment_reference': experiment, 'bank_reference': bank_reference,
            'status': 'COMPLETE_WITH_UNDETERMINED' if any(count['undetermined'] for count in by_arm.values()) else 'COMPLETE',
            'evaluation_continuation_reference': self.config['evaluation_continuation_reference'],
            'native_quota_continuation_reference': self.config['native_quota_continuation_reference'],
            'full_enrollment_retained': True, 'official_grader_retries': False, 'native_outcome_retries': False}
        if len(by_arm) == 2:
            report['paired_comparison'] = self.grader_module.paired_counts(
                [row for row in rows if row['arm'] == 'BASELINE'], [row for row in rows if row['arm'] == 'PDF_MEMORY'])
        reference = core.retain(self.root/'reports'/(name+'.json'), report)
        if not self.latest('EVALUATION_COMPLETE', name):
            self.record('EVALUATION_COMPLETE', {'report_reference': reference, 'status': report['status']}, job=name)
        return report, reference

    def run(self):
        with core.locked(Path(self.v16_config['pipeline_root'])/'run.lock'):
            return self.v16.run.__func__(self)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run', 'status', 'validate'))
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    controller = EvaluationQuotaContinuation(args.config)
    print(json.dumps(controller.run() if args.command == 'run' else controller.status()))
