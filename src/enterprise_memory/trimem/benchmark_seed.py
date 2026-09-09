"""Admin-only deterministic identity provisioning for production benchmarks.

The benchmark runtime connects as ``api_service`` and therefore cannot invent
or provision tenant identity/FK rows.  This preflight is deliberately separate:
it accepts the admin DSN once, verifies that connection can bypass RLS, inserts
only deterministic identity/policy/job rows, reloads every field exactly, and
disposes the admin engine before returning a secret-free evidence seal.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from .schema import canonical_hash


class BenchmarkIdentitySeedError(RuntimeError):
    """The admin seed could not prove an exact deterministic identity set."""


def _required(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("%s is required and must be canonical" % name)
    return value


def _uuid(value: object, name: str) -> str:
    raw = _required(value, name)
    try:
        normalized = str(uuid.UUID(raw))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("%s must be a canonical UUID" % name) from exc
    if normalized != raw:
        raise ValueError("%s must be a canonical UUID" % name)
    return normalized


def _task_value(task: object, name: str) -> Any:
    if isinstance(task, Mapping):
        return task.get(name)
    return getattr(task, name, None)


def _policy_id(org_id: str, repository_id: str, task_id: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "trimem-task-policy:%s:%s:%s" % (org_id, repository_id, task_id),
        )
    )


def _permission_id(org_id: str, repository_id: str, user_id: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "trimem-benchmark-repository-read:%s:%s:%s"
            % (org_id, repository_id, user_id),
        )
    )


def _normalize_tasks(
    tasks: Sequence[object],
    identity_resolver: Callable[[object], Mapping[str, str]],
) -> tuple[str, str, tuple[dict[str, Any], ...]]:
    if isinstance(tasks, (str, bytes, bytearray)):
        raise ValueError("tasks must be a sequence")
    frozen = tuple(tasks)
    if not frozen:
        raise ValueError("tasks cannot be empty")
    org_ids = {_uuid(_task_value(task, "org_id"), "task.org_id") for task in frozen}
    user_ids = {_uuid(_task_value(task, "user_id"), "task.user_id") for task in frozen}
    if len(org_ids) != 1 or len(user_ids) != 1:
        raise ValueError("one benchmark stream requires one exact org/user identity")
    org_id, user_id = next(iter(org_ids)), next(iter(user_ids))
    rows = []
    seen_task_ids: set[str] = set()
    for task in frozen:
        task_id = _required(_task_value(task, "task_id"), "task.task_id")
        if task_id in seen_task_ids:
            raise ValueError("tasks contain a duplicate task_id")
        seen_task_ids.add(task_id)
        repository = _required(
            _task_value(task, "repository"), "task.repository"
        )
        commit = _required(_task_value(task, "commit"), "task.commit")
        raw_paths = _task_value(task, "editable_paths")
        if not isinstance(raw_paths, (tuple, list)) or any(
            not isinstance(item, str) or not item for item in raw_paths
        ):
            raise ValueError("task.editable_paths must be a string sequence")
        identity = identity_resolver(task)
        if not isinstance(identity, Mapping) or set(identity) != {
            "repository_id",
            "solve_job_id",
        }:
            raise ValueError("identity_resolver returned an invalid shape")
        repository_id = _uuid(identity["repository_id"], "repository_id")
        solve_job_id = _uuid(identity["solve_job_id"], "solve_job_id")
        rows.append(
            {
                "task_id": task_id,
                "repository": repository,
                "commit": commit,
                "editable_paths": list(raw_paths),
                "repository_id": repository_id,
                "task_policy_id": _policy_id(org_id, repository_id, task_id),
                "solve_job_id": solve_job_id,
            }
        )
    if len({row["solve_job_id"] for row in rows}) != len(rows):
        raise ValueError("identity_resolver returned duplicate solve_job_id values")
    repository_bindings: dict[str, str] = {}
    for row in rows:
        previous = repository_bindings.setdefault(
            row["repository"], row["repository_id"]
        )
        if previous != row["repository_id"]:
            raise ValueError("one repository slug resolved to multiple UUIDs")
    return org_id, user_id, tuple(rows)


def _as_mapping(row: object, label: str) -> Mapping[str, Any]:
    if not isinstance(row, Mapping):
        raise BenchmarkIdentitySeedError("%s canonical reload is missing" % label)
    return row


async def _seed(
    *,
    engine: object,
    experiment_id: str,
    stream_id: str,
    org_id: str,
    user_id: str,
    rows: tuple[dict[str, Any], ...],
) -> Mapping[str, Any]:
    external_key = "trimem-benchmark-org:" + org_id
    external_subject = "trimem-benchmark-user:" + user_id
    async with engine.begin() as connection:
        role = (
            await connection.execute(
                text(
                    "SELECT current_user AS role_name,rolsuper,rolbypassrls "
                    "FROM pg_roles WHERE rolname=current_user"
                )
            )
        ).mappings().first()
        role = _as_mapping(role, "admin role")
        if role.get("rolsuper") is not True and role.get("rolbypassrls") is not True:
            raise BenchmarkIdentitySeedError(
                "benchmark identity seeding requires a BYPASSRLS admin connection"
            )

        await connection.execute(
            text(
                "INSERT INTO organisations(id,external_key) VALUES(:id,:external_key) "
                "ON CONFLICT DO NOTHING"
            ),
            {"id": org_id, "external_key": external_key},
        )
        observed_org = (
            await connection.execute(
                text("SELECT id,external_key FROM organisations WHERE id=:id"),
                {"id": org_id},
            )
        ).mappings().first()
        if dict(_as_mapping(observed_org, "organisation")) != {
            "id": uuid.UUID(org_id),
            "external_key": external_key,
        }:
            raise BenchmarkIdentitySeedError("organisation identity is already bound")

        await connection.execute(
            text(
                "INSERT INTO users(id,org_id,external_subject) "
                "VALUES(:id,:org_id,:external_subject) ON CONFLICT DO NOTHING"
            ),
            {
                "id": user_id,
                "org_id": org_id,
                "external_subject": external_subject,
            },
        )
        observed_user = (
            await connection.execute(
                text(
                    "SELECT id,org_id,external_subject FROM users WHERE id=:id"
                ),
                {"id": user_id},
            )
        ).mappings().first()
        if dict(_as_mapping(observed_user, "user")) != {
            "id": uuid.UUID(user_id),
            "org_id": uuid.UUID(org_id),
            "external_subject": external_subject,
        }:
            raise BenchmarkIdentitySeedError("user identity is already bound")

        evidence_rows = []
        for item in rows:
            await connection.execute(
                text(
                    "INSERT INTO repositories(id,org_id,external_repo_id) "
                    "VALUES(:id,:org_id,:external_repo_id) ON CONFLICT DO NOTHING"
                ),
                {
                    "id": item["repository_id"],
                    "org_id": org_id,
                    "external_repo_id": item["repository"],
                },
            )
            observed_repository = (
                await connection.execute(
                    text(
                        "SELECT id,org_id,external_repo_id,provider,default_branch "
                        "FROM repositories WHERE id=:id"
                    ),
                    {"id": item["repository_id"]},
                )
            ).mappings().first()
            if dict(_as_mapping(observed_repository, "repository")) != {
                "id": uuid.UUID(item["repository_id"]),
                "org_id": uuid.UUID(org_id),
                "external_repo_id": item["repository"],
                "provider": "github",
                "default_branch": "main",
            }:
                raise BenchmarkIdentitySeedError(
                    "repository identity is already bound"
                )

            permission_id = _permission_id(
                org_id, item["repository_id"], user_id
            )
            await connection.execute(
                text(
                    "INSERT INTO repository_permissions("
                    "id,org_id,repository_id,subject_type,subject_id,can_read,"
                    "can_modify,path_globs,branch_globs,version) VALUES("
                    ":id,:org_id,:repository_id,'user',:subject_id,true,false,"
                    "ARRAY[]::text[],ARRAY[]::text[],1) ON CONFLICT DO NOTHING"
                ),
                {
                    "id": permission_id,
                    "org_id": org_id,
                    "repository_id": item["repository_id"],
                    "subject_id": user_id,
                },
            )
            observed_permission = (
                await connection.execute(
                    text(
                        "SELECT id,org_id,repository_id,subject_type,subject_id,"
                        "can_read,can_modify,path_globs,branch_globs,version "
                        "FROM repository_permissions WHERE id=:id"
                    ),
                    {"id": permission_id},
                )
            ).mappings().first()
            if dict(_as_mapping(observed_permission, "repository permission")) != {
                "id": uuid.UUID(permission_id),
                "org_id": uuid.UUID(org_id),
                "repository_id": uuid.UUID(item["repository_id"]),
                "subject_type": "user",
                "subject_id": uuid.UUID(user_id),
                "can_read": True,
                "can_modify": False,
                "path_globs": [],
                "branch_globs": [],
                "version": 1,
            }:
                raise BenchmarkIdentitySeedError(
                    "repository permission is already bound"
                )

            policy = {
                "id": item["task_policy_id"],
                "org_id": org_id,
                "repository_id": item["repository_id"],
                "task_key": item["task_id"],
                "editable_paths": item["editable_paths"],
                "target_symbol": "__trimem_benchmark__",
                "exact_signature": "__trimem_benchmark__()",
                "test_bundle_ref": "trimem-benchmark:" + item["task_id"],
            }
            await connection.execute(
                text(
                    "INSERT INTO task_execution_policies("
                    "id,org_id,repository_id,task_key,editable_paths,target_symbol,"
                    "exact_signature,test_bundle_ref) VALUES("
                    ":id,:org_id,:repository_id,:task_key,:editable_paths,:target_symbol,"
                    ":exact_signature,:test_bundle_ref) ON CONFLICT DO NOTHING"
                ),
                policy,
            )
            observed_policy = (
                await connection.execute(
                    text(
                        "SELECT id,org_id,repository_id,task_key,editable_paths,"
                        "target_symbol,exact_signature,test_bundle_ref "
                        "FROM task_execution_policies WHERE id=:id"
                    ),
                    {"id": item["task_policy_id"]},
                )
            ).mappings().first()
            expected_policy = {
                **policy,
                "id": uuid.UUID(policy["id"]),
                "org_id": uuid.UUID(org_id),
                "repository_id": uuid.UUID(policy["repository_id"]),
            }
            if dict(_as_mapping(observed_policy, "task policy")) != expected_policy:
                raise BenchmarkIdentitySeedError(
                    "task execution policy is already bound"
                )

            spec = {
                "schema": "trimem/benchmark-seeded-solve-job/1.0",
                "experiment_id": experiment_id,
                "stream_id": stream_id,
                "task_id": item["task_id"],
                "repository": item["repository"],
                "commit": item["commit"],
            }
            job = {
                "id": item["solve_job_id"],
                "org_id": org_id,
                "submitter_user_id": user_id,
                "repository_id": item["repository_id"],
                "task_policy_id": item["task_policy_id"],
                "logical_request_id": "trimem-benchmark:%s:%s:%s"
                % (experiment_id, stream_id, item["task_id"]),
                "idempotency_key": "trimem-benchmark-seed:" + item["solve_job_id"],
                "spec_json": spec,
            }
            await connection.execute(
                text(
                    "INSERT INTO solve_jobs("
                    "id,org_id,submitter_user_id,repository_id,task_policy_id,"
                    "logical_request_id,idempotency_key,spec_json) VALUES("
                    ":id,:org_id,:submitter_user_id,:repository_id,:task_policy_id,"
                    ":logical_request_id,:idempotency_key,CAST(:spec_json AS jsonb)) "
                    "ON CONFLICT DO NOTHING"
                ),
                {**job, "spec_json": json.dumps(spec, sort_keys=True)},
            )
            observed_job = (
                await connection.execute(
                    text(
                        "SELECT id,org_id,submitter_user_id,repository_id,task_policy_id,"
                        "logical_request_id,idempotency_key,spec_json "
                        "FROM solve_jobs WHERE id=:id"
                    ),
                    {"id": item["solve_job_id"]},
                )
            ).mappings().first()
            expected_job = {
                **job,
                "id": uuid.UUID(job["id"]),
                "org_id": uuid.UUID(org_id),
                "submitter_user_id": uuid.UUID(user_id),
                "repository_id": uuid.UUID(job["repository_id"]),
                "task_policy_id": uuid.UUID(job["task_policy_id"]),
            }
            if dict(_as_mapping(observed_job, "solve job")) != expected_job:
                raise BenchmarkIdentitySeedError("solve job identity is already bound")
            evidence_rows.append(
                {
                    "task_id": item["task_id"],
                    "repository": item["repository"],
                    "repository_id": item["repository_id"],
                    "repository_permission_id": permission_id,
                    "task_policy_id": item["task_policy_id"],
                    "solve_job_id": item["solve_job_id"],
                    "spec_hash": canonical_hash(spec),
                }
            )

    body = {
        "schema": "trimem/benchmark-identity-seed-evidence/1.0",
        "experiment_id": experiment_id,
        "stream_id": stream_id,
        "org_id": org_id,
        "user_id": user_id,
        "admin_role": str(role["role_name"]),
        "admin_bypassrls": bool(role["rolbypassrls"] or role["rolsuper"]),
        "rows": evidence_rows,
    }
    return {**body, "digest": canonical_hash(body)}


def seed_benchmark_identities(
    *,
    admin_database_url: str,
    experiment_id: str,
    stream_id: str,
    tasks: Sequence[object],
    identity_resolver: Callable[[object], Mapping[str, str]],
    engine_factory: Optional[Callable[[str], object]] = None,
) -> Mapping[str, Any]:
    """Provision and seal one stream's deterministic FK identities as admin."""

    database = _required(admin_database_url, "admin_database_url")
    try:
        parsed = make_url(database)
    except Exception as exc:
        raise ValueError("admin_database_url is invalid") from exc
    if parsed.get_backend_name() not in {"postgresql", "postgres"}:
        raise ValueError("admin_database_url must use PostgreSQL")
    if parsed.drivername not in {"postgresql+asyncpg", "postgres+asyncpg"}:
        raise ValueError("admin_database_url must use asyncpg")
    if parsed.username in {"api_service", "worker_service", "index_worker_service"}:
        raise ValueError("runtime service roles cannot seed benchmark identities")
    experiment = _required(experiment_id, "experiment_id")
    stream = _required(stream_id, "stream_id")
    if not callable(identity_resolver):
        raise TypeError("identity_resolver is required")
    org_id, user_id, rows = _normalize_tasks(tasks, identity_resolver)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "seed_benchmark_identities must run before entering an application event loop"
        )
    engine = (engine_factory or (
        lambda value: create_async_engine(value, future=True)
    ))(database)

    async def run() -> Mapping[str, Any]:
        try:
            return await _seed(
                engine=engine,
                experiment_id=experiment,
                stream_id=stream,
                org_id=org_id,
                user_id=user_id,
                rows=rows,
            )
        finally:
            dispose = getattr(engine, "dispose", None)
            if callable(dispose):
                result = dispose()
                if hasattr(result, "__await__"):
                    await result

    return asyncio.run(run())


__all__ = ["BenchmarkIdentitySeedError", "seed_benchmark_identities"]
