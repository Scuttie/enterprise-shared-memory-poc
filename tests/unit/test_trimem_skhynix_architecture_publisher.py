from pathlib import Path
import json
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import trimem_skhynix_architecture_publisher as publisher


@pytest.mark.parametrize('effort',['ultra','high'])
def test_reflection_has_no_mcp_or_host_tools_and_is_fresh(tmp_path,effort):
    config={'model':'gpt-6-astra','authentication':'CHATGPT','codex_binary':'codex.exe',
        'worker_cwd':'C:/worker','windows_python':'C:/python.exe','reasoning_effort':effort}
    command=publisher.publisher_command(config,tmp_path)
    assert '--ephemeral' in command and '--ignore-user-config' in command
    assert not any('mcp_servers.' in value for value in command)
    assert 'resume' not in command and 'fork' not in command
    assert 'forced_login_method="chatgpt"' in command
    assert 'model_reasoning_effort="'+effort+'"' in command


@pytest.mark.parametrize('event',[
    {'type':'item.completed','item':{'type':'mcp_tool_call'}},
    {'type':'item.completed','item':{'type':'command_execution'}},
    {'type':'thread.started','thread_id':'second'},
    {'type':'turn.failed'},
])
def test_reflection_rejects_tools_reused_context_and_failed_turns(event):
    events=[{'type':'thread.started','thread_id':'first'},{'type':'turn.started'},
            {'type':'item.completed','item':{'type':'agent_message','text':'{}'}},
            {'type':'turn.completed'},event]
    with pytest.raises(ValueError):
        publisher.validate_events(events)


@pytest.fixture
def launch_case(tmp_path,monkeypatch):
    export={'schema':'skhynix/native-architecture-public-reflection/2.0','sources':[]}
    reflection=tmp_path/'reflection.json'
    publisher.write_new(reflection,export)
    config={'model':'gpt-6-astra','authentication':'CHATGPT','codex_binary':'codex.exe',
        'worker_cwd':str(tmp_path/'cwd'),'worker_output':str(tmp_path/'output'),
        'windows_python':'python.exe','reasoning_effort':'ultra',
        'reflection_reference':{'path':str(reflection),'sha256':publisher.digest(reflection.read_bytes())}}
    config_path=tmp_path/'config.json'
    state={'calls':0,'response_changes':{},'file_changes':{},'events_change':lambda events:events}
    def popen(command,**kwargs):
        state['calls']+=1
        assert 'OPENAI_API_KEY' not in kwargs['env'] and 'CODEX_API_KEY' not in kwargs['env']
        class Process:
            returncode=0
            def communicate(self,prompt,timeout):
                proposal={'schema':'skhynix/native-architecture-reflection-proposals/1.0',
                    'reflection_sha256':config['reflection_reference']['sha256'],'proposals':[]}
                response=proposal|state['response_changes']
                response_text=publisher.canonical(response).decode()
                state['response_text']=response_text
                events=[{'type':'thread.started','thread_id':'actual-fresh-thread'},
                    {'type':'turn.started'},
                    {'type':'item.completed','item':{'type':'agent_message','text':response_text}},
                    {'type':'turn.completed','usage':{'input_tokens':100,'output_tokens':20}}]
                for event in state['events_change'](events):
                    kwargs['stdout'].write(publisher.canonical(event)+b'\n')
                publisher.write_new(Path(command[command.index('-o')+1]),proposal|state['file_changes'])
        return Process()
    monkeypatch.setattr(publisher.subprocess,'Popen',popen)
    def invoke():
        publisher.write_new(config_path,config)
        return publisher.publish(config_path)
    return state,config,reflection,invoke,tmp_path


@pytest.mark.parametrize('effort',['ultra','high'])
def test_native_response_launch_and_public_input_are_bound(launch_case,effort):
    state,config,_,invoke,root=launch_case
    config['reasoning_effort']=effort
    receipt=invoke()
    assert receipt['thread_id']=='actual-fresh-thread'
    assert receipt['response_text_sha256']==publisher.digest(state['response_text'].encode())
    assert receipt['proposal_reference']['sha256']==publisher.digest((root/'output/proposals.json').read_bytes())
    assert receipt['gate_b_promotions']==0 and receipt['validation_required'] is True
    assert state['calls']==1
    assert publisher.read(root/'output/launch.json')['reasoning_effort']==effort


def test_changed_proposal_file_cannot_borrow_a_real_native_thread(launch_case):
    state,_,_,invoke,_=launch_case
    state['file_changes']={'proposals':[{'different':'not the native output'}]}
    with pytest.raises(ValueError,match='differs from the actual'):
        invoke()


@pytest.mark.parametrize('failure',['hash','reflection_sha','cap','private','effort'])
def test_invalid_public_input_or_configuration_is_rejected(launch_case,failure):
    state,config,reflection,invoke,_=launch_case
    if failure=='hash':config['reflection_reference']['sha256']='0'*64
    elif failure=='reflection_sha':
        state['response_changes']=state['file_changes']={'reflection_sha256':'0'*64}
    elif failure=='effort':config['reasoning_effort']='medium'
    else:
        value=publisher.read(reflection)
        value.update({'hidden_grader':{'test_patch':'private'}} if failure=='private' else {'large':'x'*publisher.CAP})
        reflection.write_bytes(publisher.canonical(value))
        config['reflection_reference']['sha256']=publisher.digest(reflection.read_bytes())
    with pytest.raises(ValueError):invoke()
    assert state['calls']==int(failure=='reflection_sha')


@pytest.mark.parametrize('change',[
    lambda events:events+[events[-1]],
    lambda events:[event for event in events if event.get('type')!='turn.started'],
    lambda events:[event for event in events if event.get('type')!='item.completed'],
    lambda events:events[:2]+[{'type':'item.completed','item':{'type':'error','message':'failure'}}]+events[2:],
])
def test_bad_turn_sequence_or_error_never_receives_completion(launch_case,change):
    state,_,_,invoke,root=launch_case
    state['events_change']=change
    with pytest.raises(ValueError):invoke()
    assert not (root/'output/completion.json').exists()
