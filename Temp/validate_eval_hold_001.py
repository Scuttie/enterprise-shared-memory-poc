"""Validate a real held evaluation and all 15 retained official results."""
from pathlib import Path
import importlib.util,json,sys
import trimem_skhynix_architecture_pipeline as core

REPO=Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
BASE=REPO/'artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/evaluation-continuation-001'
module_path=REPO/'scripts/trimem_skhynix_evaluation_continuation.py'
name='skhynix_hold_actual_validation'
spec=importlib.util.spec_from_file_location(name,module_path)
module=importlib.util.module_from_spec(spec)
sys.modules[name]=module
spec.loader.exec_module(module)
amendment_reference=core.ref(BASE/'amendment.json')
amendment=core.check(amendment_reference)
config=core.check(amendment['previous_configuration_reference'])
operations=core.FrozenOperations(config)
cohort_root=Path(amendment['baseline_cohort_reference']['path']).parent
hook=operations.modules['quarantine'].make_quarantine_hook(cohort_root.parent/'quarantine')
runner=operations.modules['cohort'].CohortRunner(cohort_root,quarantine_hook=hook,
    cleanup_operations=operations.modules['cleanup'])
with core.locked(cohort_root/'run.lock'),runner._journal_snapshot():
    before=core.ref(sorted((cohort_root/'events').glob('*.json'))[-1])
    original=runner.full_audit()
    row=next(r for r in runner.schedule if r['task_id']==amendment['initial_held_task_id'])
    held=module.retain_hold(BASE/'preflight',runner,row,amendment_reference=amendment_reference,create=True)
    assert held is not None
    assert before==core.ref(sorted((cohort_root/'events').glob('*.json'))[-1])
    assert original['by_arm']['BASELINE']['official_complete']==15
    assert original['by_arm']['BASELINE']['resolved']==13
    result={'schema':'skhynix/evaluation-continuation-preflight/1.0','status':'PASS',
        'implementation_reference':core.ref(module_path),'amendment_reference':amendment_reference,
        'original_cohort_event_tail_reference':before,'original_official_counts':original['by_arm'],
        'held_reference':held[1],'held_reason':held[0]['reason'],'original_journal_unchanged':True,
        'model_calls':0,'official_grader_runs':0}
    reference=core.retain(BASE/'actual-hold-preflight.json',result)
    print(json.dumps({'reference':reference,**result}))
