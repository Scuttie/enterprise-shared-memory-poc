from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.parse import unquote

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import trimem_development_trigger_d112 as trigger  # noqa: E402
import trimem_d122_qdrant_nofile_rehearsal as rehearsal  # noqa: E402


CONTAINER_ID = "a" * 64
IMAGE_ID = "sha256:" + "b" * 64
CONTAINER_NAME = "trimem-d122-qdrant-rehearsal-unit"
HOST_PORT = 16_334


def _inspect_document() -> dict[str, Any]:
    return {
        "Config": {
            "Image": trigger.QDRANT_SERVICE_IMAGE,
            "Labels": {rehearsal.OWNER_LABEL: rehearsal.OWNER_VALUE},
        },
        "HostConfig": {
            "PortBindings": {
                "6333/tcp": [
                    {"HostIp": "127.0.0.1", "HostPort": str(HOST_PORT)}
                ]
            },
            "Ulimits": [{"Hard": 65_535, "Name": "nofile", "Soft": 65_535}],
        },
        "Id": CONTAINER_ID,
        "Image": IMAGE_ID,
        "Mounts": [],
        "Name": "/" + CONTAINER_NAME,
        "State": {"Running": True},
    }


def _validate_inspect(document: Mapping[str, Any]) -> None:
    rehearsal.validate_container_inspect(
        document,
        container_id=CONTAINER_ID,
        container_name=CONTAINER_NAME,
        host_port=HOST_PORT,
        image_id=IMAGE_ID,
        require_running=True,
    )


class _TopologyHttp:
    """In-memory Qdrant protocol double; it never opens a socket."""

    def __init__(self) -> None:
        self.collections: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []

    def text(self, method: str, path: str) -> str:
        raise AssertionError("topology exercise must use JSON requests")

    @staticmethod
    def _parts(path: str) -> tuple[str, str]:
        route = path.partition("?")[0]
        components = route.split("/")
        assert components[:2] == ["", "collections"]
        return unquote(components[2]), "/".join(components[3:])

    def json(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]:
        self.calls.append((method, path))
        name, suffix = self._parts(path)
        if method == "PUT" and suffix == "":
            assert payload == {
                "vectors": {"distance": "Cosine", "size": 384}
            }
            assert name not in self.collections
            self.collections[name] = {"indexes": {}, "point": None}
            return {"result": True, "status": "ok"}
        state = self.collections[name]
        if method == "PUT" and suffix == "index":
            assert payload is not None
            state["indexes"][payload["field_name"]] = payload["field_schema"]
            return {"result": {"status": "completed"}, "status": "ok"}
        if method == "PUT" and suffix == "points":
            assert payload is not None and len(payload["points"]) == 1
            state["point"] = deepcopy(payload["points"][0])
            return {"result": {"status": "completed"}, "status": "ok"}
        if method == "GET" and suffix == "":
            assert state["point"] is not None
            return {
                "result": {
                    "config": {
                        "params": {
                            "vectors": {"distance": "Cosine", "size": 384}
                        }
                    },
                    "payload_schema": {
                        field: {"data_type": schema}
                        for field, schema in state["indexes"].items()
                    },
                    "points_count": 1,
                },
                "status": "ok",
            }
        if method == "POST" and suffix == "points/count":
            assert payload == {"exact": True}
            return {"result": {"count": 1}, "status": "ok"}
        if method == "POST" and suffix == "points/scroll":
            assert payload == {
                "limit": 2,
                "with_payload": True,
                "with_vector": True,
            }
            return {
                "result": {
                    "next_page_offset": None,
                    "points": [deepcopy(state["point"])],
                },
                "status": "ok",
            }
        raise AssertionError((method, path, payload))


