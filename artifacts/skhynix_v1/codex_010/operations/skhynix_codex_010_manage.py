"""Native010 operations helper. Importing it never starts WSL or an experiment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

CENTRAL = "/home/trimem-runner/skhynix-codex-010"
PYTHON = "/opt/trimem-rehearsals/e932-preflight/venv/bin/python"
PUBLIC_PYTHON = "/opt/miniconda3/envs/testbed/bin/python"
HEAD = "d4fd304339687b42c645ae84872a72eddddcda97"
DEFAULT_NAME = "recovery-20428-r1"


def run_identity(name: str) -> tuple[str, int]:
    match = re.fullmatch(r"recovery-(20428|20438)-r([12])", name)
    if match is None:
        raise ValueError("Expected recovery-20428-r1/r2 or recovery-20438-r1/r2")
    return match.group(1), int(match.group(2))


def remote_code(args: argparse.Namespace) -> str:
    number, repetition = run_identity(args.name)
    base = CENTRAL + "/" + args.name
    code = "from pathlib import Path, PurePosixPath\nimport hashlib,json,subprocess,os,sys,re\n"
    code += "central=Path(" + repr(CENTRAL) + ")\nbase=Path(" + repr(base) + ")\n"
    code += "HEAD=" + repr(HEAD) + "\n"
    if args.command == "python":
        if not args.code_file:
            raise ValueError("python requires --code-file")
        return code + Path(args.code_file).read_text(encoding="utf-8-sig")
    if args.command in ("snapshot", "prepare", "grade"):
        code += r"""
def sha(raw):return hashlib.sha256(raw).hexdigest()
def safe_relative(relative):
 if not isinstance(relative,str) or not relative or '\\' in relative:
  raise ValueError('NONCANONICAL_FREEZE_PATH')
 path=PurePosixPath(relative)
 if path.is_absolute() or path.as_posix()!=relative or any(part in ('','.','..','.git') for part in path.parts):
  raise ValueError('NONCANONICAL_FREEZE_PATH')
 if not ((path.parts[0] in ('src','scripts') and path.suffix=='.py') or
   (path.parts[:2]==('configs','skhynix_v1') and len(path.parts)==3 and path.name.endswith('manifest.json'))):
  raise ValueError('UNEXPECTED_FREEZE_PATH_SCOPE')
 return relative

def checked_file(root,relative):
 relative=safe_relative(relative);path=root/relative
 if root.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
  raise ValueError('FROZEN_INPUT_ABSENT_OR_OUTSIDE_ROOT')
 current=path
 while current!=root:
  if current.is_symlink():raise ValueError('LINKED_FROZEN_INPUT')
  current=current.parent
 return path

freeze_raw=(central/'source-freeze.json').read_bytes();freeze=json.loads(freeze_raw)
launch=json.loads((central/'launch-contract.json').read_text());freeze_sha=sha(freeze_raw)
if freeze.get('schema')!='skhynix/native010-source-freeze/1.0' or freeze_sha!=launch['source_freeze_sha256']:
 raise ValueError('SOURCE_FREEZE_BINDING_DIFFERS')
if freeze.get('head',HEAD)!=HEAD:raise ValueError('SOURCE_BASE_HEAD_DIFFERS')
expected=freeze.get('sha256')
if not isinstance(expected,dict) or not expected:raise ValueError('EMPTY_OR_INVALID_SOURCE_FREEZE')
for relative,digest in expected.items():
 safe_relative(relative)
 if not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest):raise ValueError('INVALID_FREEZE_SHA256')
source=base/'source'
if central.is_symlink() or central.resolve()!=central or base.resolve()!=base or not base.is_relative_to(central):
 raise ValueError('EXPERIMENT_OUTPUT_PATH_DIFFERS')
"""
    if args.command == "snapshot":
        code += r"""
if any(path.exists() or path.is_symlink() for path in (source,base/'execution/plan.json',base/'source-snapshot.json')):
 raise ValueError('REFUSE_EXISTING_SOURCE_PLAN_OR_SNAPSHOT')
win=Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
if (central/'supplemental-manifest.json').read_bytes()!=(win/'configs/skhynix_v1/codex_005_manifest.json').read_bytes():
 raise ValueError('NATIVE010_REQUIRES_BYTE_IDENTICAL_NATIVE005_MANIFEST')
for relative,digest in expected.items():
 if sha(checked_file(win,relative).read_bytes())!=digest:raise ValueError('LIVE_INPUT_DIFFERS_FROM_FREEZE')
base.mkdir(parents=True,exist_ok=True)
subprocess.run(['git','clone','--quiet','--no-hardlinks','--no-checkout','/home/trimem-runner/skhynix-codex-001/source',str(source)],check=True)
subprocess.run(['git','-C',str(source),'checkout','--quiet','--detach',HEAD],check=True)
if source.is_symlink() or source.resolve()!=source:raise ValueError('SOURCE_OUTPUT_PATH_DIFFERS')
hashes={}
for relative,digest in sorted(expected.items()):
 raw=checked_file(win,relative).read_bytes()
 if sha(raw)!=digest:raise ValueError('LIVE_INPUT_CHANGED_DURING_COPY')
 out=source/relative
 if not out.resolve().is_relative_to(source):raise ValueError('COPY_OUTPUT_ESCAPES_SOURCE')
 out.parent.mkdir(parents=True,exist_ok=True)
 current=out
 while current!=source:
  if current.is_symlink():raise ValueError('LINKED_COPY_OUTPUT')
  current=current.parent
 out.write_bytes(raw);hashes[relative]=sha(checked_file(source,relative).read_bytes())
 if hashes[relative]!=digest:raise ValueError('COPIED_INPUT_HASH_DIFFERS')
