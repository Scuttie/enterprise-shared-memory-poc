import importlib.util
from pathlib import Path
import pytest


spec=importlib.util.spec_from_file_location('architecture_native',
    Path(__file__).resolve().parents[2]/'scripts/trimem_skhynix_architecture_native.py')
native=importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def message(method, params=None):
    return {'jsonrpc':'2.0','id':1,'method':method,'params':params or {}}


def test_mcp_discovery_never_calls_cell():
    def forbidden(_):
        pytest.fail('MCP discovery accessed a cell')
    for method in ('initialize','ping','tools/list','resources/list','unknown'):
        result=native.mcp_response(message(method),forbidden)
        assert result['id']==1
    assert native.mcp_response({'jsonrpc':'2.0','method':'notifications/initialized'},forbidden) is None
    tools=native.mcp_response(message('tools/list'),forbidden)['result']['tools']
    assert [t['name'] for t in tools]==['action']


@pytest.mark.parametrize('params',[
    {'name':'admit','arguments':{'request':{}}},
    {'name':'action','arguments':{'request':{},'token':'foreign'}},
    {'name':'action','arguments':{}},
])
def test_mcp_rejects_non_action_surface(params):
    calls=[]
    result=native.mcp_response(message('tools/call',params),lambda r:calls.append(r))
    assert result['error']['code']==-32602
    assert not calls


def test_mcp_preserves_request_and_public_result():
    request={'op':'tool','name':'read_file','arguments':{'path':'src/한글.py'}}
    calls=[]
    def action(value):
        calls.append(value)
        return {'ok':True,'result':{'text':'한글'},'budget':{'requests_remaining':2}}
    result=native.mcp_response(message('tools/call',{'name':'action','arguments':{'request':request}}),action)
    assert calls==[request]
    assert native.json.loads(result['result']['content'][0]['text'])['result']['text']=='한글'


def test_command_requires_model_and_chatgpt_and_new_context():
    config={'model':'gpt-6-astra','authentication':'CHATGPT','codex_binary':'codex.exe',
        'worker_cwd':'C:/worker','windows_python':'C:/python.exe','reasoning_effort':'ultra'}
    command=native.worker_command(config,Path('C:/launch.json'))
    assert command[1]=='exec' and 'resume' not in command and 'fork' not in command
    assert '--ignore-user-config' in command and '--ephemeral' in command
    assert 'forced_login_method="chatgpt"' in command
    assert 'web_search="disabled"' in command
    assert 'mcp_servers.benchmark.enabled_tools=["action"]' in command
    assert 'mcp_servers.benchmark.tools.action.approval_mode="approve"' in command
    for feature in native.DISABLED_FEATURES:
        index=command.index(feature)
        assert command[index-1]=='--disable'
    for changes in ({'model':'other'},{'authentication':'API'}):
        with pytest.raises(ValueError):
            native.worker_command(config|changes,Path('C:/launch.json'))


def test_wsl_command_uses_argv_and_fixed_runtime():
    args=['action','--cell-config','/home/trimem-runner/a file;name.json']
    result=native.wsl_python({'linux_source_root':'/home/trimem-runner/source'},'manager.py',args)
    assert result[-1]=='/home/trimem-runner/a file;name.json'
    assert result[-len(args):]==args
    assert not {'sh','bash','powershell','cmd.exe'}.intersection(result)


@pytest.mark.parametrize('item',[
    {'type':'command_execution'}, {'type':'file_change'}, {'type':'web_search'},
    {'type':'unexpected_future_tool'}, {'type':'mcp_tool_call','server':'foreign','tool':'action'},
    {'type':'mcp_tool_call','server':'benchmark','tool':'admit'},
])
def test_unknown_or_foreign_native_tool_is_a_violation(item):
    assert native.outside_broker_item(item)


def test_only_broker_action_and_passive_items_are_allowed():
    assert native.outside_broker_item({'type':'mcp_tool_call','server':'benchmark','tool':'action'}) is None
    for kind in native.PASSIVE_ITEM_TYPES:
        assert native.outside_broker_item({'type':kind}) is None


@pytest.mark.parametrize('failure',['nonzero','timeout','json'])
def test_manager_transport_failures_leave_private_receipts(tmp_path,monkeypatch,failure):
    from types import SimpleNamespace
    def run(*args,**kwargs):
        if failure=='timeout':
            raise native.subprocess.TimeoutExpired('manager',180)
        return SimpleNamespace(returncode=1 if failure=='nonzero' else 0,
            stdout=b'not-json',stderr=b'manager traceback')
    monkeypatch.setattr(native.subprocess,'run',run)
    config={'linux_source_root':'/source','linux_cell_config':'/cell', 'worker_output':str(tmp_path)}
    with pytest.raises(RuntimeError,match='Trusted benchmark manager'):
        native.manager_command(config,'action',{'secret':'not-for-model'})
    receipts=list(tmp_path.glob('manager-error-*.json'))
    assert len(receipts)==1
    assert b'not-for-model' not in receipts[0].read_bytes()
