"""Frozen public-metadata selection for the Native011 controlled transfer study.

Public issue text chooses the cohort. Restricted row columns are used only for
opaque row binding and the existing official grader handoff, never for selection.
Earlier manifests and chronology claims are not changed by this separate profile.
"""
from __future__ import annotations

from pathlib import Path
import re

import trimem_skhynix_native_dataset as dataset

SCHEMA = "skhynix/native-controlled-transfer-manifest/1.0"
CHRONOLOGY = "RETROSPECTIVE_DISJOINT_TASKS_NO_CHRONOLOGICAL_DEPLOYMENT_CLAIM"
SCOPE = "PUBLIC_ISSUE_SELECTED_MECHANISM_TRANSFER_NOT_RANDOM_NOT_GLOBAL_HELDOUT"
SOURCES = ("sympy__sympy-20428", "sympy__sympy-20438")
PRIOR_PATHS = dataset.EXCLUSION_PATHS + tuple(
    f"configs/skhynix_v1/codex_{n:03}_manifest.json" for n in (2, 3, 4, 5, 6, 7, 9)
) + ("configs/skhynix_v1/codex_003_preliminary_manifest.json",)
PUBLIC_PYTHON = "/opt/miniconda3/envs/testbed/bin/python"
PUBLIC_RUNTIME_CODE = (
    "import json,platform,subprocess,sys; import sympy; "
    "print(json.dumps({'python_version':platform.python_version(),"
    "'python_executable':sys.executable,'sympy_version':sympy.__version__,"
    "'sympy_file':sympy.__file__}),flush=True); "
    "p=subprocess.run([sys.executable,'bin/test','--help'],stdout=subprocess.PIPE,"
    "stderr=subprocess.PIPE,universal_newlines=True); "
    "print(json.dumps({'help_returncode':p.returncode,'help_stdout':p.stdout,"
    "'help_stderr':p.stderr}),flush=True); sys.exit(p.returncode)"
)


def _error(message):
    raise dataset.SupplementalDatasetError(message)


def _read(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 1024 * 1024:
        _error("Controlled transfer input is unavailable or too large")
    raw = path.read_bytes()
    value = dataset.benchmark.strict_json_loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        _error("Controlled transfer input must be an object")
    return raw, value


def _exclusions(root):
    excluded = set(SOURCES) | {"sympy__sympy-21596"}
    bindings = []
    for relative in PRIOR_PATHS:
        raw, value = _read(root / relative)
        targets = value.get("targets")
        if not isinstance(targets, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("instance_id"), str)
            for row in targets
        ):
            _error("Prior enrollment identities are invalid")
        excluded.update(row["instance_id"] for row in targets)
        bindings.append({"path": relative, "raw_sha256": dataset.sha(raw)})
    return excluded, bindings


def _selection(value, excluded):
    if not isinstance(value, dict) or set(value) != {"targets", "method", "source_instance_ids"}:
        _error("Controlled transfer selection schema differs")
    if value["method"] != "PUBLIC_ISSUE_MECHANISM_MATCH_BEFORE_SOLVER_OUTCOMES":
        _error("Controlled transfer selection method differs")
    if value["source_instance_ids"] != list(SOURCES):
        _error("Controlled transfer source identities differ")
    targets = value["targets"]
    if not isinstance(targets, list) or len(targets) != 4:
        _error("Controlled transfer requires four preselected targets")
    for row in targets:
        if not isinstance(row, dict) or set(row) != {"instance_id", "family", "rationale"}:
            _error("Controlled transfer target selection differs")
        if not isinstance(row["instance_id"], str) or not re.fullmatch(r"sympy__sympy-[0-9]+", row["instance_id"]):
            _error("Controlled transfer target identity is invalid")
        if row["family"] not in ("polynomial", "sets") or not isinstance(row["rationale"], str) or not 1 <= len(row["rationale"]) <= 2000:
            _error("Controlled transfer mechanism declaration is invalid")
    ids = [row["instance_id"] for row in targets]
    if len(set(ids)) != 4 or set(ids) & excluded:
        _error("Controlled targets overlap a source, prior enrollment or known development task")
    if [row["family"] for row in targets].count("polynomial") != 2:
        _error("Controlled transfer requires two tasks per mechanism family")
    return ids


