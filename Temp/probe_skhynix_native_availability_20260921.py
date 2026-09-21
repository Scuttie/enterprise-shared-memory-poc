"""One tiny isolated native availability check, outside benchmark attempts."""
from pathlib import Path
from datetime import datetime,timezone
import json,os,subprocess,time

repo=Path('C:/Users/jewon/esm-r23-d115-writer')
binary=Path('C:/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-codex-v1/codex.exe')
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
root=repo/'artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/evaluation-continuation-001'/('availability-'+stamp)
root.mkdir(exist_ok=False)
cwd=Path('C:/Users/jewon/AppData/Local/Temp')/('skhynix-availability-'+stamp)
cwd.mkdir(exist_ok=False)
args=[str(binary),'exec','--ignore-user-config','--ephemeral','--json','--skip-git-repo-check',
      '--sandbox','read-only','-C',str(cwd),'-m','gpt-6-astra','-c','forced_login_method="chatgpt"',
      '-c','model_reasoning_effort="high"','-c','web_search="disabled"','--enable','skip_host_skill_discovery']
for feature in ('shell_tool','unified_exec','multi_agent','apps','plugins','browser_use',
                'browser_use_external','computer_use','image_generation','view_image','hooks','memories','goals','shell_snapshot'):
    args.extend(['--disable',feature])
args.append('-')
env={k:v for k,v in os.environ.items() if k not in ('OPENAI_API_KEY','CODEX_API_KEY')}
start=time.time()
with (root/'events.jsonl').open('xb') as stdout,(root/'stderr.log').open('xb') as stderr:
    proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,env=env,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    timed_out=False
    try:proc.communicate(b'Reply with exactly OK. Do not use tools or access files.',timeout=45)
    except subprocess.TimeoutExpired:timed_out=True;proc.kill();proc.wait(timeout=5)
errors=[];usage=None;final=None
for line in (root/'events.jsonl').read_text(encoding='utf-8').splitlines():
    event=json.loads(line)
    if event.get('type') in ('error','turn.failed'):
        errors.append(event.get('message') or (event.get('error') or {}).get('message'))
    if event.get('type')=='turn.completed':usage=event.get('usage')
    item=event.get('item') or {}
    if item.get('type')=='agent_message':final=item.get('text')
value={'schema':'skhynix/native-availability-probe/1.0','checked_at_utc':datetime.now(timezone.utc).isoformat(),
       'requested_model':'gpt-6-astra','reasoning_effort':'high','authentication':'CHATGPT_FORCED',
       'exit_code':proc.returncode,'timed_out':timed_out,'elapsed_seconds':time.time()-start,
       'service_errors':errors,'usage':usage,'received_expected_reply':final is not None and final.strip()=='OK',
       'benchmark_attempts_started':0,'grader_runs':0,'model_availability_probes':1,'purchases':0}
with (root/'receipt.json').open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
print(json.dumps({'artifact':str(root/'receipt.json'),**value},ensure_ascii=False))
