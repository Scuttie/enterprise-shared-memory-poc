from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from enterprise_memory.trimem.accounting import canonical_bytes
from enterprise_memory.trimem.function_tools import (
    FUNCTION_TOOL_BY_NAME,
    FUNCTION_TOOLS_SHA256,
    canonical_bytes as function_tool_bytes,
    detached_function_tools,
    validate_function_arguments,
)
from enterprise_memory.trimem.git_workspace import GitCheckoutWorkspace
from enterprise_memory.trimem.runtime_lock import RuntimeLock
from enterprise_memory.trimem.workspace import (
    InMemoryRepositoryWorkspace,
    LIST_FILES_MAX_RESPONSE_BYTES,
    LIST_FILES_PAGINATION_CONTRACT_SHA256,
    ToolExecutionError,
    list_files_page,
)


LIST_ARGUMENTS = {
    "path_prefix": None,
    "start_after": None,
    "limit": 200,
}


def _large_paths() -> list[str]:
    paths = [
        f"src/package_{index:05d}/component_{index:05d}_implementation.py"
        for index in range(10_000)
    ]
    paths.extend(
        "very-long/"
        + (f"segment-{index:02d}-" + "x" * 90 + "/") * 3
        + f"module-{index:02d}.py"
        for index in range(12)
    )
    return sorted(paths)


def _collect_pages(workspace, *, path_prefix=None, limit=200):
    cursor = None
    files: list[str] = []
    pages: list[dict] = []
    while True:
        page = workspace.execute(
            "list_files",
            {
                "path_prefix": path_prefix,
                "start_after": cursor,
                "limit": limit,
            },
        )
        assert len(canonical_bytes(page)) <= LIST_FILES_MAX_RESPONSE_BYTES
        pages.append(page)
        files.extend(page["files"])
        if not page["truncated"]:
            break
        assert page["next_start_after"] == page["files"][-1]
        cursor = page["next_start_after"]
    return files, pages


def _git(root: Path, *args: str, input_text: str | None = None) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        input=None if input_text is None else input_text.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return completed.stdout.decode("utf-8", errors="strict").strip()


def test_large_repository_pages_are_bounded_and_reconstruct_exact_listing():
    paths = _large_paths()
    assert len(canonical_bytes(paths)) >= 319_417
    workspace = InMemoryRepositoryWorkspace(
        {path: "" for path in reversed(paths)},
        editable_paths=(paths[0],),
    )

    reconstructed, pages = _collect_pages(workspace)

    assert reconstructed == paths
    assert len(reconstructed) == len(set(reconstructed))
    assert {page["full_matching_listing_sha256"] for page in pages} == {
        hashlib.sha256(canonical_bytes(paths)).hexdigest()
    }
    assert all(page["returned_count"] == len(page["files"]) for page in pages)
    assert all(page["total_matching_count"] == len(paths) for page in pages)
    assert pages[-1]["next_start_after"] is None
    assert pages[-1]["truncated"] is False

    empty_final = workspace.execute(
        "list_files",
        {
            "path_prefix": None,
            "start_after": paths[-1],
            "limit": 200,
        },
    )
    assert empty_final == {
        "path_prefix": None,
        "start_after": paths[-1],
        "files": [],
        "returned_count": 0,
        "total_matching_count": len(paths),
        "next_start_after": None,
        "truncated": False,
        "full_matching_listing_sha256": pages[0][
            "full_matching_listing_sha256"
        ],
    }


def test_byte_cap_returns_fewer_than_requested_paths_with_exact_continuation():
    paths = [
        "src/"
        + (f"segment-{index:03d}-" + "q" * 80 + "/") * 3
        + f"value-{index:03d}.py"
        for index in range(500)
    ]
    workspace = InMemoryRepositoryWorkspace(
        {path: "" for path in paths},
        editable_paths=(paths[0],),
    )

    first = workspace.execute("list_files", dict(LIST_ARGUMENTS))

    assert 0 < first["returned_count"] < 200
    assert first["truncated"] is True
    assert len(canonical_bytes(first)) <= LIST_FILES_MAX_RESPONSE_BYTES
    second = workspace.execute(
        "list_files",
        {
            **LIST_ARGUMENTS,
            "start_after": first["next_start_after"],
        },
    )
    assert second["files"][0] == paths[first["returned_count"]]
    assert (
        second["full_matching_listing_sha256"]
        == first["full_matching_listing_sha256"]
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"path_prefix": None, "start_after": None},
        {**LIST_ARGUMENTS, "extra": None},
        {**LIST_ARGUMENTS, "limit": 0},
        {**LIST_ARGUMENTS, "limit": 201},
        {**LIST_ARGUMENTS, "limit": True},
        {**LIST_ARGUMENTS, "path_prefix": ""},
        {**LIST_ARGUMENTS, "path_prefix": "./src"},
        {**LIST_ARGUMENTS, "path_prefix": "src/"},
        {**LIST_ARGUMENTS, "path_prefix": "../src"},
        {**LIST_ARGUMENTS, "path_prefix": "/host/src"},
        {**LIST_ARGUMENTS, "path_prefix": "C:/host/src"},
        {**LIST_ARGUMENTS, "path_prefix": "src\\package"},
        {**LIST_ARGUMENTS, "path_prefix": ".git/objects"},
        {**LIST_ARGUMENTS, "start_after": "./src/a.py"},
        {**LIST_ARGUMENTS, "start_after": "src/missing.py"},
    ],
)
def test_list_files_rejects_invalid_shape_path_prefix_and_cursor(arguments):
    workspace = InMemoryRepositoryWorkspace(
        {"src/a.py": "", "tests/test_a.py": ""},
        editable_paths=("src/a.py",),
    )
    with pytest.raises(ToolExecutionError):
        workspace.execute("list_files", arguments)