def _rows(path, ids):
    import pyarrow.parquet as pq
    public = pq.read_table(path, columns=list(dataset.NATIVE004_PUBLIC_COLUMNS),
                           filters=[("instance_id", "in", ids)]).to_pylist()
    if len(public) != len(ids) or {row["instance_id"] for row in public} != set(ids) or any(
        row["repo"] != dataset.REPOSITORY for row in public
    ):
        _error("Controlled public source identities differ")
    public = {row["instance_id"]: dict(row) for row in public}
    # Cohort is fixed before any restricted column is decoded. These rows are
    # never printed or used to derive the treatment or selection rationale.
    rows = pq.read_table(path, filters=[("instance_id", "in", ids)]).to_pylist()
    if len(rows) != len(ids) or {row["instance_id"] for row in rows} != set(ids):
        _error("Controlled grader row identities differ")
    return public, {row["instance_id"]: dict(row) for row in rows}


def _runtime_file(path, expected_sha256):
    if (not isinstance(path, str) or not Path(path).is_absolute()
            or not isinstance(expected_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)):
        _error("Controlled public runtime receipt binding is invalid")
    try:
        if Path(path).resolve() != Path(path):
            _error("Controlled public runtime receipt path is indirect")
        raw, value = _read(path)
    except (OSError, ValueError, dataset.SupplementalDatasetError) as exc:
        raise dataset.SupplementalDatasetError("Controlled public runtime receipt is unavailable") from exc
    if dataset.sha(raw) != expected_sha256:
        _error("Controlled public runtime receipt hash differs")
    return value


def _runtime_argv(checkout, image):
    return ["docker", "run", "--rm", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "64", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "-e", "PYTHONDONTWRITEBYTECODE=1", "--mount",
            f"type=bind,source={checkout},target=/testbed,readonly",
            "--workdir", "/testbed", "--entrypoint", PUBLIC_PYTHON, image,
            "-c", PUBLIC_RUNTIME_CODE]


def _validate_runtime_receipt(evidence, base_commit):
    receipt = _runtime_file(evidence["runtime_receipt_path"], evidence["runtime_receipt_sha256"])
    expected = {
        "instance_id": evidence["instance_id"], "base_commit": base_commit,
        "image": evidence["image"], "public_python": PUBLIC_PYTHON,
        "python_version": evidence["python_version"].removeprefix("Python "),
        "runner_sha256": evidence["runner_sha256"],
        "runtime_probe_sha256": evidence["probe_sha256"],
        "sympy_import_path": "/testbed/sympy/__init__.py",
        "image_architecture": "amd64", "image_os": "linux",
    }
    if (any(receipt.get(key) != value for key, value in expected.items())
            or receipt.get("runtime_compatible") is not True
            or receipt.get("repo_digest_verified") is not True
            or any(type(receipt.get(key)) is not int or receipt[key] != 0 for key in (
                "help_returncode", "public_probe_returncode", "issue_probes", "model_calls",
                "official_grader_calls", "test_commands"))
            or not isinstance(receipt.get("sympy_version"), str) or not receipt["sympy_version"]):
        _error("Controlled public runtime receipt identity or outcome differs")
    checkout = receipt.get("base_checkout")
    if (not isinstance(checkout, str) or not Path(checkout).is_absolute()
            or Path(checkout).name != "sympy-" + base_commit
            or Path(checkout).resolve() != Path(checkout)):
        _error("Controlled public runtime base checkout binding differs")
    runner = Path(checkout) / "bin/test"
    if (not runner.is_file() or runner.is_symlink() or runner.resolve() != runner
            or runner.stat().st_size > 1024 * 1024
            or dataset.sha(runner.read_bytes()) != evidence["runner_sha256"]):
        _error("Controlled public runtime runner bytes differ")
    probe = _runtime_file(receipt.get("runtime_probe_path"), evidence["probe_sha256"])
    if (probe.get("argv") != _runtime_argv(checkout, evidence["image"])
            or probe.get("cwd") is not None
            or type(probe.get("returncode")) is not int or probe["returncode"] != 0
            or not isinstance(probe.get("stdout"), str)
            or not isinstance(probe.get("stderr"), str)):
        _error("Controlled public runtime command or outcome differs")
    try:
        output = [dataset.benchmark.strict_json_loads(line) for line in probe["stdout"].splitlines()]
    except (ValueError, TypeError) as exc:
        raise dataset.SupplementalDatasetError("Controlled public runtime output is invalid") from exc
    if (len(output) != 2 or not all(isinstance(item, dict) for item in output)
            or output[0] != {"python_version": receipt["python_version"],
                "python_executable": PUBLIC_PYTHON, "sympy_version": receipt["sympy_version"],
                "sympy_file": receipt["sympy_import_path"]}
            or set(output[1]) != {"help_returncode", "help_stdout", "help_stderr"}
            or type(output[1]["help_returncode"]) is not int or output[1]["help_returncode"] != 0
            or not isinstance(output[1]["help_stdout"], str)
            or not output[1]["help_stdout"].lower().startswith("usage: test ")
            or "--help" not in output[1]["help_stdout"]
            or output[1]["help_stderr"] != ""):
        _error("Controlled public runtime import or help evidence differs")


