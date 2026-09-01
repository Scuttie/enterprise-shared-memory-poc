"""Run the frozen 6-instance/12-target official grader smoke after approval."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from enterprise_memory.trimem.grader import GradeRequest, GradeResult, GraderInvocationFailure  # noqa: E402
from enterprise_memory.trimem.workspace import WorkspaceGraderContext  # noqa: E402
from trimem_benchmark_run import (  # noqa: E402
    BenchmarkExecutionError,
    evidence_reference,
    grader_factory,
    image_entries,
    observed_target_digest,
    prepare_harnesses,
    read_json,
    restricted_evidence_references,
    sha256_bytes,
    validate_benchmark_environment,
    validate_exec_approval,
    write_json,
)
from trimem_select_targets import canonical_bytes, instance_id, load_sources, row_hash  # noqa: E402
from trimem_grader_smoke_protocol import (  # noqa: E402
    NOOP_BASELINE_CONTENT,
    NOOP_BASELINE_LOCK,
    NOOP_BASELINE_PATCH,
    NOOP_BASELINE_PATH,
    SmokeProtocolError,
    validate_serial_targets,
)
from trimem_pull_locked_images import (  # noqa: E402
    pull_and_observe_image,
    remove_materialized_image,
)


EMPTY_PATCH_SHA256 = sha256_bytes(b"")


class _SerialImageLifecycle:
    """Keep at most one target image plus one Multi harness image resident."""

    def __init__(
        self,
        *,
        approval: Mapping[str, Any],
        evidence_root: Path,
        targets: list[dict[str, Any]],
        images: Mapping[str, Mapping[str, Any]],
        support: list[tuple[str, str]],
    ) -> None:
        self.approval = approval
        self.evidence_root = evidence_root
        self.targets = targets
        self.images = images
        self.support = support
        self.events: list[dict[str, Any]] = []
        self.operation_index = 0
        self.current_instance: str | None = None
        self.support_resident = False
        self.max_resident_target_images = 0
        self.max_resident_support_images = 0
        self.status = "IN_PROGRESS"
        self.failure: dict[str, Any] | None = None
        self.evidence_root.mkdir(parents=True, exist_ok=True)

        multi_pairs = [
            pair_index
            for pair_index, target in enumerate(targets[0::2])
            if str(target["benchmark_id"]).startswith("multi_swe_bench")
        ]
        if not multi_pairs or len(support) != 1:
            raise BenchmarkExecutionError(
                "grader-smoke Multi rows require exactly one frozen support image"
            )
        if multi_pairs != list(range(multi_pairs[0], multi_pairs[-1] + 1)):
            raise BenchmarkExecutionError(
                "grader-smoke Multi identities must form one contiguous serial region"
            )
        self.last_multi_target_index = (multi_pairs[-1] * 2) + 1
        self._write_report()

    def _write_report(self) -> None:
        target_pulls = sum(
            event["action"] == "PULL_TARGET" for event in self.events
        )
        support_pulls = sum(
            event["action"] == "PULL_SUPPORT" for event in self.events
        )
        removals = sum(
            event["action"] in {"REMOVE_TARGET", "REMOVE_SUPPORT"}
            for event in self.events
        )
        write_json(self.evidence_root / "image-lifecycle-report.json", {
            "schema": "trimem/grader-smoke-image-lifecycle/1.0",
            "status": self.status,
            "phase": self.approval["phase"],
            "approval_artifact_sha256": self.approval["approval_artifact_sha256"],
            "git_head": self.approval["git_head"],
            "expected": {
                "target_image_pulls": 6,
                "support_image_pulls": 1,
                "exact_image_removals": 7,
                "max_resident_target_images": 1,
                "max_resident_support_images": 1,
            },
            "actual": {
                "target_image_pulls": target_pulls,
                "support_image_pulls": support_pulls,
                "exact_image_removals": removals,
                "max_resident_target_images": self.max_resident_target_images,
                "max_resident_support_images": self.max_resident_support_images,
                "resident_target_images": int(self.current_instance is not None),
                "resident_support_images": int(self.support_resident),
            },
            "failure": self.failure,
            "events": self.events,
        })

    def _pull(self, *, action: str, image: str, identity: str) -> None:
        try:
            record = pull_and_observe_image(
                image, self.evidence_root, self.operation_index
            )
        except BaseException as exc:
            self.events.append({
                "action": action + "_FAILED",
                "identity": identity,
                "image": image,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            self.operation_index += 1
            self.status = "FAILED"
            self._write_report()
            raise
        self.operation_index += 1
        self.events.append({"action": action, "identity": identity, "record": record})

    def _remove(
        self, *, action: str, image: str, tag: str, identity: str
    ) -> None:
        try:
            record = remove_materialized_image(
                image, [tag], self.evidence_root, self.operation_index
            )
        except BaseException as exc:
            self.events.append({
                "action": action + "_FAILED",
                "identity": identity,
                "image": image,
                "tag": tag,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            self.operation_index += 1
            self.status = "CLEANUP_FAILED"
            self._write_report()
            raise
        self.operation_index += 1
        self.events.append({"action": action, "identity": identity, "record": record})

    def before_target(self, index: int, target: Mapping[str, Any]) -> None:
        instance = str(target["instance_id"])
        probe = target["probe"]
        if probe == "GOLD":
            if self.current_instance is not None:
                raise BenchmarkExecutionError(
                    "next smoke identity started before exact target image removal"
                )
            if str(target["benchmark_id"]).startswith("multi_swe_bench"):
                if not self.support_resident:
                    support_image, _ = self.support[0]
                    self.support_resident = True
                    self.max_resident_support_images = 1
                    self._write_report()
                    self._pull(
                        action="PULL_SUPPORT",
                        image=support_image,
                        identity="multi_swe_bench_support",
                    )
            entry = self.images[instance]
            self.current_instance = instance
            self.max_resident_target_images = 1
            self._write_report()
            self._pull(
                action="PULL_TARGET", image=str(entry["image"]), identity=instance
            )
        elif probe == "NOOP_BASELINE":
            if self.current_instance != instance:
                raise BenchmarkExecutionError(
                    "NOOP_BASELINE did not reuse its immediately preceding GOLD image"
                )
        else:
            raise BenchmarkExecutionError(f"unsupported smoke probe at index {index}")
        self._write_report()

    def after_target(self, index: int, target: Mapping[str, Any]) -> None:
        if target["probe"] != "NOOP_BASELINE":
            return
        instance = str(target["instance_id"])
        if self.current_instance != instance:
            raise BenchmarkExecutionError("smoke image lifecycle identity drift")
        entry = self.images[instance]
        self._remove(
            action="REMOVE_TARGET",
            image=str(entry["image"]),
            tag=str(entry["harness_image_tag"]),
            identity=instance,
        )
        self.current_instance = None
        if index == self.last_multi_target_index:
            support_image, support_tag = self.support[0]
            self._remove(
                action="REMOVE_SUPPORT",
                image=support_image,
                tag=support_tag,
                identity="multi_swe_bench_support",
            )
            self.support_resident = False
        self._write_report()

    def finish(self) -> None:
        actual = {
            "target_pulls": sum(
                event["action"] == "PULL_TARGET" for event in self.events
            ),
            "support_pulls": sum(
                event["action"] == "PULL_SUPPORT" for event in self.events
            ),
            "removals": sum(
                event["action"] in {"REMOVE_TARGET", "REMOVE_SUPPORT"}
                for event in self.events
            ),
        }
        if (
            actual != {"target_pulls": 6, "support_pulls": 1, "removals": 7}
            or self.current_instance is not None
            or self.support_resident
            or self.max_resident_target_images != 1
            or self.max_resident_support_images != 1
        ):
            raise BenchmarkExecutionError(
                f"grader-smoke image lifecycle failed closed: {actual}"
            )
        self.status = "PASS"
        self._write_report()

    def abort(self, exc: BaseException) -> None:
        """Best-effort exact cleanup while preserving the original failure."""

        if self.status == "PASS":
            return
        self.failure = {"error_type": type(exc).__name__, "error": str(exc)}
        cleanup_failures: list[dict[str, str]] = []
        if self.current_instance is not None:
            instance = self.current_instance
            entry = self.images[instance]
            try:
                self._remove(
                    action="REMOVE_TARGET",
                    image=str(entry["image"]),
                    tag=str(entry["harness_image_tag"]),
                    identity=instance,
                )
                self.current_instance = None
            except BaseException as cleanup_exc:
                cleanup_failures.append({
                    "identity": instance,
                    "error_type": type(cleanup_exc).__name__,
                    "error": str(cleanup_exc),
                })
        if self.support_resident:
            support_image, support_tag = self.support[0]
            try:
                self._remove(
                    action="REMOVE_SUPPORT",
                    image=support_image,
                    tag=support_tag,
                    identity="multi_swe_bench_support",
                )
                self.support_resident = False
            except BaseException as cleanup_exc:
                cleanup_failures.append({
                    "identity": "multi_swe_bench_support",
                    "error_type": type(cleanup_exc).__name__,
                    "error": str(cleanup_exc),
                })
        if cleanup_failures:
            self.status = "CLEANUP_FAILED"
            self.failure["cleanup_failures"] = cleanup_failures
        else:
            self.status = "FAILED"
        self._write_report()


def _smoke_targets(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        raise BenchmarkExecutionError("grader-smoke targets are missing")
    try:
        validate_serial_targets(
            matrix_kind=manifest.get("matrix_kind"),
            noop_baseline=manifest.get("noop_baseline"),
            targets=targets,
        )
    except SmokeProtocolError as exc:
        raise BenchmarkExecutionError(str(exc)) from exc
    if sha256_bytes(canonical_bytes(targets)) != manifest.get("target_set_sha256"):
        raise BenchmarkExecutionError("grader-smoke target-set digest mismatch")
    return [dict(target) for target in targets]


def _gold_patch(benchmark_id: str, row: Mapping[str, Any]) -> str:
    field = "patch" if benchmark_id == "swebench_verified" else "fix_patch"
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkExecutionError(f"frozen GOLD row lacks {field}")
    return value


def _patch_for_target(
    target: Mapping[str, Any], source: Mapping[str, Any], manifest: Mapping[str, Any]
) -> str:
    probe = target.get("probe")
    if probe == "GOLD":
        patch = _gold_patch(str(target.get("benchmark_id")), source)
    elif probe == "NOOP_BASELINE":
        if manifest.get("noop_baseline") != NOOP_BASELINE_LOCK:
            raise BenchmarkExecutionError("NOOP_BASELINE patch is not bound to the frozen manifest")
        patch = NOOP_BASELINE_PATCH.decode("utf-8")
    else:
        raise BenchmarkExecutionError(f"unsupported grader-smoke probe: {probe}")
    raw = patch.encode("utf-8")
    if not patch.strip() or not raw or sha256_bytes(raw) == EMPTY_PATCH_SHA256:
        raise BenchmarkExecutionError(f"grader-smoke refuses empty patch before evaluator: {target.get('target_id')}")
    return patch


def _rows_for_targets(targets: list[dict[str, Any]], cache: Path) -> dict[tuple[str, str], dict[str, Any]]:
    sources, _ = load_sources(cache)
    wanted = {(row["benchmark_id"], row["instance_id"]) for row in targets}
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for benchmark_id, rows in sources.items():
        for row in rows:
            key = (benchmark_id, instance_id(row))
            if key in wanted:
                if key in result:
                    raise BenchmarkExecutionError(f"duplicate official source row: {key}")
                result[key] = dict(row)
    if set(result) != wanted:
        raise BenchmarkExecutionError("official smoke source rows are missing")
    for target in targets:
        source = result[(target["benchmark_id"], target["instance_id"])]
        if row_hash(source) != target["source_row_sha256"]:
            raise BenchmarkExecutionError(f"official smoke source-row hash drift: {target['target_id']}")
    return result


def _run_git(
    args: list[str], *, cwd: Path | None = None, check: bool = True,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False, timeout=120,
        env=dict(env) if env is not None else None,
    )
    if check and completed.returncode != 0:
        raise BenchmarkExecutionError(
            f"credential-free NOOP_BASELINE git audit failed: {' '.join(args[:3])}: "
            f"{completed.stderr.strip()}"
        )
    return completed


def _run_git_bytes(
    args: list[str], *, cwd: Path | None = None, env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=False, check=False, timeout=120,
        env=dict(env) if env is not None else None,
    )
    if completed.returncode != 0:
        raise BenchmarkExecutionError(
            f"credential-free NOOP_BASELINE git audit failed: {' '.join(args[:3])}: "
            f"{completed.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return completed


def audit_noop_baseline_checkouts(checkout_map_path: Path, output_path: Path) -> dict[str, Any]:
    """Prove the one frozen marker patch against six local exact-commit repositories."""

    manifest = read_json(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    targets = _smoke_targets(manifest)
    identity_targets = targets[0::2]
    mapping_document = read_json(checkout_map_path)
    repositories = mapping_document.get("repositories")
    expected_repositories = {target["repository"] for target in identity_targets}
    if (
        mapping_document.get("schema") != "trimem/noop-baseline-checkout-map/1.0"
        or not isinstance(repositories, dict)
        or set(repositories) != expected_repositories
        or any(not isinstance(path, str) or not path for path in repositories.values())
    ):
        raise BenchmarkExecutionError("NOOP_BASELINE checkout map must bind exactly six repositories")

    rows = []
    for target in identity_targets:
        source = Path(repositories[target["repository"]]).resolve()
        if not source.is_dir():
            raise BenchmarkExecutionError(f"NOOP_BASELINE source checkout is missing: {target['repository']}")
        commit = target["base_commit"]
        _run_git(["-C", str(source), "cat-file", "-e", f"{commit}^{{commit}}"])
        absent = _run_git(
            ["-C", str(source), "cat-file", "-e", f"{commit}:{NOOP_BASELINE_PATH}"],
            check=False,
        )
        if absent.returncode == 0:
            raise BenchmarkExecutionError(
                f"NOOP_BASELINE marker already exists at base commit: {target['instance_id']}"
            )
        base_tree = _run_git(
            ["-C", str(source), "rev-parse", f"{commit}^{{tree}}"]
        ).stdout.strip()
        with tempfile.TemporaryDirectory(prefix="trimem-noop-baseline-audit-") as raw_temp:
            temp = Path(raw_temp)
            audit_env = {**os.environ, "GIT_INDEX_FILE": str(temp / "audit.index")}
            _run_git(["-C", str(source), "read-tree", commit], env=audit_env)
            patch_path = temp / "noop-baseline.patch"
            patch_path.write_bytes(NOOP_BASELINE_PATCH)
            _run_git(
                ["-C", str(source), "apply", "--cached", "--check", str(patch_path)],
                env=audit_env,
            )
            _run_git(
                ["-C", str(source), "apply", "--cached", str(patch_path)], env=audit_env,
            )
            changed = _run_git([
                "-C", str(source), "diff", "--cached", "--no-renames", "--name-status", commit,
            ], env=audit_env).stdout.splitlines()
            if changed != [f"A\t{NOOP_BASELINE_PATH}"]:
                raise BenchmarkExecutionError(
                    f"NOOP_BASELINE touched unexpected paths for {target['instance_id']}: {changed}"
                )
            marker = _run_git_bytes(
                ["-C", str(source), "show", f":0:{NOOP_BASELINE_PATH}"], env=audit_env,
            ).stdout
            if marker != NOOP_BASELINE_CONTENT:
                raise BenchmarkExecutionError(
                    f"NOOP_BASELINE marker bytes differ for {target['instance_id']}"
                )
        rows.append({
            "base_commit": commit,
            "base_tree": base_tree,
            "changed_paths": [NOOP_BASELINE_PATH],
            "forbidden_source_test_build_or_package_paths_touched": [],
            "isolated_temporary_index": True,
            "instance_id": target["instance_id"],
            "patch_applies_cached": True,
            "repository": target["repository"],
            "root_marker_absent_at_base": True,
            "staged_marker_sha256": sha256_bytes(marker),
        })
    body = {
        "schema": "trimem/noop-baseline-six-commit-audit/1.0",
        "manifest_target_set_sha256": manifest["target_set_sha256"],
        "noop_baseline": NOOP_BASELINE_LOCK,
        "rows": rows,
        "status": "PASS",
    }
    report = {**body, "audit_sha256": sha256_bytes(canonical_bytes(body))}
    write_json(output_path, report)
    return report


def _grader_test_evidence(
    grade: GradeResult, *, task_dir: Path, grader_root: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    trimem = grade.report.get("_trimem") if isinstance(grade.report, Mapping) else None
    test_evidence = trimem.get("test_evidence") if isinstance(trimem, Mapping) else None
    if not isinstance(test_evidence, Mapping):
        raise BenchmarkExecutionError("official grader returned no actual test evidence")
    result = []
    for name in ("test_output", "official_test_status"):
        source_reference = test_evidence.get(name)
        if not isinstance(source_reference, Mapping):
            raise BenchmarkExecutionError(f"official grader returned no {name} reference")
        relative = source_reference.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise BenchmarkExecutionError(f"official grader returned unsafe {name} reference")
        source = (grader_root / relative).resolve()
        if grader_root.resolve() not in source.parents or not source.is_file():
            raise BenchmarkExecutionError(f"official grader {name} evidence is missing")
        reference = evidence_reference(task_dir, source)
        if (
            reference.get("sha256") != source_reference.get("sha256")
            or reference.get("bytes") != source_reference.get("bytes")
            or reference.get("bytes", 0) <= 0
            or not source.read_bytes().strip()
        ):
            raise BenchmarkExecutionError(f"official grader {name} evidence digest/size mismatch")
        result.append(reference)
    summary = test_evidence.get("summary")
    if not isinstance(summary, Mapping):
        raise BenchmarkExecutionError("official grader returned no test-status summary")
    return result[0], result[1], dict(summary)


def _run_smoke_impl(
    approval_path: Path,
    output_root: Path,
    image_evidence_root: Path,
    lifecycle_holder: list[_SerialImageLifecycle],
) -> dict[str, Any]:
    validate_benchmark_environment()
    approval_raw = approval_path.read_bytes()
    approval = validate_exec_approval("grader-smoke", approval_path)
    if sha256_bytes(approval_raw) != approval.get("approval_artifact_sha256"):
        raise BenchmarkExecutionError("exact external approval bytes/hash mismatch")
    manifest = read_json(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    targets = _smoke_targets(manifest)
    rows = _rows_for_targets(targets, ROOT / ".trimem-exec/datasets")
    images, support = image_entries(require_benchmark=False)
    harnesses = prepare_harnesses(ROOT / ".trimem-exec/harnesses")
    output_root.mkdir(parents=True, exist_ok=True)
    lifecycle = _SerialImageLifecycle(
        approval=approval,
        evidence_root=image_evidence_root,
        targets=targets,
        images=images,
        support=support,
    )
    lifecycle_holder.append(lifecycle)
    restricted_approval_path = output_root / "restricted-external-approval.json"
    restricted_approval_path.write_bytes(approval_raw)
    try:
        restricted_approval_path.chmod(0o600)
    except OSError:
        pass
    write_json(output_root / "external-approval-evidence.json", {
        "approval_artifact_sha256": approval["approval_artifact_sha256"],
        "approved_request_sha256": approval["approved_request_sha256"],
        "approved_workflow_run_id": approval["approved_workflow_run_id"],
        "approved_workflow_run_attempt": approval["approved_workflow_run_attempt"],
        "freeze_sha256": approval["freeze_sha256"],
        "git_head": approval["git_head"],
        "phase": approval["phase"],
    })
    failures = []
    for index, target in enumerate(targets):
        lifecycle.before_target(index, target)
        source = rows[(target["benchmark_id"], target["instance_id"])]
        patch = _patch_for_target(target, source, manifest)
        patch_raw = patch.encode("utf-8")
        patch_sha256 = sha256_bytes(patch_raw)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", target["target_id"])
        task_dir = output_root / f"{index:03d}-{safe}"
        task_dir.mkdir(parents=True, exist_ok=True)
        restricted_patch_path = task_dir / "restricted-input" / "applied.patch"
        restricted_patch_path.parent.mkdir(parents=True, exist_ok=True)
        restricted_patch_path.write_bytes(patch_raw)
        try:
            restricted_patch_path.chmod(0o600)
        except OSError:
            pass
        applied_patch_ref = evidence_reference(task_dir, restricted_patch_path)
        grader = grader_factory(
            target, source, images[target["instance_id"]], harnesses,
            task_dir / "official-grader", f"smoke-{target['probe'].lower()}", support,
        )
        request = GradeRequest(
            task_id=target["target_id"], repository=target["repository"],
            base_commit=target["base_commit"], patch=patch,
            workspace=WorkspaceGraderContext(
                kind="official-grader-smoke-private-patch",
                repository_files={}, base_commit=target["base_commit"],
            ),
        )
        try:
            grade = grader.grade(request)
            execution_status = "SUCCESS"
        except GraderInvocationFailure as exc:
            grade = exc.result
            execution_status = "FAILURE"
            failures.append(target["target_id"])
        if not (
            execution_status == "SUCCESS"
            and grade.exit_code == 0
            and grade.official is True
            and grade.container_started is True
            and grade.status == "success"
        ):
            failures.append(target["target_id"])
        stdout_path, stderr_path, report_path = (
            task_dir / "stdout.txt", task_dir / "stderr.txt", task_dir / "report.json"
        )
        stdout_path.write_text(grade.stdout, encoding="utf-8", newline="\n")
        stderr_path.write_text(grade.stderr, encoding="utf-8", newline="\n")
        write_json(report_path, grade.report)
        patch_path = task_dir / "patch-evidence.json"
        write_json(patch_path, {
            "schema": "trimem/grader-smoke-patch-evidence/1.0",
            "mode": "OFFICIAL_GRADER_SMOKE_PRIVATE_PATCH",
            "probe": target["probe"],
            "patch_bytes": len(patch_raw),
            "patch_nonempty": True,
            "patch_sha256": patch_sha256,
            "restricted_applied_patch": applied_patch_ref,
            "noop_baseline_changed_paths": (
                [NOOP_BASELINE_PATH] if target["probe"] == "NOOP_BASELINE" else None
            ),
            "source_row_sha256": target["source_row_sha256"],
            "applied_patch_bytes_retained": "RESTRICTED_EVIDENCE_ONLY",
            "gold_or_test_bytes_public": False,
        })
        try:
            observed = observed_target_digest(grade)
        except BenchmarkExecutionError:
            observed = "UNPROVEN"
            failures.append(target["target_id"])
        grader_root = task_dir / "official-grader"
        test_output_ref, test_status_ref, test_summary = _grader_test_evidence(
            grade, task_dir=task_dir, grader_root=grader_root
        )
        trimem_report = grade.report.get("_trimem") if isinstance(grade.report, Mapping) else None
        if not isinstance(trimem_report, Mapping):
            raise BenchmarkExecutionError("official grader report has no evaluator evidence")
        tests_path = task_dir / "tests-evidence.json"
        write_json(tests_path, {
            "schema": "trimem/grader-smoke-tests-evidence/1.0",
            "official_test_status": {
                "bytes": test_status_ref["bytes"], "sha256": test_status_ref["sha256"],
            },
            "probe": target["probe"],
            "summary": test_summary,
            "target_id": target["target_id"],
            "test_output": {
                "bytes": test_output_ref["bytes"], "sha256": test_output_ref["sha256"],
            },
        })
        container_path = task_dir / "container-evidence.json"
        write_json(container_path, {
            "schema": "trimem/grader-smoke-container-evidence/1.0",
            "container_digest": grade.container_digest,
            "container_started": grade.container_started,
            "exit_code": grade.exit_code,
            "official": grade.official,
            "status": grade.status,
            "target_id": target["target_id"],
        })
        evaluator_path = task_dir / "evaluator-evidence.json"
        write_json(evaluator_path, {
            "schema": "trimem/grader-smoke-evaluator-evidence/1.0",
            "benchmark_id": trimem_report.get("benchmark_id"),
            "dataset_revision": trimem_report.get("dataset_revision"),
            "grader_id": grade.grader_id,
            "harness_revision": trimem_report.get("harness_revision"),
            "source_row_sha256": trimem_report.get("source_row_sha256"),
            "target_id": target["target_id"],
        })
        digest_path = task_dir / "digest-evidence.json"
        write_json(digest_path, {
            "schema": "trimem/grader-smoke-digest-evidence/1.0",
            "container_digest": grade.container_digest,
            "expected_image_digest": images[target["instance_id"]]["expected_digest"],
            "observed_image_digest": observed,
            "target_id": target["target_id"],
        })
        record = {
            "target_id": target["target_id"],
            "benchmark_id": target["benchmark_id"],
            "order_index": target["order_index"],
            "arm": target["probe"],
            "probe": target["probe"],
            "execution_status": execution_status,
            "grader_exit_code": grade.exit_code,
            "grader_id": grade.grader_id,
            "grader_status": grade.status,
            "grader_container_digest": grade.container_digest,
            "container_started": grade.container_started,
            "official_grader": grade.official,
            "resolved": grade.resolved,
            "patch_bytes": len(patch_raw),
            "patch_sha256": patch_sha256,
            "expected_image_digest": images[target["instance_id"]]["expected_digest"],
            "observed_image_digest": observed,
            "actual_accounting": {
                "model_gateway_calls": 0, "paid_model_calls": 0,
                "grader_calls": 1, "grader_containers": int(grade.container_started),
                "official_grader_runs": int(grade.official and grade.container_started),
            },
            "evidence": {
                "patch": evidence_reference(task_dir, patch_path),
                "tests": evidence_reference(task_dir, tests_path),
                "container": evidence_reference(task_dir, container_path),
                "evaluator": evidence_reference(task_dir, evaluator_path),
                "stdout": evidence_reference(task_dir, stdout_path),
                "stderr": evidence_reference(task_dir, stderr_path),
                "report": evidence_reference(task_dir, report_path),
                "digest": evidence_reference(task_dir, digest_path),
                "applied_patch": applied_patch_ref,
                "test_output": test_output_ref,
                "official_test_status": test_status_ref,
                "restricted_grader_raw": restricted_evidence_references(
                    task_dir, grader_root
                ),
            },
        }
        write_json(task_dir / f"{safe}.result.json", record)
        if grade.resolved is not target["expected_resolved"]:
            failures.append(target["target_id"])
        lifecycle.after_target(index, target)
    lifecycle.finish()
    official_runs = sum(
        read_json(path)["actual_accounting"]["official_grader_runs"]
        for path in output_root.rglob("*.result.json")
    )
    grader_containers = sum(
        read_json(path)["actual_accounting"]["grader_containers"]
        for path in output_root.rglob("*.result.json")
    )
    if official_runs != 12:
        failures.append("OFFICIAL_GRADER_RUN_COUNT")
    if grader_containers != 12:
        failures.append("GRADER_CONTAINER_COUNT")
    report = {
        "schema": "trimem/grader-smoke-execution/1.0",
        "expected_target_count": 12,
        "observed_target_count": len(targets),
        "probe_counts": {
            probe: sum(target["probe"] == probe for target in targets)
            for probe in ("GOLD", "NOOP_BASELINE")
        },
        "empty_patch_ids": [],
        "failures": sorted(set(failures)),
        "grader_containers": grader_containers,
        "official_grader_runs": official_runs,
        "patch_applied_count": 12 if not failures else 0,
        "tests_executed_count": 12 if not failures else 0,
        "digest_match_count": 12 if not failures else 0,
        "infrastructure_failure_count": 0 if not failures else len(set(failures)),
        "model_gateway_calls": 0,
        "paid_model_calls": 0,
        "status": "PASS" if not failures else "FAIL",
    }
    write_json(output_root / "smoke-execution-summary.json", report)
    if failures:
        raise BenchmarkExecutionError(f"grader smoke failed closed: {sorted(set(failures))}")
    return report


def run_smoke(
    approval_path: Path, output_root: Path, image_evidence_root: Path
) -> dict[str, Any]:
    lifecycle_holder: list[_SerialImageLifecycle] = []
    try:
        return _run_smoke_impl(
            approval_path, output_root, image_evidence_root, lifecycle_holder
        )
    except BaseException as exc:
        if lifecycle_holder:
            try:
                lifecycle_holder[0].abort(exc)
            except BaseException as cleanup_exc:
                if hasattr(exc, "add_note"):
                    exc.add_note(
                        "grader-smoke exact image cleanup/reporting also failed: "
                        f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                    )
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approval-file", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--image-evidence-dir", type=Path)
    parser.add_argument("--audit-checkout-map", type=Path)
    parser.add_argument("--audit-output", type=Path)
    args = parser.parse_args()
    try:
        audit_mode = args.audit_checkout_map is not None or args.audit_output is not None
        if audit_mode:
            if (
                args.audit_checkout_map is None
                or args.audit_output is None
                or args.approval_file is not None
                or args.output_dir is not None
                or args.image_evidence_dir is not None
            ):
                raise BenchmarkExecutionError(
                    "checkout audit requires only --audit-checkout-map and --audit-output"
                )
            report = audit_noop_baseline_checkouts(
                args.audit_checkout_map.resolve(), args.audit_output.resolve()
            )
        else:
            if (
                args.approval_file is None
                or args.output_dir is None
                or args.image_evidence_dir is None
            ):
                raise BenchmarkExecutionError(
                    "official smoke requires --approval-file, --output-dir, and "
                    "--image-evidence-dir"
                )
            report = run_smoke(
                args.approval_file.resolve(),
                args.output_dir.resolve(),
                args.image_evidence_dir.resolve(),
            )
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