if hashes!=expected:raise ValueError('COPIED_FILE_MAP_DIFFERS_FROM_EXACT_FREEZE')
if (central/'source-freeze.json').read_bytes()!=freeze_raw:raise ValueError('SOURCE_FREEZE_CHANGED_DURING_COPY')
receipt={'schema':'skhynix/native010-operational-source-snapshot/1.0','source':str(source),
 'copied_from':str(win),'source_freeze_sha256':freeze_sha,'copied_file_sha256':hashes}
with (base/'source-snapshot.json').open('x') as stream:
 json.dump(receipt,stream,sort_keys=True,indent=2);stream.write('\n')
print(json.dumps({'status':'SOURCE_COPIED','copied_files':len(hashes),'source':str(source),'source_freeze_sha256':freeze_sha}))
"""
    elif args.command in ("prepare", "grade"):
        code += r"""
snapshot=json.loads((base/'source-snapshot.json').read_text())
if (snapshot.get('schema')!='skhynix/native010-operational-source-snapshot/1.0' or
 snapshot.get('source')!=str(source) or snapshot.get('source_freeze_sha256')!=freeze_sha or
 snapshot.get('copied_file_sha256')!=expected):raise ValueError('SOURCE_SNAPSHOT_DIFFERS_FROM_EXACT_FREEZE')
for relative,digest in expected.items():
 if sha(checked_file(source,relative).read_bytes())!=digest:raise ValueError('FROZEN_SOURCE_CHANGED')
"""
        command = [PYTHON, base + "/source/scripts/trimem_skhynix_codex.py", args.command,
                   "--run-root", base + "/execution"]
        if args.command == "prepare":
            code += "if (base/'execution/plan.json').exists():raise ValueError('REFUSE_EXISTING_PLAN')\n"
            code += "if not (central/'diagnostic-bank.json').is_file():raise ValueError('FROZEN_DIAGNOSTIC_BANK_REQUIRED')\n"
            command += ["--workspace-root", base + "/workspaces", "--dataset-cache-root",
                        "/opt/trimem-rehearsals/e932-preflight/datasets", "--harness-root",
                        "/opt/trimem-rehearsals/e932-preflight/harnesses", "--public-python", PUBLIC_PYTHON,
                        "--target-id", "swebench_verified--sympy__sympy-" + number,
                        "--experiment-id", "skhynix-native-codex-010-" + args.name,
                        "--solver-user-id", "native-codex-010-" + args.name,
                        "--supplemental-manifest", CENTRAL + "/supplemental-manifest.json",
                        "--frozen-memory-bank", CENTRAL + "/diagnostic-bank.json"]
            code += "result=subprocess.run(" + repr(command) + ",cwd=source);raise SystemExit(result.returncode)\n"
        else:
            if args.cell not in ("A", "C"):
                raise ValueError("Native010 permits official grading only for A and C; B is unused")
            command += ["--cell", args.cell]
            code += "result=subprocess.run(" + repr(command) + ",cwd=source,capture_output=True)\n"
            code += r"""
if result.returncode:
 print(json.dumps({'status':'GRADE_COMMAND_FAILED','returncode':result.returncode,
  'stdout_sha256':sha(result.stdout),'stderr_sha256':sha(result.stderr),
  'private_output_omitted':True}));raise SystemExit(result.returncode)
try:summary=json.loads(result.stdout.decode().splitlines()[-1])
except (ValueError,UnicodeError,IndexError):
 print(json.dumps({'status':'GRADE_PUBLIC_SUMMARY_PARSE_FAILED','stdout_sha256':sha(result.stdout),
  'stderr_sha256':sha(result.stderr),'private_output_omitted':True}));raise SystemExit(1)
allowed=('target_id','cell','resolved','official','actions','agent_completed','memory_injections',
 'memory_bytes','tool_errors','patch_sha256','wall_seconds','separate_model_api_calls','codex_tokens_and_cost')
print(json.dumps({key:summary[key] for key in allowed if key in summary}))
"""
    elif args.command == "status":
        code += r"""
for cell in ('A','B','C'):
 root=base/'execution/cells'/cell
 if not (root/'state.json').is_file():continue
 state=json.loads((root/'state.json').read_text())
 row={'cell':cell,'intended_solver_cell':cell in ('A','C')}
 for key in ('status','actions','started_at','submitted_at','memory_injections','memory_bytes'):
  if key in state:row[key]=state[key]
 if (root/'public-result.json').is_file():
  result=json.loads((root/'public-result.json').read_text())
  for key in ('resolved','official','agent_completed','patch_sha256'):
   if key in result:row[key]=result[key]
 print(json.dumps(row))
"""
    else:
        raise ValueError("Unknown native010 operation")
    return code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("python", "snapshot", "prepare", "grade", "status"))
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--cell", choices=("A", "C"), default="A")
    parser.add_argument("--code-file")
    args = parser.parse_args()
    try:
        code = remote_code(args)
    except ValueError as exc:
        parser.error(str(exc))
    command = ["wsl.exe", "-d", "TriMemRunner2404", "--user", "trimem-runner", "--exec", "env",
               "LD_LIBRARY_PATH=/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib",
               "HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1", "PYTHONDONTWRITEBYTECODE=1", PYTHON, "-"]
    result = subprocess.run(command, input=code.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    sys.stdout.buffer.write(result.stdout)
    if result.returncode:
        if args.command == "grade":
            import hashlib
            print(json.dumps({"status":"GRADE_WRAPPER_FAILED","returncode":result.returncode,
                "stderr_sha256":hashlib.sha256(result.stderr).hexdigest(),"private_output_omitted":True}))
        else:
            sys.stderr.buffer.write(result.stderr[-8000:])
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