def _assemble(*, cache_root, root, selection, images, runtime):
    excluded, bindings = _exclusions(root)
    ids = _selection(selection, excluded)
    path, spec = dataset._locked_dataset(cache_root, root)
    public, rows = _rows(path, ids)
    image_map = dataset._validate_images(images, ids)
    if not isinstance(runtime, list) or len(runtime) != len(ids):
        _error("Controlled public runtime evidence is missing")
    for instance, evidence in zip(ids, runtime):
        if not isinstance(evidence, dict) or set(evidence) != {
            "instance_id", "image", "python_executable", "python_version", "runner_sha256",
            "probe_sha256", "status", "runtime_receipt_path", "runtime_receipt_sha256"
        }:
            _error("Controlled public runtime evidence schema differs")
        if (evidence["instance_id"] != instance or evidence["image"] != image_map[instance]["image"]
            or evidence["python_executable"] != PUBLIC_PYTHON
            or not isinstance(evidence["python_version"], str)
            or not re.fullmatch(r"Python 3\.[0-9]+\.[0-9]+", evidence["python_version"])
            or evidence["status"] != "PASS_PUBLIC_RUNTIME_ONLY"
            or any(not isinstance(evidence[k], str) or not re.fullmatch(r"[0-9a-f]{64}", evidence[k])
                   for k in ("runner_sha256", "probe_sha256"))):
            _error("Controlled public runtime identity differs")
        _validate_runtime_receipt(evidence, public[instance]["base_commit"])
    targets = []
    for index, instance in enumerate(ids):
        row = rows[instance]
        instruction = dataset.benchmark.public_instruction(row, dataset.BENCHMARK)
        targets.append({"target_id": dataset.BENCHMARK + "--" + instance,
            "instance_id": instance, "benchmark_id": dataset.BENCHMARK,
            "repository": dataset.REPOSITORY, "language": "python",
            "base_commit": row["base_commit"], "dataset_revision": spec["dataset_revision"],
            "source_row_sha256": dataset.sha(dataset.canonical(row)), "order_index": index,
            "role": "EVALUATION", "public_issue_created_at": row["created_at"],
            "public_instruction_sha256": dataset.sha(instruction.encode("utf-8"))})
    manifest = {"schema": SCHEMA, "status": "FROZEN", "selection": selection,
        "dataset": spec, "excluded_manifests": bindings, "targets": targets,
        "public_selected_metadata": [public[instance] for instance in ids],
        "images": images, "public_runtime_evidence": runtime,
        "scope_claim": SCOPE, "chronology_claim": CHRONOLOGY,
        "planner_llm_involved_at_selection": True, "solver_model_calls_at_selection": 0,
        "new_target_grader_runs_at_selection": 0,
        "restricted_source_use": "OPAQUE_ROW_HASH_AND_EXISTING_GRADER_HANDOFF_ONLY"}
    return targets, rows, image_map, manifest


def build_controlled_manifest(*, cache_root, output_path, selection, images, runtime, root=dataset.ROOT):
    output_path = Path(output_path)
    if output_path.exists() or output_path.is_symlink():
        _error("Controlled manifest already exists; never overwrite")
    result = _assemble(cache_root=Path(cache_root), root=Path(root), selection=selection,
                       images=images, runtime=runtime)[3]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("xb") as stream:
        stream.write(dataset.canonical(result) + b"\n")
    return result


def load_controlled_rows(manifest_path, cache_root, *, expected_sha256, root=dataset.ROOT):
    raw, value = _read(manifest_path)
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or dataset.sha(raw) != expected_sha256:
        _error("Controlled manifest raw hash differs")
    result = _assemble(cache_root=Path(cache_root), root=Path(root), selection=value.get("selection"),
                       images=value.get("images"), runtime=value.get("public_runtime_evidence"))
    if dataset.canonical(value) != dataset.canonical(result[3]):
        _error("Controlled manifest scientific inputs differ")
    return result
