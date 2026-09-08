"""Credential-free rehearsal of the complete TriMem Qdrant topology.

This command owns one disposable, digest-pinned Qdrant container.  It proves
that the container has the frozen ``nofile`` contract before creating the same
number of physical collections and payload indexes required by the six DEV
streams.  It never reads a model credential, starts a grader, or pulls an
image.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener
import uuid


ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT / "scripts", ROOT / "src"):
    value = str(import_root)
    if value not in sys.path:
        sys.path.insert(0, value)

from trimem_development_trigger_d112 import (  # noqa: E402
    DOCKER_AUTHORITY_ENV,
    DOCKER_LOCAL_PREFIX,
    QDRANT_NOFILE_HARD,
    QDRANT_NOFILE_SOFT,
    QDRANT_SERVICE_IMAGE,
)
from enterprise_memory.trimem.production_runtime import benchmark_namespace  # noqa: E402
from enterprise_memory.trimem.schema import (  # noqa: E402
    GraphKind,
    VECTOR_INDEX_SCHEMA_VERSION,
)
from enterprise_memory.trimem.vector_index import (  # noqa: E402
    PAYLOAD_INDEXES,
    PAYLOAD_FIELDS,
    QdrantVectorIndexV2,
    VectorReference,
)


REPORT_SCHEMA = "trimem/d122-qdrant-nofile-topology-rehearsal/1.0"
OWNER_LABEL = "trimem.d122.owner"
OWNER_VALUE = "qdrant-nofile-topology-rehearsal"
CONTAINER_NAME_PREFIX = "trimem-d122-qdrant-rehearsal"
QDRANT_CONTAINER_PORT = 6333
QDRANT_VERSION = "1.12.4"
VECTOR_DIMENSION = 384
STREAM_SPECS = (
    ("M2-baseline", "M2"),
    ("M2-precision", "M2"),
    ("M2-recall", "M2"),
    ("M2-balanced", "M2"),
    ("M0", "M0"),
    ("M1", "M1"),
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTAINER_NAME = re.compile(r"^trimem-d122-qdrant-rehearsal(?:-[a-z0-9][a-z0-9-]{0,40})?$")
_NOFILE_LINE = re.compile(
    r"^Max open files[ \t]+(?P<soft>[0-9]+|unlimited)[ \t]+"
    r"(?P<hard>[0-9]+|unlimited)[ \t]+files[ \t]*$",
    re.MULTILINE,
)

FORBIDDEN_ENVIRONMENT_NAMES = frozenset(
    {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "DEEPSEEK_API_KEY",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "MODEL_API_KEY",
        "OPENAI_API_KEY",
        "TRIMEM_EVIDENCE_PASSPHRASE",
        "TRIMEM_EXEC_APPROVAL_B64",
        "UPSTAGE_API_KEY",
    }
)
FORBIDDEN_ENVIRONMENT_PREFIXES = (
    "ANTHROPIC_",
    "AZURE_OPENAI_",
    "COHERE_",
    "GOOGLE_API_",
    "MISTRAL_",
    "OPENAI_",
    "TRIMEM_EXEC_",
    "TRIMEM_GRADER_",
    "TRIMEM_MODEL_",
    "TRIMEM_OFFICIAL_GRADER_",
)


class RehearsalError(RuntimeError):
    """The credential-free service rehearsal failed closed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def reject_protected_environment(environment: Mapping[str, str]) -> None:
    """Reject protected/model/grader/API authority before any side effect."""

    present = sorted(
        name
        for name in environment
        if name in FORBIDDEN_ENVIRONMENT_NAMES
        or name in DOCKER_AUTHORITY_ENV
        or any(name.startswith(prefix) for prefix in FORBIDDEN_ENVIRONMENT_PREFIXES)
    )
    if present:
        raise RehearsalError(
            "credential-free Qdrant rehearsal environment contains protected "
            "authority names: " + ",".join(present)
        )