def test_exact_pinned_image_and_nofile_create_contract() -> None:
    rehearsal.validate_frozen_contract()
    argv = rehearsal.docker_create_argv(CONTAINER_NAME, HOST_PORT)

    assert rehearsal.QDRANT_SERVICE_IMAGE == trigger.QDRANT_SERVICE_IMAGE
    assert rehearsal.QDRANT_NOFILE_SOFT == trigger.QDRANT_NOFILE_SOFT == 65_535
    assert rehearsal.QDRANT_NOFILE_HARD == trigger.QDRANT_NOFILE_HARD == 65_535
    assert argv == [
        *trigger.DOCKER_LOCAL_PREFIX,
        "create",
        "--pull=never",
        "--name",
        CONTAINER_NAME,
        "--label",
        f"{rehearsal.OWNER_LABEL}={rehearsal.OWNER_VALUE}",
        "--publish",
        f"127.0.0.1:{HOST_PORT}:6333",
        "--ulimit",
        "nofile=65535:65535",
        trigger.QDRANT_SERVICE_IMAGE,
    ]
    assert "--volume" not in argv and "-v" not in argv


@pytest.mark.parametrize(
    "name",
    [
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "DOCKER_HOST",
        "GH_TOKEN",
        "OPENAI_API_KEY",
        "TRIMEM_EVIDENCE_PASSPHRASE",
        "TRIMEM_EXEC_APPROVAL_B64",
        "TRIMEM_GRADER_IMAGE",
        "TRIMEM_MODEL_ID",
    ],
)
def test_protected_authority_environment_is_rejected(name: str) -> None:
    with pytest.raises(rehearsal.RehearsalError, match=name):
        rehearsal.reject_protected_environment({name: "must-not-be-read"})


def test_non_authority_environment_is_accepted() -> None:
    rehearsal.reject_protected_environment(
        {"LANG": "C", "PATH": "/usr/bin:/bin", "TRIMEM_QDRANT_URL": "unused"}
    )


def test_pid1_nofile_parser_requires_exact_finite_soft_and_hard() -> None:
    raw = (
        "Limit                     Soft Limit           Hard Limit           Units     \n"
        "Max cpu time              unlimited            unlimited            seconds   \n"
        "Max open files            65535                65535                files     \n"
        "Max locked memory         8388608              8388608              bytes     \n"
    )
    assert rehearsal.parse_pid1_nofile(raw) == {"hard": 65_535, "soft": 65_535}

    for changed in (
        raw.replace("65535                65535", "1024                 1048576"),
        raw.replace("65535                65535", "unlimited            unlimited"),
        raw + "Max open files            65535                65535                files\n",
        raw.replace("Max open files", "Max files"),
    ):
        with pytest.raises(rehearsal.RehearsalError):
            rehearsal.parse_pid1_nofile(changed)


def test_container_inspect_requires_exact_host_config_nofile_and_ownership() -> None:
    _validate_inspect(_inspect_document())

    mutations = []
    low_soft = _inspect_document()
    low_soft["HostConfig"]["Ulimits"][0]["Soft"] = 1024
    mutations.append(low_soft)
    no_ulimit = _inspect_document()
    no_ulimit["HostConfig"]["Ulimits"] = []
    mutations.append(no_ulimit)
    wrong_owner = _inspect_document()
    wrong_owner["Config"]["Labels"][rehearsal.OWNER_LABEL] = "somebody-else"
    mutations.append(wrong_owner)
    mounted = _inspect_document()
    mounted["Mounts"] = [{"Destination": "/qdrant/storage"}]
    mutations.append(mounted)
    wrong_port = _inspect_document()
    wrong_port["HostConfig"]["PortBindings"]["6333/tcp"][0]["HostIp"] = "0.0.0.0"
    mutations.append(wrong_port)

    for document in mutations:
        with pytest.raises(rehearsal.RehearsalError):
            _validate_inspect(document)


def test_plan_is_deterministic_and_production_shaped() -> None:
    plans = rehearsal.build_collection_plan()

    assert plans == rehearsal.build_collection_plan()
    assert len(plans) == 12
    assert len({plan.namespace for plan in plans}) == 6
    assert len({plan.collection_name for plan in plans}) == 12
    assert {plan.stream_id for plan in plans} == {
        "M2-baseline",
        "M2-precision",
        "M2-recall",
        "M2-balanced",
        "M0",
        "M1",
    }
    for plan in plans:
        assert len(plan.vector) == 384
        assert plan.vector[0] == 1.0
        assert set(plan.vector[1:]) == {0.0}
        assert set(plan.payload) == set(rehearsal.PAYLOAD_FIELDS)
        assert plan.payload["collection_scope"] == plan.scope
        assert (plan.payload["owner_user_id"] is None) == (plan.scope == "shared")


