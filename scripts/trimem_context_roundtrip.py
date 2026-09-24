"""Credential-free production-shaped D1.9 context and restart rehearsal.

This gate intentionally creates a disposable Git repository large enough to
reproduce the `_009` failure class.  It drives the production workspace,
recording/tool evidence, prompt projection, read-only budget preview, and
checkpoint recovery code with a local replay provider.  It never opens a
network connection, starts a grader container, or pulls an image.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from enterprise_memory.trimem.accounting import (  # noqa: E402
    RawEvidenceLedger,
    canonical_bytes,
    sha256_bytes,
)
from enterprise_memory.trimem.agent_runtime import (  # noqa: E402
    CodingTask,
    InjectedCrash,
    NoMemoryController,
    TriMemAgentRuntime,
)
from enterprise_memory.trimem.checkpoint import FileCheckpointStore  # noqa: E402
from enterprise_memory.trimem.context_projection import (  # noqa: E402
    MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES,
    MAX_SOLVE_PROMPT_UTF8_BYTES,
)
from enterprise_memory.trimem.gateway import (  # noqa: E402
    GatewayRequest,
    GatewayResponse,
    ReplayModelGateway,
    ReservationPreflight,
    gateway_request_sha256,
)
from enterprise_memory.trimem.git_workspace import (  # noqa: E402
    GitCheckoutWorkspace,
    GitCheckoutWorkspaceFactory,
)
from enterprise_memory.trimem.grader import GradeResult  # noqa: E402
from enterprise_memory.trimem.runtime_lock import RuntimeLock  # noqa: E402
from enterprise_memory.trimem.workspace import (  # noqa: E402
    LIST_FILES_MAX_RESPONSE_BYTES,
    PublicTestResult,
    RecordingToolExecutor,
    list_files_page,
)
from trimem_benchmark_run import (  # noqa: E402
    AtomicBudgetLedger,
    JournaledModelGateway,
    TerminalInvocationJournal,
)


MINIMUM_PATHS = 10_000
MINIMUM_UNBOUNDED_LISTING_BYTES = 319_417
TASK_ID = "d19-context-roundtrip"
RUN_ID = TASK_ID + "-M0"
STREAM_ID = "D19-CONTEXT-ROUNDTRIP"
CRASH_LOGICAL_CALL_ID = f"{TASK_ID}:M0:solve:0002"


class ContextRoundTripError(RuntimeError):
    """The credential-free D1.9 rehearsal did not close every invariant."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContextRoundTripError(message)


def run_git(
    repository: Path,
    *arguments: str,
    input_text: str | None = None,
) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        input=None if input_text is None else input_text.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ContextRoundTripError(
            completed.stderr.decode("utf-8", errors="strict").strip()
            or "disposable Git operation failed"
        )
    return completed.stdout.decode("utf-8", errors="strict").strip()


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def build_large_repository(repository: Path) -> tuple[str, list[str]]:
    """Return the committed base and exact tracked+untracked public listing."""

    repository.mkdir(parents=True)
    run_git(repository, "init", "--quiet")
    run_git(repository, "config", "user.email", "trimem-roundtrip@example.invalid")
    run_git(repository, "config", "user.name", "TriMem D1.9 round trip")
    run_git(repository, "config", "core.autocrlf", "false")
    write_text(repository / "README.md", "credential-free D1.9 fixture\n")
    write_text(repository / "src/value.py", "VALUE = 1\n")
    long_line = "public-context-" + ("x" * 104) + "\n"
    write_text(repository / "docs/context.txt", long_line * 1_000)

    paths = [
        (
            "repository_listing/"
            f"component_{index:05d}_with_a_deliberately_long_public_path_"
            f"{index:05d}.py"
        )
        for index in range(MINIMUM_PATHS + 12)
    ]
    # Materializing ten thousand files is needlessly slow on the exact Windows
    # and Linux runners this gate must cover.  Populate the real Git index with
    # immutable empty blobs, then mark those fixture-only entries skip-worktree.
    # GitCheckoutWorkspace still sees the exact tracked repository surface via
    # ``git ls-files`` while the three files used by runtime operations remain
    # ordinary physical files.  Two additional physical files prove untracked
    # enumeration through the same production implementation.
    untracked = set(paths[:2])
    tracked = [relative for relative in paths if relative not in untracked]
    run_git(repository, "add", "--all")
    empty_blob = run_git(repository, "hash-object", "-w", "--stdin", input_text="")
    run_git(
        repository,
        "update-index",
        "--index-info",
        input_text="".join(
            f"100644 {empty_blob}\t{relative}\n" for relative in tracked
        ),
    )
    run_git(repository, "commit", "--quiet", "-m", "fixture base")
    base_commit = run_git(repository, "rev-parse", "HEAD")
    run_git(
        repository,
        "update-index",
        "--skip-worktree",
        "--stdin",
        input_text="".join(relative + "\n" for relative in tracked),
    )
    for relative in sorted(untracked):
        write_text(repository / relative, "# untracked public fixture\n")

    listing = sorted(["README.md", "docs/context.txt", "src/value.py", *paths])
    require(len(listing) >= MINIMUM_PATHS, "large repository path count is too small")
    require(
        len(canonical_bytes(listing)) >= MINIMUM_UNBOUNDED_LISTING_BYTES,
        "large repository listing does not reproduce the historical size class",
    )
    return base_commit, listing


