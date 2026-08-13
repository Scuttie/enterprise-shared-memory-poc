"""P4 artifact test harness. Requires DATABASE_URL (PostgreSQL). The object store is parametrized: a local
filesystem store always, plus an S3/MinIO store when MINIO_ENDPOINT is set (ci-artifacts). Credential-free
synthetic tenants; no company credentials."""
import os
import sys
import uuid
import asyncio
import pytest
from sqlalchemy import text

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
from enterprise_memory.persistence.database import make_engine            # noqa: E402

_CREDS = {"postgres": ("postgres", "postgres"), "api": ("api_service", "api_pw")}


def eng(role="api"):
    u, p = _CREDS[role]
    return make_engine(u, p)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _require_db():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("no DATABASE_URL (ci-artifacts only)")


@pytest.fixture
def orgs():
    async def _seed():
        e = eng("postgres")
        out = {}
        async with e.begin() as c:
            for k in ("A", "B"):
                org, usr = uuid.uuid4(), uuid.uuid4()
                await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                                {"i": org, "k": "org-art-%s-%s" % (k, org)})
                await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                                {"i": usr, "o": org, "s": "u-" + str(usr)})
                out[k] = {"org": org, "user": usr}
        await e.dispose()
        return out
    return run(_seed())


def _store_params():
    params = ["local"]
    if os.environ.get("MINIO_ENDPOINT"):
        params.append("s3")
    return params


@pytest.fixture(params=_store_params())
def store(request, tmp_path):
    if request.param == "local":
        from enterprise_memory.artifacts.store import LocalArtifactStore
        return LocalArtifactStore(str(tmp_path / "artifacts"))
    endpoint = os.environ["MINIO_ENDPOINT"]
    key = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    secret = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
    bucket = os.environ.get("MINIO_BUCKET", "esm-artifacts-test")
    import boto3
    c = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=key, aws_secret_access_key=secret,
                     use_ssl=False, region_name="us-east-1")
    try:
        c.create_bucket(Bucket=bucket)
    except Exception:
        pass
    from enterprise_memory.artifacts.store import S3ArtifactStore
    return S3ArtifactStore(endpoint, bucket, key, secret, secure=False, sse="AES256")
