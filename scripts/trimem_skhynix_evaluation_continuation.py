"""Explicit evaluation accounting amendment over the unchanged frozen solver.

Known terminal grader ambiguities remain unscored. The enrolled schedule and
original cohort journals are retained; no grade, completion or cleanup event is
invented for an unscored cell. Native execution and grading are never retried.
"""
from contextlib import ExitStack
from pathlib import Path
import argparse
import importlib.util
import json
import math
import sys
import time

import trimem_skhynix_architecture_pipeline as core
from enterprise_memory.trimem.grader import GraderInvocationFailure

SCHEMA = 'skhynix/evaluation-continuation-pipeline/1.0'
AMENDMENT_SCHEMA = 'skhynix/evaluation-accounting-amendment/1.0'
POLICY = 'RETAIN_TERMINAL_AMBIGUITY_UNSCORED_AND_CONTINUE_FIXED_SCHEDULE'
HOLD_SCHEMA = 'skhynix/evaluation-grade-undetermined/1.0'


def fail(message):
    raise core.PipelineError(message)


def load_bound(reference):
    path = core.check(reference, decode=False)
    name = 'skhynix_bound_evaluation_controller_' + reference['sha256']
    if name in sys.modules:
        module = sys.modules[name]
        if core.ref(module.__file__) != reference:
            fail('Bound orchestration source changed')
        return module
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def result_counts(rows, planned):
    if type(planned) is not int or planned < 1 or len(rows) != planned or len({r['task_id'] for r in rows}) != planned:
        fail('Result rows must preserve each enrolled task exactly once per arm')
    official = [r for r in rows if r['official'] is True and type(r['resolved']) is bool]
    held = [r for r in rows if r['official'] is False and r['resolved'] is None]
    if len(official) + len(held) != planned:
        fail('Unknown grade is not an official failure or success')
    resolved = sum(r['resolved'] for r in official)
    return {'planned':planned, 'attempted':planned, 'official_complete':len(official),
        'resolved':resolved, 'unresolved':len(official)-resolved, 'undetermined':len(held),
        'official_completed_solve_rate':resolved/len(official) if official else None,
        'full_enrollment_solve_rate':resolved/planned if not held else None,
        'full_enrollment_solve_rate_bounds':[resolved/planned,(resolved+len(held))/planned]}


def paired_counts(baseline, memory):
    off = {r['task_id']:r for r in baseline}
    on = {r['task_id']:r for r in memory}
    if len(off) != len(baseline) or len(on) != len(memory) or set(off) != set(on) or not off:
        fail('Paired comparison requires identical, nonduplicated task enrollment')
    a, b = result_counts(baseline,len(off)), result_counts(memory,len(on))
    ids = sorted(k for k in off if off[k]['official'] and on[k]['official'])
    wins_off = sum(off[k]['resolved'] for k in ids)
    wins_on = sum(on[k]['resolved'] for k in ids)
    delta = 100*(wins_on-wins_off)/len(ids) if ids else None
    return {'planned_pairs':len(off), 'completed_pairs':len(ids), 'missing_pairs':len(off)-len(ids),
        'baseline_resolved_on_complete_pairs':wins_off, 'memory_resolved_on_complete_pairs':wins_on,
        'completed_pair_delta_percentage_points':delta,
        'full_enrollment_delta_percentage_points':delta if len(ids)==len(off) else None,
        'full_enrollment_delta_percentage_point_bounds':[
            100*(b['resolved']-a['resolved']-a['undetermined'])/len(off),
            100*(b['resolved']+b['undetermined']-a['resolved'])/len(off)]}


def hold_path(root, runner, row):
    identity = core.digest(core.canonical_bytes([runner.manifest['experiment_reference'],row['task_id'],row['arm']]))
    return Path(root)/'unscored'/f'{identity}.json'


