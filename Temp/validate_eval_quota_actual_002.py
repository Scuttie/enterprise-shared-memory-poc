"""Validate retained real quota evidence and prior score references, without solving."""
from pathlib import Path
import importlib.util,json,sys
import trimem_skhynix_architecture_pipeline as core

REPO=Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
BASE=REPO/'artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/evaluation-continuation-002'
source=REPO/'scripts/trimem_skhynix_evaluation_quota_continuation.py'
source_ref=core.ref(source)
name='skhynix_quota_actual_preflight'
spec=importlib.util.spec_from_file_location(name,source)
module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
config_path=REPO/'configs/skhynix_v1/architecture_002_pipeline_v16.json'
config=core.read(config_path)
v16_module=module.load_bound(config['pipeline_source_reference'])
controller=v16_module.EvaluationContinuation(config_path)
amendment_ref=core.ref(BASE/'amendment.json')
amendment=core.check(amendment_ref)
with core.locked(controller.root/'run.lock'),controller.prior._controller_locks():
    stages={row['size']:row for row in controller.config['training_stages']}
    runner,experiment=controller.runner('DEVELOPMENT_BASELINE',stages[24],None,'baseline')
    with core.locked(runner.root/'run.lock'),runner._journal_snapshot():
        tail=core.ref(sorted((runner.root/'events').glob('*.json'))[-1])
        assert tail==amendment['baseline_event_tail_reference']
        failed=next(row for row in runner.schedule if row['task_id']==amendment['initial_held_task_id'])
        print(json.dumps({'stage':'AUTHENTICATING_ORIGINAL_NATIVE_QUOTA','task_id':failed['task_id']}),flush=True)
        proof,proof_ref=module.retain_quota_hold(BASE/'preflight',runner,failed,amendment_reference=amendment_ref,create=True)
        prior=core.check(core.ref(BASE.parent/'interim-results-20260920T133030Z-v2.json'))
        official=[]
        for row in prior['rows']:
            if row.get('outcome') not in ('RESOLVED','UNRESOLVED'):continue
            result=core.check(row['result_reference']);audit=core.check(row['execution_audit_reference'])
            assert result['official'] is True and type(result['resolved']) is bool
            assert result['resolved']==row['resolved'] and result['task_id']==row['task_id']
            assert audit['passed'] is True and audit['errors']==[]
            assert result['execution_audit_sha256']==row['execution_audit_reference']['sha256']
            assert result['patch_sha256']==audit['patch_sha256']
            assert result['broker_status']['memory_injections']==0
            official.append({'task_id':row['task_id'],'resolved':row['resolved'],'result_reference':row['result_reference'],'audit_reference':row['execution_audit_reference']})
        assert len(official)==15 and sum(row['resolved'] for row in official)==13
        grade_row=next(row for row in runner.schedule if row['task_id']==controller.amendment['initial_held_task_id'])
        grade=v16_module.retain_hold(controller.root,runner,grade_row,amendment_reference=config['evaluation_continuation_reference'])
        assert grade and grade[0]['reason']=='no_tests_collected'
        assert core.ref(source)==source_ref
        assert core.ref(sorted((runner.root/'events').glob('*.json'))[-1])==tail
        for reference in amendment['initial_held_evidence_references'].values():core.check(reference,decode=False)
        bank_ref=core.read(BASE.parent/'startup-validation-v15.json')['bank_reference']
        bank=core.check(bank_ref);core.check(bank['authority'],decode=False);core.check(bank['source_authority'],decode=False)
        value={'schema':'skhynix/actual-native-quota-preflight/1.0','status':'PASS',
            'implementation_reference':source_ref,'amendment_reference':amendment_ref,
            'original_cohort_event_tail_reference':tail,'quota_hold_reference':proof_ref,
            'grader_hold_reference':grade[1],'bank_reference':bank_ref,
            'official_counts':{'official_complete':15,'resolved':13,'unresolved':2},
            'official_evidence':official,'grader_undetermined':1,'native_quota_undetermined':1,
            'original_journal_unchanged':True,'model_calls':0,'official_grader_runs':0,
            'validation':'Original failed native audit/worker lineage/sealed submission; unchanged official result and audit hashes; existing authenticated grader hold. Full cohort runtime revalidation remains enforced before next solve.'}
        result_ref=core.retain(BASE/'actual-quota-preflight.json',value)
        print(json.dumps({'status':'PASS','reference':result_ref,'quota_hold_reference':proof_ref,'official_counts':value['official_counts']}),flush=True)