def validate_frozen_contract() -> None:
    if not re.fullmatch(r"qdrant/qdrant@sha256:[0-9a-f]{64}", QDRANT_SERVICE_IMAGE):
        raise RehearsalError("pinned Qdrant image contract is malformed")
    if (QDRANT_NOFILE_SOFT, QDRANT_NOFILE_HARD) != (65_535, 65_535):
        raise RehearsalError("pinned Qdrant nofile contract differs")
    if VECTOR_DIMENSION != 384:
        raise RehearsalError("rehearsal vector dimension differs")
    if VECTOR_INDEX_SCHEMA_VERSION != 2:
        raise RehearsalError("production vector-index schema version differs")
    if tuple(PAYLOAD_INDEXES) != (
        ("index_schema_version", "integer"),
        ("collection_scope", "keyword"),
        ("memory_kind", "keyword"),
        ("org_id", "keyword"),
        ("owner_user_id", "keyword"),
        ("repository_id", "keyword"),
    ):
        raise RehearsalError("production payload-index contract differs")


def docker_create_argv(container_name: str, host_port: int) -> list[str]:
    if not _CONTAINER_NAME.fullmatch(container_name):
        raise RehearsalError("diagnostic container name is outside its owned prefix")
    if type(host_port) is not int or not 1024 <= host_port <= 65_535:
        raise RehearsalError("diagnostic host port is invalid")
    return [
        *DOCKER_LOCAL_PREFIX,
        "create",
        "--pull=never",
        "--name",
        container_name,
        "--label",
        f"{OWNER_LABEL}={OWNER_VALUE}",
        "--publish",
        f"127.0.0.1:{host_port}:{QDRANT_CONTAINER_PORT}",
        "--ulimit",
        f"nofile={QDRANT_NOFILE_SOFT}:{QDRANT_NOFILE_HARD}",
        QDRANT_SERVICE_IMAGE,
    ]


def parse_pid1_nofile(raw: str) -> dict[str, int]:
    matches = list(_NOFILE_LINE.finditer(raw))
    if len(matches) != 1:
        raise RehearsalError("PID1 limits contain no unique Max open files row")
    values: dict[str, int] = {}
    for name in ("soft", "hard"):
        value = matches[0].group(name)
        if value == "unlimited":
            raise RehearsalError("PID1 nofile limit is not the exact finite contract")
        values[name] = int(value)
    if values != {
        "hard": QDRANT_NOFILE_HARD,
        "soft": QDRANT_NOFILE_SOFT,
    }:
        raise RehearsalError("PID1 nofile limits differ from the frozen contract")
    return values


def _required_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RehearsalError(f"{label} is not an object")
    return value


def validate_container_inspect(
    document: Mapping[str, Any],
    *,
    container_id: str,
    container_name: str,
    host_port: int,
    image_id: str,
    require_running: bool,
) -> None:
    config = _required_mapping(document.get("Config"), "container Config")
    labels = _required_mapping(config.get("Labels"), "container Labels")
    host = _required_mapping(document.get("HostConfig"), "container HostConfig")
    port_bindings = _required_mapping(host.get("PortBindings"), "container PortBindings")
    expected_binding = [{"HostIp": "127.0.0.1", "HostPort": str(host_port)}]
    state = _required_mapping(document.get("State"), "container State")
    ulimits = host.get("Ulimits")
    expected_ulimits = [
        {
            "Hard": QDRANT_NOFILE_HARD,
            "Name": "nofile",
            "Soft": QDRANT_NOFILE_SOFT,
        }
    ]
    if (
        document.get("Id") != container_id
        or document.get("Name") != "/" + container_name
        or document.get("Image") != image_id
        or config.get("Image") != QDRANT_SERVICE_IMAGE
        or labels.get(OWNER_LABEL) != OWNER_VALUE
        or ulimits != expected_ulimits
        or port_bindings.get(f"{QDRANT_CONTAINER_PORT}/tcp") != expected_binding
        or document.get("Mounts") != []
        or type(state.get("Running")) is not bool
        or (require_running and state.get("Running") is not True)
    ):
        raise RehearsalError("owned Qdrant container identity/configuration differs")


@dataclass(frozen=True)
class CollectionPlan:
    stream_id: str
    arm_id: str
    namespace: str
    scope: str
    collection_name: str
    point_id: str
    payload: Mapping[str, object]
    vector: tuple[float, ...]

    def report_row(self) -> dict[str, Any]:
        return {
            "arm_id": self.arm_id,
            "collection_name": self.collection_name,
            "namespace": self.namespace,
            "payload_sha256": sha256_bytes(canonical_bytes(self.payload)),
            "point_id": self.point_id,
            "scope": self.scope,
            "stream_id": self.stream_id,
            "vector_sha256": sha256_bytes(canonical_bytes(self.vector)),
        }