def retain_hold(root, runner, row, *, amendment_reference, create=False):
    """Authenticate only an already terminal, known ambiguous official attempt."""
    proof_path = hold_path(root,runner,row)
    existing = core.read(proof_path) if proof_path.exists() else None
    path = Path(row['cell_config'])
    if existing is None and not create:
        return None
    events = runner._cell_events(row)
    stages = {e['stage'] for e in events}
    if (runner.manifest['phase'] != 'EVALUATION' or
            not {'SOLVE_COMPLETE','GRADE_STARTED','INFRA_ERROR'} <= stages or
            stages & {'GRADED','GRADE_UNDETERMINED','CELL_COMPLETE','LEARNED','CLEANED'}):
        fail('Held evaluation must be a submitted, grading-blocked, unscored attempt')
    errors = [e for e in events if e['stage']=='INFRA_ERROR']
    if (not errors or errors[-1]['details'].get('error_type') != 'GraderInvocationFailure' or
            errors[-1]['details'].get('automatic_retry') is not False):
        fail('Only a terminal official grading ambiguity can be held')
    if any((path.parent/name).exists() for name in ('public-result.json','grader-private.json','native-execution-failure.json')):
        fail('Held evaluation conflicts with a grade or native execution failure')
    cell = runner._validate_cell(row)
    # _validate_cell returns its validated cell mapping in the frozen API.
    if not isinstance(cell,dict):
        cell = core.read(path)
    task, arm = row['task_id'],row['arm']
    model = 'trimem-v1-'+arm
    run_id = core.digest((task+':'+model).encode())[:20]
    aggregate_path = Path(cell['prepared_output_root'])/'official-grader'/task/'report'/(model+'.'+run_id+'.json')
    if not aggregate_path.is_file() or not (path.parent/'grader-pending.json').is_file():
        if existing is not None:
            fail('Retained ambiguity lost its terminal aggregate')
        return None
    aggregate_ref = core.ref(aggregate_path)
    # This frozen pure classifier authenticates exact counts and IDs; it does not
    # change phase policy, invoke a grader, or treat unresolved as authoritative.
    classification = runner.operations._known_terminal_training_aggregate(core.check(aggregate_ref),cell['target']['instance_id'])
    if classification is None:
        if existing is not None:
            fail('Retained ambiguity no longer has its original known reason')
        return None
    solved = next(e for e in events if e['stage']=='SOLVE_COMPLETE')
    prior_audit_ref = core.ref(path.parent/'execution-audit.json')
    if solved['details'].get('execution_audit_reference') != prior_audit_ref:
        fail('Held grade requires its original successful audit before inspection')
    runner.operations.execution_audit(path)
    status = runner._broker_status(path)
    audit_ref = core.ref(path.parent/'execution-audit.json')
    audit = core.check(audit_ref)
    pending_ref = core.ref(path.parent/'grader-pending.json')
    pending = core.check(pending_ref)
    patch_ref = core.ref(Path(cell['broker_root'])/'submission.diff')
    submission_ref = core.ref(Path(cell['broker_root'])/'submission.json')
    submission = core.check(submission_ref)
    if (status['status'] != 'SUBMITTED' or status['unfinished_actions'] != 0 or
            audit.get('passed') is not True or audit.get('errors') != [] or
            audit['patch_sha256'] != patch_ref['sha256'] or
            audit['event_tail_sha256'] != status['event_tail_sha256'] or
            audit['configuration_sha256'] != core.digest(core.canonical_bytes(runner._row_config(row))) or
            status['submission'] != submission or submission['patch_sha256'] != patch_ref['sha256'] or
            submission['task_id'] != task or submission['arm'] != arm or
            set(pending) != {'patch_sha256','started_at'} or pending['patch_sha256'] != patch_ref['sha256'] or
            type(pending['started_at']) not in (int,float) or not math.isfinite(pending['started_at']) or
            type(submission['submitted_at']) not in (int,float) or not math.isfinite(submission['submitted_at']) or
            pending['started_at'] < submission['submitted_at']):
        fail('Held grade does not bind its original native audit and sealed patch')
    if solved['details']['execution_audit_reference'] != audit_ref:
        fail('Held grade native audit changed after submission')
    references = {'cell':core.ref(path),'audit':audit_ref,'pending':pending_ref,'aggregate':aggregate_ref,
        'patch':patch_ref,'submission':submission_ref,
        'graded_error_event':core.ref(runner.root/'events'/f"{errors[-1]['sequence']:08d}.json")}
    value = {'schema':HOLD_SCHEMA,'policy':POLICY,'amendment_reference':amendment_reference,
        'experiment_reference':runner._row_experiment_reference(row),'cohort_reference':core.ref(runner.root/'cohort.json'),
        'task_id':task,'arm':arm,'phase':'EVALUATION','official':False,'resolved':None,
        'grader_status':'undetermined','classification':classification[0],'reason':classification[1],
        'references':references,'broker_event_tail_sha256':status['event_tail_sha256'],
        'memory_injections':status['memory_injections'], 'resources_retained':True,
        'model_calls':0,'official_grader_runs':0,'native_retries':False,'official_grader_retries':False,
        'training_memory_writes':0}
    if existing is not None and existing != value:
        fail('Unscored evaluation evidence changed')
    for reference in references.values():
        core.check(reference,decode=False)
    reference = core.retain(proof_path,value)
    return value,reference


