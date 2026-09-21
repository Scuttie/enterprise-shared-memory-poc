from pathlib import Path
import sys
import pytest

sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'src'),str(Path(__file__).resolve().parents[2]/'scripts')]
import trimem_skhynix_architecture_run as manager


def completion(**changes):
    return {'admitted':True,'outside_broker_tool_events':[],'errors':[],
            'timed_out':False,'exit_code':0}|changes


@pytest.mark.parametrize('changes,code',[
    ({'admitted':False},0),({'outside_broker_tool_events':['web_search']},0),
    ({'errors':['invalid JSON event']},0),({'exit_code':1},0),({},1),
    ({'timed_out':True,'errors':['invalid event']},1),
    ({'transport_errors':[{'message':'MCP tool call requires approval, but approval policy is never'}]},0),
])
def test_sealed_patch_does_not_override_failed_native_delivery_audit(changes,code):
    with pytest.raises(RuntimeError):
        manager.native_completion_status(completion(**changes),code)


def test_only_auditable_timeout_is_a_budget_outcome():
    assert manager.native_completion_status(completion(timed_out=True,exit_code=1),1)=='BUDGET_TIMEOUT'
    assert manager.native_completion_status(completion(),0)=='COMPLETE'


@pytest.mark.parametrize('phase',['TRAINING','EVALUATION'])
def test_prompt_prefix_is_reserved_from_handoff_cap(phase):
    from enterprise_memory.trimem.native_architecture_context import HandoffLimits
    prefix=manager.prompt_prefix(phase)
    limit=HandoffLimits(max_packet_bytes=manager.HANDOFF_PROMPT_CAP-len(prefix))
    assert len(prefix)+limit.max_packet_bytes==196608
    assert 'Manager handoff packet:' in prefix.decode()


def test_action_identity_cannot_be_supplied_by_worker(monkeypatch):
    class Broker:
        def action(self,*_):
            pytest.fail('Invalid worker request reached the broker')
    monkeypatch.setattr(manager,'open_cell',lambda path:({}, {}, Broker()))
    with pytest.raises(ValueError,match='assigned'):
        manager.command_cell('action','ignored',{'worker_id':'w','token':'t','request_id':'trusted',
            'request':{'op':'info','request_id':'model-selected'}})


@pytest.fixture
def sealed_native_cell(tmp_path,monkeypatch):
    config={'native_control_root':str(tmp_path/'native')}
    value={'phase':'TRAINING','target':{'instance_id':'fixture-1'},'arm':'PDF_MEMORY',
           'task_public':{'task_id':'fixture-1'}}
    status={'status':'SUBMITTED','workers_issued':1,'workers_admitted':1,
            'event_tail_sha256':'a'*64,'submission':{'patch_sha256':'b'*64}}
    class Broker:
        def status(self):return status
    monkeypatch.setattr(manager,'open_cell',lambda *args,**kwargs:(value,config,Broker()))
    output=tmp_path/'native/TRAINING/fixture-1/PDF_MEMORY/worker-001/output'
    output.mkdir(parents=True)
    raw=manager.canonical({'type':'thread.started','thread_id':'fresh-1'})+b'\n'
    (output/'events.jsonl').write_bytes(raw)
    manager.write_new(output/'completion.json',completion(thread_id='fresh-1',events_sha256=manager.digest(raw)))
    cell=tmp_path/'cell.json'
    return cell,output


def test_successful_execution_audit_is_stable_and_detects_later_event_change(sealed_native_cell):
    cell,output=sealed_native_cell
    first=manager.execution_audit(cell)
    assert first['passed'] and manager.execution_audit(cell)==first
    (output/'events.jsonl').write_bytes(b'changed')
    with pytest.raises(RuntimeError,match='audit differs'):
        manager.execution_audit(cell)


def test_outer_launcher_failure_rejects_clean_codex_completion(sealed_native_cell):
    cell,_=sealed_native_cell
    manager.write_new(cell.parent/'native-execution-failure.json',{'launcher_returncode':1})
    with pytest.raises(RuntimeError,match='execution audit failed'):
        manager.run_workers(cell)
    with pytest.raises(RuntimeError,match='execution audit failed'):
        manager.grade_cell(cell)


@pytest.mark.parametrize('entry',['execution_audit','run_workers','grade_cell'])
def test_sealed_manager_failure_cannot_be_resumed_or_graded(sealed_native_cell,entry):
    cell,output=sealed_native_cell
    manager.write_new(output/'manager-error-private.json',{'operation':'action'})
    with pytest.raises(RuntimeError,match='execution audit failed'):
        getattr(manager,entry)(cell)
    assert manager.read(cell.parent/'execution-audit.json')['passed'] is False
    with pytest.raises(RuntimeError,match='execution audit failed'):
        getattr(manager,entry)(cell)
    assert not (cell.parent/'public-result.json').exists()