def build_collection_plan() -> tuple[CollectionPlan, ...]:
    vector = (1.0,) + (0.0,) * (VECTOR_DIMENSION - 1)
    rows: list[CollectionPlan] = []
    for stream_id, arm_id in STREAM_SPECS:
        slug = re.sub(r"[^a-z0-9-]", "-", stream_id.casefold())
        namespace = benchmark_namespace(
            f"d122-qdrant-{slug}", "development", arm_id
        )
        index = QdrantVectorIndexV2(object(), VECTOR_DIMENSION, namespace=namespace)
        for scope, collection_name, memory_kind in (
            ("private", index.private_collection, GraphKind.USER_SEMANTIC),
            ("shared", index.shared_collection, GraphKind.ORGANISATION_SEMANTIC),
        ):
            def stable_id(kind: str) -> str:
                return str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"trimem-d122:{namespace}:{scope}:{kind}",
                    )
                )

            reference = VectorReference(
                graph_id=stable_id("graph"),
                node_id=stable_id("node"),
                content_hash="sha256:" + hashlib.sha256(
                    f"trimem-d122:{namespace}:{scope}:content".encode("utf-8")
                ).hexdigest(),
                org_id=stable_id("org"),
                memory_kind=memory_kind,
                owner_user_id=(stable_id("user") if scope == "private" else None),
                repository_id=stable_id("repository"),
                namespace=namespace,
            )
            rows.append(
                CollectionPlan(
                    stream_id=stream_id,
                    arm_id=arm_id,
                    namespace=namespace,
                    scope=scope,
                    collection_name=collection_name,
                    point_id=reference.point_id,
                    payload=reference.payload(),
                    vector=vector,
                )
            )
    if (
        len(rows) != 12
        or len({row.namespace for row in rows}) != 6
        or len({row.collection_name for row in rows}) != 12
        or any(len(row.vector) != VECTOR_DIMENSION for row in rows)
        or any(set(row.payload) != set(PAYLOAD_FIELDS) for row in rows)
    ):
        raise RehearsalError("production-shaped Qdrant topology differs")
    return tuple(rows)


class HttpTransport(Protocol):
    def text(self, method: str, path: str) -> str: ...

    def json(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]: ...