def held_task_ids(root, amendment_reference):
    tasks = set()
    for path in sorted((Path(root)/'unscored').glob('*.json')):
        proof = core.read(path)
        if (proof.get('schema') != HOLD_SCHEMA or proof.get('amendment_reference') != amendment_reference or
                proof.get('policy') != POLICY or proof.get('phase') != 'EVALUATION' or
                proof.get('official') is not False or proof.get('resolved') is not None):
            fail('Invalid retained cross-arm hold proof')
        identity = core.digest(core.canonical_bytes([proof['experiment_reference'],proof['task_id'],proof['arm']]))
        if path.name != identity+'.json':
            fail('Hold proof filename differs from its enrolled cell')
        for reference in proof['references'].values():
            core.check(reference,decode=False)
        tasks.add(proof['task_id'])
    return tasks


def advance_one(runner, *, root, amendment_reference):
    """Preserve the frozen runner's locks/checks and advance one non-held cell."""
    held_tasks = held_task_ids(root,amendment_reference)
    with core.locked(runner.root/'run.lock'), runner._journal_snapshot():
        runner.operations.load_experiment(runner.manifest['experiment_reference']['path'])
        runner._check_execution_api()
        core.check(runner.manifest['experiment_reference'])
        runner._check_controller_source()
        if runner.manifest['bank_reference'] is not None:
            core.check(runner.manifest['bank_reference'])
        # Validate all retained holds before cleanup; a paired task with one
        # unscored arm retains both checkouts rather than forging cleanup proof.
        for row in runner.schedule:
            proof = retain_hold(root,runner,row,amendment_reference=amendment_reference)
            if proof:
                held_tasks.add(row['task_id'])
        for row in runner.schedule:
            stages = {e['stage'] for e in runner._cell_events(row)}
            if 'CELL_COMPLETE' in stages:
                if row['task_id'] not in held_tasks:
                    runner._cleanup(row)
                runner._validate_result(row)
                continue
            if hold_path(root,runner,row).exists():
                continue
            if 'GRADE_STARTED' in stages:
                proof = retain_hold(root,runner,row,amendment_reference=amendment_reference,create=True)
                if proof:
                    return {'kind':'HELD','task_id':row['task_id'],'arm':row['arm'],'reference':proof[1]}
            storage = Path(runner.config['run_root'])
            while not storage.exists():
                storage = storage.parent
            free = runner.disk_free(storage)
            if free < runner.manifest['min_free_bytes']:
                runner._record('DISK_BLOCK',row,{'free_bytes':free,'minimum_bytes':runner.manifest['min_free_bytes'],'operation_started':False})
                fail('Insufficient storage; no solve or grade started')
            try:
                runner._advance(row)
            except Exception as exc:
                runner._record('INFRA_ERROR',row,{'error_type':type(exc).__name__,'error':str(exc)[:2000],
                    'automatic_retry':False,'result_is_not_a_solver_failure':True})
                if isinstance(exc,GraderInvocationFailure):
                    proof = retain_hold(root,runner,row,amendment_reference=amendment_reference,create=True)
                    if proof:
                        return {'kind':'HELD','task_id':row['task_id'],'arm':row['arm'],'reference':proof[1]}
                raise
            if row['task_id'] not in held_tasks:
                try:
                    runner._cleanup(row)
                except Exception as exc:
                    runner._record('INFRA_ERROR',row,{'operation':'CLEANUP','error_type':type(exc).__name__,
                        'error':str(exc)[:2000],'solver_retry':False})
                    raise
            return {'kind':'OFFICIAL','task_id':row['task_id'],'arm':row['arm']}
    return {'kind':'EXHAUSTED'}