def test_prefix_and_cursor_are_bound_to_the_same_filtered_listing():
    workspace = InMemoryRepositoryWorkspace(
        {
            "docs/index.md": "",
            "src/a.py": "",
            "src/lib/b.py": "",
            "src2/not-in-directory.py": "",
        },
        editable_paths=("src/a.py",),
    )
    first = workspace.execute(
        "list_files",
        {"path_prefix": "src", "start_after": None, "limit": 1},
    )
    assert first["files"] == ["src/a.py"]
    second = workspace.execute(
        "list_files",
        {
            "path_prefix": "src",
            "start_after": first["next_start_after"],
            "limit": 200,
        },
    )
    assert second["files"] == ["src/lib/b.py"]
    with pytest.raises(ToolExecutionError, match="previously returned"):
        workspace.execute(
            "list_files",
            {
                "path_prefix": "src",
                "start_after": "docs/index.md",
                "limit": 200,
            },
        )


def test_large_git_and_in_memory_workspaces_return_byte_identical_pages(tmp_path):
    paths = _large_paths()
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "trimem@example.invalid")
    _git(root, "config", "user.name", "TriMem Test")
    empty_blob = _git(root, "hash-object", "-w", "--stdin", input_text="")
    untracked = set(paths[:2])
    index_rows = "".join(
        f"100644 {empty_blob}\t{path}\n" for path in paths if path not in untracked
    )
    _git(root, "update-index", "--index-info", input_text=index_rows)
    _git(root, "commit", "-m", "fixture")
    commit = _git(root, "rev-parse", "HEAD")
    for path in untracked:
        target = root / Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("UNTRACKED = True\n", encoding="utf-8")
    in_memory = InMemoryRepositoryWorkspace(
        {path: "" for path in paths},
        editable_paths=(paths[0],),
    )
    checkout = GitCheckoutWorkspace(root, base_commit=commit)

    memory_files, memory_pages = _collect_pages(in_memory)
    git_files, git_pages = _collect_pages(checkout)

    assert memory_files == git_files == paths
    assert canonical_bytes(memory_pages) == canonical_bytes(git_pages)
    assert all(".git" not in path.split("/") for path in git_files)
    assert all(str(tmp_path).replace("\\", "/") not in path for path in git_files)


def test_duplicate_repository_listing_and_oversize_single_path_fail_closed():
    with pytest.raises(ToolExecutionError, match="duplicate"):
        list_files_page(["src/a.py", "src/a.py"], LIST_ARGUMENTS)
    path = "src/" + "x" * 40_000
    with pytest.raises(ToolExecutionError, match="exceeds"):
        list_files_page([path], LIST_ARGUMENTS)


def test_native_schema_runtime_lock_and_contract_hash_bind_pagination():
    schema = FUNCTION_TOOL_BY_NAME["list_files"]["parameters"]
    assert schema["required"] == ["path_prefix", "start_after", "limit"]
    assert set(schema["required"]) == set(schema["properties"]) == {
        "path_prefix",
        "start_after",
        "limit",
    }
    assert schema["additionalProperties"] is False
    assert schema["properties"]["limit"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 200,
    }
    assert FUNCTION_TOOLS_SHA256 == hashlib.sha256(
        function_tool_bytes(detached_function_tools())
    ).hexdigest()
    with pytest.raises(ValueError, match="SCHEMA_FAILURE"):
        validate_function_arguments("list_files", {})
    manifest = RuntimeLock().to_manifest()
    assert (
        manifest["list_files_pagination_contract_sha256"]
        == LIST_FILES_PAGINATION_CONTRACT_SHA256
    )
    assert json.loads(json.dumps(schema, sort_keys=True)) == schema