def pagination_arguments(listing: list[str]) -> list[dict[str, Any]]:
    arguments: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(4):
        row = {"path_prefix": None, "start_after": cursor, "limit": 200}
        page = list_files_page(listing, row)
        require(
            len(canonical_bytes(page)) <= LIST_FILES_MAX_RESPONSE_BYTES,
            "production list_files page exceeded its model-visible cap",
        )
        require(page["files"], "large-repository pagination ended unexpectedly")
        arguments.append(row)
        cursor = page["next_start_after"]
        require(cursor is not None, "large-repository pagination lacked a cursor")
    return arguments


class CheckoutReplayGrader:
    """Local checkout assertion behind the production grader interface."""

    content_hash = sha256_bytes(b"trimem-d19-checkout-replay-grader-v1")

    def grade(self, request: Any) -> GradeResult:
        checkout = Path(str(request.workspace.checkout_root))
        resolved = (checkout / "src/value.py").read_text(encoding="utf-8") == (
            "VALUE = 2\n"
        )
        return GradeResult(
            task_id=request.task_id,
            resolved=resolved,
            exit_code=0 if resolved else 1,
            stdout="credential-free checkout assertion passed\n" if resolved else "",
            stderr="" if resolved else "credential-free checkout assertion failed\n",
            report={"task_id": request.task_id, "resolved": resolved},
            grader_id="trimem-context-roundtrip-replay-v1",
            container_digest="replay@sha256:" + self.content_hash,
            official=False,
            wall_time_ms=0,
            container_started=False,
            status="success" if resolved else "fixture_failure",
        )


