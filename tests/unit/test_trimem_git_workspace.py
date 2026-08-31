import json
from pathlib import Path
import subprocess

import pytest

from enterprise_memory.trimem.git_workspace import (
    DockerSandboxCommandRunner,
    GitCheckoutWorkspace,
    GitCheckoutWorkspaceFactory,
)
from enterprise_memory.trimem.accounting import RawEvidenceLedger
from enterprise_memory.trimem.agent_runtime import (
    CodingTask,
    InjectedCrash,
    NoMemoryController,
    TriMemAgentRuntime,
)
from enterprise_memory.trimem.checkpoint import CheckpointMismatch, FileCheckpointStore
from enterprise_memory.trimem.gateway import (
    GatewayInvocationFailure,
    GatewayResponse,
    ReplayModelGateway,
)
from enterprise_memory.trimem.grader import GradeResult
from enterprise_memory.trimem.runtime_lock import RuntimeLock
from enterprise_memory.trimem.workspace import PublicCommandResult, ToolExecutionError


class FakeCommandRunner:
    content_hash = "c" * 64

    def run(self, root, argv, *, cwd, timeout_seconds):
        return PublicCommandResult(
            exit_code=0,
            stdout="cwd=%s argv=%s" % (cwd or ".", " ".join(argv)),
        )


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    _git(root, "config", "user.email", "trimem@example.invalid")
    _git(root, "config", "user.name", "TriMem Fixture")
    _git(root, "config", "core.autocrlf", "false")
    (root / "src").mkdir()
    (root / "src" / "value.py").write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
    (root / ".github").mkdir()
    (root / ".github" / "policy.txt").write_text("safe\n", encoding="utf-8", newline="\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "fixture")
    return root, _git(root, "rev-parse", "HEAD")


def test_git_workspace_edits_tracked_and_new_files_and_restores_patch(tmp_path):
    root, commit = _repository(tmp_path)
    workspace = GitCheckoutWorkspace(root, base_commit=commit)
    assert ".github/policy.txt" in workspace.execute("list_files", {})["files"]
    assert workspace.execute("read_file", {"path": "src/value.py"})["content"] == "VALUE = 1\n"
    workspace.execute("write_file", {"path": "src/value.py", "content": "VALUE = 2\n"})
    workspace.execute("write_file", {"path": "src/new.py", "content": "NEW = True\n"})
    patch = workspace.patch()
    assert "VALUE = 2" in patch and "src/new.py" in patch
    state = workspace.checkpoint_state()

    clone = tmp_path / "clone"
    subprocess.run(["git", "-c", "core.autocrlf=false", "clone", "-q", str(root), str(clone)], check=True)
    _git(clone, "config", "core.autocrlf", "false")
    restored = GitCheckoutWorkspace(clone, base_commit=commit)
    restored.restore_checkpoint(state)
    assert restored.patch() == patch
    assert restored.grader_context(base_commit=commit).checkout_root == str(clone.resolve())


def test_git_workspace_refuses_path_escape_base_drift_and_unhashed_public_runner(tmp_path):
    root, commit = _repository(tmp_path)
    workspace = GitCheckoutWorkspace(root, base_commit=commit)
    with pytest.raises(ToolExecutionError, match="traversal"):
        workspace.execute("read_file", {"path": "../outside"})
    with pytest.raises(ToolExecutionError, match="HEAD"):
        GitCheckoutWorkspace(root, base_commit="0" * 40)
    with pytest.raises(ValueError, match="content hash"):
        GitCheckoutWorkspaceFactory(
            {"task": root}, {"task": commit}, public_tests={"task": lambda _: None}
        )


def test_git_workspace_factory_identity_excludes_machine_specific_checkout_path(tmp_path):
    root, commit = _repository(tmp_path)
    clone = tmp_path / "second"
    subprocess.run(["git", "-c", "core.autocrlf=false", "clone", "-q", str(root), str(clone)], check=True)
    left = GitCheckoutWorkspaceFactory(
        {"task": root}, {"task": commit}, command_runners={"task": FakeCommandRunner()}
    )
    right = GitCheckoutWorkspaceFactory(
        {"task": clone}, {"task": commit}, command_runners={"task": FakeCommandRunner()}
    )
    assert left.production_capable is True
    assert left.content_hash == right.content_hash


def test_git_workspace_chunk_read_and_locked_command_runner(tmp_path):
    root, commit = _repository(tmp_path)
    (root / "src" / "large.py").write_text(
        "".join("LINE_%04d\n" % value for value in range(1000)),
        encoding="utf-8",
        newline="\n",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "large")
    commit = _git(root, "rev-parse", "HEAD")
    workspace = GitCheckoutWorkspace(root, base_commit=commit, command_runner=FakeCommandRunner())
    window = workspace.execute(
        "read_file", {"path": "src/large.py", "start_line": 401, "max_lines": 5}
    )
    assert window["content"].startswith("LINE_0400\n")
    assert window["end_line"] == 405 and window["total_lines"] == 1000
    result = workspace.execute(
        "run_command", {"argv": ["python", "-m", "pytest"], "cwd": ".", "timeout_seconds": 30}
    )
    assert result["exit_code"] == 0
    assert result["argv"] == ["python", "-m", "pytest"]


def test_digest_pinned_docker_runner_lock_is_fail_closed():
    with pytest.raises(ValueError, match="sha256"):
        DockerSandboxCommandRunner("example/task:latest")
    left = DockerSandboxCommandRunner("example/task@sha256:" + "a" * 64)
    right = DockerSandboxCommandRunner("example/task@sha256:" + "a" * 64)
    assert left.content_hash == right.content_hash


def test_common_runtime_uses_injected_git_workspace_and_checkout_grader_context(tmp_path):
    root, commit = _repository(tmp_path)
    task = CodingTask(
        task_id="git-task",
        org_id="org",
        user_id="alice",
        repository="example/repo",
        commit=commit,
        instruction="Set VALUE to two.",
        files={},
        editable_paths=(),
    )

    def reply(request):
        if request.call_kind == "decompose":
            return json.dumps({"subtasks": [{
                "id": "replace-value",
                "objective": "replace the obsolete value literal",
                "predicted_operation": "replace integer literal",
                "depends_on": [],
                "files": ["src/value.py"],
            }]})
        if request.call_kind == "extract":
            return json.dumps({
                "episode": {"summary": "updated", "action": "replace", "outcome": "passed"},
                "semantic_candidate": {
                    "preconditions": "literal is obsolete", "operation": "replace literal",
                    "invariant": "integer type", "non_applicability": "dynamic value",
                    "verification": "checkout grader",
                    "applicability_scope": "EXACT_REPOSITORY",
                },
            })
        if request.step_no == 1:
            return json.dumps({"tool": "write_file", "arguments": {
                "path": "src/value.py", "content": "VALUE = 2\n",
            }})
        return json.dumps({"tool": "complete_subtask", "arguments": {"evidence": "edit applied"}})

    class CheckoutGrader:
        def grade(self, request):
            checkout = Path(request.workspace.checkout_root)
            resolved = (checkout / "src/value.py").read_text(encoding="utf-8") == "VALUE = 2\n"
            return GradeResult(
                task_id=request.task_id, resolved=resolved, exit_code=0 if resolved else 1,
                stdout="passed" if resolved else "", stderr="" if resolved else "failed",
                report={"task_id": request.task_id, "resolved": resolved},
                grader_id="checkout-replay", container_digest="replay@sha256:" + "b" * 64,
                official=False, wall_time_ms=0,
            )

    factory = GitCheckoutWorkspaceFactory({task.task_id: root}, {task.task_id: commit})
    runtime = TriMemAgentRuntime(
        runtime_lock=RuntimeLock(),
        model_gateway=ReplayModelGateway(reply),
        grader_gateway=CheckoutGrader(),
        memory_controller=NoMemoryController(),
        evidence=RawEvidenceLedger(tmp_path / "evidence"),
        checkpoint_store=FileCheckpointStore(tmp_path / "checkpoints"),
        workspace_factory=factory,
    )
    result = runtime.run(task, arm="M0")
    assert result.resolved is True
    checkpoint = FileCheckpointStore(tmp_path / "checkpoints").load(
        "git-task-M0", required_config_hashes=None
    )
    assert checkpoint.config_hashes["workspace"] == factory.content_hash
    assert checkpoint.workspace_state["kind"] == "trimem-git-checkout-workspace-v1"


def test_git_runtime_rolls_forward_fsynced_write_tool_after_precheckpoint_crash(
    tmp_path,
):
    root, commit = _repository(tmp_path)
    task = CodingTask(
        task_id="git-crash-window",
        org_id="org",
        user_id="alice",
        repository="example/repo",
        commit=commit,
        instruction="Set VALUE to two.",
        files={},
        editable_paths=(),
    )

    def reply(request):
        if request.call_kind == "decompose":
            return json.dumps({"subtasks": [{
                "id": "replace-value",
                "objective": "replace the obsolete value literal",
                "predicted_operation": "replace integer literal",
                "depends_on": [],
                "files": ["src/value.py"],
            }]})
        if request.call_kind == "extract":
            return json.dumps({
                "episode": {
                    "summary": "updated",
                    "action": "replace",
                    "outcome": "passed",
                },
                "semantic_candidate": {
                    "preconditions": "literal is obsolete",
                    "operation": "replace literal",
                    "invariant": "integer type",
                    "non_applicability": "dynamic value",
                    "verification": "checkout grader",
                    "applicability_scope": "EXACT_REPOSITORY",
                },
            })
        if request.step_no == 1:
            return json.dumps({"tool": "write_file", "arguments": {
                "path": "src/value.py",
                "content": "VALUE = 2\n",
            }})
        return json.dumps({
            "tool": "complete_subtask",
            "arguments": {"evidence": "edit applied"},
        })

    class CheckoutGrader:
        def grade(self, request):
            checkout = Path(request.workspace.checkout_root)
            resolved = (
                checkout / "src/value.py"
            ).read_text(encoding="utf-8") == "VALUE = 2\n"
            return GradeResult(
                task_id=request.task_id,
                resolved=resolved,
                exit_code=0 if resolved else 1,
                stdout="passed" if resolved else "",
                stderr="" if resolved else "failed",
                report={"task_id": request.task_id, "resolved": resolved},
                grader_id="checkout-replay",
                container_digest="replay@sha256:" + "b" * 64,
                official=False,
                wall_time_ms=0,
            )

    gateway = ReplayModelGateway(reply)
    evidence = RawEvidenceLedger(tmp_path / "crash-evidence")
    checkpoints = FileCheckpointStore(tmp_path / "crash-checkpoints")
    factory = GitCheckoutWorkspaceFactory(
        {task.task_id: root}, {task.task_id: commit}
    )
    runtime = TriMemAgentRuntime(
        runtime_lock=RuntimeLock(),
        model_gateway=gateway,
        grader_gateway=CheckoutGrader(),
        memory_controller=NoMemoryController(),
        evidence=evidence,
        checkpoint_store=checkpoints,
        workspace_factory=factory,
    )

    with pytest.raises(InjectedCrash, match="durable tool evidence"):
        runtime.run(
            task,
            arm="M0",
            crash_after_tool_evidence_step=1,
        )
    assert (root / "src/value.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    interrupted = checkpoints.load(
        "git-crash-window-M0", required_config_hashes=None
    )
    assert interrupted.state == "DECOMPOSED"
    assert interrupted.next_step_no == 1
    assert interrupted.workspace_state["patch"] == ""
    assert evidence.verify()["last_event_hash"] != interrupted.evidence_event_hash

    result = runtime.run(task, arm="M0", resume=True)
    assert result.resolved is True
    assert (root / "src/value.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert gateway.invocations.count("git-crash-window:M0:solve:0001") == 1
    assert gateway.invocations.count("git-crash-window:M0:solve:0002") == 1
    assert result.accounting["summary"]["by_call_kind"]["solve"]["calls"] == 2

    events = [
        json.loads(line)
        for line in evidence.events_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert sum(
        event["event_type"] == "model_request"
        and event["payload"].get("logical_call_id")
        == "git-crash-window:M0:solve:0001"
        for event in events
    ) == 1
    assert sum(
        event["event_type"] == "tool_result"
        and event["payload"].get("step_no") == 1
        for event in events
    ) == 1


def _recovery_reply(request):
    if request.call_kind == "decompose":
        return json.dumps({"subtasks": [{
            "id": "replace-value",
            "objective": "replace the obsolete value literal",
            "predicted_operation": "replace integer literal",
            "depends_on": [],
            "files": ["src/value.py"],
        }]})
    if request.call_kind == "extract":
        return json.dumps({
            "episode": {
                "summary": "updated",
                "action": "replace",
                "outcome": "passed",
            },
            "semantic_candidate": {
                "preconditions": "literal is obsolete",
                "operation": "replace literal",
                "invariant": "integer type",
                "non_applicability": "dynamic value",
                "verification": "checkout grader",
                "applicability_scope": "EXACT_REPOSITORY",
            },
        })
    if request.step_no == 1:
        return json.dumps({
            "tool": "write_file",
            "arguments": {"path": "src/value.py", "content": "VALUE = 2\n"},
        })
    return json.dumps({
        "tool": "complete_subtask",
        "arguments": {"evidence": "edit applied"},
    })


class _CrashWindowGateway:
    def __init__(self, *, crash_call=None, failure_call=None, attempt_call=None):
        self.crash_call = crash_call
        self.failure_call = failure_call
        self.attempt_call = attempt_call
        self.invocations = []
        self._crashed = False
        self._failed = False

    def invoke(self, request):
        self.invocations.append(request.logical_call_id)
        if request.logical_call_id == self.crash_call and not self._crashed:
            self._crashed = True
            raise InjectedCrash("injected after external request")
        if request.logical_call_id == self.failure_call and not self._failed:
            self._failed = True
            raise GatewayInvocationFailure(
                provider="test-provider",
                model="test-model",
                status="provider_failure",
                attempt=3,
                input_tokens=13,
                output_tokens=5,
                cached_input_tokens=2,
                reasoning_tokens=1,
                wall_time_ms=17,
                response_text="provider failed",
            )
        text = _recovery_reply(request)
        return GatewayResponse(
            text=text,
            provider="credential-free-replay",
            model="crash-window-v1",
            input_tokens=13,
            output_tokens=7,
            cached_input_tokens=2,
            reasoning_tokens=1,
            wall_time_ms=3,
            paid=False,
            attempt=3 if request.logical_call_id == self.attempt_call else 1,
        )


class _CountingCheckoutGrader:
    def __init__(self, *, crash_request=False):
        self.calls = 0
        self.crash_request = crash_request

    def grade(self, request):
        self.calls += 1
        if self.crash_request:
            raise InjectedCrash("injected after grader request")
        checkout = Path(request.workspace.checkout_root)
        resolved = (
            checkout / "src/value.py"
        ).read_text(encoding="utf-8") == "VALUE = 2\n"
        return GradeResult(
            task_id=request.task_id,
            resolved=resolved,
            exit_code=0 if resolved else 1,
            stdout="passed" if resolved else "",
            stderr="" if resolved else "failed",
            report={"task_id": request.task_id, "resolved": resolved},
            grader_id="checkout-replay",
            container_digest="replay@sha256:" + "b" * 64,
            official=False,
            wall_time_ms=11,
        )


class _CountingLifecycle:
    def __init__(self):
        self.store_calls = 0
        self.credit_calls = 0
        self.prepare_calls = 0

    def prepare_store_experience(self, task, extraction, grade, injections):
        self.prepare_calls += 1

    def store_experience(self, task, graph, extraction, grade, injections):
        self.store_calls += 1
        return {
            "storage_action": "TEST",
            "retained_records": 1,
            "archived_records": 0,
            "net_memory_growth": 1,
        }

    def credit_outcome(self, task, grade, injections, *, outcome_metrics):
        self.credit_calls += 1
        return {"credited": 0}


def _crash_runtime(tmp_path, *, gateway=None, grader=None, lifecycle=None):
    root, commit = _repository(tmp_path)
    task = CodingTask(
        task_id="git-crash-matrix",
        org_id="org",
        user_id="alice",
        repository="example/repo",
        commit=commit,
        instruction="Set VALUE to two.",
        files={},
        editable_paths=(),
    )
    gateway = gateway or _CrashWindowGateway()
    grader = grader or _CountingCheckoutGrader()
    evidence = RawEvidenceLedger(tmp_path / "matrix-evidence")
    runtime = TriMemAgentRuntime(
        runtime_lock=RuntimeLock(),
        model_gateway=gateway,
        grader_gateway=grader,
        memory_controller=NoMemoryController(),
        evidence=evidence,
        checkpoint_store=FileCheckpointStore(tmp_path / "matrix-checkpoints"),
        workspace_factory=GitCheckoutWorkspaceFactory(
            {task.task_id: root}, {task.task_id: commit}
        ),
        lifecycle=lifecycle,
    )
    return runtime, task, root, gateway, grader, evidence


def _events(evidence):
    return [
        json.loads(line)
        for line in evidence.events_path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_git_runtime_folds_forward_model_response_with_exact_attempt_accounting(
    tmp_path,
):
    logical_id = "git-crash-matrix:M0:solve:0001"
    gateway = _CrashWindowGateway(attempt_call=logical_id)
    runtime, task, root, gateway, _, evidence = _crash_runtime(
        tmp_path, gateway=gateway
    )
    with pytest.raises(InjectedCrash, match="model response"):
        runtime.run(task, arm="M0", crash_after_model_response_step=1)
    assert (root / "src/value.py").read_text(encoding="utf-8") == "VALUE = 1\n"

    result = runtime.run(task, arm="M0", resume=True)
    assert result.resolved is True
    assert gateway.invocations.count(logical_id) == 1
    record = next(
        row for row in result.accounting["calls"] if row["logical_call_id"] == logical_id
    )
    assert record["attempt"] == 3
    assert record["input_tokens"] == 13 and record["output_tokens"] == 7
    events = _events(evidence)
    assert sum(
        row["event_type"] == "model_response"
        and row["payload"].get("logical_call_id") == logical_id
        for row in events
    ) == 1
    assert sum(
        row["event_type"] == "tool_result"
        and row["payload"].get("step_no") == 1
        for row in events
    ) == 1


def test_git_runtime_marks_request_only_external_call_ambiguous(tmp_path):
    logical_id = "git-crash-matrix:M0:solve:0001"
    runtime, task, root, gateway, _, evidence = _crash_runtime(
        tmp_path,
        gateway=_CrashWindowGateway(crash_call=logical_id),
    )
    with pytest.raises(InjectedCrash, match="external request"):
        runtime.run(task, arm="M0")
    with pytest.raises(CheckpointMismatch, match="ambiguous external request"):
        runtime.run(task, arm="M0", resume=True)
    assert (root / "src/value.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert gateway.invocations.count(logical_id) == 1
    assert _events(evidence)[-1]["event_type"] == "recovery_blocked"


def test_git_runtime_folds_forward_durable_model_failure_without_retry(tmp_path):
    logical_id = "git-crash-matrix:M0:solve:0001"
    runtime, task, _, gateway, _, _ = _crash_runtime(
        tmp_path,
        gateway=_CrashWindowGateway(failure_call=logical_id),
    )
    with pytest.raises(GatewayInvocationFailure, match="provider_failure"):
        runtime.run(task, arm="M0")
    with pytest.raises(GatewayInvocationFailure, match="provider_failure"):
        runtime.run(task, arm="M0", resume=True)
    assert gateway.invocations.count(logical_id) == 1
    checkpoint = runtime.checkpoints.load(
        "git-crash-matrix-M0", required_config_hashes=None
    )
    call = next(
        row for row in checkpoint.accounting["calls"] if row["logical_call_id"] == logical_id
    )
    assert call["attempt"] == 3 and call["status"] == "provider_failure"


def test_git_runtime_folds_forward_grader_result_without_reexecution(tmp_path):
    runtime, task, _, _, grader, _ = _crash_runtime(tmp_path)
    with pytest.raises(InjectedCrash, match="grader result"):
        runtime.run(task, arm="M0", crash_after_grader_result=True)
    result = runtime.run(task, arm="M0", resume=True)
    assert result.resolved is True
    assert grader.calls == 1
    assert result.accounting["summary"]["grader_calls"] == 1


def test_git_runtime_refuses_ambiguous_grader_request_only_suffix(tmp_path):
    grader = _CountingCheckoutGrader(crash_request=True)
    runtime, task, _, _, grader, evidence = _crash_runtime(
        tmp_path, grader=grader
    )
    with pytest.raises(InjectedCrash, match="grader request"):
        runtime.run(task, arm="M0")
    with pytest.raises(CheckpointMismatch, match="ambiguous external request"):
        runtime.run(task, arm="M0", resume=True)
    assert grader.calls == 1
    assert _events(evidence)[-1]["event_type"] == "recovery_blocked"


@pytest.mark.parametrize(
    "crash_kw, message",
    [
        ({"crash_after_extraction_model_response": True}, "extraction model response"),
        ({"crash_after_extraction_evidence": True}, "extraction evidence"),
    ],
)
def test_git_runtime_folds_forward_extraction_without_duplicate_model_call(
    tmp_path, crash_kw, message
):
    runtime, task, _, gateway, _, evidence = _crash_runtime(tmp_path)
    with pytest.raises(InjectedCrash, match=message):
        runtime.run(task, arm="M0", **crash_kw)
    result = runtime.run(task, arm="M0", resume=True)
    logical_id = "git-crash-matrix:M0:extract:0001"
    assert gateway.invocations.count(logical_id) == 1
    assert result.accounting["summary"]["by_call_kind"]["extract"]["calls"] == 1
    assert sum(
        row["event_type"] == "experience_extracted" for row in _events(evidence)
    ) == 1


def test_git_runtime_refuses_ambiguous_extraction_request_only_suffix(tmp_path):
    logical_id = "git-crash-matrix:M0:extract:0001"
    runtime, task, _, gateway, grader, evidence = _crash_runtime(
        tmp_path,
        gateway=_CrashWindowGateway(crash_call=logical_id),
    )
    with pytest.raises(InjectedCrash, match="external request"):
        runtime.run(task, arm="M0")
    with pytest.raises(CheckpointMismatch, match="ambiguous external request"):
        runtime.run(task, arm="M0", resume=True)
    assert gateway.invocations.count(logical_id) == 1
    assert grader.calls == 1
    assert _events(evidence)[-1]["event_type"] == "recovery_blocked"


def test_git_runtime_folds_forward_patch_and_finished_evidence(tmp_path):
    runtime, task, _, _, grader, evidence = _crash_runtime(tmp_path)
    with pytest.raises(InjectedCrash, match="patch evidence"):
        runtime.run(task, arm="M0", crash_after_patch_evidence=True)
    with pytest.raises(InjectedCrash, match="terminal evidence"):
        runtime.run(
            task,
            arm="M0",
            resume=True,
            crash_after_finished_evidence=True,
        )
    result = runtime.run(task, arm="M0", resume=True)
    assert result.resolved is True and grader.calls == 1
    events = _events(evidence)
    assert sum(row["event_type"] == "patch_finalized" for row in events) == 1
    assert sum(row["event_type"] == "agent_run_finished" for row in events) == 1


def test_git_runtime_seals_prepare_hook_and_does_not_repeat_lifecycle_after_finish_crash(
    tmp_path,
):
    lifecycle = _CountingLifecycle()
    runtime, task, _, _, _, _ = _crash_runtime(
        tmp_path, lifecycle=lifecycle
    )
    with pytest.raises(InjectedCrash, match="terminal evidence"):
        runtime.run(
            task,
            arm="M0",
            crash_after_finished_evidence=True,
        )
    checkpoint = runtime.checkpoints.load(
        "git-crash-matrix-M0", required_config_hashes=None
    )
    assert checkpoint.state == "LIFECYCLE_CREDITED"
    assert lifecycle.prepare_calls == 1
    assert lifecycle.store_calls == 1 and lifecycle.credit_calls == 1
    runtime.run(task, arm="M0", resume=True)
    assert lifecycle.store_calls == 1 and lifecycle.credit_calls == 1
