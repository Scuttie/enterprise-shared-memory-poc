"""Create a deterministic, content-free inventory of restricted evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from trimem_atomic_evidence import atomic_write_bytes


SCHEMA = "trimem/restricted-evidence-inventory/1.0"


class EvidenceInventoryError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            byte_count += len(chunk)
    return byte_count, digest.hexdigest()


def _files(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as entries:
            ordered = sorted(entries, key=lambda item: item.name)
        for entry in ordered:
            path = Path(entry.path)
            mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode):
                raise EvidenceInventoryError(
                    f"restricted evidence contains a symlink: {path.relative_to(root).as_posix()}"
                )
            if stat.S_ISDIR(mode):
                stack.append(path)
                continue
            if not stat.S_ISREG(mode):
                raise EvidenceInventoryError(
                    f"restricted evidence contains a non-regular file: {path.relative_to(root).as_posix()}"
                )
            relative = path.relative_to(root).as_posix()
            byte_count, digest = _hash_file(path)
            records.append(
                {
                    "bytes": byte_count,
                    "path": relative,
                    "sha256": digest,
                }
            )
    records.sort(key=lambda item: item["path"])
    if not records:
        raise EvidenceInventoryError("restricted evidence root is empty")
    return records


def build_inventory(root: Path, *, root_label: str) -> dict[str, Any]:
    if not isinstance(root_label, str) or not root_label or "/" in root_label or "\\" in root_label:
        raise EvidenceInventoryError("root label must be one non-empty path segment")
    if root.is_symlink():
        raise EvidenceInventoryError("restricted evidence root must not be a symlink")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise EvidenceInventoryError("restricted evidence root must be a real directory")
    files = _files(root)
    payload = {
        "files": files,
        "root": root_label,
        "schema": SCHEMA,
        "total_bytes": sum(item["bytes"] for item in files),
        "total_files": len(files),
    }
    return {
        **payload,
        "inventory_sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
    }


def write_inventory(root: Path, output: Path, *, root_label: str) -> dict[str, Any]:
    root = root.resolve(strict=True)
    output_parent = output.parent.resolve(strict=True)
    output_resolved = output_parent / output.name
    if root == output_resolved or root in output_resolved.parents:
        raise EvidenceInventoryError("inventory output must be outside restricted evidence root")
    value = build_inventory(root, root_label=root_label)
    raw = _canonical(value) + b"\n"
    try:
        atomic_write_bytes(output_resolved, raw)
    except FileExistsError as exc:
        raise EvidenceInventoryError("refusing to overwrite evidence inventory") from exc
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--root-label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        value = write_inventory(
            args.root,
            args.output,
            root_label=args.root_label,
        )
    except (OSError, EvidenceInventoryError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL_CLOSED"}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "inventory_sha256": value["inventory_sha256"],
                "status": "PASS",
                "total_bytes": value["total_bytes"],
                "total_files": value["total_files"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
