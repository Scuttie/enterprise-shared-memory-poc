"""Additive SWE-bench targets for explicitly frozen native learning profiles.

Native002/003 use identity columns only. Native004 is an exploratory hand-selected
printing/codegen cohort informed by public issue titles and chronology metadata.
Native005 selects an ascending-ID cohort using public runner hashes and ancestry.
Restricted rows are decoded only after selection, for opaque hashing and grading.
The original development, held-out, smoke and image locks are never modified.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

import trimem_benchmark_run as benchmark


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "skhynix/native-supplemental-manifest/1.0"
REPOSITORY = "sympy/sympy"
BENCHMARK = "swebench_verified"
PRIOR_INSTANCE = "sympy__sympy-23262"
EXCLUSION_PATHS = tuple("configs/trimem_v1/" + name for name in (
    "development_manifest.json", "heldout_manifest.json", "grader_smoke_manifest.json",
))
SELECTION = {
    "repository": REPOSITORY, "minimum_instance_number_exclusive": 23262,
    "order": "ASCENDING_NUMERIC_INSTANCE_ID", "new_training_count": 1,
    "evaluation_count": 3, "selection_fields": ["instance_id", "repo"],
    "content_fields_used_for_selection": [],
}
NATIVE003_SELECTION = {
    "repository": REPOSITORY, "minimum_instance_number_exclusive": 23950,
    "order": "ASCENDING_NUMERIC_INSTANCE_ID", "new_training_count": 2,
    "evaluation_count": 3, "selection_fields": ["instance_id", "repo"],
    "content_fields_used_for_selection": [],
}
NATIVE003_EXCLUSION_PATHS = EXCLUSION_PATHS + (
    "configs/skhynix_v1/codex_002_manifest.json",
)
NATIVE004_EXCLUSION_PATHS = NATIVE003_EXCLUSION_PATHS + (
    "configs/skhynix_v1/codex_003_manifest.json",
)
NATIVE004_TRAINING_IDS = tuple(f"sympy__sympy-{number}" for number in (14976, 16766))
NATIVE004_EVALUATION_IDS = tuple(f"sympy__sympy-{number}" for number in (
    19346, 20916, 21930, 22080, 22456, 22914))
NATIVE004_SELECTION = {
    "profile": "NATIVE004_HISTORICAL_PRINTING_CODEGEN",
    "repository": REPOSITORY, "order": "FIXED_TRAINING_THEN_EVALUATION",
    "new_training_count": 2, "evaluation_count": 6,
    "training_instance_ids": list(NATIVE004_TRAINING_IDS),
    "evaluation_instance_ids": list(NATIVE004_EVALUATION_IDS),
    "selection_fields": ["instance_id", "repo", "problem_statement:first_line", "base_commit", "created_at"],
    "content_fields_used_for_selection": ["problem_statement:first_line"],
    "candidate_order": "ASCENDING_NUMERIC_INSTANCE_ID",
    "selection_method": "PUBLIC_TITLE_INFORMED_EXPLORATORY_HAND_SELECTED_THEMATIC_SAMPLE",
    "selection_not_claimed": ["ID_ONLY", "RANDOM", "PROVEN_DIFFICULTY"],
    "prior_training_policy": "NONE_INDEPENDENT_HISTORICAL_COHORT",
}
NATIVE004_SCOPE_CLAIM = (
    "PUBLIC_TITLE_INFORMED_EXPLORATORY_HAND_SELECTED_PRINTING_CODEGEN_SAMPLE_"
    "NOT_ID_ONLY_NOT_RANDOM_NOT_DIFFICULTY_PROVEN_NOT_ORIGINAL_HELDOUT_ENDPOINT"
)
NATIVE004_PUBLIC_COLUMNS = ("instance_id", "repo", "problem_statement", "base_commit", "created_at")
NATIVE004_CANDIDATE_FIELDS = ("instance_id", "repo", "public_title", "base_commit", "created_at")
NATIVE005_EXCLUSION_PATHS = NATIVE004_EXCLUSION_PATHS + (
    "configs/skhynix_v1/codex_004_manifest.json",
)
NATIVE005_TRAINING_IDS = tuple(f"sympy__sympy-{number}" for number in (19637, 19783))
NATIVE005_EVALUATION_IDS = tuple(f"sympy__sympy-{number}" for number in (
    19954, 20154, 20428, 20438, 20801, 21379))
NATIVE005_RUNNER_SHA256 = "da4284cc210d8db5109f916248d97a8e82f725547e60c5d9a4d6c43573e3e9d5"
NATIVE005_RUNTIME_SCREENING_SHA256 = "3c860c2964a4f679c417eabc9855cec0b88e11bbb2f44c926cd10c35e284f0a3"
NATIVE005_SELECTION = {
    "profile": "NATIVE005_PUBLIC_RUNNER_COMPATIBLE_CHRONOLOGICAL",
    "repository": REPOSITORY, "order": "ASCENDING_NUMERIC_INSTANCE_ID",
    "new_training_count": 2, "evaluation_count": 6,
    "training_instance_ids": list(NATIVE005_TRAINING_IDS),
    "evaluation_instance_ids": list(NATIVE005_EVALUATION_IDS),
    "selection_fields": ["instance_id", "repo", "base_commit", "public_git:bin/test:sha256",
                         "public_git:base_ancestry", "public_git:committer_timestamp",
                         "public_image:bin/test:sha256", "public_image:python_version"],
    "content_fields_used_for_selection": ["public_git:bin/test:sha256"],
    "public_metadata_observed_but_not_used_by_algorithm": ["problem_statement:first_line", "created_at"],
    "candidate_order": "ASCENDING_NUMERIC_INSTANCE_ID",
    "selection_method": "FIRST_LEXICOGRAPHIC_TRAINING_PAIR_WITH_FIRST_SIX_LATER_COMPATIBLE_DESCENDANTS",
    "runner_path": "bin/test", "required_runner_sha256": NATIVE005_RUNNER_SHA256,
    "required_public_python_version": "Python 3.9.20",
    "runtime_screening_raw_sha256": NATIVE005_RUNTIME_SCREENING_SHA256,
    "runner_availability_policy": "RETAIN_UNAVAILABLE_CANDIDATES_WITH_NULL_HASH",
    "chronology_requirement": "GIT_BASE_ANCESTRY_AND_STRICTLY_INCREASING_COMMIT_TIMESTAMPS",
    "selection_not_claimed": ["ID_ONLY", "RANDOM", "PROVEN_DIFFICULTY"],
    "prior_training_policy": "NONE_INDEPENDENT_RUNNER_COMPATIBLE_COHORT",
}
NATIVE005_SCOPE_CLAIM = (
    "PUBLIC_RUNNER_HASH_PYTHON_RUNTIME_AND_BASE_ANCESTRY_FILTERED_ASCENDING_ID_EXPLORATORY_SAMPLE_"
    "NOT_ID_ONLY_NOT_RANDOM_NOT_DIFFICULTY_PROVEN_NOT_ORIGINAL_HELDOUT_ENDPOINT"
)


class SupplementalDatasetError(RuntimeError):
    """An additive dataset binding differs from the declared experiment."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validated_selection(selection: Mapping[str, Any]) -> Mapping[str, Any]:
    if selection == SELECTION or selection == NATIVE003_SELECTION:
        return selection
    if canonical(selection) not in (canonical(NATIVE004_SELECTION), canonical(NATIVE005_SELECTION)):
        raise SupplementalDatasetError("Supplemental selection contract differs")
    return selection


