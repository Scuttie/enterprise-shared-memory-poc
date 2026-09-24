"""Opaque native eligibility for the already frozen DevEval 002 enrollment.

Portable copy of the retained native eligibility helper; reserve is checked on
the actual output filesystem. Historical helper bytes stay unchanged.
Runtime-only helper, no models. Use a fresh run directory on every attempt.
All source/task/test payloads stay in the ignored private root; stdout is counts.
"""
from pathlib import Path, PurePosixPath
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY/"scripts"))
import deveval_prepare as assets


def checked(reference):
    path = REPOSITORY/reference["path"]
    if not path.is_file() or assets.file_sha(path) != reference["sha256"] or path.stat().st_size != reference["bytes"]:
        raise ValueError("BOUND_REFERENCE_CHANGED")
    return path


def prepare(plan_path, output):
    plan = json.loads(plan_path.read_bytes())
    if plan["schema"] != "deveval/repository-plan/1":
        raise ValueError("INVALID_PLAN")
    checked(plan["planner_reference"]); checked(plan["asset_helper_reference"])
    metadata = checked(plan["metadata_reference"])
    archive_path = checked(plan["source_archive_reference"])
    projects = {p["project"] for p in plan["projects"]}
    if output.exists():
        raise ValueError("ELIGIBILITY_ROOT_MUST_BE_FRESH")
    output.mkdir(parents=True)
    (output/"pristine").mkdir()
    files, total, excluded_artifacts = [], 0, []
    prefixes = tuple("Source_Code/"+p+"/" for p in projects)
    with tarfile.open(archive_path, "r:gz") as archive:
        for item in archive:
            if not item.name.startswith(prefixes):
                continue
            # Archive contains a packager's stale file:/tmp/... test artifact,
            # including an absolute symlink. Never recreate that external link.
            if "file:" in item.name.split("/"):
                excluded_artifacts.append({"path":item.name,"kind":item.type.decode("ascii"),
                    "link_target_sha256":assets.hashlib.sha256(item.linkname.encode()).hexdigest() if item.linkname else None,
                    "reason":"PACKAGER_STALE_FILE_URI_ARTIFACT_NOT_EXTRACTED"})
                continue
            # POSIX permits colons in ordinary fixture filenames. Reject actual
            # traversal/absolute paths and links, rather than Windows naming.
            relative = PurePosixPath(item.name)
            if relative.is_absolute() or ".." in relative.parts or "\\" in item.name or "\x00" in item.name:
                raise ValueError("UNSAFE_ARCHIVE_PATH")
            target = output/"pristine"/Path(*relative.parts)
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not item.isfile():
                raise ValueError("ARCHIVE_LINK_OR_SPECIAL_FILE")
            total += item.size
            if total > 2*1024**3 or shutil.disk_usage(output).free < assets.MIN_FREE_BYTES+item.size:
                raise ValueError("DISK_RESERVE")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                shutil.copyfileobj(archive.extractfile(item), stream)
            target.chmod(item.mode & 0o777)
            files.append({"path": item.name, "sha256": assets.file_sha(target), "bytes": item.size})
    shutil.copytree(output/"pristine/Source_Code", output/"Source_Code")
    rows = {r["namespace"]:r for r in (json.loads(line) for line in metadata.read_bytes().splitlines())}
    tasks = []
    for task in plan["tasks"]:
        row = rows[task["task_id"]]
        if assets.hashlib.sha256(assets.canonical(row)).hexdigest() != task["metadata_row_sha256"]:
            raise ValueError("SELECTED_METADATA_CHANGED")
        tasks.append((task,row))
    receipt = {"schema":"deveval/native-eligibility-inputs/1", "plan_reference":assets.reference(plan_path),
        "source_archive_reference":plan["source_archive_reference"], "metadata_reference":plan["metadata_reference"],
        "files":files,"file_count":len(files),"file_bytes":total,"selected_task_count":len(tasks),
        "excluded_archive_artifacts":excluded_artifacts}
    assets.write_new(output/"inputs.json",receipt)
    print(json.dumps({"stage":"prepared","projects":sorted(projects),"files":len(files),"bytes":total,"tasks":len(tasks)}),flush=True)
    return plan,tasks,files


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan",type=Path,required=True)
    parser.add_argument("--private-root",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True)
    parser.add_argument("--prepare-only",action="store_true")
    parser.add_argument("--execute-prepared",action="store_true")
    args=parser.parse_args()
    if sys.version_info[:3]!=(3,9,18) or os.name!="posix": raise ValueError("PYTHON_OR_PLATFORM_CHANGED")
    plan_path,output=args.plan.resolve(),args.private_root.resolve()
    if args.execute_prepared:
        inputs=json.loads((output/"inputs.json").read_bytes())
        if assets.reference(plan_path)!=inputs["plan_reference"]:raise ValueError("PLAN_CHANGED")
        plan=json.loads(plan_path.read_bytes()); checked(plan["planner_reference"]);checked(plan["asset_helper_reference"])
        rows={r["namespace"]:r for r in (json.loads(line) for line in checked(plan["metadata_reference"]).read_bytes().splitlines())}
        tasks=[(t,rows[t["task_id"]]) for t in plan["tasks"]];files=inputs["files"]
        for item in files:
            if assets.file_sha(output/"pristine"/item["path"])!=item["sha256"] or assets.file_sha(output/item["path"])!=item["sha256"]:
                raise ValueError("PREPARED_SOURCE_CHANGED")
        if (output/"execution-started.json").exists(): raise ValueError("EXECUTION_ALREADY_STARTED")
    else:
        plan,tasks,files=prepare(plan_path,output)
    if args.prepare_only:return
    assets.write_new(output/"execution-started.json",{"plan_reference":assets.reference(plan_path),"helper_reference":assets.reference(__file__),"model_calls":0})
    env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env["PATH"]=str(Path(sys.executable).parent)+os.pathsep+env.get("PATH","")
    env["NLTK_DATA"]=str(output/"nltk_data")
    receipts=[]
    evaluator=REPOSITORY/"data/deveval_001/upstream/pass_k.py"
    for index,(task,row) in enumerate(tasks,1):
        for arm in ("reference","assertion_negative"):
            cell=output/("%02d-%s"%(index,arm));cell.mkdir()
            request={"evaluator":str(evaluator),"task":row,"arm":arm,"source_root":str(output/"Source_Code"),"junit":str(cell/"junit.xml"),"receipt":str(cell/"receipt.json")}
            assets.write_new(cell/"request.json",request)
            cell_env=dict(env,PYTEST_ADDOPTS="--junitxml="+str(cell/"junit.xml"))
            started=time.monotonic()
            with (cell/"stdout.log").open("xb") as stdout,(cell/"stderr.log").open("xb") as stderr:
                process=subprocess.Popen([sys.executable,"-B",str(Path(assets.__file__)),"--worker-request",str(cell/"request.json")],cwd=cell,env=cell_env,stdout=stdout,stderr=stderr,start_new_session=True)
                try:returncode=process.wait(timeout=85)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait();returncode=-9
            if (cell/"receipt.json").is_file():
                result=json.loads((cell/"receipt.json").read_bytes());result["receipt_reference"]=assets.reference(cell/"receipt.json")
            else:result={"task_id":task["task_id"],"project":task["project"],"arm":arm,"official_result":"InfrastructureException","source_restored":False}
            result.update(phase=task["phase"],worker_returncode=returncode,worker_wall_seconds=time.monotonic()-started,
                          stdout_reference=assets.reference(cell/"stdout.log"),stderr_reference=assets.reference(cell/"stderr.log"))
            receipts.append(result)
            print(json.dumps({"stage":"eligibility","ordinal":index,"phase":task["phase"],"arm":arm,"official_result":result["official_result"],"source_restored":result["source_restored"]}),flush=True)
            if not result["source_restored"]:raise ValueError("SOURCE_RESTORE_FAILED_STOPPED")
    original_changes,working_changes,generated_changes=[],[],[]
    for item in files:
        if assets.file_sha(output/"pristine"/item["path"])!=item["sha256"]: original_changes.append(item["path"])
        if assets.file_sha(output/item["path"])!=item["sha256"]:
            (generated_changes if assets.is_generated_build_metadata(item["path"]) else working_changes).append(item["path"])
    positive=[r for r in receipts if r["arm"]=="reference"]
    negative=[r for r in receipts if r["arm"]=="assertion_negative"]
    passed=sum(r["official_result"]=="Pass" for r in positive)
    detected=sum(r["official_result"]=="Error" and r.get("junit",{}).get("negative_marker_seen") is True and r["junit"]["unconfirmed_error_nodes"]==0 for r in negative)
    packages=subprocess.run([sys.executable,"-m","pip","freeze","--all"],capture_output=True,check=True).stdout
    (output/"runtime-pip-freeze.txt").write_bytes(packages)
    report={"schema":"deveval/native-eligibility/1","status":"PASS" if passed==detected==len(tasks) and not original_changes and not working_changes else "BLOCKED_NO_TASK_SUBSTITUTION",
        "plan_reference":assets.reference(plan_path),"helper_reference":assets.reference(__file__),"asset_helper_reference":assets.reference(assets.__file__),
        "inputs_reference":assets.reference(output/"inputs.json"),"execution_started_reference":assets.reference(output/"execution-started.json"),
        "runtime_lock_reference":assets.reference(output/"runtime-pip-freeze.txt"),"selected_tasks":len(tasks),"reference_pass":passed,"negative_confirmed":detected,
        "pristine_unchanged":not original_changes,"working_source_tests_unchanged":not working_changes,"working_generated_metadata_changes":generated_changes,
        "model_calls":0,"docker_calls":0,"private_grades_of_model_outputs":0,"cells":receipts,
        "excluded_archive_artifacts":json.loads((output/"inputs.json").read_bytes()).get("excluded_archive_artifacts",[]),
        "limitations":["Environment eligibility only; no model accuracy or dependency utilization claim.","Official Error requires exact deliberate assertion corroboration to count as a negative control.","Frozen tasks are never replaced after environment outcomes.","The archive's stale file:/tmp/... test artifact subtree is omitted; its absolute external symlink is never followed or recreated."]}
    assets.write_new(output/"eligibility.json",report);assets.write_new(args.report,report)
    print(json.dumps({k:report[k] for k in ("status","selected_tasks","reference_pass","negative_confirmed","pristine_unchanged","working_source_tests_unchanged")}),flush=True)


if __name__=="__main__":
    try:main()
    except Exception as error:
        code=str(error) if re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}",str(error)) else "DETAIL_WITHHELD"
        print(json.dumps({"status":"ERROR","exception_type":type(error).__name__,"code":code}),flush=True)
        raise SystemExit(1)
