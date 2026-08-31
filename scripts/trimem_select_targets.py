"""Reproduce the frozen TriMem V1 target sets without model/grader outcomes."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/trimem_v1"
SOURCE_URLS = {
    "swebench_verified": "https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified/resolve/{revision}/{path}",
    "multi_swe_bench_mini": "https://huggingface.co/datasets/ByteDance-Seed/Multi-SWE-bench_mini/resolve/{revision}/{path}",
    "multi_swe_bench_flash": "https://huggingface.co/datasets/ByteDance-Seed/Multi-SWE-bench-flash/resolve/{revision}/{path}",
}


class SelectionError(ValueError):
    pass


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise SelectionError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SelectionError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SelectionError(f"invalid selection JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SelectionError(f"selection JSON root is not an object: {path}")
    return value


def download_locked(spec: Mapping[str, Any], cache: Path) -> Path:
    benchmark_id = str(spec["benchmark_id"])
    target = cache / benchmark_id / Path(str(spec["path"])).name
    expected_bytes, expected_hash = int(spec["bytes"]), str(spec["sha256"])
    if target.is_file() and target.stat().st_size == expected_bytes and digest(target.read_bytes()) == expected_hash:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    url = SOURCE_URLS[benchmark_id].format(revision=spec["dataset_revision"], path=spec["path"])
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=180) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        raw = temporary.read_bytes()
        if len(raw) != expected_bytes or digest(raw) != expected_hash:
            raise SelectionError(f"pinned source file digest mismatch: {benchmark_id}")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def load_sources(cache: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, bytes]]:
    grader = read_object(CONFIG / "grader_lock.json")
    specs = grader.get("dataset_files")
    if not isinstance(specs, list) or len(specs) != 3:
        raise SelectionError("exactly three dataset source files are required")
    rows: dict[str, list[dict[str, Any]]] = {}
    raw_files: dict[str, bytes] = {}
    for spec in specs:
        if not isinstance(spec, Mapping):
            raise SelectionError("dataset source lock is malformed")
        path = download_locked(spec, cache)
        benchmark_id = str(spec["benchmark_id"])
        raw_files[benchmark_id] = path.read_bytes()
        if benchmark_id == "swebench_verified":
            try:
                import pyarrow.parquet as pq
            except (ImportError, ModuleNotFoundError) as exc:
                raise SelectionError("pyarrow is required to verify the exact SWE-bench Parquet") from exc
            decoded = pq.read_table(path).to_pylist()
        else:
            try:
                decoded = [
                    json.loads(line, object_pairs_hook=_strict_pairs)
                    for line in path.read_text(encoding="utf-8").splitlines()
                ]
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SelectionError(f"invalid pinned JSONL: {benchmark_id}") from exc
        if not decoded or any(not isinstance(row, dict) for row in decoded):
            raise SelectionError(f"source rows are empty or malformed: {benchmark_id}")
        rows[benchmark_id] = decoded
    return rows, raw_files


def instance_id(row: Mapping[str, Any]) -> str:
    value = row.get("instance_id")
    if not isinstance(value, str) or not value:
        raise SelectionError("source row has no instance_id")
    return value


def repository(benchmark_id: str, row: Mapping[str, Any]) -> str:
    if benchmark_id == "swebench_verified":
        value = row.get("repo")
    else:
        value = f"{row.get('org')}/{row.get('repo')}"
    if not isinstance(value, str) or value.count("/") != 1 or "None" in value:
        raise SelectionError("source row repository is malformed")
    return value


def base_commit(benchmark_id: str, row: Mapping[str, Any]) -> str:
    value = row.get("base_commit") if benchmark_id == "swebench_verified" else row.get("base", {}).get("sha")
    if not isinstance(value, str) or len(value) != 40:
        raise SelectionError("source row base commit is not exact")
    return value


def language(benchmark_id: str, row: Mapping[str, Any], aliases: Mapping[str, str]) -> str:
    if benchmark_id == "swebench_verified":
        return "python"
    value = str(row.get("language", "")).lower()
    normalized = aliases.get(value, value)
    if not normalized:
        raise SelectionError("source row language is missing")
    return normalized


def row_hash(row: Mapping[str, Any]) -> str:
    return digest(canonical_bytes(row))


def row_target(benchmark_id: str, revision: str, row: Mapping[str, Any], order_index: int,
               aliases: Mapping[str, str]) -> dict[str, Any]:
    iid = instance_id(row)
    return {
        "base_commit": base_commit(benchmark_id, row),
        "benchmark_id": benchmark_id,
        "dataset_revision": revision,
        "instance_id": iid,
        "language": language(benchmark_id, row, aliases),
        "order_index": order_index,
        "repository": repository(benchmark_id, row),
        "source_row_sha256": row_hash(row),
        "target_id": f"{benchmark_id}--{iid}",
    }


def reproduce_smoke(rows: Mapping[str, list[dict[str, Any]]], revisions: Mapping[str, str],
                    aliases: Mapping[str, str], seed: str) -> list[dict[str, Any]]:
    selected: list[tuple[str, dict[str, Any]]] = []
    for benchmark_id in ("swebench_verified", "multi_swe_bench_mini", "multi_swe_bench_flash"):
        ranked = _ranked_rows(seed, "grader-smoke", benchmark_id, rows[benchmark_id], set())
        selected.extend(
            (benchmark_id, row)
            for row in _take_distinct_repositories(benchmark_id, ranked, 2)
        )
    result = []
    for benchmark_id, row in selected:
        common = row_target(benchmark_id, revisions[benchmark_id], row, 0, aliases)
        common.pop("order_index")
        common.pop("target_id")
        for probe, expected in (("GOLD", True), ("NOOP", False)):
            result.append({
                **common,
                "expected_resolved": expected,
                "probe": probe,
                "target_id": f"{benchmark_id}--{common['instance_id']}--{probe.lower()}",
            })
    return result


def _score(seed: str, split: str, benchmark_id: str, row: Mapping[str, Any]) -> str:
    material = f"{seed}|trimem-selector-v3|{split}|{benchmark_id}|{instance_id(row)}"
    return digest(material.encode("utf-8"))


def _ranked_rows(seed: str, split: str, benchmark_id: str,
                 source_rows: list[dict[str, Any]], excluded: set[str]) -> list[dict[str, Any]]:
    eligible = [row for row in source_rows if instance_id(row) not in excluded]
    if len({instance_id(row) for row in eligible}) != len(eligible):
        raise SelectionError(f"duplicate eligible instance_id in {benchmark_id}")
    return sorted(
        eligible,
        key=lambda row: (_score(seed, split, benchmark_id, row), instance_id(row)),
    )


def _take_distinct_repositories(benchmark_id: str, ranked: list[dict[str, Any]],
                                count: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in ranked:
        repo = repository(benchmark_id, row)
        if repo in seen:
            continue
        selected.append(row)
        seen.add(repo)
        if len(selected) == count:
            return selected
    raise SelectionError(f"not enough repository-distinct rows in {benchmark_id}")


def _heldout_language_rows(seed: str, benchmark_id: str, ranked: list[dict[str, Any]],
                           aliases: Mapping[str, str], count: int) -> list[dict[str, Any]]:
    languages = sorted(
        {language(benchmark_id, row, aliases) for row in ranked},
        key=lambda value: (
            digest(
                f"{seed}|trimem-selector-v3|heldout|{benchmark_id}|language|{value}".encode("utf-8")
            ),
            value,
        ),
    )
    if len(languages) < count:
        raise SelectionError(f"not enough normalized languages in {benchmark_id}")
    selected: list[dict[str, Any]] = []
    seen_repositories: set[str] = set()
    for value in languages[:count]:
        candidates = [row for row in ranked if language(benchmark_id, row, aliases) == value]
        distinct = [row for row in candidates if repository(benchmark_id, row) not in seen_repositories]
        winner = (distinct or candidates)[0]
        selected.append(winner)
        seen_repositories.add(repository(benchmark_id, winner))
    return selected


def reproduce_split(split: str, rows: Mapping[str, list[dict[str, Any]]],
                    revisions: Mapping[str, str], aliases: Mapping[str, str],
                    excluded: set[str], seed: str) -> list[dict[str, Any]]:
    if split == "development":
        counts = {
            "swebench_verified": 4,
            "multi_swe_bench_mini": 4,
            "multi_swe_bench_flash": 4,
        }
    elif split == "heldout":
        counts = {
            "swebench_verified": 12,
            "multi_swe_bench_mini": 8,
            "multi_swe_bench_flash": 7,
        }
    else:
        raise SelectionError(f"unknown split: {split}")
    selected_rows: list[tuple[str, dict[str, Any]]] = []
    used_instance_ids = set(excluded)
    for benchmark_id, count in counts.items():
        ranked = _ranked_rows(seed, split, benchmark_id, rows[benchmark_id], used_instance_ids)
        if split == "heldout" and benchmark_id.startswith("multi_swe_bench_"):
            chosen = _heldout_language_rows(seed, benchmark_id, ranked, aliases, count)
        else:
            chosen = _take_distinct_repositories(benchmark_id, ranked, count)
        selected_rows.extend((benchmark_id, row) for row in chosen)
        used_instance_ids.update(instance_id(row) for row in chosen)
    return [
        row_target(benchmark_id, revisions[benchmark_id], row, order_index, aliases)
        for order_index, (benchmark_id, row) in enumerate(selected_rows)
    ]


def _reject_salts(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if "salt" in str(key).lower():
                raise SelectionError("selection plan must not contain per-slot salts")
            _reject_salts(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_salts(nested)


def verify(cache: Path) -> dict[str, Any]:
    plan = read_object(CONFIG / "selection_plan.json")
    if plan.get("status") != "FROZEN_BEFORE_MODEL_OR_GRADER_RESULTS":
        raise SelectionError("selection plan is not frozen")
    if plan.get("schema") != "trimem/selection-plan/3.0":
        raise SelectionError("selection plan schema is not the public-identity selector v3")
    _reject_salts(plan)
    expected_score = (
        "sha256(seed|trimem-selector-v3|split|benchmark_id|instance_id), ascending lowercase bytes"
    )
    if plan.get("row_score") != expected_score:
        raise SelectionError("selection row-score contract drift")
    rows, _raw_files = load_sources(cache)
    grader = read_object(CONFIG / "grader_lock.json")
    revisions = {row["benchmark_id"]: row["dataset_revision"] for row in grader["dataset_files"]}
    aliases = plan.get("language_normalization")
    if not isinstance(aliases, Mapping):
        raise SelectionError("language normalization lock is missing")
    smoke_manifest = read_object(CONFIG / "grader_smoke_manifest.json")
    smoke = reproduce_smoke(rows, revisions, aliases, str(plan.get("seed")))
    if smoke != smoke_manifest.get("targets"):
        raise SelectionError("grader-smoke deterministic selection does not reproduce the manifest")
    if digest(canonical_bytes(smoke)) != smoke_manifest.get("target_set_sha256"):
        raise SelectionError("grader-smoke target-set digest mismatch")
    smoke_ids = {row["instance_id"] for row in smoke}
    development = reproduce_split(
        "development", rows, revisions, aliases, smoke_ids, str(plan.get("seed"))
    )
    development_manifest = read_object(CONFIG / "development_manifest.json")
    if development != development_manifest.get("targets"):
        raise SelectionError("development deterministic selection does not reproduce the manifest")
    if digest(canonical_bytes(development)) != development_manifest.get("target_set_sha256"):
        raise SelectionError("development target-set digest mismatch")
    development_ids = {row["instance_id"] for row in development}
    heldout = reproduce_split(
        "heldout", rows, revisions, aliases, smoke_ids | development_ids, str(plan.get("seed")),
    )
    heldout_manifest = read_object(CONFIG / "heldout_manifest.json")
    if heldout != heldout_manifest.get("targets"):
        raise SelectionError("held-out deterministic selection does not reproduce the manifest")
    if digest(canonical_bytes(heldout)) != heldout_manifest.get("target_set_sha256"):
        raise SelectionError("held-out target-set digest mismatch")
    heldout_ids = {row["instance_id"] for row in heldout}
    if len(development_ids) != len(development) or len(heldout_ids) != len(heldout):
        raise SelectionError("development or held-out contains a duplicate public instance identity")
    if smoke_ids & development_ids or smoke_ids & heldout_ids or development_ids & heldout_ids:
        raise SelectionError("smoke/development/held-out instance sets overlap")
    if Counter(row["benchmark_id"] for row in development) != Counter({
        "swebench_verified": 4, "multi_swe_bench_mini": 4, "multi_swe_bench_flash": 4,
    }):
        raise SelectionError("development benchmark strata count mismatch")
    if Counter(row["benchmark_id"] for row in heldout) != Counter({
        "swebench_verified": 12, "multi_swe_bench_mini": 8, "multi_swe_bench_flash": 7,
    }):
        raise SelectionError("held-out benchmark strata count mismatch")
    return {
        "development_instances": len(development),
        "heldout_instances": len(heldout),
        "instance_overlap": 0,
        "selection_plan_sha256": digest(canonical_bytes(plan)),
        "smoke_instances": len(smoke_ids),
        "smoke_targets": len(smoke),
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path(tempfile.gettempdir()) / "trimem-v1-source-cache")
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.cache_dir.resolve()), ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, SelectionError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