class EvaluationContinuation(core.Pipeline):
    def __init__(self,path):
        self.path,self.clock = core.absolute(path),time.time
        self.reference,self.config = core.ref(self.path),core.read(self.path)
        if core.digest(core.canonical_bytes(self.config)) != self.path.with_suffix('.sha256').read_text().strip():
            fail('Continuation configuration checksum differs')
        if self.config.get('schema') != SCHEMA or core.ref(Path(__file__).resolve()) != self.config['pipeline_source_reference']:
            fail('Continuation controller source is not the frozen revision')
        self.previous = core.check(self.config['supersedes_configuration_reference'])
        allowed = {'schema','pipeline_root','progress_root','evaluation_native_root','pipeline_source_reference',
            'supersedes_configuration_reference','revision_reason','evaluation_continuation_reference'}
        if ({k:v for k,v in self.config.items() if k not in allowed} !=
                {k:v for k,v in self.previous.items() if k not in allowed}):
            fail('Evaluation continuation cannot change solver, bank or task protocol')
        for key in ('pipeline_root','progress_root','evaluation_native_root'):
            a,b = core.absolute(self.config[key]),core.absolute(self.previous[key])
            if a==b or a in b.parents or b in a.parents:
                fail('Continuation requires distinct orchestration and new native roots')
        self.amendment = core.check(self.config['evaluation_continuation_reference'])
        if (self.amendment.get('schema') != AMENDMENT_SCHEMA or self.amendment.get('policy') != POLICY or
                self.amendment['previous_configuration_reference'] != self.config['supersedes_configuration_reference'] or
                self.amendment.get('native_outcome_retries') is not False or
                self.amendment.get('official_grading_retries') is not False or
                self.amendment.get('undetermined_as_failure') is not False or
                self.amendment.get('applies_to') != ['BASELINE','PDF_MEMORY'] or
                self.amendment.get('training_memory_updates') is not False):
            fail('Evaluation hold policy must be explicit, symmetric and unscored')
        self.previous_module = load_bound(self.previous['pipeline_source_reference'])
        self.prior = self.previous_module.ReflectionRecoveryPipeline(self.config['supersedes_configuration_reference']['path'])
        self.operations,self.scale = self.prior.operations,self.prior.scale
        self.root = Path(self.config['pipeline_root'])
        self.root.mkdir(parents=True,exist_ok=True)
        core.retain(self.root/'pipeline-binding.json',{'schema':SCHEMA,'configuration_reference':self.reference})
        (self.root/'events').mkdir(exist_ok=True)
        self.validate_predecessor()

    def validate_predecessor(self):
        receipt = self.amendment
        old_root = Path(self.previous['pipeline_root'])
        tail = receipt['previous_pipeline_event_tail_reference']
        self.scale._event_reference(tail,old_root,tail=True)
        event = core.check(tail)
        if event['stage'] != 'PIPELINE_BLOCKED':
            fail('Continuation predecessor must be the retained blocked controller')
        root = old_root/'development/baseline/run/cohort'
        if receipt['baseline_cohort_reference']['path'] != str(root/'cohort.json'):
            fail('Continuation must retain the original baseline cohort')
        manifest = core.check(receipt['baseline_cohort_reference'])
        events = self.operations.modules['cohort']._event_chain(root)
        initial = core.check(receipt['baseline_event_tail_reference'])
        if (events[initial['sequence']-1] != initial or initial['stage'] != 'INFRA_ERROR' or
                initial['task_id'] != receipt['initial_held_task_id'] or initial['arm'] != 'BASELINE' or
                manifest['arms'] != ['BASELINE'] or len(manifest['schedule']) != 60):
            fail('Original baseline prefix or grading failure changed')
        if manifest['experiment_reference'] != receipt['baseline_experiment_reference']:
            fail('Original baseline experiment changed')
        for reference in receipt['initial_held_evidence_references'].values():
            core.check(reference,decode=False)

    def progress(self):
        return self.scale.ScalePipeline.progress(self)

    def status(self):
        events = self.events()
        return {'schema':SCHEMA,'configuration_reference':self.reference,'status':
            'COMPLETE_WITH_UNDETERMINED' if self.latest('PIPELINE_COMPLETE_WITH_UNDETERMINED') else
            'COMPLETE' if self.latest('PIPELINE_COMPLETE') else
            'BLOCKED' if events and events[-1]['stage']=='PIPELINE_BLOCKED' else 'IN_PROGRESS',
            'evaluation_continuation_reference':self.config['evaluation_continuation_reference'],
            'source_attempts':240,'new_training_solves':0,'development_cells':120,'final_cells':1000,
            'native_outcome_retries':False,'official_grading_retries':False,'last_event':events[-1] if events else None}

    def runner(self,purpose,stage,bank_reference,name):
        modules = self.operations.modules
        if purpose == 'DEVELOPMENT_BASELINE':
            ref = self.amendment['baseline_experiment_reference']
            value = core.check(ref)
            root = Path(ref['path']).parent
        else:
            template = core.check(stage['execution_reference'])
            runtime = core.check(self.config['training_experiment_reference'])
            template.update({k:runtime[k] for k in ('source_root','source_sha256','loader_preflight_path','loader_preflight_sha256','codex_binary')})
            root = self.root/('final' if purpose=='FINAL_EVALUATION' else 'development')/name
            root.mkdir(parents=True,exist_ok=True)
            authority = modules['cohort'].execution.create_execution_enrollment(root/'execution-authority.json',
                dataset_reference=template['dataset_manifest'],purpose=purpose,bank_reference=bank_reference)
            value = {**template,'phase':'EVALUATION_RUNTIME','evaluation_status':'EVALUATION_READY',
                'run_root':str(root/'run'),'native_control_root':str(Path(self.config['evaluation_native_root'])/name),
                'scale_authority_reference':authority,'frozen_bank_reference':bank_reference,'pipeline_reference':self.reference}
            value.pop('training_grade_hold_policy',None)
            ref = self.scale.write_execution(root/'execution.json',value)
        cohort_root,quarantine = Path(value['run_root'])/'cohort',Path(value['run_root'])/'quarantine'
        quarantine_reference = modules['quarantine'].initialize_quarantine(quarantine,execution_reference=ref,bank_reference=bank_reference)
        hook = modules['quarantine'].make_quarantine_hook(quarantine)
        if (cohort_root/'cohort.json').exists():
            runner = modules['cohort'].CohortRunner(cohort_root,quarantine_hook=hook,cleanup_operations=modules['cleanup'])
        else:
            policy = modules['cleanup'].create_cleanup_policy(root/'cleanup-policy.json',experiment_reference=ref)
            runner = modules['cohort'].CohortRunner.create(cohort_root,experiment_path=ref['path'],phase='EVALUATION',
                bank_reference=bank_reference,quarantine_root=quarantine,quarantine_hook=hook,
                cleanup_policy_reference=policy,cleanup_operations=modules['cleanup'])
        if not self.latest('EVALUATION_CONFIGURED',name):
            self.record('EVALUATION_CONFIGURED',{'experiment_reference':ref,'cohort_reference':core.ref(cohort_root/'cohort.json'),
                'quarantine_reference':quarantine_reference,'purpose':purpose},job=name)
        return runner,ref

    def evaluation(self,purpose,stage,bank_reference,name):
        runner,experiment = self.runner(purpose,stage,bank_reference,name)
        while True:
            self.record('COHORT_ADVANCE_STARTED',{'cohort_root':str(runner.root),'planned_cells':len(runner.schedule)},job=name)
            change = advance_one(runner,root=self.root,amendment_reference=self.config['evaluation_continuation_reference'])
            self.record('COHORT_PROGRESS',{'cohort_root':str(runner.root),'change':change},job=name)
            self.progress()
            if change['kind']=='EXHAUSTED':
                break
        rows = []
        with core.locked(runner.root/'run.lock'),runner._journal_snapshot():
            runner.full_audit()
            for row in runner.schedule:
                held = retain_hold(self.root,runner,row,amendment_reference=self.config['evaluation_continuation_reference'])
                if held:
                    value,reference = held
                    rows.append({'task_id':row['task_id'],'arm':row['arm'],'official':False,'resolved':None,
                        'reference':reference,'memory_injections':value['memory_injections']})
                else:
                    value,reference = runner._validate_result(row,full_audit=True)
                    rows.append({'task_id':row['task_id'],'arm':row['arm'],'official':True,'resolved':value['resolved'],
                        'reference':reference,'memory_injections':value['broker_status']['memory_injections']})
        by_arm = {arm:result_counts([r for r in rows if r['arm']==arm],sum(r['arm']==arm for r in runner.schedule))
            for arm in runner.manifest['arms']}
        report = {'scope':'FINAL' if purpose=='FINAL_EVALUATION' else 'DEVELOPMENT','rows':rows,
            'planned':len(rows),'by_arm':by_arm,'experiment_reference':experiment,'bank_reference':bank_reference,
            'status':'COMPLETE_WITH_UNDETERMINED' if any(c['undetermined'] for c in by_arm.values()) else 'COMPLETE',
            'evaluation_continuation_reference':self.config['evaluation_continuation_reference'],
            'full_enrollment_retained':True,'official_grader_retries':False,'native_outcome_retries':False}
        if len(by_arm)==2:
            report['paired_comparison'] = paired_counts([r for r in rows if r['arm']=='BASELINE'],[r for r in rows if r['arm']=='PDF_MEMORY'])
        reference = core.retain(self.root/'reports'/(name+'.json'),report)
        if not self.latest('EVALUATION_COMPLETE',name):
            self.record('EVALUATION_COMPLETE',{'report_reference':reference,'status':report['status']},job=name)
        return report,reference

    def run(self):
        with core.locked(self.root/'run.lock'),self.prior._controller_locks():
            self.validate_predecessor()
            if self.latest('PIPELINE_COMPLETE') or self.latest('PIPELINE_COMPLETE_WITH_UNDETERMINED'):
                return self.status()
            try:
                bank = self.previous_module.validate_recovered_bank(self.previous,self.prior.previous,self.operations)
                if not self.latest('RECOVERY_BANK_VALIDATED'):
                    self.record('RECOVERY_BANK_VALIDATED',bank)
                stages = {r['size']:r for r in self.config['training_stages']}
                baseline,off_ref = self.evaluation('DEVELOPMENT_BASELINE',stages[24],None,'baseline')
                memory,on_ref = self.evaluation('DEVELOPMENT_BANK',stages[240],bank['bank_reference'],'bank-240')
                comparison = paired_counts(baseline['rows'],memory['rows'])
                selection = {'policy':'SINGLE_PREDECLARED_READY_BANK','bank_reference':bank['bank_reference'],
                    'baseline_report_reference':off_ref,'memory_report_reference':on_ref,
                    'development_paired_comparison':comparison,'final_outcomes_used':False,
                    'evaluation_continuation_reference':self.config['evaluation_continuation_reference']}
                selection_ref = core.retain(self.root/'bank-selection.json',selection)
                if not self.latest('BANK_SELECTED'):
                    self.record('BANK_SELECTED',{'reference':selection_ref})
                final,final_ref = self.evaluation('FINAL_EVALUATION',stages[240],bank['bank_reference'],'verified500')
                incomplete = any(r['status']=='COMPLETE_WITH_UNDETERMINED' for r in (baseline,memory,final))
                self.record('PIPELINE_COMPLETE_WITH_UNDETERMINED' if incomplete else 'PIPELINE_COMPLETE',
                    {'report_reference':final_ref,'selection_reference':selection_ref,'development_cells':120,'final_cells':1000})
            except Exception as exc:
                self.record('PIPELINE_BLOCKED',{'error_type':type(exc).__name__,'reason':str(exc)[:2000],
                    'native_outcome_retries':False,'official_grading_retries':False})
                self.progress()
                raise
            self.progress()
            return self.status()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('run','status','validate'))
    parser.add_argument('--config',required=True)
    args = parser.parse_args()
    controller = EvaluationContinuation(args.config)
    print(json.dumps(controller.run() if args.command=='run' else controller.status()))
