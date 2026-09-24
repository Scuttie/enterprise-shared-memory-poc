"""Trusted broker evidence for a predeclared public RED/GREEN workflow.

The verifier observes concrete stages, preserves original training scope, and
calls the real Gate A/B authority. A passing issue alone cannot create a skill.
This is one bounded public regression workflow, not a general repair skill or
evidence that its implementation assumptions hold at future target revisions.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from enterprise_memory.trimem.skill_memory import EpisodeEvidence, ProcedureTemplate, SkillMemoryStore
from trimem_skhynix_codex_learning import canonical, sha, file_sha, read, _read_training

SCHEMA = "skhynix/native-procedure-declaration/1.0"
ATTESTATION_SCHEMA = "skhynix/native-procedure-attestation/1.0"
EXPORT_SCHEMA = "skhynix/native-promoted-procedure/1.0"
PROCEDURE_ID = "python-public-regression-red-green-v1"
TEMPLATE = ProcedureTemplate(
    subgoal_signature="Python regression workflow: reproduce an assertion failure, repair implementation, and verify focused public tests",
    parameters=("source_path", "test_path", "test_argv"),
    preconditions=(
        "Inspect the current source {source_path} and existing public suite {test_path} in a clean base checkout.",
        "Use the checked public Python and test runner; run {test_argv} with no hidden tests or network.",
        "The workflow was verified on independent training sessions. Validate its runtime prerequisites on the current revision.",
    ),
    steps=(
        "Inspect source {source_path} and public suite {test_path} before modification.",
        "Add an assertion regression in {test_path} while keeping all implementation files unchanged.",
        "Run {test_argv} and observe an assertion failure in the newly added regression.",
        "Modify implementation {source_path} while retaining identical regression test bytes.",
        "Run the identical command {test_argv} and observe passing public tests.",
    ),
    verification_command="{test_argv}", language="python",
)
PUBLIC_INSTRUCTIONS = (
    "Before any file modification, inspect the implementation and its existing public test module, "
    "then call begin_procedure with source_path, test_path and test_argv. test_argv is a canonical JSON "
    "string containing [public_python, 'bin/test', test_path, '--no-colors', '--no-subprocess']. "
    "Add a new top-level undecorated test_ function containing a direct assertion. Keep every implementation "
    "file unchanged and run that command to demonstrate a real assertion failure in the new test. "
    "Then repair only source_path; do not change the regression module again. Run exactly the same command "
    "until it succeeds with at least one passing test. Submit the verified patch with no subsequent edits. "
    "A timeout, import error, syntax error or missing dependency does not count as the RED observation. "
    "If the issue cannot be handled under this workflow, report the limitation; do not invent evidence."
)

# Version one remains an immutable historical evidence contract. Named tests
# require their own declaration, template and receipt identities.
NAMED_PROCEDURE_ID = "python-public-named-regression-red-green-v2"
NAMED_SCHEMA = "skhynix/native-procedure-declaration/2.0"
NAMED_ATTESTATION_SCHEMA = "skhynix/native-procedure-attestation/2.0"
NAMED_EXPORT_SCHEMA = "skhynix/native-promoted-procedure/2.0"
NAMED_TEMPLATE = ProcedureTemplate(
    subgoal_signature="Python regression workflow: reproduce an assertion failure, repair implementation, and verify one declared public regression test",
    parameters=("source_path", "test_path", "test_name", "test_argv"),
    preconditions=(
        "Inspect the current source {source_path} and existing public suite {test_path} in a clean base checkout.",
        "Before edits or commands, bind one fresh regression name {test_name} and its checked public command {test_argv}.",
        "The public keyword filter must select only the newly declared regression. Validate the checked Python and runner on the current revision.",
    ),
    steps=(
        "Inspect source {source_path} and public suite {test_path} before modification.",
        "Append one fresh assertion regression {test_name} to {test_path}, preserving existing tests and all implementation files.",
        "Run {test_argv} and observe one failure at a direct assertion in {test_name}.",
        "Modify implementation {source_path} while retaining identical regression test bytes.",
        "Run the identical command {test_argv} and observe the selected regression passing with no skips or exceptions.",
    ),
    verification_command="{test_argv}", language="python",
)
NAMED_PUBLIC_INSTRUCTIONS = (
    "Before any file modification or command, inspect the implementation and its existing public test module, "
    "then call begin_procedure with source_path, test_path, test_name and test_argv. Choose a fresh unique "
    "test_ function name absent from all existing identifiers and matching no other function name. test_argv "
    "is a canonical JSON string containing [public_python, 'bin/test', test_path, '--no-colors', "
    "'--no-subprocess', '-k', test_name]. Append exactly one new top-level undecorated synchronous "
    "zero-argument test function with a direct body assertion; it must not be a generator. Preserve every "
    "existing module statement. Put any needed new imports inside the new function; multiple assertions "
    "may be placed in that one function. Keep all implementation files unchanged and run the bound command. "
    "The selected test must be the sole executed test and fail at its direct assertion, with no exceptions, "
    "skips, timeout or truncated output. If the buggy call raises, record that outcome inside a handler and "
    "assert after leaving the handler, so the observed failure is the direct assertion rather than an exception. "
    "Then repair only source_path and retain identical test module bytes. "
    "Run exactly the same command until its sole selected test passes without errors, skips or expected "
    "failures. Submit that verified patch with no subsequent edits. Broader public checks are additional "
    "evidence; passing one named regression does not mean the whole module passed. Official grading must "
    "also resolve the submitted patch. Report limitations honestly if this workflow cannot be completed."
)

MULTI_SOURCE_PROCEDURE_ID = "python-public-multisource-named-regression-red-green-v3"
MULTI_SOURCE_SCHEMA = "skhynix/native-procedure-declaration/3.0"
MULTI_SOURCE_ATTESTATION_SCHEMA = "skhynix/native-procedure-attestation/3.0"
MULTI_SOURCE_EXPORT_SCHEMA = "skhynix/native-promoted-procedure/3.0"
MULTI_SOURCE_TEMPLATE = ProcedureTemplate(
    subgoal_signature="Python regression workflow: reproduce one assertion failure, repair predeclared implementation files, and verify one declared public regression test",
    parameters=("source_paths", "test_path", "test_name", "test_argv"),
    preconditions=(
        "Inspect every implementation file in {source_paths} and the existing public suite {test_path} in a clean base checkout.",
        "Before edits or commands, bind one to three implementation paths, one fresh regression name {test_name}, and its checked public command {test_argv}.",
        "The public keyword filter must select only the newly declared regression. Validate the checked Python and runner on the current revision.",
    ),
    steps=(
        "Inspect every implementation file in {source_paths} and public suite {test_path} before modification.",
        "Append one fresh assertion regression {test_name} to {test_path}, preserving existing tests and all implementation files.",
        "Run {test_argv} and observe one failure at a direct assertion in {test_name}.",
        "Modify one or more implementation files in {source_paths} while retaining identical regression test bytes.",
        "Run the identical command {test_argv} and observe the selected regression passing with no skips or exceptions.",
    ),
    verification_command="{test_argv}", language="python",
)
MULTI_SOURCE_PUBLIC_INSTRUCTIONS = (
    "Before any file modification or command, inspect each intended implementation file and the existing "
    "public test module, then call begin_procedure with source_paths, test_path, test_name and test_argv. "
    "source_paths is a canonical JSON string containing one to three sorted distinct existing implementation "
    ".py paths; no tests directory or test_ filename is allowed. Bind every implementation path you may "
    "repair now; paths cannot be added later. The test module must be distinct from these paths. "
    "Choose a fresh unique test_ function name absent from all existing identifiers and matching no other "
    "function name. test_argv is a canonical JSON string containing [public_python, 'bin/test', test_path, "
    "'--no-colors', '--no-subprocess', '-k', test_name]. Append exactly one new top-level undecorated "
    "synchronous zero-argument test function with a direct body assertion; it must not be a generator. "
    "Preserve every existing module statement. Put any needed new imports inside the new function; "
    "multiple assertions may be placed in that one function. Keep all implementation files unchanged "
    "and run the bound command. The selected test must be the sole executed test and fail at its direct "
    "assertion, with no exceptions, skips, timeout or truncated output. If the buggy call raises, record "
    "that outcome inside a handler and assert after leaving the handler. Then repair only one or more "
    "prebound implementation files and retain identical test module bytes. Run exactly the same command "
    "until its sole selected test passes without errors, skips or expected failures. Broader public "
    "checks are additional evidence; after any further implementation edits, rerun the identical named "
    "command and submit that verified patch with no subsequent edits. Official grading must also resolve "
    "the submitted patch. Report limitations honestly if this workflow cannot be completed."
)


class ProcedureEvidenceError(ValueError):
    pass


def procedure_profile(procedure_id: str) -> dict:
    """Explicit allowlist; no unknown version can fall back to historical v1."""
    if procedure_id == PROCEDURE_ID:
        return {"procedure_id": PROCEDURE_ID, "schema": SCHEMA,
            "attestation_schema": ATTESTATION_SCHEMA, "export_schema": EXPORT_SCHEMA,
            "template": TEMPLATE, "public_instructions": PUBLIC_INSTRUCTIONS}
    if procedure_id == NAMED_PROCEDURE_ID:
        return {"procedure_id": NAMED_PROCEDURE_ID, "schema": NAMED_SCHEMA,
            "attestation_schema": NAMED_ATTESTATION_SCHEMA, "export_schema": NAMED_EXPORT_SCHEMA,
            "template": NAMED_TEMPLATE, "public_instructions": NAMED_PUBLIC_INSTRUCTIONS}
    if procedure_id == MULTI_SOURCE_PROCEDURE_ID:
        return {"procedure_id": MULTI_SOURCE_PROCEDURE_ID, "schema": MULTI_SOURCE_SCHEMA,
            "attestation_schema": MULTI_SOURCE_ATTESTATION_SCHEMA, "export_schema": MULTI_SOURCE_EXPORT_SCHEMA,
            "template": MULTI_SOURCE_TEMPLATE, "public_instructions": MULTI_SOURCE_PUBLIC_INSTRUCTIONS}
    raise ProcedureEvidenceError("unsupported procedure version")


def _observation_contract(named: bool = False, multi_source: bool = False) -> dict:
    contract = {
        "source_scope": "PUBLIC_TRAINING_BROKER_ONLY", "binding_before_any_modification": True,
        "red": "ADDED_ASSERTION_FAILURE_WITH_ONLY_TEST_MODULE_CHANGED",
        "green": "IDENTICAL_TEST_BYTES_AND_ARGV_WITH_IMPLEMENTATION_CHANGED",
        "final": "GREEN_PATCH_IDENTICAL_TO_OFFICIALLY_RESOLVED_SUBMISSION",
        "contributors": "DISTINCT_NATIVE_CODEX_SESSION_IDS_NOT_INDEPENDENT_HUMAN_USERS",
        "target_applicability": "SEPARATE_PUBLIC_RUNTIME_COMPATIBILITY_CERTIFICATE_REQUIRED",
    }
    if named:
        contract.update(test_scope="ONE_PREBOUND_FRESH_NAMED_REGRESSION_ONLY",
            existing_tests="ORDERED_BASE_MODULE_AST_UNCHANGED_WITH_ONE_APPENDED_FUNCTION",
            selection="UNIQUE_SUBSTRING_MATCH_WITH_EXACTLY_ONE_EXECUTED_TEST",
            red="ONE_FAILURE_AT_A_DIRECT_ASSERTION_IN_THE_PREBOUND_TEST",
            green="ONE_PASS_NO_SKIPS_EXCEPTIONS_OR_TRUNCATION_IDENTICAL_TEST_BYTES_AND_ARGV",
            target_applicability="SEPARATE_PUBLIC_RUNTIME_AND_NAMED_SELECTION_CERTIFICATE_REQUIRED")
    if multi_source:
        contract.update(implementation_scope="ONE_TO_THREE_PREBOUND_SORTED_EXISTING_IMPLEMENTATION_PATHS",
            implementation_state="PER_FILE_SHA256_MAP_AND_CANONICAL_MAP_DIGEST",
            red_implementation="ALL_IMPLEMENTATION_FILES_UNCHANGED",
            green_implementation="NONEMPTY_CHANGED_SUBSET_OF_PREBOUND_IMPLEMENTATION_PATHS")
    return contract


def _write_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def declare_procedure(output_path: Path, authority_org_id: str, training_task_ids: list[str],
                      procedure_version: str = "1") -> dict:
    if (not isinstance(authority_org_id, str) or not authority_org_id.strip() or
            len(training_task_ids) < 2 or len(set(training_task_ids)) != len(training_task_ids) or
            any(not isinstance(value, str) or not value.strip() for value in training_task_ids)):
        raise ProcedureEvidenceError("declaration requires an authority and distinct training task identities")
    versions = {"1": PROCEDURE_ID, "2": NAMED_PROCEDURE_ID, "3": MULTI_SOURCE_PROCEDURE_ID}
    if procedure_version not in versions:
        raise ProcedureEvidenceError("unsupported procedure version")
    profile = procedure_profile(versions[procedure_version])
    template = profile["template"]
    declaration = {"schema": profile["schema"], "procedure_id": profile["procedure_id"],
        "authority_org_id": authority_org_id, "training_task_ids": sorted(training_task_ids),
        "template": asdict(template), "template_hash": template.content_hash,
        "public_instructions": profile["public_instructions"],
        "observation_contract": _observation_contract(procedure_version in ("2", "3"), procedure_version == "3")}
    _write_new(Path(output_path), declaration)
    return {"path": str(Path(output_path).resolve()), "sha256": file_sha(Path(output_path)),
            "template_hash": template.content_hash, "procedure_id": profile["procedure_id"]}


def load_declaration(path: Path, expected_sha256: str, task_id: str | None = None) -> dict:
    path = Path(path)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or "") or file_sha(path) != expected_sha256:
        raise ProcedureEvidenceError("procedure declaration hash differs")
    declaration = read(path)
    profile = procedure_profile(declaration.get("procedure_id"))
    try:
        template = ProcedureTemplate(**declaration["template"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProcedureEvidenceError("invalid procedure template") from exc
    training = declaration.get("training_task_ids", [])
    if (declaration.get("schema") != profile["schema"] or
            template != profile["template"] or declaration.get("template_hash") != template.content_hash or
            declaration.get("public_instructions") != profile["public_instructions"] or
            not isinstance(declaration.get("authority_org_id"), str) or not declaration["authority_org_id"] or
            len(training) < 2 or len(set(training)) != len(training) or training != sorted(training)):
        raise ProcedureEvidenceError("unsupported or altered procedure declaration")
    if (profile["procedure_id"] in (NAMED_PROCEDURE_ID, MULTI_SOURCE_PROCEDURE_ID) and
            declaration.get("observation_contract") != _observation_contract(True,
                profile["procedure_id"] == MULTI_SOURCE_PROCEDURE_ID)):
        raise ProcedureEvidenceError("named procedure observation contract differs")
    if task_id is not None and task_id not in training:
        raise ProcedureEvidenceError("task is not a declared training task")
    return declaration


def _safe_path(value: Any) -> str:
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", value) or
            value.startswith("/") or any(part in ("..", ".git") for part in PurePosixPath(value).parts) or
            str(PurePosixPath(value)) != value or value in (".", "")):
        raise ProcedureEvidenceError("procedure paths must be safe canonical repository-relative paths")
    return value


def validate_bindings(declaration: dict, bindings: dict, public_python: str) -> dict:
    profile = procedure_profile(declaration.get("procedure_id"))
    template = profile["template"]
    multi_source = profile["procedure_id"] == MULTI_SOURCE_PROCEDURE_ID
    named = profile["procedure_id"] in (NAMED_PROCEDURE_ID, MULTI_SOURCE_PROCEDURE_ID)
    if declaration.get("schema") != profile["schema"] or declaration.get("template_hash") != template.content_hash:
        raise ProcedureEvidenceError("binding uses an unsupported template")
    if not isinstance(bindings, dict) or set(bindings) != set(template.parameters):
        raise ProcedureEvidenceError("bindings must contain exactly the declared procedure parameters")
    test = _safe_path(bindings["test_path"])
    if multi_source:
        raw_paths = bindings["source_paths"]
        try:
            sources = json.loads(raw_paths) if isinstance(raw_paths, str) else None
        except ValueError as exc:
            raise ProcedureEvidenceError("source_paths must be a canonical JSON string") from exc
        if (not isinstance(sources, list) or not 1 <= len(sources) <= 3 or
                any(not isinstance(path, str) for path in sources) or
                sources != sorted(set(sources)) or canonical(sources).decode() != raw_paths):
            raise ProcedureEvidenceError("source_paths must contain one to three sorted distinct canonical paths")
        sources = [_safe_path(path) for path in sources]
        if any("tests" in PurePosixPath(path).parts or PurePosixPath(path).name.startswith("test_") for path in sources):
            raise ProcedureEvidenceError("source_paths may contain only implementation files")
    else:
        sources = [_safe_path(bindings["source_path"])]
    if (test in sources or any(not source.endswith(".py") for source in sources) or
            not test.endswith(".py") or "/tests/" not in test):
        raise ProcedureEvidenceError("source and existing public Python test module must be distinct")
    if (not isinstance(public_python, str) or not public_python.startswith("/") or
            not Path(public_python).name.startswith("python")):
        raise ProcedureEvidenceError("public Python must be the declared absolute testbed executable")
    argv = [public_python, "bin/test", test, "--no-colors", "--no-subprocess"]
    if named:
        if (not isinstance(bindings["test_name"], str) or
                not re.fullmatch(r"test_[A-Za-z0-9_]{1,120}", bindings["test_name"])):
            raise ProcedureEvidenceError("named regression must have a bounded test_ identifier")
        argv.extend(("-k", bindings["test_name"]))
    expected = canonical(argv).decode("utf-8")
    if not isinstance(bindings["test_argv"], str):
        raise ProcedureEvidenceError("test_argv must be a canonical JSON string")
    try:
        supplied = json.loads(bindings["test_argv"])
    except (ValueError, TypeError) as exc:
        raise ProcedureEvidenceError("test_argv must be JSON") from exc
    if supplied != argv:
        raise ProcedureEvidenceError("test_argv differs from the declared focused public runner")
    result = {"test_path": test, "test_argv": expected}
    result.update({"source_paths": canonical(sources).decode()} if multi_source else {"source_path": sources[0]})
    if named:
        result["test_name"] = bindings["test_name"]
    return result


def _public_file(root: Path, relative: str) -> Path:
    relative = _safe_path(relative)
    path = root / relative
    current = path
    while current != root:
        if current.is_symlink():
            raise ProcedureEvidenceError("linked procedure evidence is not allowed")
        current = current.parent
    if not path.is_file() or root not in path.resolve().parents:
        raise ProcedureEvidenceError("procedure evidence file is absent or outside checkout")
    return path


def _test_functions(raw: bytes) -> list[dict]:
    try:
        module = ast.parse(raw)
    except (SyntaxError, UnicodeError, ValueError):
        return []
    rows = []
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            rows.append({"name": node.name, "sha256": sha(ast.dump(node, include_attributes=False).encode()),
                "assertion_count": sum(isinstance(child, ast.Assert) for child in ast.walk(node)),
                "decorator_count": len(node.decorator_list),
                "parameter_count": len(node.args.posonlyargs) + len(node.args.args) + len(node.args.kwonlyargs)})
    return sorted(rows, key=lambda row: row["name"])


def _named_module(raw: bytes, name: str) -> dict:
    try:
        module = ast.parse(raw)
    except (SyntaxError, UnicodeError, ValueError):
        return {"test_name": name, "parse_valid": False}
    identifiers, matches = set(), []
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            identifiers.add(node.name)
        elif isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.arg):
            identifiers.add(node.arg)
        elif isinstance(node, ast.alias):
            identifiers.add(node.asname or node.name.split(".")[0])
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and name in node.name:
            matches.append({"name": node.name, "sha256": sha(ast.dump(node, include_attributes=False).encode()),
                "top_level": node in module.body, "async": isinstance(node, ast.AsyncFunctionDef),
                "generator": any(isinstance(child, (ast.Yield, ast.YieldFrom)) for child in ast.walk(node)),
                "decorator_count": len(node.decorator_list),
                "parameter_count": len(node.args.posonlyargs) + len(node.args.args) + len(node.args.kwonlyargs)
                    + int(node.args.vararg is not None) + int(node.args.kwarg is not None),
                "direct_assert_lines": [child.lineno for child in node.body if isinstance(child, ast.Assert)]})
    return {"test_name": name, "parse_valid": True, "bound_name_present": name in identifiers,
        "matching_definitions": matches,
        "module_node_sha256": [sha(ast.dump(node, include_attributes=False).encode()) for node in module.body]}


def validate_named_base(snapshot: dict, name: str) -> None:
    scope = snapshot.get("named_regression", {})
    if (scope.get("test_name") != name or scope.get("parse_valid") is not True or
            scope.get("bound_name_present") is not False or scope.get("matching_definitions") != []):
        raise ProcedureEvidenceError("named regression must be fresh and match no existing identifier or function")


def _named_addition(base: dict, snapshot: dict, name: str) -> dict | None:
    scope = snapshot.get("named_regression", {})
    original = base.get("named_regression", {}).get("module_node_sha256", [])
    nodes, matches = scope.get("module_node_sha256", []), scope.get("matching_definitions", [])
    if (scope.get("test_name") != name or scope.get("parse_valid") is not True or
            len(nodes) != len(original) + 1 or nodes[:-1] != original or len(matches) != 1):
        return None
    selected = matches[0]
    if (selected.get("name") != name or selected.get("top_level") is not True or
            selected.get("async") is not False or selected.get("generator") is not False or
            selected.get("decorator_count") != 0 or selected.get("parameter_count") != 0 or
            not selected.get("direct_assert_lines") or nodes[-1] != selected.get("sha256")):
        return None
    return selected


def named_runner_outcome(result: dict, argv: list[str], *, red: bool = False,
                         test_name: str | None = None, assertion_lines: list[int] | None = None) -> bool:
    """Validate actual one-test public-runner output, never an arbitrary pass label."""
    if (result.get("argv") != argv or result.get("cwd") != "." or
            type(result.get("exit_code")) is not int or result["exit_code"] != int(red) or
            result.get("timed_out") is not False or result.get("output_truncated") is not False):
        return False
    output = str(result.get("stdout", "")) + "\n" + str(result.get("stderr", ""))
    outcome, marker, status = ("failed", "F", "FAIL") if red else ("passed", ".", "OK")
    summaries = re.findall(r"(?m)^[ =]*tests finished:[ \t]*([^\r\n]*?)[ \t]*, in [0-9]+(?:\.[0-9]+)? seconds[ =]*$", output)
    # This frozen SymPy runner prints the zero passed count on a failing run.
    # Tie all global counts to one exact footer rather than ignoring zero counts.
    expected_summaries = (["1 failed"], ["0 passed, 1 failed"]) if red else (["1 passed"],)
    opposite_counts = [0] if red and summaries == ["0 passed, 1 failed"] else []
    collection = re.findall(r"(?m)^([A-Za-z0-9_./-]+\.py)\[([0-9]+)\][ \t]+([^\r\n]*)$", output)
    if (summaries not in expected_summaries or len(re.findall(r"(?m)^[ =]*tests finished:", output)) != 1 or
            len(collection) != 1 or collection[0][:2] != (argv[2], "1") or
            not re.fullmatch(re.escape(marker) + r"[ \t]+\[" + status + r"\][ \t]*", collection[0][2]) or
            _counts(output, outcome) != [1] or _counts(output, "passed" if red else "failed") != opposite_counts or
            re.search(r"\b[0-9]+ (?:skipped|xfailed|xpassed|expected to fail|exceptions?)\b", output)):
        return False
    exception_names = re.findall(
        r"(?m)^([A-Za-z_]\w*(?:Error|Exception)|Exception|Error)(?::[^\r\n]*)?[ \t]*$", output)
    tracebacks = re.findall(r"(?m)^Traceback \(most recent call last\):[ \t]*$", output)
    if exception_names != (["AssertionError"] if red else []) or len(tracebacks) != int(red):
        return False
    if red:
        if not test_name or not assertion_lines:
            return False
        frames = re.findall(r'File "([^"\r\n]+)", line ([0-9]+), in ([A-Za-z_][A-Za-z0-9_]*)', output)
        if not frames:
            return False
        path, line, function = frames[-1]
        if path != "/testbed/" + argv[2] or function != test_name or int(line) not in assertion_lines:
            return False
    return True


def capture_workspace(workspace, bindings: dict) -> dict:
    """Manager-only actual public state; no source/test/patch text leaves this capture."""
    root = Path(workspace.root).resolve()
    multi_source = "source_paths" in bindings
    source_paths = json.loads(bindings["source_paths"]) if multi_source else [bindings["source_path"]]
    sources = {path: _public_file(root, path) for path in source_paths}
    test = _public_file(root, bindings["test_path"])
    runner = _public_file(root, "bin/test")
    if any(path.stat().st_size > 2_000_000 for path in (*sources.values(), test, runner)):
        raise ProcedureEvidenceError("procedure public file exceeds capture bound")
    patch = workspace.patch()
    paths = set()
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            match = re.fullmatch(r"diff --git a/([A-Za-z0-9_./-]+) b/([A-Za-z0-9_./-]+)", line)
            if match is None:
                raise ProcedureEvidenceError("unsupported changed path in procedure capture")
            paths.update(_safe_path(value) for value in match.groups())
    if patch and not paths:
        raise ProcedureEvidenceError("patch has no canonical changed-file headers")
    test_raw = test.read_bytes()
    source_hashes = {path: file_sha(source) for path, source in sources.items()}
    snapshot = {"schema": "skhynix/public-procedure-workspace/1.0", "patch_sha256": sha(patch.encode()),
        "changed_paths": sorted(paths),
        "source_sha256": sha(canonical(source_hashes)) if multi_source else source_hashes[source_paths[0]],
        "test_sha256": sha(test_raw),
        "runner_sha256": file_sha(runner), "test_functions": _test_functions(test_raw)}
    if "test_name" in bindings:
        snapshot["schema"] = "skhynix/public-procedure-workspace/2.0"
        snapshot["named_regression"] = _named_module(test_raw, bindings["test_name"])
    if multi_source:
        snapshot.update(schema="skhynix/public-procedure-workspace/3.0", source_file_sha256=source_hashes)
    return snapshot


def _validate_source_map(snapshot: dict, source_paths: list[str]) -> None:
    mapping = snapshot.get("source_file_sha256")
    if (snapshot.get("schema") != "skhynix/public-procedure-workspace/3.0" or
            not isinstance(mapping, dict) or set(mapping) != set(source_paths) or
            any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                for value in mapping.values()) or snapshot.get("source_sha256") != sha(canonical(mapping))):
        raise ProcedureEvidenceError("prebound implementation file map differs from its workspace digest")


def _validate_multi_source_history(events: list[dict], base: dict, red: dict,
                                   red_sequence: int, source_paths: list[str], test_path: str) -> None:
    """Check every observed mutation, including command changes later restored."""
    for event in events:
        request = event["request"]
        if (request.get("op") != "tool" or
                request.get("name") not in ("write_file", "replace_text", "run_command") or not _result(event)):
            continue
        snapshots = [_snapshot(event)]
        if request["name"] == "run_command":
            before = _result(event).get("procedure_snapshot_before")
            if not isinstance(before, dict):
                raise ProcedureEvidenceError("public command lacks its preceding workspace capture")
            snapshots.append(before)
        for snapshot in snapshots:
            _validate_source_map(snapshot, source_paths)
            for key in ("patch_sha256", "test_sha256", "runner_sha256"):
                if not isinstance(snapshot.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot[key]):
                    raise ProcedureEvidenceError("intermediate workspace capture digest is invalid")
            changed = [path for path in source_paths if
                snapshot["source_file_sha256"][path] != base["source_file_sha256"][path]]
            if snapshot["test_sha256"] != base["test_sha256"]:
                changed.append(test_path)
            if snapshot.get("changed_paths") != sorted(changed) or snapshot["runner_sha256"] != base["runner_sha256"]:
                raise ProcedureEvidenceError("intermediate command or write changed files outside its declared scope")
            if event["sequence"] <= red_sequence and snapshot["source_file_sha256"] != base["source_file_sha256"]:
                raise ProcedureEvidenceError("implementation changed before the RED observation")
            if event["sequence"] > red_sequence and snapshot["test_sha256"] != red["test_sha256"]:
                raise ProcedureEvidenceError("regression module changed after RED in an intermediate command or write")


def _events(root: Path) -> list[dict]:
    # The learning validator additionally joins this chain to the official
    # receipt, sealed patch, submission identity and persistent broker state.
    rows, tail = [], "0" * 64
    for sequence, raw in enumerate((root / "tool-events.jsonl").read_bytes().splitlines(), 1):
        row = json.loads(raw)
        digest = row.pop("sha256")
        if row["sequence"] != sequence or row["previous_sha256"] != tail or digest != sha(canonical(row)):
            raise ProcedureEvidenceError("procedure broker event chain differs")
        rows.append(row)
        tail = digest
    return rows


def _result(event: dict) -> dict:
    response = event.get("result", {})
    return response.get("result", {}) if response.get("ok") is True else {}


def _snapshot(event: dict) -> dict:
    value = _result(event).get("procedure_snapshot")
    if not isinstance(value, dict):
        raise ProcedureEvidenceError("broker command or submission lacks actual workspace capture")
    for key in ("patch_sha256", "source_sha256", "test_sha256", "runner_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", value.get(key, "")):
            raise ProcedureEvidenceError("workspace capture digest is invalid")
    return value


def _command(event: dict, argv: list[str]) -> bool:
    request = event["request"]
    return (request.get("op") == "tool" and request.get("name") == "run_command" and
            request.get("arguments", {}).get("argv") == argv and
            request.get("arguments", {}).get("cwd") in (None, ".", "./") and bool(_result(event)))


def _output(event: dict) -> str:
    result = _result(event)
    return str(result.get("stdout", "")) + "\n" + str(result.get("stderr", ""))


def _counts(text: str, outcome: str) -> list[int]:
    return [int(value) for value in re.findall(r"\b(\d+) " + re.escape(outcome) + r"\b", text)]


def _stage_receipt(name: str, events: list[dict]) -> dict:
    return {"stage": name, "broker_sequences": [event["sequence"] for event in events],
        "request_sha256": [sha(canonical(event["request"])) for event in events],
        "response_sha256": [sha(canonical(event["result"])) for event in events]}


def attest_procedure(run_root: Path, cell: str, declaration_path: Path, declaration_sha256: str) -> dict:
    """Derive five observed stages from authoritative broker records, never solver claims."""
    run, root = Path(run_root).resolve(), Path(run_root).resolve() / "cells" / cell
    source = _read_training(run, cell)
    plan, submission = read(run / "plan.json"), read(root / "submission.json")
    task = plan["public_task"]
    declaration = load_declaration(declaration_path, declaration_sha256, task["task_id"])
    profile = procedure_profile(declaration["procedure_id"])
    template = profile["template"]
    multi_source = profile["procedure_id"] == MULTI_SOURCE_PROCEDURE_ID
    named = profile["procedure_id"] in (NAMED_PROCEDURE_ID, MULTI_SOURCE_PROCEDURE_ID)
    ref = plan.get("procedure_declaration")
    if (not isinstance(ref, dict) or ref.get("sha256") != declaration_sha256 or
            Path(ref.get("path", "")).resolve() != Path(declaration_path).resolve() or
            plan["experiment_id"] != declaration["authority_org_id"] or
            source["provenance"]["resolved"] is not True):
        raise ProcedureEvidenceError("training plan, authority, predeclaration or official resolution differs")
    events = _events(root)
    begins = [event for event in events if event["request"].get("op") == "begin_procedure"]
    successful_begins = [event for event in begins if event["result"].get("ok") is True] if named else begins
    if (len(successful_begins) != 1 or not isinstance(_result(successful_begins[0]), dict) or
            not _result(successful_begins[0])):
        raise ProcedureEvidenceError("exactly one successful pre-write procedure binding is required")
    begin, receipt = successful_begins[0], _result(successful_begins[0])
    if named:
        for attempt in begins:
            if attempt is begin:
                continue
            failure = attempt["result"]
            if (attempt["sequence"] >= begin["sequence"] or failure.get("ok") is not False or
                    failure.get("error_type") != "ProcedureEvidenceError" or "result" in failure or
                    not isinstance(failure.get("error"), str) or not failure["error"].strip()):
                raise ProcedureEvidenceError("only failed validation calls before the successful binding are allowed")
    public_python = plan.get("public_python")
    bindings = validate_bindings(declaration, receipt["bindings"], public_python)
    source_paths = json.loads(bindings["source_paths"]) if multi_source else [bindings["source_path"]]
    if (receipt.get("declaration_sha256") != declaration_sha256 or
            receipt.get("template_hash") != template.content_hash or receipt.get("sequence") != begin["sequence"] or
            validate_bindings(declaration, begin["request"].get("bindings"), public_python) != bindings or
            read(root / "procedure-binding.json") != receipt):
        raise ProcedureEvidenceError("binding journal and persistent declaration receipt differ")
    base = receipt.get("workspace_snapshot", {})
    if base.get("changed_paths") != [] or base.get("patch_sha256") != sha(b""):
        raise ProcedureEvidenceError("procedure binding did not observe a pristine base checkout")
    if named:
        validate_named_base(base, bindings["test_name"])
    if multi_source:
        _validate_source_map(base, source_paths)
    writes = [event for event in events if event["request"].get("op") == "tool" and
              event["request"].get("name") in ("write_file", "replace_text")]
    if any(event["sequence"] < begin["sequence"] and event["request"].get("op") == "tool" and
           event["request"].get("name") in ("write_file", "replace_text", "run_command") for event in events):
        raise ProcedureEvidenceError("file modification preceded procedure binding")
    successful_writes = [event for event in writes if _result(event)]
    test_writes = [event for event in successful_writes
                   if event["request"]["arguments"].get("path") == bindings["test_path"]]
    source_writes = [event for event in successful_writes
                     if event["request"]["arguments"].get("path") in source_paths]
    if not test_writes or not source_writes:
        raise ProcedureEvidenceError("no actual regression and implementation edits were observed")
    first_test_write = test_writes[0]["sequence"]
    inspected = []
    for path in (*source_paths, bindings["test_path"]):
        matches = [event for event in events if event["sequence"] < first_test_write and
            event["request"].get("op") == "tool" and event["request"].get("name") == "read_file" and
            event["request"].get("arguments", {}).get("path") == path and _result(event)]
        if not matches:
            raise ProcedureEvidenceError("source and public regression suite were not inspected before edits")
        inspected.append(matches[-1])
    argv = json.loads(bindings["test_argv"])
    commands = [event for event in events if _command(event, argv)]
    base_functions = {row["name"] for row in base.get("test_functions", [])}
    red_candidates = []
    for event in commands:
        if event["sequence"] <= first_test_write:
            continue
        output, result = _output(event), _result(event)
        if (type(result.get("exit_code")) is not int or result["exit_code"] == 0 or
                "AssertionError" not in output or not any(_counts(output, "failed")) or
                (not named and re.search(r"\b(?:ImportError|ModuleNotFoundError|SyntaxError|IndentationError|TimeoutError|FileNotFoundError)\b", output))):
            continue
        snapshot = _snapshot(event)
        if multi_source:
            _validate_source_map(snapshot, source_paths)
        if result.get("procedure_snapshot_before") != snapshot:
            raise ProcedureEvidenceError("RED command changed public workspace state during execution")
        if named:
            selected = _named_addition(base, snapshot, bindings["test_name"])
            if selected is None or not named_runner_outcome(result, argv, red=True,
                    test_name=bindings["test_name"], assertion_lines=selected["direct_assert_lines"]):
                continue
        additions = [row for row in snapshot.get("test_functions", []) if row["name"] not in base_functions and
            row["assertion_count"] > 0 and row["decorator_count"] == 0 and row["parameter_count"] == 0 and
            re.search(r"\b" + re.escape(row["name"]) + r"\b", output)]
        if (snapshot["changed_paths"] == [bindings["test_path"]] and
                snapshot["source_sha256"] == base.get("source_sha256") and
                snapshot["test_sha256"] != base.get("test_sha256") and
                snapshot["runner_sha256"] == base.get("runner_sha256") and additions):
            red_candidates.append((event, snapshot, additions))
    if not red_candidates:
        raise ProcedureEvidenceError("no genuine added assertion failure with unchanged implementation was verified")
    red, red_snapshot, additions = red_candidates[0]
    if multi_source:
        _validate_multi_source_history(events, base, red_snapshot, red["sequence"], source_paths, bindings["test_path"])
    if any(event["sequence"] <= red["sequence"] for event in source_writes):
        raise ProcedureEvidenceError("implementation was edited before the RED observation")
    if any(event["sequence"] > red["sequence"] for event in test_writes):
        raise ProcedureEvidenceError("regression module was edited after RED")
    if any(event["request"]["arguments"].get("path") not in (*source_paths, bindings["test_path"])
           for event in successful_writes):
        raise ProcedureEvidenceError("the bounded procedure edited files outside its declared source and test")
    green_candidates = []
    for event in commands:
        result, output = _result(event), _output(event)
        if (event["sequence"] <= red["sequence"] or result.get("exit_code") != 0 or
                not any(_counts(output, "passed")) or any(_counts(output, "failed"))):
            continue
        snapshot = _snapshot(event)
        if multi_source:
            _validate_source_map(snapshot, source_paths)
        if result.get("procedure_snapshot_before") != snapshot:
            raise ProcedureEvidenceError("GREEN command changed public workspace state during execution")
        if named and (not named_runner_outcome(result, argv) or
                _named_addition(base, snapshot, bindings["test_name"]) is None):
            continue
        changed_sources = [path for path in source_paths if
            snapshot["source_file_sha256"][path] != base["source_file_sha256"][path]] if multi_source else source_paths
        if (changed_sources and snapshot["changed_paths"] == sorted((*changed_sources, bindings["test_path"])) and
                snapshot["test_sha256"] == red_snapshot["test_sha256"] and
                snapshot["source_sha256"] != base.get("source_sha256") and
                snapshot["runner_sha256"] == base.get("runner_sha256")):
            green_candidates.append((event, snapshot))
    if not green_candidates:
        raise ProcedureEvidenceError("no identical public regression command passed after implementation repair")
    green, green_snapshot = green_candidates[-1]
    if any(event["sequence"] > green["sequence"] for event in successful_writes):
        raise ProcedureEvidenceError("file edit occurred after final verified GREEN")
    final_snapshot = _snapshot(events[-1])
    if multi_source:
        _validate_source_map(final_snapshot, source_paths)
    if final_snapshot != green_snapshot or final_snapshot["patch_sha256"] != submission["patch_sha256"]:
        raise ProcedureEvidenceError("GREEN workspace differs from the officially submitted patch")
    # Each sentence is attached only after the corresponding concrete broker
    # predicates passed, with the selected request/result hashes retained below.
    rendered = template.render(bindings)
    observed_actions = list(rendered.steps) if named else [
        f"Inspect source {bindings['source_path']} and public suite {bindings['test_path']} before modification.",
        f"Add an assertion regression in {bindings['test_path']} while keeping all implementation files unchanged.",
        f"Run {bindings['test_argv']} and observe an assertion failure in the newly added regression.",
        f"Modify implementation {bindings['source_path']} while retaining identical regression test bytes.",
        f"Run the identical command {bindings['test_argv']} and observe passing public tests.",
    ]
    if tuple(observed_actions) != rendered.steps or canonical(argv).decode() != rendered.verification_command:
        raise ProcedureEvidenceError("observed action labels differ from the predeclared bound procedure")
    selected_source_writes = [event for event in source_writes if red["sequence"] < event["sequence"] < green["sequence"]]
    if not selected_source_writes:
        raise ProcedureEvidenceError("implementation edit was not bracketed by RED and GREEN")
    attestation = {"schema": profile["attestation_schema"], "status": "VERIFIED", "procedure_id": profile["procedure_id"],
        "declaration_sha256": declaration_sha256, "template_hash": template.content_hash,
        "authority_org_id": plan["experiment_id"], "contributor_id": plan["solver_user_id"],
        "contributor_kind": "INDEPENDENT_NATIVE_CODEX_SESSION_NOT_HUMAN_USER", "task_id": task["task_id"],
        "repository": task["repository"], "source_revision": task["commit"], "cell": cell,
        "bindings": bindings, "observed_actions": observed_actions,
        "verification_command": canonical(argv).decode(),
        "stages": [_stage_receipt("INSPECT", inspected),
            _stage_receipt("ADD_REGRESSION", [event for event in test_writes if event["sequence"] < red["sequence"]]),
            _stage_receipt("RED", [red]), _stage_receipt("REPAIR_IMPLEMENTATION", selected_source_writes),
            _stage_receipt("GREEN", [green])],
        "regression_names": sorted(row["name"] for row in additions),
        "base_workspace": base, "red_workspace": red_snapshot, "green_workspace": green_snapshot,
        "public_test_passed_counts": _counts(_output(green), "passed"),
        "source_provenance": source["provenance"], "official_training_resolved": True,
        "target_fix_validated": False, "target_workflow_applicability": "REQUIRES_SEPARATE_COMPATIBILITY_CERTIFICATE"}
    digest = sha(canonical(attestation))
    evidence = EpisodeEvidence(org_id=plan["experiment_id"], user_id=plan["solver_user_id"],
        repository=task["repository"], task_id=task["task_id"], revision=task["commit"],
        subgoal=template.subgoal_signature, summary="Observed the predeclared public regression RED/GREEN workflow.",
        actions=tuple(observed_actions), succeeded=True, verification_command=canonical(argv).decode(),
        verification_evidence_hash="sha256:" + digest,
        created_at=datetime.fromtimestamp(submission["submitted_at"], timezone.utc).isoformat().replace("+00:00", "Z"),
        procedure_hash=template.content_hash, parameter_bindings=tuple(sorted(bindings.items())),
        artifact_hashes=(("declaration", "sha256:" + declaration_sha256),
            ("submitted_patch", "sha256:" + submission["patch_sha256"]),
            ("official_public_result", "sha256:" + source["provenance"]["public_result_sha256"]),
            ("broker_event_tail", "sha256:" + source["provenance"]["tool_event_tail_sha256"])))
    return {"attestation": attestation, "attestation_sha256": digest, "episode_evidence": asdict(evidence)}


def promote_and_export(declaration_path: Path, declaration_sha256: str,
                       training_cells: list[dict], output_root: Path) -> dict:
    """Promote verified observations through the real authority, then freeze its public view."""
    declaration = load_declaration(declaration_path, declaration_sha256)
    profile = procedure_profile(declaration["procedure_id"])
    template = profile["template"]
    output_root = Path(output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise ProcedureEvidenceError("refusing to overwrite a frozen or partial procedure authority")
    attestations = [attest_procedure(Path(row["run_root"]), row["cell"], declaration_path, declaration_sha256)
                    for row in training_cells]
    task_ids = [row["attestation"]["task_id"] for row in attestations]
    contributors = [row["attestation"]["contributor_id"] for row in attestations]
    verifiers = [row["attestation_sha256"] for row in attestations]
    if min(len(set(task_ids)), len(set(contributors)), len(set(verifiers))) < 2:
        raise ProcedureEvidenceError("promotion requires distinct tasks, native sessions and verifier artifacts")
    if set(task_ids) != set(declaration["training_task_ids"]) or len(task_ids) != len(set(task_ids)):
        raise ProcedureEvidenceError("promotion must cover each declared training task exactly once")
    output_root.mkdir(parents=True, exist_ok=True)
    authority = output_root / "gate-ab-private.sqlite3"
    with SkillMemoryStore(authority) as store:
        episodes = [store.record_episode(EpisodeEvidence(**row["episode_evidence"])) for row in attestations]
        skill = store.promote_skill(template, [row.episode_id for row in episodes],
                                    org_id=declaration["authority_org_id"])
    for index, value in enumerate(attestations):
        _write_new(output_root / f"training-{index + 1}-private-attestation.json", value)
    view = skill.execution_view()
    export = {"schema": profile["export_schema"], "status": "ACTUALLY_PROMOTED_BY_GATE_B",
        "declaration_sha256": declaration_sha256, "procedure_id": profile["procedure_id"],
        "authority_org_id": declaration["authority_org_id"], "training_task_ids": sorted(task_ids),
        "contributor_kind": "DISTINCT_NATIVE_CODEX_SESSION_IDS_NOT_INDEPENDENT_HUMANS",
        "contributor_count": len(set(contributors)), "verified_skill_count": 1,
        "authority_db": {"path": str(authority.resolve()), "sha256": file_sha(authority)},
        "declaration": {"path": str(Path(declaration_path).resolve()), "sha256": declaration_sha256},
        "attestations": [{"path": str((output_root / f"training-{index + 1}-private-attestation.json").resolve()),
                          "sha256": file_sha(output_root / f"training-{index + 1}-private-attestation.json"),
                          "attestation_sha256": row["attestation_sha256"]}
                         for index, row in enumerate(attestations)],
        "promoted_skill": asdict(skill), "public_execution_view": view,
        "public_execution_view_sha256": sha(view.encode()), "public_execution_view_bytes": len(view.encode()),
        "training_runner_sha256": sorted({row["attestation"]["base_workspace"]["runner_sha256"] for row in attestations}),
        "target_workflow_applicability": "REQUIRES_SEPARATE_COMPATIBILITY_CERTIFICATE",
        "target_fix_validated": False, "same_public_payload_required_for_memory_arms": True,
        "source_revisions_rebound": False, "model_api_calls": 0}
    path = output_root / "promoted-procedure.json"
    _write_new(path, export)
    return {"path": str(path.resolve()), "sha256": file_sha(path), "skill_id": skill.skill_id,
            "verified_skill_count": 1, "support_count": skill.support_count,
            "contributor_count": skill.contributor_count, "public_execution_view_bytes": len(view.encode())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    declare = commands.add_parser("declare")
    declare.add_argument("--output", type=Path, required=True)
    declare.add_argument("--authority-org", required=True)
    declare.add_argument("--training-task-id", action="append", required=True)
    declare.add_argument("--procedure-version", choices=("1", "2", "3"), default="1")
    promote = commands.add_parser("promote")
    promote.add_argument("--declaration", type=Path, required=True)
    promote.add_argument("--declaration-sha256", required=True)
    promote.add_argument("--training-spec", type=Path, required=True)
    promote.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "declare":
        result = declare_procedure(args.output, args.authority_org, args.training_task_id, args.procedure_version)
    else:
        result = promote_and_export(args.declaration, args.declaration_sha256,
                                     read(args.training_spec)["training_cells"], args.output_root)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