def _exclusions(root: Path, selection: Mapping[str, Any] = SELECTION
                ) -> tuple[set[str], list[dict[str, str]], Mapping[str, Any] | None]:
    ids: set[str] = set()
    bindings = []
    prior = None
    selection = _validated_selection(selection)
    independent = selection in (NATIVE004_SELECTION, NATIVE005_SELECTION)
    paths = (NATIVE005_EXCLUSION_PATHS if selection == NATIVE005_SELECTION else
             NATIVE004_EXCLUSION_PATHS if selection == NATIVE004_SELECTION else
             NATIVE003_EXCLUSION_PATHS if selection == NATIVE003_SELECTION else EXCLUSION_PATHS)
    for relative in paths:
        raw = (root / relative).read_bytes()
        value = benchmark.strict_json_loads(raw.decode("utf-8"))
        bindings.append({"path": relative, "raw_sha256": sha(raw)})
        for target in value["targets"]:
            ids.add(str(target["instance_id"]))
            if target["instance_id"] == PRIOR_INSTANCE and not independent:
                if prior is not None and prior != target:
                    raise SupplementalDatasetError("Prior training identity is ambiguous")
                prior = target
    if prior is None and not independent:
        raise SupplementalDatasetError("Prior training target is absent")
    return ids, bindings, prior