class _CredentialFreeBudgetDelegate:
    """Zero-cost delegate behind the production request-lifecycle journal."""

    content_hash = sha256_bytes(b"trimem-d19-preflighted-replay-gateway-v1")

    def __init__(
        self,
        replay: ReplayModelGateway,
        ledger: AtomicBudgetLedger,
        evidence: RawEvidenceLedger,
    ) -> None:
        self.replay = replay
        self.ledger = ledger
        self.evidence = evidence
        self.preflights: list[ReservationPreflight] = []
        self.native_solve_requests = 0
        self.reservations: dict[str, ReservationPreflight] = {}

    @staticmethod
    def _task_arm_key(request: GatewayRequest) -> str:
        return f"{STREAM_ID}:{request.arm}:{request.task_id}"

    @staticmethod
    def _ledger_call_id(request: GatewayRequest) -> str:
        return f"{STREAM_ID}:{request.logical_call_id}"

    def preview_reservation(self, request: GatewayRequest) -> ReservationPreflight:
        # RecordingModelGateway calls this before it appends model_request.
        prior = [
            event
            for event in self.evidence.verified_suffix("0" * 64)
            if event.get("event_type") == "model_request"
            and event.get("payload", {}).get("logical_call_id")
            == request.logical_call_id
        ]
        if not prior:
            require(
                all(row.ledger_logical_call_id != self._ledger_call_id(request) for row in self.preflights),
                "fresh logical request was previewed more than once",
            )
        preflight = self.ledger.preview_reservation(
            self._ledger_call_id(request),
            request_sha256=gateway_request_sha256(request),
            task_arm_key=self._task_arm_key(request),
            call_kind=request.call_kind,
            input_upper_bound=max(1, len(request.prompt.encode("utf-8"))) + 4_096,
            output_cap=request.max_output_tokens,
        )
        self.preflights.append(preflight)
        return preflight

    def reserve_preflighted(
        self, request: GatewayRequest, preflight: ReservationPreflight
    ) -> str:
        require(isinstance(preflight, ReservationPreflight), "request skipped production preflight")
        require(
            preflight.request_sha256 == gateway_request_sha256(request)
            and preflight.ledger_logical_call_id == self._ledger_call_id(request),
            "request/preflight identity differs",
        )
        existing = self.reservations.get(request.logical_call_id)
        require(
            existing in {None, preflight},
            "credential-free reservation identity changed",
        )
        self.reservations[request.logical_call_id] = preflight
        return preflight.reservation_id

    def request_row(self, request: GatewayRequest) -> Mapping[str, Any] | None:
        preflight = self.reservations.get(request.logical_call_id)
        if preflight is None:
            return None
        return {
            "status": "RESERVED",
            "reservation_id": preflight.reservation_id,
            "task_arm_key": preflight.task_arm_key,
            "call_kind": preflight.call_kind,
            "input_upper_bound": preflight.input_upper_bound,
            "output_cap": preflight.output_cap,
        }

    def send_reserved(
        self, request: GatewayRequest, preflight: ReservationPreflight
    ) -> GatewayResponse:
        require(
            self.reservations.get(request.logical_call_id) == preflight,
            "credential-free request was not reserved in its fake ledger",
        )
        if request.call_kind == "solve":
            self.native_solve_requests += 1
            require(request.function_tools is not None, "native function tools were not supplied")
            require(
                request.function_tools_sha256 == RuntimeLock().function_tools_sha256,
                "native function-tool schema hash differs",
            )
        return self.replay.invoke(request)

    def reconcile_success(
        self, preflight: ReservationPreflight, response: GatewayResponse
    ) -> None:
        del response
        self.reservations.pop(
            preflight.ledger_logical_call_id.removeprefix(STREAM_ID + ":"),
            None,
        )

    def reconcile_failure(self, preflight: ReservationPreflight, failure: Any) -> None:
        del failure
        self.reconcile_success(preflight, GatewayResponse(
            text="", provider="credential-free", model="credential-free",
            input_tokens=0, output_tokens=0, wall_time_ms=0, paid=False,
        ))


class PreflightedReplayGateway:
    """Production journal + real read-only budget preview + fake provider."""

    content_hash = sha256_bytes(b"trimem-d19-journaled-replay-gateway-v1")

    def __init__(
        self,
        replay: ReplayModelGateway,
        ledger: AtomicBudgetLedger,
        evidence: RawEvidenceLedger,
        *,
        crash_once: bool,
    ) -> None:
        self.crash_once = crash_once
        self.delegate = _CredentialFreeBudgetDelegate(replay, ledger, evidence)
        self.journaled = JournaledModelGateway(
            self.delegate,
            TerminalInvocationJournal(evidence.root.parent / "terminal-journal"),
        )

    @property
    def preflights(self) -> list[ReservationPreflight]:
        return self.delegate.preflights

    @property
    def native_solve_requests(self) -> int:
        return self.delegate.native_solve_requests

    def preview_reservation(
        self, request: GatewayRequest
    ) -> ReservationPreflight | None:
        return self.journaled.preview_reservation(request)

    def invoke_preflighted(
        self, request: GatewayRequest, preflight: ReservationPreflight | None
    ) -> GatewayResponse:
        if self.crash_once and request.logical_call_id == CRASH_LOGICAL_CALL_ID:
            self.crash_once = False
            # RecordingModelGateway has durably appended model_request, while
            # the production journal and provider boundary remain untouched.
            raise InjectedCrash("simulated NOT_SENT request-only restart")
        return self.journaled.invoke_preflighted(request, preflight)

    def invoke(self, request: GatewayRequest) -> GatewayResponse:
        return self.invoke_preflighted(request, self.preview_reservation(request))

    def replay_terminal(self, request: GatewayRequest) -> GatewayResponse | None:
        return self.journaled.replay_terminal(request)

    def request_lifecycle(self, request: GatewayRequest) -> Mapping[str, Any]:
        return self.journaled.request_lifecycle(request)


