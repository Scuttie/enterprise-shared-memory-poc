"""Production-capable repository workspace backed by an isolated Git checkout.

The orchestrator owns checkout creation and sandboxing.  This module never
clones a repository, changes branches, or runs hidden tests.  It verifies the
expected base commit, exposes the frozen coding tools, and supports hash-bound
checkpoint resume through a Git patch.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import posixpath
import re
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Optional

from .accounting import canonical_bytes, sha256_bytes
from .workspace import (
    PublicCommandResult,
    PublicTestResult,
    SandboxCommandRunner,
    ToolExecutionError,
    WorkspaceGraderContext,
    _bounded_text_replacement,
    _validated_dag_revision_arguments,
)


TOOL_NAMES = frozenset({
    "list_files", "read_file", "search", "write_file", "replace_text",
    "run_public_tests", "run_command", "revise_subtask_dag", "complete_subtask",
})

_DIGEST_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]*@sha256:[0-9a-f]{64}$")


class DockerSandboxCommandRunner:
    """Run public repository commands in one immutable task image.

    No host shell is involved, the task checkout is the only host mount, the
    container receives no host environment variables, and networking is
    disabled.  The orchestrator must pull and independently inspect the exact
    digest before constructing this runner; ``--pull=never`` prevents this
    boundary from silently resolving a tag or downloading an image.
    """

    schema_version = "trimem/docker-command-runner/1.0"

    def __init__(
        self,
        image: str,
        *,
        docker_binary: str = "docker",
        container_workspace: str = "/testbed",
        max_timeout_seconds: int = 120,
        max_output_bytes_per_stream: int = 262_144,
        memory_limit: str = "8g",
        cpu_limit: str = "4",
        pids_limit: int = 1024,
        tmpfs_size_bytes: int = 1_073_741_824,
    ):
        if not _DIGEST_IMAGE.fullmatch(str(image)):
            raise ValueError("command runner image must be frozen by sha256 digest")
        if not docker_binary or not container_workspace.startswith("/"):
            raise ValueError("docker binary and absolute container workspace are required")
        if not 1 <= int(max_timeout_seconds) <= 3600:
            raise ValueError("max command timeout must be in 1..3600 seconds")
        if not 1024 <= int(max_output_bytes_per_stream) <= 16 * 1024 * 1024:
            raise ValueError("command output cap must be in 1024..16777216 bytes")
        if int(pids_limit) <= 0 or int(tmpfs_size_bytes) <= 0:
            raise ValueError("container resource limits must be positive")
        self.image = str(image)
        self.docker_binary = str(docker_binary)
        self.container_workspace = container_workspace.rstrip("/") or "/workspace"
        self.max_timeout_seconds = int(max_timeout_seconds)
        self.max_output_bytes_per_stream = int(max_output_bytes_per_stream)
        self.memory_limit = str(memory_limit)
        self.cpu_limit = str(cpu_limit)
        self.pids_limit = int(pids_limit)
        self.tmpfs_size_bytes = int(tmpfs_size_bytes)
        self.content_hash = sha256_bytes(canonical_bytes({
            "schema": self.schema_version,
            "image": self.image,
            "docker_binary": self.docker_binary,
            "container_workspace": self.container_workspace,
            "network": "none",
            "pull": "never",
            "host_environment": "fixed-allowlist-for-docker-cli-only; none forwarded to container",
            "container_environment": {
                "CI": "1",
                "HOME": "/tmp/trimem-home",
                "PYTHONDONTWRITEBYTECODE": "1",
                "TMPDIR": "/tmp",
            },
            "root_filesystem": "read_only_except_checkout_and_tmpfs",
            "checkout_git_metadata": "nested_read_only_bind",
            "max_timeout_seconds": self.max_timeout_seconds,
            "max_output_bytes_per_stream": self.max_output_bytes_per_stream,
            "memory_limit": self.memory_limit,
            "cpu_limit": self.cpu_limit,
            "pids_limit": self.pids_limit,
            "tmpfs_size_bytes": self.tmpfs_size_bytes,
            "cap_drop": "ALL",
            "no_new_privileges": True,
        }))

    def run(
        self,
        root: Path,
        argv: tuple[str, ...],
        *,
        cwd: Optional[str],
        timeout_seconds: int,
    ) -> PublicCommandResult:
        checkout = Path(root).resolve(strict=True)
        git_metadata = (checkout / ".git").resolve(strict=True)
        if not checkout.is_dir() or not git_metadata.is_dir():
            raise ToolExecutionError("command root is not a Git checkout")
        if "," in str(checkout):
            raise ToolExecutionError("Docker mount source containing a comma is unsupported")
        if not argv or any(not isinstance(item, str) or not item or "\x00" in item for item in argv):
            raise ToolExecutionError("command argv is invalid")
        timeout = int(timeout_seconds)
        if not 1 <= timeout <= self.max_timeout_seconds:
            raise ToolExecutionError("command timeout exceeds the frozen runner cap")
        workdir = self.container_workspace
        if cwd:
            relative = _safe_relative(cwd)
            local_cwd = (checkout / Path(relative)).resolve(strict=True)
            if checkout not in local_cwd.parents or not local_cwd.is_dir():
                raise ToolExecutionError("command cwd is outside the checkout or not a directory")
            workdir = posixpath.join(workdir, relative)

        fd, cid_name = tempfile.mkstemp(prefix="trimem-docker-cid-")
        os.close(fd)
        os.unlink(cid_name)  # Docker requires a not-yet-existing cidfile.
        command = [
            self.docker_binary, "run", "--rm", "--pull=never", "--cidfile", cid_name,
            "--network", "none", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", str(self.pids_limit),
            "--memory", self.memory_limit, "--cpus", self.cpu_limit,
            "--read-only", "--env", "CI=1", "--env", "HOME=/tmp/trimem-home",
            "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "TMPDIR=/tmp",
            "--tmpfs", f"/tmp:rw,nosuid,nodev,size={self.tmpfs_size_bytes}",
            "--mount", f"type=bind,source={checkout},target={self.container_workspace}",
            "--mount", (
                f"type=bind,source={git_metadata},"
                f"target={self.container_workspace}/.git,readonly"
            ),
            "--workdir", workdir, "--entrypoint", argv[0], self.image, *argv[1:],
        ]
        cli_env = _docker_cli_environment()
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=cli_env,
        )
        stdout = bytearray()
        stderr = bytearray()
        overflow = threading.Event()

        def collect(stream, sink: bytearray) -> None:
            assert stream is not None
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return
                remaining = self.max_output_bytes_per_stream - len(sink)
                if remaining > 0:
                    sink.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()
                    return

        threads = [
            threading.Thread(target=collect, args=(process.stdout, stdout), daemon=True),
            threading.Thread(target=collect, args=(process.stderr, stderr), daemon=True),
        ]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + timeout
        timed_out = False
        output_truncated = False
        try:
            while process.poll() is None:
                if overflow.is_set():
                    output_truncated = True
                    process.kill()
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    process.kill()
                    break
                time.sleep(0.02)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if overflow.is_set():
                output_truncated = True
            if timed_out or output_truncated:
                self._remove_container(cid_name, cli_env)
        finally:
            for thread in threads:
                thread.join(timeout=1)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            if os.path.exists(cid_name):
                os.unlink(cid_name)

        if timed_out:
            exit_code = 124
            stderr.extend(b"\ncommand exceeded frozen timeout")
        elif output_truncated:
            exit_code = 125
            stderr.extend(b"\ncommand exceeded frozen output cap")
        else:
            exit_code = int(process.returncode or 0)
        return PublicCommandResult(
            exit_code=exit_code,
            stdout=bytes(stdout).decode("utf-8", errors="replace"),
            stderr=bytes(stderr[:self.max_output_bytes_per_stream]).decode("utf-8", errors="replace"),
            timed_out=timed_out,
            output_truncated=output_truncated,
        )

    def _remove_container(self, cid_name: str, environment: Mapping[str, str]) -> None:
        try:
            cid = Path(cid_name).read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            return
        if not re.fullmatch(r"[0-9a-f]{12,64}", cid):
            return
        subprocess.run(
            [self.docker_binary, "rm", "-f", cid],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=dict(environment),
            check=False,
            timeout=15,
        )


class GitCheckoutWorkspace:
    """Tool implementation for one disposable, already checked-out repository."""

    def __init__(
        self,
        root: str | Path,
        *,
        base_commit: str,
        public_test: Optional[Callable[[Path], PublicTestResult]] = None,
        command_runner: Optional[SandboxCommandRunner] = None,
        max_read_bytes: int = 131_072,
        max_search_hits: int = 100,
        allow_checkpoint_recovery: bool = False,
    ):
        self.root = Path(root).resolve()
        self.base_commit = str(base_commit)
        self.public_test = public_test
        self.command_runner = command_runner
        self.max_read_bytes = int(max_read_bytes)
        self.max_search_hits = int(max_search_hits)
        self.allow_checkpoint_recovery = bool(allow_checkpoint_recovery)
        if not self.root.is_dir() or not (self.root / ".git").exists():
            raise ToolExecutionError("workspace is not a Git checkout")
        if self.max_read_bytes <= 0 or self.max_search_hits <= 0:
            raise ValueError("workspace read/search caps must be positive")
        if command_runner is not None:
            digest = getattr(command_runner, "content_hash", None)
            if (
                not isinstance(command_runner, SandboxCommandRunner)
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise ValueError("sandbox command runner must expose a sha256 content hash")
        observed = self._git("rev-parse", "HEAD").stdout.strip()
        if observed != self.base_commit:
            raise ToolExecutionError("workspace HEAD differs from frozen base commit")

    @property
    def tool_names(self) -> frozenset[str]:
        return TOOL_NAMES

    def execute(self, tool: str, arguments: dict) -> dict:
        if tool not in TOOL_NAMES:
            raise ToolExecutionError("unknown tool")
        if tool == "list_files":
            _exact_arguments(arguments, set())
            return {"files": self._repository_files()}
        if tool == "read_file":
            _optional_arguments(arguments, {"path"}, {"start_line", "max_lines"})
            path = self._path(arguments["path"], must_exist=True)
            if not path.is_file():
                raise ToolExecutionError("path is not a file")
            return self._read_file_window(path, arguments)
        if tool == "search":
            if set(arguments) not in ({"query"}, {"query", "path"}):
                raise ToolExecutionError("search expects query and optional path")
            query = arguments.get("query")
            if not isinstance(query, str) or not query:
                raise ToolExecutionError("search query must be non-empty")
            requested = arguments.get("path")
            prefix = None if requested is None else self._relative(arguments["path"])
            hits = []
            for relative in self._repository_files():
                if prefix is not None and relative != prefix and not relative.startswith(prefix.rstrip("/") + "/"):
                    continue
                path = self._path(relative, must_exist=True)
                if not path.is_file() or path.stat().st_size > self.max_read_bytes:
                    continue
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except UnicodeDecodeError:
                    continue
                for line_no, line in enumerate(lines, 1):
                    if query in line:
                        hits.append({"path": relative, "line": line_no, "text": line[:1000]})
                        if len(hits) >= self.max_search_hits:
                            return {"query": query, "hits": hits, "truncated": True}
            return {"query": query, "hits": hits, "truncated": False}
        if tool == "write_file":
            _exact_arguments(arguments, {"path", "content"})
            content = arguments.get("content")
            if not isinstance(content, str):
                raise ToolExecutionError("content must be text")
            path = self._path(arguments["path"], must_exist=False)
            if path.exists() and path.stat().st_size > 16_384:
                raise ToolExecutionError("FULL_FILE_REWRITE_TOO_LARGE_USE_REPLACE_TEXT")
            path.parent.mkdir(parents=True, exist_ok=True)
            new_file = not path.exists()
            path.write_text(content, encoding="utf-8", newline="\n")
            relative = path.relative_to(self.root).as_posix()
            if new_file:
                self._git("add", "--intent-to-add", "--", relative)
            return {
                "path": relative,
                "content_hash": sha256_bytes(content.encode("utf-8")),
                "bytes": len(content.encode("utf-8")),
            }
        if tool == "replace_text":
            path = self._path(arguments.get("path") if isinstance(arguments, dict) else None, must_exist=True)
            if not path.is_file():
                raise ToolExecutionError("replace_text requires an existing editable file")
            try:
                raw = path.read_bytes()
                current = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ToolExecutionError("binary/non-UTF-8 file is not editable") from exc
            relative = path.relative_to(self.root).as_posix()
            replacement, result = _bounded_text_replacement(relative, current, arguments)
            encoded = replacement.encode("utf-8")
            descriptor, temp_name = tempfile.mkstemp(prefix=".trimem-replace-", dir=path.parent)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temp_name, path.stat().st_mode)
                os.replace(temp_name, path)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            return result
        if tool == "run_public_tests":
            _exact_arguments(arguments, set())
            if self.public_test is None:
                return {
                    "passed": False,
                    "exit_code": 2,
                    "stdout": "",
                    "stderr": "public test runner unavailable; hidden grader is not exposed",
                }
            result = self.public_test(self.root)
            if not isinstance(result, PublicTestResult):
                raise ToolExecutionError("public test runner returned an invalid result")
            return {
                "passed": result.passed,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        if tool == "run_command":
            _optional_arguments(arguments, {"argv"}, {"cwd", "timeout_seconds"})
            argv, cwd, timeout = _validated_command_arguments(arguments)
            if self.command_runner is None:
                raise ToolExecutionError("production sandbox command runner is not configured")
            result = self.command_runner.run(self.root, argv, cwd=cwd, timeout_seconds=timeout)
            if not isinstance(result, PublicCommandResult):
                raise ToolExecutionError("sandbox command runner returned an invalid result")
            return {
                "argv": list(argv),
                "cwd": cwd or ".",
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timed_out": result.timed_out,
                "output_truncated": result.output_truncated,
            }
        if tool == "revise_subtask_dag":
            return _validated_dag_revision_arguments(arguments)
        if tool == "complete_subtask":
            _exact_arguments(arguments, {"evidence"})
            evidence = arguments.get("evidence")
            if not isinstance(evidence, str) or not evidence.strip():
                raise ToolExecutionError("completion evidence must be non-empty")
            return {"completed": True, "evidence": evidence.strip()}
        raise AssertionError("unreachable")

    def patch(self) -> str:
        # Intent-to-add makes new files visible without staging their content.
        for relative in self._untracked_files():
            self._git("add", "--intent-to-add", "--", relative)
        return self._git("diff", "--binary", "--no-ext-diff", "--", check=True).stdout

    def checkpoint_state(self) -> Mapping[str, Any]:
        patch = self.patch()
        return {
            "kind": "trimem-git-checkout-workspace-v1",
            "base_commit": self.base_commit,
            "patch": patch,
            "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
        }

    def _checkpoint_patch(self, state: Mapping[str, Any]) -> str:
        if set(state) != {"kind", "base_commit", "patch", "patch_sha256"}:
            raise ToolExecutionError("Git workspace checkpoint shape mismatch")
        if state.get("kind") != "trimem-git-checkout-workspace-v1" or state.get("base_commit") != self.base_commit:
            raise ToolExecutionError("Git workspace checkpoint identity mismatch")
        patch = state.get("patch")
        digest = state.get("patch_sha256")
        if not isinstance(patch, str) or hashlib.sha256(patch.encode("utf-8")).hexdigest() != digest:
            raise ToolExecutionError("Git workspace checkpoint patch hash mismatch")
        return patch

    def _replace_patch(self, patch: str) -> None:
        """Replace only this disposable checkout's uncommitted patch.

        Reversing the exact observed patch avoids branch movement, index reset,
        or touching anything outside the task checkout.  Every transition is
        verified by regenerating Git's binary diff.
        """

        current = self.patch()
        if current:
            self._git(
                "apply", "--reverse", "--binary", "--whitespace=nowarn", "-",
                input_text=current,
            )
        if self.patch():
            raise ToolExecutionError("Git workspace patch rollback was not exact")
        if patch:
            self._git("apply", "--binary", "--whitespace=nowarn", "-", input_text=patch)
        if self.patch() != patch:
            raise ToolExecutionError("Git workspace checkpoint patch replacement differed")

    def restore_checkpoint(self, state: Mapping[str, Any]) -> None:
        patch = self._checkpoint_patch(state)
        current = self.patch()
        if current == patch:
            return
        if current:
            raise ToolExecutionError("Git workspace is neither clean nor checkpoint-identical")
        if patch:
            self._git("apply", "--binary", "--whitespace=nowarn", "-", input_text=patch)
            if self.patch() != patch:
                raise ToolExecutionError("restored Git patch differs from checkpoint")

    def recover_completed_tool(
        self,
        state: Mapping[str, Any],
        *,
        tool: str,
        arguments: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> None:
        """Prove and roll forward one fsynced tool-result crash suffix.

        Only deterministic ``write_file`` and ``replace_text`` mutations are recoverable.  The
        factory marks its roots as disposable benchmark checkouts; direct
        workspaces remain fail-closed.  An unrelated dirty patch is restored to
        the prior checkpoint and rejected rather than silently preserved.
        """

        checkpoint_patch = self._checkpoint_patch(state)
        if tool not in {"write_file", "replace_text"}:
            self.restore_checkpoint(state)
            return
        if not self.allow_checkpoint_recovery:
            raise ToolExecutionError(
                "completed-tool recovery requires a disposable checkout factory"
            )
        if tool == "write_file":
            if set(arguments) != {"path", "content"} or not isinstance(arguments.get("content"), str):
                raise ToolExecutionError("recovered write_file arguments are invalid")
            if set(result) != {"path", "content_hash", "bytes"}:
                raise ToolExecutionError("recovered write_file result is invalid")
        else:
            if set(arguments) != {"path", "expected_file_sha256", "old_text", "new_text"}:
                raise ToolExecutionError("recovered replace_text arguments are invalid")
            if set(result) != {"path", "prior_sha256", "new_sha256", "old_bytes", "new_bytes", "replacements"}:
                raise ToolExecutionError("recovered replace_text result is invalid")

        observed_after_crash = self.patch()
        try:
            self._replace_patch(checkpoint_patch)
            replayed = self.execute(tool, dict(arguments))
            deterministic_patch = self.patch()
            if replayed != dict(result):
                raise ToolExecutionError("recovered write_file result differs from evidence")
            if observed_after_crash not in {checkpoint_patch, deterministic_patch}:
                raise ToolExecutionError(
                    "post-crash Git patch is not the checkpoint or evidenced write"
                )
        except BaseException:
            self._replace_patch(checkpoint_patch)
            raise

    def rollback_checkpoint(self, state: Mapping[str, Any]) -> None:
        """Restore a prior patch only for a factory-owned disposable checkout."""

        if not self.allow_checkpoint_recovery:
            raise ToolExecutionError(
                "checkpoint rollback requires a disposable checkout factory"
            )
        self._replace_patch(self._checkpoint_patch(state))

    def grader_context(self, *, base_commit: str) -> WorkspaceGraderContext:
        if base_commit != self.base_commit:
            raise ToolExecutionError("grader base commit differs from workspace")
        return WorkspaceGraderContext(
            kind="git_checkout",
            repository_files={},
            checkout_root=str(self.root),
            base_commit=self.base_commit,
        )

    def _repository_files(self) -> list[str]:
        tracked = self._git("ls-files", "-z").stdout.split("\0")
        return sorted(set(item for item in tracked if item) | set(self._untracked_files()))

    def _untracked_files(self) -> list[str]:
        values = self._git("ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0")
        return sorted(item for item in values if item)

    def _read_file_window(self, path: Path, arguments: Mapping[str, Any]) -> dict[str, Any]:
        start = arguments.get("start_line", 1)
        maximum = arguments.get("max_lines", 400)
        if isinstance(start, bool) or not isinstance(start, int) or start < 1:
            raise ToolExecutionError("start_line must be a positive integer")
        if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 2000:
            raise ToolExecutionError("max_lines must be an integer in 1..2000")
        selected: list[str] = []
        selected_bytes = 0
        total_lines = 0
        try:
            with path.open("r", encoding="utf-8", errors="strict", newline="") as stream:
                for total_lines, line in enumerate(stream, 1):
                    if total_lines < start or len(selected) >= maximum:
                        continue
                    encoded = line.encode("utf-8")
                    if selected_bytes + len(encoded) > self.max_read_bytes:
                        break
                    selected.append(line)
                    selected_bytes += len(encoded)
                # If the output cap ended the first pass early, continue only
                # to count lines. This makes chunk metadata deterministic.
                for total_lines, _ in enumerate(stream, total_lines + 1):
                    pass
        except UnicodeDecodeError as exc:
            raise ToolExecutionError("binary/non-UTF-8 file is not readable") from exc
        if not selected and total_lines >= start:
            raise ToolExecutionError("selected line exceeds frozen read byte cap")
        end = start + len(selected) - 1
        return {
            "path": path.relative_to(self.root).as_posix(),
            "content": "".join(selected),
            "start_line": start,
            "end_line": end,
            "returned_start_line": start,
            "returned_end_line": end,
            "total_file_bytes": path.stat().st_size,
            "full_file_sha256": sha256_bytes(path.read_bytes()),
            "total_lines": total_lines,
            "truncated": end < total_lines,
        }

    def _relative(self, value: object) -> str:
        if not isinstance(value, str) or not value or "\\" in value:
            raise ToolExecutionError("invalid repository path")
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
            raise ToolExecutionError("repository path traversal refused")
        normalized = path.as_posix()
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if not normalized:
            raise ToolExecutionError("invalid repository path")
        return normalized

    def _path(self, value: object, *, must_exist: bool) -> Path:
        relative = self._relative(value)
        target = (self.root / relative).resolve(strict=must_exist)
        if self.root not in target.parents:
            raise ToolExecutionError("repository path escaped checkout")
        # Existing symlinks can otherwise turn a write into an out-of-tree edit.
        current = self.root
        for part in Path(relative).parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ToolExecutionError("symlink repository paths are refused")
        return target

    def _git(self, *args: str, check: bool = True, input_text: Optional[str] = None):
        if input_text is None:
            raw = subprocess.run(
                ["git", "-C", str(self.root), *args],
                capture_output=True, text=True, encoding="utf-8", errors="strict", check=False,
            )
            completed = raw
        else:
            # Text-mode stdin translates LF to CRLF on Windows and corrupts a
            # canonical Git patch. Send exact UTF-8 bytes on every platform.
            raw = subprocess.run(
                ["git", "-C", str(self.root), *args],
                input=input_text.encode("utf-8"), capture_output=True, check=False,
            )
            completed = SimpleNamespace(
                returncode=raw.returncode,
                stdout=raw.stdout.decode("utf-8", errors="strict"),
                stderr=raw.stderr.decode("utf-8", errors="strict"),
            )
        if check and completed.returncode != 0:
            raise ToolExecutionError(
                "Git workspace command failed: " + (completed.stderr.strip() or str(completed.returncode))
            )
        return completed


class GitCheckoutWorkspaceFactory:
    """Immutable task/base-commit to disposable-checkout binding."""

    def __init__(
        self,
        checkout_roots: Mapping[str, str | Path],
        base_commits: Mapping[str, str],
        *,
        public_tests: Optional[Mapping[str, Callable[[Path], PublicTestResult]]] = None,
        public_test_runner_hashes: Optional[Mapping[str, str]] = None,
        command_runners: Optional[Mapping[str, SandboxCommandRunner]] = None,
        max_read_bytes: int = 131_072,
        max_search_hits: int = 100,
    ):
        if set(checkout_roots) != set(base_commits) or not checkout_roots:
            raise ValueError("checkout roots and base commits require the same non-empty task set")
        self.checkout_roots = {str(key): Path(value).resolve() for key, value in checkout_roots.items()}
        self.base_commits = {str(key): str(value) for key, value in base_commits.items()}
        self.public_tests = dict(public_tests or {})
        self.public_test_runner_hashes = dict(public_test_runner_hashes or {})
        self.command_runners = dict(command_runners or {})
        if set(self.public_tests) != set(self.public_test_runner_hashes):
            raise ValueError("every public test runner requires an immutable content hash")
        for digest in self.public_test_runner_hashes.values():
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise ValueError("public test runner hash must be sha256")
        if set(self.command_runners) - set(self.checkout_roots):
            raise ValueError("sandbox command runner references an unknown task")
        command_runner_hashes: dict[str, str] = {}
        for task_id, runner in self.command_runners.items():
            digest = getattr(runner, "content_hash", None)
            if (
                not isinstance(runner, SandboxCommandRunner)
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise ValueError("every sandbox command runner requires a sha256 content hash")
            command_runner_hashes[task_id] = digest
        # Host-only Git editing remains useful for credential-free tests, but
        # a benchmark factory is production-capable only when every task has a
        # digest-bound isolated command runner.
        self.production_capable = bool(self.checkout_roots) and set(self.command_runners) == set(
            self.checkout_roots
        )
        self.max_read_bytes = int(max_read_bytes)
        self.max_search_hits = int(max_search_hits)
        self.content_hash = sha256_bytes(canonical_bytes({
            "factory": "trimem-git-checkout-workspace-factory-v1",
            "task_base_commits": self.base_commits,
            "public_test_runner_hashes": self.public_test_runner_hashes,
            "sandbox_command_runner_hashes": command_runner_hashes,
            "production_capable": self.production_capable,
            "checkpoint_crash_recovery": "deterministic-completed-edit-roll-forward-v2",
            "max_read_bytes": self.max_read_bytes,
            "max_search_hits": self.max_search_hits,
            "tool_names": sorted(TOOL_NAMES),
        }))

    def __call__(self, task: Any) -> GitCheckoutWorkspace:
        if task.task_id not in self.checkout_roots or self.base_commits.get(task.task_id) != task.commit:
            raise ToolExecutionError("task is not bound to this frozen checkout factory")
        return GitCheckoutWorkspace(
            self.checkout_roots[task.task_id],
            base_commit=task.commit,
            public_test=self.public_tests.get(task.task_id),
            command_runner=self.command_runners.get(task.task_id),
            max_read_bytes=self.max_read_bytes,
            max_search_hits=self.max_search_hits,
            allow_checkpoint_recovery=True,
        )


def _exact_arguments(arguments: object, expected: set[str]) -> None:
    if not isinstance(arguments, dict) or set(arguments) != expected:
        raise ToolExecutionError("arguments must be exactly %r" % sorted(expected))


def _optional_arguments(arguments: object, required: set[str], optional: set[str]) -> None:
    if not isinstance(arguments, dict):
        raise ToolExecutionError("arguments must be an object")
    keys = set(arguments)
    if not required <= keys or keys - required - optional:
        raise ToolExecutionError(
            "arguments require %r and allow only %r as optional"
            % (sorted(required), sorted(optional))
        )


def _validated_command_arguments(
    arguments: Mapping[str, Any],
) -> tuple[tuple[str, ...], Optional[str], int]:
    argv = arguments.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or len(argv) > 64
        or any(not isinstance(item, str) or not item or "\x00" in item for item in argv)
        or sum(len(item.encode("utf-8")) for item in argv) > 32_768
    ):
        raise ToolExecutionError("argv must be 1..64 non-empty strings within 32768 UTF-8 bytes")
    cwd = arguments.get("cwd")
    if cwd in (".", "./"):
        cwd = None
    elif cwd is not None:
        cwd = _safe_relative(cwd)
    timeout = arguments.get("timeout_seconds", 120)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 120:
        raise ToolExecutionError("timeout_seconds must be an integer in 1..120")
    return tuple(argv), cwd, timeout


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ToolExecutionError("invalid repository path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
        raise ToolExecutionError("repository path traversal refused")
    normalized = path.as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized == ".":
        raise ToolExecutionError("invalid repository path")
    return normalized


def _docker_cli_environment() -> dict[str, str]:
    # These values are consumed by the Docker *client* only.  None is passed to
    # the container, so API keys and benchmark credentials cannot cross the
    # tool boundary through the host process environment.
    allowed = {
        "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC",
        "TEMP", "TMP", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


__all__ = [
    "DockerSandboxCommandRunner",
    "GitCheckoutWorkspace",
    "GitCheckoutWorkspaceFactory",
    "TOOL_NAMES",
]