def _additional_prior_training_targets(root: Path, selection: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Retain native002's training identity without reading its outcomes."""
    if _validated_selection(selection) in (SELECTION, NATIVE004_SELECTION, NATIVE005_SELECTION):
        return []
    previous = benchmark.read_json(root / NATIVE003_EXCLUSION_PATHS[-1])
    training = [target for target in previous["targets"] if target.get("role") == "TRAINING"]
    if (previous.get("status") != "FROZEN" or previous.get("selection") != SELECTION
            or [target.get("instance_id") for target in training] != ["sympy__sympy-23413"]):
        raise SupplementalDatasetError("Additional prior training identity differs")
    return [{key: target[key] for key in (
        "target_id", "instance_id", "base_commit", "source_row_sha256")} for target in training]


def select_identities(rows: list[Mapping[str, Any]], excluded: set[str],
                      selection: Mapping[str, Any] = SELECTION) -> list[str]:
    """Verify a supported identity split; never inspect task content here."""
    selection = _validated_selection(selection)
    candidates = []
    seen = set()
    for row in rows:
        instance = row.get("instance_id")
        if row.get("repo") != REPOSITORY:
            continue
        if not isinstance(instance, str) or not re.fullmatch(r"sympy__sympy-[0-9]+", instance):
            raise SupplementalDatasetError("Malformed SymPy public identity")
        if instance in seen:
            raise SupplementalDatasetError("Duplicate SymPy public identity")
        seen.add(instance)
        number = int(instance.rsplit("-", 1)[1])
        if instance not in excluded and (selection in (NATIVE004_SELECTION, NATIVE005_SELECTION) or
                number > selection["minimum_instance_number_exclusive"]):
            candidates.append((number, instance))
    if selection in (NATIVE004_SELECTION, NATIVE005_SELECTION):
        # Fixed profiles additionally verify their public evidence at build/load.
        # Identity validation here is not the complete selection procedure.
        selected = [*selection["training_instance_ids"], *selection["evaluation_instance_ids"]]
        if not set(selected).issubset(instance for _, instance in candidates):
            raise SupplementalDatasetError("Hand-selected identities are absent or excluded")
        return selected
    count = selection["new_training_count"] + selection["evaluation_count"]
    selected = [instance for _, instance in sorted(candidates)[:count]]
    if len(selected) != count:
        raise SupplementalDatasetError("Insufficient disjoint public identities")
    return selected


def _public_candidate_metadata(path: Path, excluded: set[str]) -> list[dict[str, Any]]:
    """Read the public candidate view without decoding gold fields or issue bodies."""
    import pyarrow.parquet as pq
    candidates = []
    seen = set()
    for row in pq.read_table(path, columns=list(NATIVE004_PUBLIC_COLUMNS)).to_pylist():
        if row["repo"] != REPOSITORY:
            continue
        instance = row["instance_id"]
        if not isinstance(instance, str) or not re.fullmatch(r"sympy__sympy-[0-9]+", instance):
            raise SupplementalDatasetError("Malformed SymPy public identity")
        if instance in seen:
            raise SupplementalDatasetError("Duplicate SymPy public identity")
        seen.add(instance)
        if instance in excluded:
            continue
        statement = row["problem_statement"]
        title = statement.split("\n", 1)[0].rstrip("\r") if isinstance(statement, str) else None
        if (not title or not isinstance(row["base_commit"], str)
                or not re.fullmatch(r"[0-9a-f]{40}", row["base_commit"])
                or not isinstance(row["created_at"], str) or not row["created_at"]):
            raise SupplementalDatasetError("Public candidate metadata is malformed")
        candidates.append({"instance_id": instance, "repo": row["repo"], "public_title": title,
                           "base_commit": row["base_commit"], "created_at": row["created_at"]})
    candidates.sort(key=lambda row: int(row["instance_id"].rsplit("-", 1)[1]))
    return candidates


def _native004_selection_evidence(path: Path, excluded: set[str]) -> dict[str, Any]:
    """Reproduce the complete public candidate view without decoding gold fields."""
    candidates = _public_candidate_metadata(path, excluded)
    selected = select_identities(candidates, excluded, NATIVE004_SELECTION)
    by_id = {row["instance_id"]: row for row in candidates}
    selected_metadata = [by_id[instance] for instance in selected]
    return {"candidate_fields": list(NATIVE004_CANDIDATE_FIELDS), "candidates": candidates,
            "candidates_canonical_sha256": sha(canonical(candidates)),
            "selected_public_metadata": selected_metadata,
            "selected_public_metadata_canonical_sha256": sha(canonical(selected_metadata))}


def _native005_selection_evidence(path: Path, excluded: set[str], history: Path,
                                   runtime_screening: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute the complete public selection before restricted row decoding."""
    candidates = _public_candidate_metadata(path, excluded)
    runners = _public_runner_evidence(history, candidates)
    runtimes = _validated_runtime_screening(runtime_screening, runners,
        expected_sha256=NATIVE005_SELECTION["runtime_screening_raw_sha256"])
    selected = _runner_compatible_identities(history, candidates, runners,
        runner_sha256=NATIVE005_RUNNER_SHA256, evaluation_count=NATIVE005_SELECTION["evaluation_count"],
        runtime_eligible_ids={instance for instance, row in runtimes.items() if row["eligible"]})
    if selected != select_identities(candidates, excluded, NATIVE005_SELECTION):
        raise SupplementalDatasetError("Runner-compatible public selection differs from the frozen profile")
    by_id = {row["instance_id"]: row for row in candidates}
    selected_metadata = [by_id[instance] for instance in selected]
    return {"candidate_fields": list(NATIVE004_CANDIDATE_FIELDS), "candidates": candidates,
            "candidates_canonical_sha256": sha(canonical(candidates)),
            "selected_public_metadata": selected_metadata,
            "selected_public_metadata_canonical_sha256": sha(canonical(selected_metadata)),
            "runner_evidence": runners, "runner_evidence_canonical_sha256": sha(canonical(runners)),
            "required_runner_sha256": NATIVE005_RUNNER_SHA256,
            "method": NATIVE005_SELECTION["selection_method"],
            "runtime_screening": runtime_screening,
            "runtime_screening_raw_sha256": sha(canonical(runtime_screening) + b"\n"),
            "runtime_screening_canonical_sha256": sha(canonical(runtime_screening))}


def _locked_dataset(cache_root: Path, root: Path) -> tuple[Path, dict[str, Any]]:
    lock = benchmark.read_json(root / "configs/trimem_v1/grader_lock.json")
    specs = [row for row in lock["dataset_files"] if row["benchmark_id"] == BENCHMARK]
    if len(specs) != 1:
        raise SupplementalDatasetError("Pinned SWE dataset binding is missing")
    spec = specs[0]
    path = cache_root / BENCHMARK / spec["dataset_revision"] / Path(spec["path"]).name
    if (not path.is_file() or path.is_symlink() or path.stat().st_size != spec["bytes"]
            or sha(path.read_bytes()) != spec["sha256"]):
        raise SupplementalDatasetError("Pinned cached SWE parquet bytes differ")
    return path, spec


def _selected_rows(path: Path, excluded: set[str], selection: Mapping[str, Any] = SELECTION
                   ) -> tuple[list[str], dict[str, dict[str, Any]]]:
    import pyarrow.parquet as pq
    # This first read is intentionally restricted to public identity columns.
    selected = select_identities(pq.read_table(path, columns=["instance_id", "repo"]).to_pylist(),
                                 excluded, selection)
    wanted = set(selected)
    rows = {}
    for row in pq.read_table(path, filters=[("instance_id", "in", selected)]).to_pylist():
        identity = row["instance_id"]
        if identity in wanted:
            if identity in rows:
                raise SupplementalDatasetError("Duplicate selected source row")
            rows[identity] = dict(row)
    if set(rows) != wanted:
        raise SupplementalDatasetError("Selected source rows are missing")
    return selected, rows


def _git(history: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    env = benchmark._hermetic_git_environment()
    env["GIT_NO_LAZY_FETCH"] = "1"
    return subprocess.run(benchmark._hermetic_git_command(["-C", str(history), *arguments]),
                          capture_output=True, text=True, check=False, timeout=120, env=env)


def _git_blob(history: Path, object_name: str) -> subprocess.CompletedProcess[bytes]:
    """Read public blob bytes without newline conversion or implicit fetching."""
    env = benchmark._hermetic_git_environment()
    env["GIT_NO_LAZY_FETCH"] = "1"
    return subprocess.run(benchmark._hermetic_git_command([
        "-C", str(history), "cat-file", "blob", object_name]),
        capture_output=True, check=False, timeout=120, env=env)


def _public_runner_evidence(history: Path, candidates: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep every candidate, including unavailable public runner objects."""
    if not history.is_dir() or history.is_symlink():
        raise SupplementalDatasetError("Public history checkout is unavailable")
    origin = _git(history, ["remote", "get-url", "origin"])
    if origin.returncode or origin.stdout.strip() != "https://github.com/sympy/sympy.git":
        raise SupplementalDatasetError("Public history origin differs")
    evidence = []
    for row in candidates:
        commit = row["base_commit"]
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise SupplementalDatasetError("Malformed public runner commit")
        result = _git_blob(history, commit + ":bin/test")
        evidence.append({"instance_id": row["instance_id"], "base_commit": commit,
                         "runner_path": "bin/test", "runner_returncode": result.returncode,
                         "runner_sha256": sha(result.stdout) if result.returncode == 0 else None})
    return evidence


def _public_evidence_file(path_value: Any, expected_sha256: Any) -> dict[str, Any]:
    if (not isinstance(path_value, str) or not Path(path_value).is_absolute()
            or not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)):
        raise SupplementalDatasetError("Public runtime receipt binding is malformed")
    path = Path(path_value)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 4 * 1024 * 1024:
        raise SupplementalDatasetError("Public runtime receipt is unavailable")
    raw = path.read_bytes()
    if sha(raw) != expected_sha256:
        raise SupplementalDatasetError("Public runtime receipt bytes differ")
    value = benchmark.strict_json_loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise SupplementalDatasetError("Public runtime receipt is not an object")
    return value


def _validated_runtime_screening(screening: Mapping[str, Any], runners: list[Mapping[str, Any]], *,
                                  expected_sha256: str) -> dict[str, dict[str, Any]]:
    """Verify sealed public probe receipts, without running containers or models."""
    if sha(canonical(screening) + b"\n") != expected_sha256:
        raise SupplementalDatasetError("Frozen public runtime screening bytes differ")
    compatible_ids = [row["instance_id"] for row in runners
                      if row["runner_returncode"] == 0 and row["runner_sha256"] == NATIVE005_RUNNER_SHA256]
    expected_keys = {"schema", "status", "selection_or_experiment_ready", "solver_model_calls", "new_grader_calls",
                     "required_public_runner_sha256", "required_public_python_version", "eligibility_rule",
                     "requested_image_count", "screened_image_count", "eligible_image_count", "images"}
    if (set(screening) != expected_keys or type(screening["schema"]) is not int or screening["schema"] != 1
            or screening["status"] != "PUBLIC_RUNTIME_SCREENING_COMPLETE"
            or screening["selection_or_experiment_ready"] is not False
            or any(type(screening[key]) is not int or screening[key] != 0
                   for key in ("solver_model_calls", "new_grader_calls"))
            or screening["required_public_runner_sha256"] != NATIVE005_RUNNER_SHA256
            or screening["required_public_python_version"] != "Python 3.9.20"
            or screening["eligibility_rule"] != (
                "repo_digest_verified AND public_preflight_returncode == 0 AND exact runner SHA AND exact Python version")
            or any(type(screening[key]) is not int or screening[key] != len(compatible_ids)
                   for key in ("requested_image_count", "screened_image_count"))
            or not isinstance(screening["images"], list)
            or [row.get("instance_id") for row in screening["images"]] != compatible_ids):
        raise SupplementalDatasetError("Public runtime screening does not cover every runner-compatible candidate")
    mapped = {}
    for row in screening["images"]:
        instance, image = row["instance_id"], row["image"]
        name = "swebench/sweb.eval.x86_64." + instance.replace("__", "_1776_")
        registry = _public_evidence_file(row["registry_evidence_path"], row["registry_response_sha256"])
        registry_entry = {"instance_id": instance, "benchmark_id": BENCHMARK,
                          "image": image, "harness_image_tag": name + ":latest",
                          "registry_evidence_url": f"https://hub.docker.com/v2/repositories/{name}/tags/latest",
                          "registry_response_sha256": row["registry_response_sha256"],
                          "registry_response_canonical_sha256": row["registry_response_canonical_sha256"],
                          "registry_last_updated_utc": registry["last_updated"], "registry_response": registry}
        _validate_images([registry_entry], [instance])
        if (row["registry_entry_canonical_sha256"] != sha(canonical(registry_entry))
                or row["image_digest"] != image.rsplit("@", 1)[1]):
            raise SupplementalDatasetError("Public runtime registry identity differs")
        digest = _public_evidence_file(row["digest_verification_evidence_path"],
                                       row["digest_verification_evidence_sha256"])
        if (digest.get("instance_id") != instance or digest.get("image") != image
                or digest.get("command") != ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image]
                or not isinstance(digest.get("repo_digests"), list) or image not in digest["repo_digests"]
                or type(digest.get("pull_returncode")) is not int or digest["pull_returncode"] != 0
                or row["repo_digest_verified"] is not True):
            raise SupplementalDatasetError("Public runtime image digest receipt differs")
        public = _public_evidence_file(row["runtime_evidence_path"], row["runtime_evidence_sha256"])
        expected_command = ["docker", "run", "--name", "native005-screening-preflight-" + instance.rsplit("-", 1)[1],
            "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "64", "--entrypoint", "/bin/sh", image, "-c",
            "sha256sum /testbed/bin/test && /opt/miniconda3/envs/testbed/bin/python --version"]
        original_command = [*expected_command]
        original_command[3] = "native005-public-preflight-" + instance.rsplit("-", 1)[1]
        if (public != row["public_preflight"] or public.get("instance_id") != instance or public.get("image") != image
                or public.get("command") not in (expected_command, original_command)
                or public.get("read_only_container") is not True or public.get("network") != "none"
                or type(public.get("returncode")) is not int
                or not isinstance(public.get("stdout"), str) or not isinstance(public.get("stderr"), str)
                or any(row["public_runner_preflight_" + key] != public[key] for key in ("returncode", "stdout", "stderr"))):
            raise SupplementalDatasetError("Public runtime probe command or receipt differs")
        lines = public["stdout"].splitlines()
        runner = lines[0].split()[0] if lines and lines[0].split() else None
        version = lines[1] if len(lines) == 2 else None
        if (public["returncode"] == 0 and (len(lines) != 2
                or not re.fullmatch(r"[0-9a-f]{64}  /testbed/bin/test", lines[0])
                or not re.fullmatch(r"Python [0-9]+\.[0-9]+\.[0-9]+", lines[1]))):
            raise SupplementalDatasetError("Public runtime successful output is malformed")
        reasons = []
        if public["returncode"] != 0:
            reasons.append("PUBLIC_PREFLIGHT_NONZERO")
        if runner != NATIVE005_RUNNER_SHA256:
            reasons.append("RUNNER_SHA_MISMATCH")
        if version != "Python 3.9.20":
            reasons.append("PYTHON_VERSION_MISMATCH")
        eligible = not reasons
        if (row["runner_sha256"] != runner or row["public_runner_sha256"] != runner
                or row["python_version"] != version or row["public_python_version"] != version
                or row["python_executable"] != "/opt/miniconda3/envs/testbed/bin/python"
                or row["eligible"] is not eligible or row["ineligibility_reasons"] != reasons):
            raise SupplementalDatasetError("Public runtime eligibility disagrees with actual probe output")
        mapped[instance] = dict(row)
    if (type(screening["eligible_image_count"]) is not int
            or screening["eligible_image_count"] != sum(row["eligible"] for row in mapped.values())):
        raise SupplementalDatasetError("Public runtime eligibility count differs")
    return mapped