def replay_response(
    pages: list[dict[str, Any]], requests: list[GatewayRequest]
):
    expected_value_hash = hashlib.sha256(b"VALUE = 1\n").hexdigest()

    def respond(request: GatewayRequest) -> str:
        requests.append(request)
        if request.call_kind == "decompose":
            return json.dumps(
                {
                    "subtasks": [
                        {
                            "id": "bounded-context-repair",
                            "objective": "inspect the public repository and update the obsolete value",
                            "predicted_operation": "replace the obsolete value and verify it",
                            "depends_on": [],
                            "files": ["src/value.py"],
                            "tests": ["public checkout assertion"],
                        }
                    ]
                },
                sort_keys=True,
            )
        if request.call_kind == "extract":
            return json.dumps(
                {
                    "episode": {
                        "summary": "Paginated repository inspection preceded a verified edit.",
                        "action": "Used bounded observations and an exact replacement.",
                        "outcome": "passed",
                    },
                    "semantic_candidate": None,
                },
                sort_keys=True,
            )
        actions: dict[int, tuple[str, Mapping[str, Any]]] = {
            1: ("list_files", pages[0]),
            2: ("list_files", pages[1]),
            3: ("list_files", pages[2]),
            4: ("list_files", pages[3]),
            5: (
                "read_file",
                {"path": "docs/context.txt", "start_line": 1, "max_lines": 1_000},
            ),
            6: (
                "replace_text",
                {
                    "path": "src/value.py",
                    "expected_file_sha256": expected_value_hash,
                    "old_text": "VALUE = 1",
                    "new_text": "VALUE = 2",
                },
            ),
            7: ("run_public_tests", {}),
            8: (
                "complete_subtask",
                {"evidence": "public checkout assertion returned passed"},
            ),
        }
        tool, arguments = actions[request.step_no]
        return json.dumps(
            {"tool": tool, "arguments": arguments},
            ensure_ascii=False,
            sort_keys=True,
        )

    return respond


def fixture_caps(pricing: Mapping[str, Any]) -> dict[str, Any]:
    input_cap = 500_000
    output_cap = 8_192 + 8 * 16_384 + 8_192
    ceiling = (
        Decimal(input_cap)
        * Decimal(str(pricing["input_per_million_tokens_usd"]))
        + Decimal(output_cap)
        * Decimal(str(pricing["output_per_million_tokens_usd"]))
    ) / Decimal(1_000_000)
    return {
        "benchmark_grader_containers": 1,
        "decomposition_calls": 1,
        "extraction_calls": 1,
        "input_tokens": input_cap,
        "max_input_tokens_per_task_arm": input_cap,
        "max_model_calls_per_task_arm": 10,
        "model_calls": 10,
        "output_tokens": output_cap,
        "paid_model_calls": 10,
        "solve_calls": 8,
        "task_arm_runs": 1,
        "total_usd": 2.0,
        "uncached_token_cost_ceiling_usd": float(ceiling),
    }