def test_complete_topology_protocol_without_docker_or_network() -> None:
    http = _TopologyHttp()
    rows = rehearsal.exercise_topology(http)

    assert len(rows) == 12
    assert len(http.collections) == 12
    assert all(
        state["indexes"] == dict(rehearsal.PAYLOAD_INDEXES)
        for state in http.collections.values()
    )
    assert all(state["point"] is not None for state in http.collections.values())
    assert sum(path.endswith("/index?wait=true") for _, path in http.calls) == 72
    assert sum(path.endswith("/points/count") for _, path in http.calls) == 12
    assert sum(path.endswith("/points/scroll") for _, path in http.calls) == 12
    assert len(http.calls) == 132


def test_collection_observation_rejects_schema_count_and_scroll_drift() -> None:
    plan = rehearsal.build_collection_plan()[0]
    collection = {
        "result": {
            "config": {
                "params": {"vectors": {"distance": "Cosine", "size": 384}}
            },
            "payload_schema": {
                field: {"data_type": schema}
                for field, schema in rehearsal.PAYLOAD_INDEXES
            },
            "points_count": 1,
        },
        "status": "ok",
    }
    count = {"result": {"count": 1}, "status": "ok"}
    scroll = {
        "result": {
            "next_page_offset": None,
            "points": [
                {
                    "id": plan.point_id,
                    "payload": dict(plan.payload),
                    "vector": list(plan.vector),
                }
            ],
        },
        "status": "ok",
    }
    rehearsal.validate_collection_observation(
        plan, collection=collection, count=count, scroll=scroll
    )

    bad_schema = deepcopy(collection)
    bad_schema["result"]["payload_schema"]["repository_id"]["data_type"] = "text"
    bad_count = deepcopy(count)
    bad_count["result"]["count"] = 2
    bad_scroll = deepcopy(scroll)
    bad_scroll["result"]["points"][0]["payload"]["repository_id"] = "wrong"
    for values in (
        (bad_schema, count, scroll),
        (collection, bad_count, scroll),
        (collection, count, bad_scroll),
    ):
        with pytest.raises(rehearsal.RehearsalError):
            rehearsal.validate_collection_observation(
                plan, collection=values[0], count=values[1], scroll=values[2]
            )


def test_malformed_create_stdout_still_cleans_by_exact_owned_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDocker:
        cleanup_expected_id: str | None | object = object()

        def __init__(self, *, environment: Mapping[str, str]) -> None:
            assert environment == {}

        def exact_name_ids(self, container_name: str) -> list[str]:
            assert container_name == CONTAINER_NAME
            return []

        def image_id(self) -> str:
            return IMAGE_ID

        def command(
            self, argv: list[str], *, label: str, timeout: float = 60.0
        ) -> str:
            assert label == "owned Qdrant container creation"
            return "warning-on-stdout\n" + CONTAINER_ID

        def cleanup_owned(
            self,
            *,
            container_name: str,
            expected_id: str | None,
            host_port: int,
            image_id: str,
        ) -> dict[str, Any]:
            assert container_name == CONTAINER_NAME
            assert host_port == HOST_PORT
            assert image_id == IMAGE_ID
            FakeDocker.cleanup_expected_id = expected_id
            return {"container_absent": True, "removed_containers": 1}

    monkeypatch.setattr(rehearsal, "DockerRuntime", FakeDocker)
    monkeypatch.setattr(rehearsal, "_assert_port_available", lambda _port: None)

    with pytest.raises(rehearsal.RehearsalError, match="ID is malformed"):
        rehearsal.run_rehearsal(
            container_name=CONTAINER_NAME,
            host_port=HOST_PORT,
            startup_timeout=1.0,
            environment={},
        )
    assert FakeDocker.cleanup_expected_id is None


def test_canonical_new_report_is_one_line_and_never_overwritten(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.json"
    report = {"z": 0, "a": [True, None]}

    rehearsal.write_new_report(path, report)

    assert path.read_bytes() == b'{"a":[true,null],"z":0}\n'
    assert json.loads(path.read_bytes()) == report
    with pytest.raises(rehearsal.RehearsalError, match="must be new"):
        rehearsal.write_new_report(path, report)