def _validate_selected_runtime_images(images: list[Mapping[str, Any]], screening: Mapping[str, Any]) -> None:
    runtimes = {row["instance_id"]: row for row in screening["images"]}
    for image in images:
        runtime = runtimes.get(image["instance_id"])
        if (runtime is None or runtime["eligible"] is not True
                or any(image.get(key) != runtime[key] for key in (
                    "image", "registry_response_sha256", "registry_response_canonical_sha256"))):
            raise SupplementalDatasetError("Selected image differs from its eligible public runtime probe")


def _runner_compatible_identities(history: Path, candidates: list[Mapping[str, Any]],
                                  runner_evidence: list[Mapping[str, Any]], *,
                                  runner_sha256: str, evaluation_count: int,
                                  runtime_eligible_ids: set[str] | None = None) -> list[str]:
    """Select the first feasible ordered pair and its first later descendants."""
    if (len(candidates) != len(runner_evidence)
            or any(candidate["instance_id"] != runner["instance_id"]
                   or candidate["base_commit"] != runner["base_commit"]
                   for candidate, runner in zip(candidates, runner_evidence))):
        raise SupplementalDatasetError("Public runner evidence does not cover the candidate universe")
    eligible = [candidate for candidate, runner in zip(candidates, runner_evidence)
                if runner["runner_returncode"] == 0 and runner["runner_sha256"] == runner_sha256
                and (runtime_eligible_ids is None or candidate["instance_id"] in runtime_eligible_ids)]
    timestamps: dict[str, int] = {}
    ancestors: dict[tuple[str, str], bool] = {}

    def timestamp(commit: str) -> int:
        if commit not in timestamps:
            observed = _git(history, ["cat-file", "commit", commit])
            match = re.search(r"^committer .+ ([0-9]+) [+-][0-9]{4}$",
                              observed.stdout.split("\n\n", 1)[0], re.MULTILINE)
            if observed.returncode or match is None:
                raise SupplementalDatasetError("Commit timestamp is unavailable")
            timestamps[commit] = int(match.group(1))
        return timestamps[commit]

    def precedes(source: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
        base, head = source["base_commit"], target["base_commit"]
        pair = (base, head)
        if pair not in ancestors:
            result = _git(history, ["merge-base", "--is-ancestor", base, head])
            if result.returncode not in (0, 1):
                raise SupplementalDatasetError("Public selection ancestry lookup failed")
            ancestors[pair] = (result.returncode == 0 and timestamp(base) < timestamp(head))
        return ancestors[pair]

    for first_index, first in enumerate(eligible):
        for second_index in range(first_index + 1, len(eligible)):
            second = eligible[second_index]
            if not precedes(first, second):
                continue
            evaluation = []
            for target in eligible[second_index + 1:]:
                if precedes(first, target) and precedes(second, target):
                    evaluation.append(target)
                    if len(evaluation) == evaluation_count:
                        return [row["instance_id"] for row in [first, second, *evaluation]]
    raise SupplementalDatasetError("Insufficient runner-compatible chronological public identities")


def ancestry_evidence(history: Path, prior: Mapping[str, Any] | None,
                      targets: list[Mapping[str, Any]],
                      selection: Mapping[str, Any] = SELECTION,
                      additional_prior_training_targets: list[Mapping[str, Any]] | None = None
                      ) -> list[dict[str, Any]]:
    """Prove base ancestry locally; no issue, patch or hidden test reads."""
    if not history.is_dir() or history.is_symlink():
        raise SupplementalDatasetError("Public history checkout is unavailable")
    origin = _git(history, ["remote", "get-url", "origin"])
    if origin.returncode or origin.stdout.strip() != "https://github.com/sympy/sympy.git":
        raise SupplementalDatasetError("Public history origin differs")
    selection = _validated_selection(selection)
    training_count = selection["new_training_count"]
    training, evaluation = targets[:training_count], targets[training_count:]
    if selection in (NATIVE004_SELECTION, NATIVE005_SELECTION):
        if prior is not None or additional_prior_training_targets not in (None, []):
            raise SupplementalDatasetError("Independent historical cohort forbids prior training")
        historical = []
    else:
        if prior is None:
            raise SupplementalDatasetError("Prior training target is absent")
        historical = [prior, *(additional_prior_training_targets or [])]
    sources = [*historical, *training]
    pairs = [(source, target) for index, target in enumerate(training)
             for source in [*historical, *training[:index]]]
    pairs += [(source, target) for source in sources for target in evaluation]
    evidence = []
    for source, target in pairs:
        base, head = source["base_commit"], target["base_commit"]
        if any(not re.fullmatch(r"[0-9a-f]{40}", value) for value in (base, head)):
            raise SupplementalDatasetError("Malformed chronology commit")
        result = _git(history, ["merge-base", "--is-ancestor", base, head])
        if result.returncode != 0:
            raise SupplementalDatasetError("Training base is not an evaluation ancestor")
        timestamps = []
        for commit in (base, head):
            # cat-file reads the commit object only. `show -s` may still need
            # attributes blobs in a filtered clone and trigger a lazy fetch.
            observed = _git(history, ["cat-file", "commit", commit])
            match = re.search(r"^committer .+ ([0-9]+) [+-][0-9]{4}$",
                              observed.stdout.split("\n\n", 1)[0], re.MULTILINE)
            if observed.returncode or match is None:
                raise SupplementalDatasetError("Commit timestamp is unavailable")
            timestamps.append(int(match.group(1)))
        if timestamps[0] >= timestamps[1]:
            raise SupplementalDatasetError("Training base timestamp does not precede target")
        evidence.append({
            "source_instance_id": source["instance_id"], "source_base_commit": base,
            "target_instance_id": target["instance_id"], "target_base_commit": head,
            "source_commit_unix_seconds": timestamps[0], "target_commit_unix_seconds": timestamps[1],
            "method": "git merge-base --is-ancestor", "returncode": result.returncode,
        })
    return evidence


def _target(instance: str, row: Mapping[str, Any], spec: Mapping[str, Any], index: int,
            selection: Mapping[str, Any] = SELECTION) -> dict[str, Any]:
    return {"target_id": BENCHMARK + "--" + instance, "instance_id": instance,
            "benchmark_id": BENCHMARK, "repository": REPOSITORY, "language": "python",
            "base_commit": row["base_commit"], "dataset_revision": spec["dataset_revision"],
            "source_row_sha256": sha(canonical(row)), "order_index": index,
            "role": "TRAINING" if index < _validated_selection(selection)["new_training_count"] else "EVALUATION",
            "public_issue_created_at": row["created_at"]}


def _validate_images(value: Any, selected: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(selected):
        raise SupplementalDatasetError("Supplemental image count differs")
    mapped = {}
    for instance, entry in zip(selected, value):
        name = "swebench/sweb.eval.x86_64." + instance.replace("__", "_1776_")
        image = entry.get("image", "")
        response = entry.get("registry_response")
        if (entry.get("instance_id") != instance or entry.get("benchmark_id") != BENCHMARK
                or entry.get("harness_image_tag") != name + ":latest"
                or not re.fullmatch(re.escape(name) + r"@sha256:[0-9a-f]{64}", image)
                or entry.get("registry_evidence_url") != f"https://hub.docker.com/v2/repositories/{name}/tags/latest"
                or not isinstance(response, dict) or response.get("digest") != image.rsplit("@", 1)[1]
                or entry.get("registry_response_canonical_sha256") != sha(canonical(response))
                or not any(item.get("architecture") == "amd64" and item.get("os") == "linux"
                           for item in response.get("images", []) if isinstance(item, dict))):
            raise SupplementalDatasetError("Official supplemental image binding differs")
        mapped[instance] = dict(entry)
    return mapped


def build_supplemental_manifest(*, cache_root: Path, history: Path,
                                registry_directory: Path, output_path: Path,
                                root: Path = ROOT,
                                selection: Mapping[str, Any] = SELECTION) -> dict[str, Any]:
    """Freeze a supported selection profile before any target solving or grading."""
    if output_path.exists():
        raise SupplementalDatasetError("Supplemental manifest already exists; never overwrite")
    selection = _validated_selection(selection)
    excluded, exclusions, prior = _exclusions(root, selection)
    additional_priors = _additional_prior_training_targets(root, selection)
    dataset, spec = _locked_dataset(cache_root, root)
    runtime_screening = (_public_evidence_file(str((registry_directory / "runtime-screening.json").resolve()),
        NATIVE005_SELECTION["runtime_screening_raw_sha256"]) if selection == NATIVE005_SELECTION else None)
    selection_evidence = (_native004_selection_evidence(dataset, excluded)
                          if selection == NATIVE004_SELECTION else
                          _native005_selection_evidence(dataset, excluded, history, runtime_screening)
                          if selection == NATIVE005_SELECTION else None)
    selected, rows = _selected_rows(dataset, excluded, selection)
    targets = [_target(instance, rows[instance], spec, i, selection) for i, instance in enumerate(selected)]
    images = benchmark.strict_json_loads((registry_directory / "images.json").read_text())
    for image in images:
        raw = (registry_directory / ("registry-" + image["instance_id"].rsplit("-", 1)[1] + ".json")).read_bytes()
        if sha(raw) != image["registry_response_sha256"]:
            raise SupplementalDatasetError("Registry response bytes changed before freeze")
        image["registry_response"] = benchmark.strict_json_loads(raw.decode("utf-8"))
        image["registry_response_canonical_sha256"] = sha(canonical(image["registry_response"]))
    _validate_images(images, selected)
    if selection == NATIVE005_SELECTION:
        _validate_selected_runtime_images(images, runtime_screening)
    value = {"schema": SCHEMA, "status": "FROZEN", "selection": selection,
             "dataset": spec, "excluded_manifests": exclusions, "targets": targets,
             "prior_training_target": None if prior is None else {key: prior[key] for key in (
                 "target_id", "instance_id", "base_commit", "source_row_sha256")},
             "images": images, "history_path": str(history.resolve()),
             "ancestry": ancestry_evidence(history, prior, targets, selection, additional_priors),
             "chronology_claim": "TRAINING_BASE_ANCESTRY_ONLY_NOT_NATIVE_PATCH_UPSTREAM_MERGE",
             "scope_claim": "IDENTITY_SELECTED_SYMPY_PILOT_NOT_ORIGINAL_HELDOUT_ENDPOINT",
             "model_calls_at_selection": 0, "new_target_grader_runs_at_selection": 0}
    if selection in (NATIVE003_SELECTION, NATIVE004_SELECTION, NATIVE005_SELECTION):
        value["additional_prior_training_targets"] = additional_priors
    if selection in (NATIVE004_SELECTION, NATIVE005_SELECTION):
        value.update({"selection_evidence": selection_evidence,
                      "scope_claim": (NATIVE004_SCOPE_CLAIM if selection == NATIVE004_SELECTION else
                                      NATIVE005_SCOPE_CLAIM),
                      # The conversational planner was an LLM; its call count
                      # was not instrumented. Solver and grader counts are zero.
                      "model_calls_at_selection": None,
                      "planner_llm_involved_at_selection": True,
                      "solver_model_calls_at_selection": 0})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
    return value


def load_supplemental_rows(manifest_path: Path, cache_root: Path, *,
                           expected_sha256: str, root: Path = ROOT
                           ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]],
                                      dict[str, dict[str, Any]], dict[str, Any]]:
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            or not manifest_path.is_file() or manifest_path.is_symlink()
            or manifest_path.stat().st_size > 1024 * 1024):
        raise SupplementalDatasetError("Supplemental manifest binding is invalid")
    raw = manifest_path.read_bytes()
    if sha(raw) != expected_sha256:
        raise SupplementalDatasetError("Supplemental manifest raw hash differs")
    value = benchmark.strict_json_loads(raw.decode("utf-8"))
    if isinstance(value, dict) and value.get("schema") == "skhynix/native-disjoint-transfer-manifest/1.0":
        from trimem_skhynix_native_transfer_dataset import load_transfer_rows
        return load_transfer_rows(manifest_path, cache_root, expected_sha256=expected_sha256, root=root)
    if isinstance(value, dict) and value.get("schema") == "skhynix/native-controlled-transfer-manifest/1.0":
        from trimem_skhynix_native_controlled_dataset import load_controlled_rows
        return load_controlled_rows(manifest_path, cache_root, expected_sha256=expected_sha256, root=root)
    selection = _validated_selection(value.get("selection"))
    native004 = selection == NATIVE004_SELECTION
    native005 = selection == NATIVE005_SELECTION
    independent = native004 or native005
    if (value.get("schema") != SCHEMA or value.get("status") != "FROZEN"
            or value.get("chronology_claim") != "TRAINING_BASE_ANCESTRY_ONLY_NOT_NATIVE_PATCH_UPSTREAM_MERGE"
            or value.get("scope_claim") != (NATIVE004_SCOPE_CLAIM if native004 else
                NATIVE005_SCOPE_CLAIM if native005 else
                "IDENTITY_SELECTED_SYMPY_PILOT_NOT_ORIGINAL_HELDOUT_ENDPOINT")
            or value.get("model_calls_at_selection") != (None if independent else 0)
            or value.get("new_target_grader_runs_at_selection") != 0):
        raise SupplementalDatasetError("Supplemental selection contract differs")
    if independent:
        expected_keys = {"schema", "status", "selection", "dataset", "excluded_manifests", "targets",
                         "prior_training_target", "additional_prior_training_targets", "images",
                         "history_path", "ancestry", "chronology_claim", "scope_claim",
                         "model_calls_at_selection", "new_target_grader_runs_at_selection",
                         "planner_llm_involved_at_selection", "solver_model_calls_at_selection",
                         "selection_evidence"}
        if (set(value) != expected_keys or value["prior_training_target"] is not None
                or value["additional_prior_training_targets"] != []
                or value["planner_llm_involved_at_selection"] is not True
                or type(value["solver_model_calls_at_selection"]) is not int
                or value["solver_model_calls_at_selection"] != 0
                or type(value["new_target_grader_runs_at_selection"]) is not int):
            raise SupplementalDatasetError("Independent historical cohort selection or prior training differs")
    excluded, exclusions, prior = _exclusions(root, selection)
    additional_priors = _additional_prior_training_targets(root, selection)
    dataset, spec = _locked_dataset(cache_root, root)
    if native004 and value["selection_evidence"] != _native004_selection_evidence(dataset, excluded):
        raise SupplementalDatasetError("Public candidate metadata or selection evidence differs")
    if native005 and value["selection_evidence"] != _native005_selection_evidence(
            dataset, excluded, Path(value["history_path"]), value["selection_evidence"]["runtime_screening"]):
        raise SupplementalDatasetError("Public candidate metadata or runner selection evidence differs")
    selected, rows = _selected_rows(dataset, excluded, selection)
    targets = [_target(instance, rows[instance], spec, i, selection) for i, instance in enumerate(selected)]
    expected_prior = None if prior is None else {key: prior[key] for key in (
        "target_id", "instance_id", "base_commit", "source_row_sha256")}
    if (value.get("dataset") != spec or value.get("excluded_manifests") != exclusions
            or value.get("targets") != targets or value.get("prior_training_target") != expected_prior):
        raise SupplementalDatasetError("Supplemental targets, exclusions or source row hashes differ")
    if (selection in (NATIVE003_SELECTION, NATIVE004_SELECTION, NATIVE005_SELECTION)
            and value.get("additional_prior_training_targets") != additional_priors):
        raise SupplementalDatasetError("Additional prior training identities differ")
    images = _validate_images(value.get("images"), selected)
    if native005:
        _validate_selected_runtime_images(list(images.values()), value["selection_evidence"]["runtime_screening"])
    if value.get("ancestry") != ancestry_evidence(Path(value["history_path"]), prior, targets,
                                                selection, additional_priors):
        raise SupplementalDatasetError("Supplemental ancestry evidence differs")
    return targets, rows, images, value
