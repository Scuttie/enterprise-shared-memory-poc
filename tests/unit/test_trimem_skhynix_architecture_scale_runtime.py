"""Exact scale enrollment and cohort scheduling; public synthetic records only."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

import trimem_skhynix_architecture_run as run
import trimem_skhynix_architecture_cohort as cohort
from test_trimem_skhynix_architecture_cohort import EffortOperations


def retain(path, value):
    cohort.write(path, value)
    return cohort.reference(path)


@pytest.fixture
def scaled(tmp_path, monkeypatch):
    # Public-source reconstruction is independently exercised by scale_dataset tests.
    # This fixture preserves the exact population shapes while avoiding Parquet I/O.
    monkeypatch.setitem(sys.modules, 'trimem_skhynix_architecture_scale_dataset',
        SimpleNamespace(validate_scale_manifest=lambda value: value))
    monkeypatch.setattr(run, 'load_experiment', lambda path: cohort.read(path))

    def make(count=24):
        folder=tmp_path/str(count); folder.mkdir()
        ops=EffortOperations(folder)
        targets=[]
        for role, scope, size in [('TRAINING',None,count),('EVALUATION','DEVELOPMENT',60),('EVALUATION','FINAL',500)]:
            for i in range(size):
                identity=f'training-{i:03d}' if role=='TRAINING' else f'evaluation-{scope.lower()}-{i:03d}'
                targets.append({'target_id':identity,'instance_id':identity,'repository':'synthetic/public',
                    'base_commit':'a'*40,'instruction_sha256':cohort.sha(f'Public issue {identity}'.encode()),
                    'role':role,'order_index':len(targets), **({'evaluation_scope':scope} if scope else {})})
        dataset={'schema':run.SCALE_DATASET_SCHEMA,'targets':targets,'training_count':count,'evaluation_count':560,
            'development_count':60,'final_evaluation_count':500}
        dataset_ref=retain(folder/'dataset.json',dataset)
        ops.config.update(dataset_manifest=dataset_ref,reasoning_effort='high',model='gpt-6-astra',authentication='CHATGPT',
            limits={'task_requests':120,'task_seconds':1200},source_sha256={})
        cohort.write(ops.experiment,ops.config)
        scope={key:[cohort._descriptor(row) for row in targets if row['role']==role]
            for role,key in [('TRAINING','training_tasks'),('EVALUATION','evaluation_tasks')]}
        scope.update(phase='TRAINING',org_id=ops.config['org_id'])
        bank=retain(folder/'bank.json',{'frozen':True,'scope':scope,
            'layer_counts':{'L1_episodes':1,'L2_nodes':1,'L2_edges':1,'L3_skills':1}})
        return SimpleNamespace(root=folder,ops=ops,dataset=dataset,dataset_ref=dataset_ref,bank=bank)

    return make


def authorize(case,purpose,*,adoption=None):
    bank=case.bank if purpose in ('DEVELOPMENT_BANK','FINAL_EVALUATION') else None
    authority=run.create_execution_enrollment(case.root/'enrollment.json',dataset_reference=case.dataset_ref,
        purpose=purpose,bank_reference=bank,source_adoption_reference=adoption)
    case.ops.config.update(scale_authority_reference=authority,
        phase='TRAINING_RUNTIME' if purpose.startswith('TRAINING_') else 'EVALUATION_RUNTIME',
        evaluation_status='EVALUATION_READY')
    cohort.write(case.ops.experiment,case.ops.config)
    return authority


@pytest.mark.parametrize('count,purpose,size,arms,first',[
    (120,'TRAINING_INCREMENT',96,['PDF_MEMORY'],'training-024'),
    (240,'TRAINING_INCREMENT',120,['PDF_MEMORY'],'training-120'),
    (24,'DEVELOPMENT_BASELINE',60,['BASELINE'],'evaluation-development-000'),
    (24,'DEVELOPMENT_BANK',60,['PDF_MEMORY'],'evaluation-development-000'),
    (120,'DEVELOPMENT_BANK',60,['PDF_MEMORY'],'evaluation-development-000'),
    (240,'FINAL_EVALUATION',500,['BASELINE','PDF_MEMORY'],'evaluation-final-000')])
def test_exact_population_and_arms_are_derived_not_caller_selected(scaled,count,purpose,size,arms,first):
    case=scaled(count); authorize(case,purpose)
    scope=run.execution_enrollment(case.ops.config)
    assert len(scope['task_ids'])==size and scope['task_ids'][0]==first and scope['arms']==arms
    runner=cohort.CohortRunner.create(case.root/'cohort',experiment_path=case.ops.experiment,
        phase='TRAINING' if purpose.startswith('TRAINING_') else 'EVALUATION',
        bank_reference=scope['bank_reference'],operations=case.ops,
        bank_validator=lambda *_:{'L1':1,'L2':1,'L3':1},disk_free=lambda _:10**15)
    assert len(runner.schedule)==size*len(arms)
    assert {row['arm'] for row in runner.schedule}==set(arms)
    assert runner.manifest['scope']=='FULL_AUTHORIZED_SCALE_COHORT'
    assert runner.manifest['cumulative_training_count']==count
    if purpose in ('TRAINING_INCREMENT','DEVELOPMENT_BASELINE'):
        result=runner.run(cell_limit=1)
        assert result['completed_cells']==1
        assert case.ops.calls[0][1]==first
        assert result['paired_comparison'] is None


def test_scaled_dataset_without_new_authority_cannot_weaken_legacy_count_guard(scaled):
    case=scaled(120)
    with pytest.raises(ValueError,match='explicit new'):
        cohort.CohortRunner.create(case.root/'bad',experiment_path=case.ops.experiment,phase='TRAINING',operations=case.ops)


@pytest.mark.parametrize('field,value',[('task_ids',['training-000']),('arms',['BASELINE']),('cumulative_training_count',24)])
def test_self_consistent_authority_hash_cannot_change_exact_increment(scaled,field,value):
    case=scaled(120); reference=authorize(case,'TRAINING_INCREMENT')
    bad={**cohort.checked(reference),field:value}
    case.ops.config['scale_authority_reference']=retain(reference['path'],bad)
    with pytest.raises(ValueError,match='scope differs'):
        run.execution_enrollment(case.ops.config)


@pytest.mark.parametrize('key,value',[('reasoning_effort','ultra'),('model','different'),('authentication','API'),
    ('limits',{'task_requests':121,'task_seconds':1200}),('limits',{'task_requests':120,'task_seconds':1201})])
def test_scaled_runtime_keeps_exact_high_model_and_task_budgets(scaled,key,value):
    case=scaled(120); authorize(case,'TRAINING_INCREMENT'); case.ops.config[key]=value
    with pytest.raises(ValueError,match='fixed Astra/high'):
        run.execution_enrollment(case.ops.config)


@pytest.mark.parametrize('task,arm',[('training-000','PDF_MEMORY'),('training-024','BASELINE'),('evaluation-final-000','PDF_MEMORY')])
def test_direct_prepare_rejects_old_training_and_other_arms_before_environment(scaled,monkeypatch,task,arm):
    case=scaled(120); authorize(case,'TRAINING_INCREMENT')
    monkeypatch.setattr(run,'environment',lambda *_a,**_k:pytest.fail('Invalid scope reached environment preparation'))
    with pytest.raises(ValueError,match='outside its frozen scale'):
        run.prepare_cell(case.ops.experiment,task,arm)


def test_development_baseline_is_bank_free_and_cannot_be_repeated_as_later_stage(scaled):
    case=scaled(120)
    with pytest.raises(ValueError,match='single bank-free24'):
        authorize(case,'DEVELOPMENT_BASELINE')


def test_development_c_requires_its_exact_bank_and_entire_sixty(scaled):
    case=scaled(); authorize(case,'DEVELOPMENT_BANK')
    with pytest.raises(cohort.CohortError,match='entire exact'):
        cohort.CohortRunner.create(case.root/'bad',experiment_path=case.ops.experiment,phase='EVALUATION',
            target_ids=['evaluation-development-000'],bank_reference=case.bank,operations=case.ops)
    with pytest.raises(cohort.CohortError,match='bank differs'):
        cohort.CohortRunner.create(case.root/'wrong-bank',experiment_path=case.ops.experiment,phase='EVALUATION',
            bank_reference=None,operations=case.ops)


def source_adoption(case,*,count=18):
    original={**case.ops.config,'dataset_manifest':case.dataset_ref,'phase':'TRAINING_RUNTIME'}
    original.pop('scale_authority_reference',None)
    config_ref=retain(case.root/'original-config.json',original)
    rows=[]
    for index in range(count):
        target=case.dataset['targets'][index]; identity=target['target_id']
        folder=Path(original['run_root'])/'cells/TRAINING'/identity/'PDF_MEMORY'
        cell={'phase':'TRAINING','arm':'PDF_MEMORY','experiment_config':config_ref['path'],
            'bank_reference':None,'bank_sha256':run.EMPTY_BANK_SHA,
            'task_public':{'task_id':identity,'repository':target['repository'],'commit':target['base_commit'],
                'instruction':f'Public issue {identity}'}}
        cell_ref=retain(folder/'cell.json',cell)
        (folder/'cell.sha256').write_text(cohort.sha(cohort.canonical(cell)))
        patch=folder/'broker/submission.diff'; patch.parent.mkdir(); patch.write_bytes(b'public synthetic patch')
        patch_ref=cohort.reference(patch)
        submission=retain(folder/'broker/submission.json',{'task_id':identity,'patch_sha256':patch_ref['sha256'],
            'arm':'PDF_MEMORY','configuration_sha256':cohort.sha(cohort.canonical(original)),'bank_sha256':run.EMPTY_BANK_SHA})
        audit=retain(folder/'execution-audit.json',{'task_id':identity,'passed':True,'errors':[],
            'patch_sha256':patch_ref['sha256'],'arm':'PDF_MEMORY','configuration_sha256':cohort.sha(cohort.canonical(original))})
        result=retain(folder/'public-result.json',{'task_id':identity,'official':True,'grader_status':'success','resolved':False,
            'patch_sha256':patch_ref['sha256'],'experiment_sha256':cohort.sha(cohort.canonical(original)),
            'execution_audit_sha256':audit['sha256']}) if index<count-1 else None
        summary=retain(folder/'public-grade-summary.json',{'classification':'AMBIGUOUS_NO_TESTS_COLLECTED'}) if result is None else None
        rows.append({'task_id':identity,'cell_reference':cell_ref,'audit_reference':audit,'submission_reference':submission,
            'submission_patch_reference':patch_ref,'official_result_reference':result,'official_summary_reference':summary,
            'classification':'OFFICIAL_COMPLETE' if result is not None else 'AMBIGUOUS_NO_TESTS_COLLECTED'})
    return retain(case.root/'source-adoption.json',{'schema':'skhynix/architecture-scale-source-adoption/1.0','rows':rows,
        'predecessor_configrefs':[config_ref],'source_count':count,'official_complete':count-1,
        'model_calls':0,'official_grader_runs':0,'outcome_retries':False})


def test_original24_remainder_preserves_ambiguous_attempt_and_schedules_only_six(scaled):
    case=scaled(); adoption=source_adoption(case); authorize(case,'TRAINING_REMAINDER_24',adoption=adoption)
    scope=run.execution_enrollment(case.ops.config)
    assert scope['task_ids']==[f'training-{i:03d}' for i in range(18,24)]
    assert len(scope['adopted_source_task_ids'])==18
    assert cohort.checked(adoption)['official_complete']==17
    runner=cohort.CohortRunner.create(case.root/'cohort',experiment_path=case.ops.experiment,phase='TRAINING',operations=case.ops)
    assert len(runner.schedule)==6 and runner.manifest['adopted_training_source_count']==18
    status=runner.run(cell_limit=1)
    assert status['completed_cells']==1 and status['adopted_training_source_count']==18
    assert [call for call in case.ops.calls if call[0]=='solve']==[('solve','training-018','PDF_MEMORY')]


@pytest.mark.parametrize('change',[None,'nonterminal','wrong_reason','wrong_instance','scored','wrong_path','boolean_count'])
def test_missing_module_adoption_retains_unscored_terminal_source_only(scaled,change):
    case=scaled(); adoption=source_adoption(case)
    value=cohort.checked(adoption); row=value['rows'][-1]
    original=cohort.checked(value['predecessor_configrefs'][0])
    target=case.dataset['targets'][17]
    summary={'total_instances':1,'submitted_instances':1,'completed_instances':1,
        'ambiguous_failure_instances':1,'infra_failure_instances':0,'empty_patch_instances':0,
        'error_instances':0,'unstopped_instances':0,'incomplete_ids':[],'unstopped_containers':[],
        'failure_reasons':{target['instance_id']:'missing_module'}}
    path=Path(original['run_root'])/'environment/TRAINING/cells/PDF_MEMORY'/row['task_id']/'official-grader'/row['task_id']/'report/aggregate.json'
    if change=='nonterminal': summary['completed_instances']=0
    elif change=='wrong_reason': summary['failure_reasons'][target['instance_id']]='no_tests_collected'
    elif change=='wrong_instance': summary['failure_reasons']={'different-instance':'missing_module'}
    elif change=='scored': row['official_result_reference']=value['rows'][0]['official_result_reference']
    elif change=='wrong_path': path=case.root/'unbound-summary.json'
    elif change=='boolean_count': summary['completed_instances']=True
    row['classification']='AMBIGUOUS_MISSING_MODULE'
    row['official_summary_reference']=retain(path,summary)
    adoption=retain(adoption['path'],value)
    if change is not None:
        with pytest.raises(ValueError):
            authorize(case,'TRAINING_REMAINDER_24',adoption=adoption)
    else:
        authorize(case,'TRAINING_REMAINDER_24',adoption=adoption)
        scope=run.execution_enrollment(case.ops.config)
        assert row['task_id'] in scope['adopted_source_task_ids']
        assert row['task_id'] not in scope['task_ids']
        assert cohort.checked(adoption)['official_complete']==17
        assert not (Path(row['cell_reference']['path']).parent/'public-result.json').exists()


@pytest.mark.parametrize('change',['duplicate','audit','patch','ambiguous_score','count','membership'])
def test_remainder_adoption_rejects_unproven_or_relabelled_sources(scaled,change):
    case=scaled(); ref=source_adoption(case); value=cohort.checked(ref)
    if change=='duplicate': value['rows'][1]=value['rows'][0]
    elif change=='audit':
        row=value['rows'][0]; row['audit_reference']=retain(row['audit_reference']['path'],{'passed':False,'errors':['failed']})
    elif change=='patch': Path(value['rows'][0]['submission_patch_reference']['path']).write_bytes(b'changed')
    elif change=='ambiguous_score': value['rows'][-1]['official_result_reference']=value['rows'][0]['official_result_reference']
    elif change=='count': value['official_complete']=18
    else: value['rows'][0]['task_id']='evaluation-final-000'
    ref=retain(ref['path'],value)
    with pytest.raises(ValueError):
        authorize(case,'TRAINING_REMAINDER_24',adoption=ref)


def test_bank_scope_requires_full_union_and_exact_cumulative_sources(scaled,monkeypatch):
    import trimem_skhynix_architecture_memory as memory
    case=scaled(120)
    scope={key:[cohort._descriptor(row) for row in case.dataset['targets'] if row['role']==role]
        for role,key in [('TRAINING','training_tasks'),('EVALUATION','evaluation_tasks')]}
    scope['org_id']=case.ops.config['org_id']
    manifest={'scope':scope,'layer_counts':{'L1':1,'L2':1,'L3':1}}
    bank=SimpleNamespace(manifest=manifest,close=lambda:None)
    monkeypatch.setattr(memory,'load_frozen_bank',lambda *_:bank)
    assert cohort.validate_evaluation_bank(case.bank,case.dataset,case.ops.config)==manifest['layer_counts']
    scope['evaluation_tasks']=scope['evaluation_tasks'][:60]
    with pytest.raises(cohort.CohortError,match='enrollment differs'):
        cohort.validate_evaluation_bank(case.bank,case.dataset,case.ops.config)


@pytest.mark.parametrize('change',['training_subset','dev_only','quarantine','no_skill','organisation'])
def test_direct_scale_bank_authority_rejects_incomplete_or_cross_scope_memory(scaled,change):
    case=scaled(120); bank=cohort.checked(case.bank)
    if change=='training_subset': bank['scope']['training_tasks']=bank['scope']['training_tasks'][:24]
    elif change=='dev_only': bank['scope']['evaluation_tasks']=bank['scope']['evaluation_tasks'][:60]
    elif change=='quarantine': bank['scope']['phase']='EVALUATION_QUARANTINE'
    elif change=='no_skill': bank['layer_counts']['L3_skills']=0
    else: bank['scope']['org_id']='other-organisation'
    case.bank=retain(case.bank['path'],bank)
    if change=='organisation':
        authorize(case,'DEVELOPMENT_BANK')
        with pytest.raises(ValueError,match='organisation'):
            run.execution_enrollment(case.ops.config)
    else:
        with pytest.raises(ValueError,match='Scale'):
            authorize(case,'DEVELOPMENT_BANK')


def test_adoption_cannot_use_old_task_under_new_increment_configuration(scaled):
    case=scaled(120); authority=authorize(case,'TRAINING_INCREMENT')
    adoption=source_adoption(case,count=1)
    value=cohort.checked(adoption)
    original_ref=value['predecessor_configrefs'][0]
    value['predecessor_configrefs'][0]=retain(original_ref['path'],{
        **cohort.checked(original_ref),'scale_authority_reference':authority})
    adoption=retain(adoption['path'],value)
    with pytest.raises(ValueError,match='original execution task subset'):
        run._adopted_scale_sources(adoption,case.dataset)


def scoped_adoption(case):
    adoption=source_adoption(case,count=3)
    value=cohort.checked(adoption)
    original_ref=value['predecessor_configrefs'][0]
    original=cohort.checked(original_ref)
    original['scale_authority_reference']=retain(case.root/'owner-scope.json',{'task_ids':['training-000','training-001','training-002']})
    value['predecessor_configrefs'][0]=retain(original_ref['path'],original)
    config_sha=cohort.sha(cohort.canonical(original))
    for row in value['rows']:
        for key in ('audit_reference','submission_reference'):
            data=cohort.checked(row[key]); data['configuration_sha256']=config_sha
            row[key]=retain(row[key]['path'],data)
        if row['official_result_reference'] is not None:
            data=cohort.checked(row['official_result_reference'])
            data.update(experiment_sha256=config_sha,execution_audit_sha256=row['audit_reference']['sha256'])
            row['official_result_reference']=retain(row['official_result_reference']['path'],data)
    return retain(adoption['path'],value),value,original


def test_adopted_owner_scope_is_validated_once_per_call_without_persistent_cache(scaled,monkeypatch):
    case=scaled(); adoption,value,original=scoped_adoption(case)
    calls=[]
    def enrollment(config,dataset):
        calls.append(config)
        return cohort.checked(config['scale_authority_reference'])
    monkeypatch.setattr(run,'execution_enrollment',enrollment)
    for expected_calls in (1,2):
        assert run._adopted_scale_sources(adoption,case.dataset)==['training-000','training-001','training-002']
        assert len(calls)==expected_calls


@pytest.mark.parametrize('mutation',['owner','authority','dataset','later_patch','wrong_membership'])
def test_local_owner_scope_reuse_rejects_mutations_and_checks_each_membership(scaled,monkeypatch,mutation):
    case=scaled(); adoption,value,original=scoped_adoption(case)
    calls=[]
    def enrollment(config,dataset):
        calls.append(config)
        result=cohort.checked(config['scale_authority_reference'])
        if mutation=='wrong_membership':
            return {'task_ids':['training-000','training-002']}
        if mutation=='owner':
            Path(value['predecessor_configrefs'][0]['path']).write_text('{}')
        elif mutation=='authority':
            Path(config['scale_authority_reference']['path']).write_text('{}')
        elif mutation=='dataset':
            Path(config['dataset_manifest']['path']).write_text('{}')
        else:
            Path(value['rows'][1]['submission_patch_reference']['path']).write_bytes(b'changed second-row patch')
        return result
    monkeypatch.setattr(run,'execution_enrollment',enrollment)
    with pytest.raises(ValueError):
        run._adopted_scale_sources(adoption,case.dataset)
    assert len(calls)==1
