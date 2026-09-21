"""Validate the pinned v16 controller, unchanged bank and original held cell."""
from pathlib import Path
import importlib.util,json,sys
import trimem_skhynix_architecture_pipeline as core

REPO=Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
BASE=REPO/'artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/evaluation-continuation-001'
config_path=REPO/'configs/skhynix_v1/architecture_002_pipeline_v16.json'
config=core.read(config_path)
source=core.check(config['pipeline_source_reference'],decode=False)
name='skhynix_bound_continuation_startup'
spec=importlib.util.spec_from_file_location(name,source)
module=importlib.util.module_from_spec(spec)
sys.modules[name]=module
spec.loader.exec_module(module)
controller=module.EvaluationContinuation(config_path)
with core.locked(controller.root/'run.lock'),controller.prior._controller_locks():
    preflight_ref=core.ref(BASE/'actual-hold-preflight.json')
    preflight=core.check(preflight_ref)
    assert preflight['status']=='PASS'
    assert preflight['implementation_reference']['sha256']==config['pipeline_source_reference']['sha256']
    assert preflight['amendment_reference']==config['evaluation_continuation_reference']
    root=Path(controller.amendment['baseline_cohort_reference']['path']).parent
    with core.locked(root/'run.lock'):
        assert preflight['original_cohort_event_tail_reference']==core.ref(sorted((root/'events').glob('*.json'))[-1])
        held=core.check(preflight['held_reference'])
        for reference in held['references'].values():
            core.check(reference,decode=False)
        bank_validation_ref=core.ref(BASE.parent/'startup-validation-v15.json')
        prior_bank=core.check(bank_validation_ref)
        assert prior_bank['status']=='READY'
        assert prior_bank['reflection_recovery_reference']==config['reflection_recovery_reference']
        bank=core.check(prior_bank['bank_reference'])
        core.check(bank['authority'],decode=False)
        core.check(bank['source_authority'],decode=False)
        value={'schema':'skhynix/evaluation-continuation-startup/1.0','status':'READY_FOR_RUN',
            'configuration_reference':core.ref(config_path),'controller_reference':config['pipeline_source_reference'],
            'amendment_reference':config['evaluation_continuation_reference'],
            'preflight_reference':preflight_ref,'prior_bank_validation_reference':bank_validation_ref,
            'bank_reference':prior_bank['bank_reference'],'bank_authority_hashes_unchanged':True,
            'full_bank_revalidation':'PERFORMED_BY_CONTROLLER_BEFORE_NEXT_SOLVE',
            'held_reference':preflight['held_reference'],'held_reason':held['reason'],
            'original_official_counts':preflight['original_official_counts'],'source_runtime_unchanged':True,
            'model_calls':0,'official_grader_runs':0}
        reference=core.retain(BASE/'startup-validation-v16.json',value)
        print(json.dumps({'reference':reference,**value}))
