"""Publish metadata-only progress; never copy state/prompts/candidates/private tests."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT=next(path for path in Path(__file__).resolve().parents if (path/'configs/skhynix_v1/lcb_002_luna_pilot.json').is_file())
source=ROOT/'data/skhynix_lcb_002/pilot-001/summary.json'
value=json.loads(source.read_text(encoding='utf-8'))
target=ROOT/'artifacts/skhynix_v1/lcb_002/pilot-progress-001.json'
metadata={key:value.get(key) for key in ('schema','experiment_id','status','label','arms',
    'paired','effective_paired','private_grading_ready','manager_seconds_this_invocation',
    'hidden_feedback_to_model','test_partition_model_calls')}
metadata.update(observed_at=datetime.now(timezone.utc).isoformat(),
    summary_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    last_model_code_commit='7b5c7e5',
    final_score=value.get('status')=='COMPLETE')
if value.get('bank'):
    metadata['bank']={key:value['bank'].get(key) for key in ('sha256','layer_counts')}
metadata['task_results']=[{key:row.get(key) for key in ('task_id','arm','status','error_type',
    'outcome','resolved','passed','grade_status','capture_status','memory_injection_count',
    'memory_injections_by_kind','wall_seconds','tool_seconds','tool_actions','public_test_runs',
    'tokens','session_count','handoff_count')} for row in value.get('cells',[])]
target.write_text(json.dumps(metadata,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'path':str(target.relative_to(ROOT)),'status':metadata['status'],
    'cells':len(metadata['task_results']),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}))