class LocalQdrantHttp:
    def __init__(self, host_port: int, *, timeout: float = 30.0) -> None:
        if type(host_port) is not int or not 1024 <= host_port <= 65_535:
            raise RehearsalError("Qdrant HTTP port is invalid")
        self._origin = f"http://127.0.0.1:{host_port}"
        self._timeout = timeout
        self._opener = build_opener(ProxyHandler({}))

    def _request(
        self, method: str, path: str, payload: Mapping[str, Any] | None
    ) -> bytes:
        if not path.startswith("/") or "://" in path:
            raise RehearsalError("Qdrant request escaped the loopback origin")
        body = None if payload is None else canonical_bytes(payload)
        request = Request(
            self._origin + path,
            data=body,
            headers=({"Content-Type": "application/json"} if body is not None else {}),
            method=method,
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.status != 200:
                    raise RehearsalError("Qdrant returned a non-200 response")
                return response.read()
        except HTTPError as exc:
            detail = exc.read(1024).decode("utf-8", errors="replace")
            raise RehearsalError(
                f"Qdrant HTTP {exc.code}: {detail[:512]}"
            ) from None
        except (TimeoutError, URLError, OSError) as exc:
            raise RehearsalError(f"Qdrant loopback request failed: {type(exc).__name__}") from None

    def text(self, method: str, path: str) -> str:
        return self._request(method, path, None).decode("utf-8", errors="strict")

    def json(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]:
        try:
            value = json.loads(self._request(method, path, payload))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RehearsalError("Qdrant response is not canonical UTF-8 JSON") from exc
        return _required_mapping(value, "Qdrant response")


class DockerRuntime:
    def __init__(self, *, environment: Mapping[str, str]) -> None:
        self._environment = {
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": environment.get("PATH", "/usr/bin:/bin"),
        }

    def command(
        self, argv: Sequence[str], *, label: str, timeout: float = 60.0
    ) -> str:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            check=False,
            env=self._environment,
            timeout=timeout,
        )
        try:
            stdout = completed.stdout.decode("utf-8", errors="strict").strip()
            stderr = completed.stderr.decode("utf-8", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise RehearsalError(f"{label} output is not UTF-8") from exc
        if completed.returncode != 0:
            raise RehearsalError(f"{label} failed: {stderr[-512:]}")
        return stdout

    def exact_name_ids(self, container_name: str) -> list[str]:
        raw = self.command(
            [
                *DOCKER_LOCAL_PREFIX,
                "ps",
                "-aq",
                "--no-trunc",
                "--filter",
                f"name=^/{container_name}$",
            ],
            label="exact diagnostic container query",
        )
        rows = raw.splitlines() if raw else []
        if len(rows) != len(set(rows)) or any(not _HEX64.fullmatch(row) for row in rows):
            raise RehearsalError("diagnostic container query returned malformed IDs")
        return rows

    def image_id(self) -> str:
        raw = self.command(
            [
                *DOCKER_LOCAL_PREFIX,
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                QDRANT_SERVICE_IMAGE,
            ],
            label="cached pinned Qdrant image inspection",
        )
        if not _IMAGE_ID.fullmatch(raw):
            raise RehearsalError("cached pinned Qdrant image ID is malformed")
        return raw

    def inspect(self, container_id: str) -> Mapping[str, Any]:
        raw = self.command(
            [
                *DOCKER_LOCAL_PREFIX,
                "container",
                "inspect",
                "--format",
                "{{json .}}",
                container_id,
            ],
            label="owned Qdrant container inspection",
        )
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RehearsalError("Docker inspection is not JSON") from exc
        return _required_mapping(value, "Docker inspection")

    def cleanup_owned(
        self,
        *,
        container_name: str,
        expected_id: str | None,
        host_port: int,
        image_id: str,
    ) -> dict[str, Any]:
        ids = self.exact_name_ids(container_name)
        if not ids:
            return {"container_absent": True, "removed_containers": 0}
        if len(ids) != 1 or (expected_id is not None and ids[0] != expected_id):
            raise RehearsalError("cleanup refused a non-owned container identity")
        document = self.inspect(ids[0])
        validate_container_inspect(
            document,
            container_id=ids[0],
            container_name=container_name,
            host_port=host_port,
            image_id=image_id,
            require_running=False,
        )
        self.command(
            [
                *DOCKER_LOCAL_PREFIX,
                "rm",
                "-f",
                "--volumes",
                "--",
                ids[0],
            ],
            label="owned Qdrant container cleanup",
        )
        if self.exact_name_ids(container_name):
            raise RehearsalError("owned Qdrant container remains after cleanup")
        return {"container_absent": True, "removed_containers": 1}


def _result(response: Mapping[str, Any], label: str) -> Any:
    if response.get("status") != "ok" or "result" not in response:
        raise RehearsalError(f"{label} response did not pass")
    return response["result"]


def validate_collection_observation(
    plan: CollectionPlan,
    *,
    collection: Mapping[str, Any],
    count: Mapping[str, Any],
    scroll: Mapping[str, Any],
) -> None:
    info = _required_mapping(_result(collection, "collection schema"), "collection result")
    config = _required_mapping(info.get("config"), "collection config")
    params = _required_mapping(config.get("params"), "collection params")
    vectors = _required_mapping(params.get("vectors"), "collection vectors")
    payload_schema = _required_mapping(info.get("payload_schema"), "payload schema")
    expected_indexes = dict(PAYLOAD_INDEXES)
    observed_indexes = {
        name: _required_mapping(value, f"payload index {name}").get("data_type")
        for name, value in payload_schema.items()
    }
    if (
        vectors.get("size") != VECTOR_DIMENSION
        or vectors.get("distance") != "Cosine"
        or observed_indexes != expected_indexes
        or info.get("points_count") != 1
    ):
        raise RehearsalError("collection schema/count differs")
    count_result = _required_mapping(_result(count, "exact count"), "count result")
    if count_result != {"count": 1}:
        raise RehearsalError("exact collection count differs")
    scroll_result = _required_mapping(_result(scroll, "scroll"), "scroll result")
    points = scroll_result.get("points")
    if not isinstance(points, list) or len(points) != 1:
        raise RehearsalError("scroll did not return one reference point")
    point = _required_mapping(points[0], "scroll point")
    vector = point.get("vector")
    if (
        point.get("id") != plan.point_id
        or point.get("payload") != dict(plan.payload)
        or not isinstance(vector, list)
        or len(vector) != VECTOR_DIMENSION
        or any(type(value) not in {int, float} for value in vector)
        or tuple(float(value) for value in vector) != plan.vector
        or scroll_result.get("next_page_offset") is not None
    ):
        raise RehearsalError("scrolled reference point differs")


def exercise_topology(http: HttpTransport) -> list[dict[str, Any]]:
    plans = build_collection_plan()
    rows: list[dict[str, Any]] = []
    for plan in plans:
        name = quote(plan.collection_name, safe="")
        base = f"/collections/{name}"
        if _result(
            http.json(
                "PUT",
                base,
                {"vectors": {"distance": "Cosine", "size": VECTOR_DIMENSION}},
            ),
            "collection creation",
        ) is not True:
            raise RehearsalError("collection creation result differs")
        for field_name, field_schema in PAYLOAD_INDEXES:
            index_result = _required_mapping(
                _result(
                    http.json(
                        "PUT",
                        base + "/index?wait=true",
                        {"field_name": field_name, "field_schema": field_schema},
                    ),
                    "payload-index creation",
                ),
                "payload-index result",
            )
            if index_result.get("status") != "completed":
                raise RehearsalError("payload-index operation did not complete")
        upsert_result = _required_mapping(
            _result(
                http.json(
                    "PUT",
                    base + "/points?wait=true",
                    {
                        "points": [
                            {
                                "id": plan.point_id,
                                "payload": dict(plan.payload),
                                "vector": list(plan.vector),
                            }
                        ]
                    },
                ),
                "reference-point upsert",
            ),
            "reference-point result",
        )
        if upsert_result.get("status") != "completed":
            raise RehearsalError("reference-point upsert did not complete")
        collection = http.json("GET", base)
        count = http.json("POST", base + "/points/count", {"exact": True})
        scroll = http.json(
            "POST",
            base + "/points/scroll",
            {"limit": 2, "with_payload": True, "with_vector": True},
        )
        validate_collection_observation(
            plan, collection=collection, count=count, scroll=scroll
        )
        rows.append(plan.report_row())
    return rows


def _assert_port_available(host_port: int) -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", host_port))
    except OSError as exc:
        raise RehearsalError("diagnostic loopback port is unavailable") from exc
    finally:
        probe.close()


def _wait_ready(http: HttpTransport, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            http.text("GET", "/readyz")
            return
        except RehearsalError:
            time.sleep(0.2)
    raise RehearsalError("Qdrant did not become ready before the deadline")


def run_rehearsal(
    *,
    container_name: str,
    host_port: int,
    startup_timeout: float,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    source_environment = os.environ if environment is None else environment
    reject_protected_environment(source_environment)
    validate_frozen_contract()
    create_argv = docker_create_argv(container_name, host_port)
    _assert_port_available(host_port)
    docker = DockerRuntime(environment=source_environment)
    if docker.exact_name_ids(container_name):
        raise RehearsalError("owned diagnostic container name already exists")
    image_id = docker.image_id()
    container_id: str | None = None
    cleanup: dict[str, Any] | None = None
    primary_error: BaseException | None = None
    observations: dict[str, Any] = {}
    try:
        created_output = docker.command(
            create_argv, label="owned Qdrant container creation"
        )
        if not _HEX64.fullmatch(created_output):
            raise RehearsalError("created Qdrant container ID is malformed")
        # Do not claim an identity until Docker's output has passed the exact
        # contract.  If create succeeded but emitted malformed stdout, cleanup
        # may still discover and validate the owned resource by exact name.
        container_id = created_output
        docker.command(
            [*DOCKER_LOCAL_PREFIX, "start", container_id],
            label="owned Qdrant container start",
        )
        document = docker.inspect(container_id)
        validate_container_inspect(
            document,
            container_id=container_id,
            container_name=container_name,
            host_port=host_port,
            image_id=image_id,
            require_running=True,
        )
        limits = docker.command(
            [
                *DOCKER_LOCAL_PREFIX,
                "exec",
                container_id,
                "sh",
                "-c",
                "cat /proc/1/limits",
            ],
            label="Qdrant PID1 limit inspection",
        )
        pid1_nofile = parse_pid1_nofile(limits)
        http = LocalQdrantHttp(host_port)
        _wait_ready(http, startup_timeout)
        service = http.json("GET", "/")
        if service.get("version") != QDRANT_VERSION:
            raise RehearsalError("running Qdrant version differs")
        collections = exercise_topology(http)
        http.text("GET", "/readyz")
        observations = {
            "collections": collections,
            "host_config_nofile": {
                "hard": QDRANT_NOFILE_HARD,
                "soft": QDRANT_NOFILE_SOFT,
            },
            "pid1_nofile": pid1_nofile,
            "qdrant_version": service["version"],
        }
    except BaseException as exc:
        primary_error = exc
    try:
        cleanup = docker.cleanup_owned(
            container_name=container_name,
            expected_id=container_id,
            host_port=host_port,
            image_id=image_id,
        )
    except BaseException as exc:
        if primary_error is not None:
            raise RehearsalError(
                "rehearsal failed and strict owned-resource cleanup also failed"
            ) from exc
        raise
    if primary_error is not None:
        raise primary_error
    assert cleanup is not None
    collection_rows = observations["collections"]
    return {
        "cleanup": cleanup,
        "container": {
            "create_argv_sha256": sha256_bytes(canonical_bytes(create_argv)),
            "host_port": host_port,
            "image": QDRANT_SERVICE_IMAGE,
            "image_id": image_id,
            "pull_policy": "never",
        },
        "credential_access": False,
        "grader_containers": 0,
        # The process is pull-never and cannot perform benchmark image work.
        # A caller may preload the one pinned Qdrant support image separately.
        "benchmark_image_pulls": 0,
        "rehearsal_process_image_pulls": 0,
        "model_api_calls": 0,
        "model_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "service_containers": 1,
        "host_config_nofile": observations["host_config_nofile"],
        "pid1_nofile": observations["pid1_nofile"],
        "qdrant_version": observations["qdrant_version"],
        "schema": REPORT_SCHEMA,
        "status": "PASS",
        "task_arm_runs": 0,
        "tokens": 0,
        "topology": {
            "collection_count": len(collection_rows),
            "collections": collection_rows,
            "dimension": VECTOR_DIMENSION,
            "exact_count_validations": len(collection_rows),
            "namespace_count": len({row["namespace"] for row in collection_rows}),
            "payload_index_count": len(collection_rows) * len(PAYLOAD_INDEXES),
            "payload_indexes_per_collection": len(PAYLOAD_INDEXES),
            "points_per_collection": 1,
            "scroll_validations": len(collection_rows),
            "stream_count": len(STREAM_SPECS),
        },
        "total_usd": 0.0,
    }


def write_new_report(path: Path, report: Mapping[str, Any]) -> None:
    if path.is_symlink() or path.exists():
        raise RehearsalError("rehearsal report path must be new and direct")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(report) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--container-name", default=CONTAINER_NAME_PREFIX)
    parser.add_argument("--host-port", default=16_334, type=int)
    parser.add_argument("--startup-timeout-seconds", default=120.0, type=float)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = run_rehearsal(
            container_name=args.container_name,
            host_port=args.host_port,
            startup_timeout=args.startup_timeout_seconds,
        )
        write_new_report(args.report, report)
    except (OSError, RehearsalError, subprocess.TimeoutExpired, ValueError) as exc:
        print(
            canonical_bytes(
                {
                    "error": str(exc),
                    "schema": REPORT_SCHEMA,
                    "status": "FAIL",
                }
            ).decode("utf-8"),
            file=sys.stderr,
        )
        return 1
    print("TRIMEM_D122_QDRANT_NOFILE_TOPOLOGY_REHEARSAL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