def run_roundtrip() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="trimem-d19-context-") as directory:
        root = Path(directory)
        repository = root / "repository"
        base_commit, listing = build_large_repository(repository)
        page_arguments = pagination_arguments(listing)
        task = CodingTask(
            task_id=TASK_ID,
            org_id="credential-free-org",
            user_id="credential-free-user",
            repository="fixture/large-public-repository",
            commit=base_commit,
            instruction="Inspect the public repository, set VALUE to 2, and verify it.",
            files={},
            editable_paths=(),
        )

        def public_test(checkout: Path) -> PublicTestResult:
            passed = (checkout / "src/value.py").read_text(encoding="utf-8") == (
                "VALUE = 2\n"
            )
            return PublicTestResult(
                passed=passed,
                exit_code=0 if passed else 1,
                stdout=("public-test-output-" + ("y" * 96) + "\n") * 900,
                stderr="" if passed else "value mismatch\n",
            )

        factory = GitCheckoutWorkspaceFactory(
            {TASK_ID: repository},
            {TASK_ID: base_commit},
            public_tests={TASK_ID: public_test},
            public_test_runner_hashes={
                TASK_ID: sha256_bytes(b"trimem-d19-public-test-v1")
            },
        )
        production_workspace = factory(task)
        require(
            isinstance(production_workspace, GitCheckoutWorkspace),
            "factory did not construct the production Git workspace",
        )
        # The runtime must instantiate this exact recorder around that workspace.
        require(
            RecordingToolExecutor.__module__ == "enterprise_memory.trimem.workspace",
            "production recording tool executor identity differs",
        )

        cost = json.loads(
            (ROOT / "configs/trimem_v1/cost_plan.json").read_text(encoding="utf-8")
        )
        pricing = cost["model_pricing"]
        budget = AtomicBudgetLedger(
            root / "budget.json",
            approval_digest=sha256_bytes(b"credential-free-d19-approval"),
            caps=fixture_caps(pricing),
            pricing=pricing,
        )
        task_arm_key = f"{STREAM_ID}:M0:{TASK_ID}"
        task_arm_reservation_id = budget.reserve_task_arm(task_arm_key)

        evidence = RawEvidenceLedger(root / "evidence")
        checkpoints = FileCheckpointStore(root / "checkpoints")
        observed_requests: list[GatewayRequest] = []
        response = replay_response(page_arguments, observed_requests)
        first_delegate = PreflightedReplayGateway(
            ReplayModelGateway(response), budget, evidence, crash_once=True
        )

        def runtime(delegate: PreflightedReplayGateway) -> TriMemAgentRuntime:
            return TriMemAgentRuntime(
                runtime_lock=RuntimeLock(),
                model_gateway=delegate,
                grader_gateway=CheckoutReplayGrader(),
                memory_controller=NoMemoryController(),
                evidence=evidence,
                checkpoint_store=checkpoints,
                workspace_factory=factory,
            )

        try:
            runtime(first_delegate).run(task, arm="M0", run_id=RUN_ID)
        except InjectedCrash as exc:
            require(
                str(exc) == "simulated NOT_SENT request-only restart",
                "unexpected injected restart boundary",
            )
        else:
            raise ContextRoundTripError("request-only restart was not exercised")

        interrupted = checkpoints.load(RUN_ID, required_config_hashes=None)
        require(
            interrupted.state == "RECALL_PREPARED"
            and interrupted.next_step_no == 2,
            "restart did not preserve the prepared solve boundary",
        )
        events_before_resume = evidence.verified_suffix("0" * 64)
        require(
            sum(
                event.get("event_type") == "model_request"
                and event.get("payload", {}).get("logical_call_id")
                == CRASH_LOGICAL_CALL_ID
                for event in events_before_resume
            )
            == 1,
            "restart boundary lacks exactly one durable request event",
        )

        resumed_delegate = PreflightedReplayGateway(
            ReplayModelGateway(response), budget, evidence, crash_once=False
        )
        result = runtime(resumed_delegate).run(
            task, arm="M0", run_id=RUN_ID, resume=True
        )
        require(result.resolved is True, "credential-free terminal cell did not resolve")
        terminal = checkpoints.load(RUN_ID, required_config_hashes=None)
        require(terminal.state == "DONE", "terminal checkpoint did not reach DONE")
        budget.complete_task_arm(
            task_arm_key,
            task_arm_reservation_id,
            status="CELL_TERMINAL",
            container_started=False,
        )
        terminal_ledger = json.loads(budget.path.read_text(encoding="utf-8"))
        task_arm_ledger = terminal_ledger["task_arms"].get(task_arm_key)
        outstanding = terminal_ledger.get("outstanding")
        require(
            isinstance(task_arm_ledger, Mapping)
            and task_arm_ledger.get("status") == "CELL_TERMINAL"
            and task_arm_ledger.get("container_started") is False,
            "credential-free task-arm ledger did not reach CELL_TERMINAL",
        )
        require(
            isinstance(outstanding, Mapping)
            and all(value in {0, 0.0} for value in outstanding.values()),
            "credential-free task-arm ledger retains an outstanding reservation",
        )
        require(
            terminal_ledger["actual"]["task_arm_runs"] == 1
            and terminal_ledger["actual"]["grader_containers"] == 0,
            "credential-free terminal accounting crossed the grader boundary",
        )
        evidence_report = evidence.verify()
        events = evidence.verified_suffix("0" * 64)
        require(
            sum(
                event.get("event_type") == "model_request"
                and event.get("payload", {}).get("logical_call_id")
                == CRASH_LOGICAL_CALL_ID
                for event in events
            )
            == 1,
            "resume duplicated the durable model request",
        )

        solve_requests = [
            request for request in observed_requests if request.call_kind == "solve"
        ]
        require(len(solve_requests) == 8, "solve request count differs after resume")
        final_solve = solve_requests[-1]
        projection = final_solve.prompt_projection
        require(
            isinstance(projection, Mapping)
            and projection.get("projected_history_bytes", 0)
            <= MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES
            and len(final_solve.prompt.encode("utf-8"))
            <= MAX_SOLVE_PROMPT_UTF8_BYTES,
            "next solve prompt is not bounded",
        )
        require(
            projection.get("raw_history_bytes", 0)
            > projection.get("projected_history_bytes", 0),
            "large exact history did not exercise deterministic projection",
        )
        require(
            '"tool_schema"' not in final_solve.prompt
            and RuntimeLock().function_tools_sha256 in final_solve.prompt,
            "textual/native function schema separation differs",
        )
        summary = result.accounting["summary"]
        require(
            summary["paid_model_calls"] == 0
            and summary["grader_containers"] == 0
            and summary["official_grader_runs"] == 0,
            "credential-free rehearsal crossed a paid or official boundary",
        )

        aggregate = {
            "schema": "trimem/context-roundtrip-aggregate/1.0",
            "terminal_cells": 1,
            "resolved_cells": int(result.resolved),
            "terminal_task_arm_status": task_arm_ledger["status"],
            "ledger_outstanding_zero": True,
            "terminal_checkpoint_sha256": terminal.content_hash,
            "evidence_tail_hash": result.evidence_tail_hash,
            "paid_model_calls": summary["paid_model_calls"],
            "official_grader_runs": summary["official_grader_runs"],
        }
        require(
            json.loads(canonical_bytes(aggregate)) == aggregate,
            "terminal aggregate canonical round trip failed",
        )
        return {
            "schema": "trimem/context-roundtrip/1.0",
            "status": "PASS",
            "repository_paths": len(listing),
            "unbounded_listing_bytes": len(canonical_bytes(listing)),
            "list_files_pages_exercised": 4,
            "raw_history_bytes": projection["raw_history_bytes"],
            "projected_history_bytes": projection["projected_history_bytes"],
            "final_solve_prompt_bytes": len(final_solve.prompt.encode("utf-8")),
            "request_only_restart": "NOT_SENT_REPLAYED_WITHOUT_DUPLICATE_REQUEST",
            "terminal_cells": 1,
            "terminal_task_arm_status": task_arm_ledger["status"],
            "ledger_outstanding_zero": True,
            "aggregate_roundtrip": "PASS",
            "evidence_events": evidence_report["events"],
            "real_provider_calls": 0,
            "paid_calls": 0,
            "official_graders": 0,
            "benchmark_images": 0,
            "total_usd": 0,
        }


def main() -> int:
    try:
        report = run_roundtrip()
    except (ContextRoundTripError, OSError, ValueError, RuntimeError) as exc:
        print(f"TRIMEM_CONTEXT_ROUNDTRIP_PASS: false ({exc})")
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    print("TRIMEM_CONTEXT_ROUNDTRIP_PASS: true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
