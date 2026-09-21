"""Read account limits from the experiment's Codex binary without starting a turn."""
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import queue
import subprocess
import threading
import time

repo = Path('C:/Users/jewon/esm-r23-d115-writer')
binary = Path('C:/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-codex-v1/codex.exe')
env = {k:v for k,v in os.environ.items() if k not in ('OPENAI_API_KEY','OPENAI_BASE_URL','OPENAI_ORG_ID')}
proc = subprocess.Popen([str(binary),'app-server','--stdio','-c','forced_login_method="chatgpt"'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    text=True, encoding='utf-8', cwd=repo, env=env,
    creationflags=subprocess.CREATE_NO_WINDOW)
messages = queue.Queue()
def reader():
    for line in proc.stdout:
        try:
            messages.put(json.loads(line))
        except json.JSONDecodeError:
            pass
threading.Thread(target=reader,daemon=True).start()
def send(value):
    proc.stdin.write(json.dumps(value)+'\n'); proc.stdin.flush()
def request(identity,method,params=None):
    value={'id':identity,'method':method}
    if params is not None:value['params']=params
    send(value)
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        msg=messages.get(timeout=max(.1,deadline-time.monotonic()))
        if msg.get('id')==identity:
            if 'error' in msg:raise RuntimeError(str(msg['error'])[:400])
            return msg['result']
    raise TimeoutError(method)
try:
    request(1,'initialize',{'clientInfo':{'name':'skhynix_credit_diagnostic','version':'1.0'}})
    send({'method':'initialized','params':{}})
    account=request(2,'account/read',{'refreshToken':False}).get('account') or {}
    rates=request(3,'account/rateLimits/read')
    rates={key:value for key,value in rates.items() if key not in ('accountId','email','accountEmail')}
    # Account identifiers, email addresses and tokens are deliberately not persisted.
    value={'schema':'skhynix/read-only-codex-credit-check/1.0',
        'checked_at_utc':datetime.now(timezone.utc).isoformat(),
        'binary':str(binary),'authentication_type':account.get('type'),
        'plan_type':account.get('planType'),'limits':rates,
        'model_turns_started':0,'credit_resets_consumed':0,'purchases':0}
    out=repo/'artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/evaluation-continuation-001'/('codex-credit-check-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
    with out.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(json.dumps({'artifact':str(out),**value},ensure_ascii=False))
finally:
    proc.terminate()
    try:proc.wait(timeout=5)
    except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
