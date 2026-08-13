"""Object stores (P4 §9). Content-addressed, SHA-256-verified on write and read; a key is never overwritten
with different content. LocalArtifactStore is for tests/dev; S3ArtifactStore targets S3/MinIO (private
bucket, server-side encryption, short-lived presigned GET only — no presigned PUT). Sync internals; the
async ArtifactService drives them on a worker thread."""
from __future__ import annotations
import os
from abc import ABC, abstractmethod
from typing import Optional

from .records import sha256_hex


class ArtifactStoreError(Exception):
    pass


class HashMismatch(ArtifactStoreError):
    pass


class ArtifactStore(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes, expected_hash: str) -> dict: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def head(self, key: str) -> Optional[dict]: ...

    def exists(self, key: str) -> bool:
        return self.head(key) is not None

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def create_presigned_get(self, key: str, ttl_seconds: int = 300) -> str: ...

    @abstractmethod
    def health(self) -> dict: ...

    @abstractmethod
    def list_keys(self, prefix: str) -> list: ...

    def verify(self, key: str, expected_hash: str) -> bool:
        """Read the object back and confirm its SHA-256 — the strongest integrity check."""
        try:
            return sha256_hex(self.get(key)) == expected_hash
        except Exception:
            return False

    def close(self) -> None:
        pass


class LocalArtifactStore(ArtifactStore):
    def __init__(self, base_dir: str):
        self._base = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def _path(self, key: str) -> str:
        if key.startswith("/") or ".." in key.split("/"):
            raise ArtifactStoreError("unsafe key")
        return os.path.join(self._base, key.replace("/", os.sep))

    def put(self, key: str, data: bytes, expected_hash: str) -> dict:
        if sha256_hex(data) != expected_hash:
            raise HashMismatch("write hash mismatch")
        p = self._path(key)
        if os.path.exists(p):
            with open(p, "rb") as f:
                if sha256_hex(f.read()) != expected_hash:      # never overwrite a key with new content
                    raise ArtifactStoreError("content-address collision with different content")
            return {"size": len(data), "sha256": expected_hash, "existed": True}
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
        return {"size": len(data), "sha256": expected_hash, "existed": False}

    def get(self, key: str) -> bytes:
        p = self._path(key)
        if not os.path.exists(p):
            raise ArtifactStoreError("not found")
        with open(p, "rb") as f:
            data = f.read()
        return data

    def head(self, key: str) -> Optional[dict]:
        p = self._path(key)
        if not os.path.exists(p):
            return None
        return {"size": os.path.getsize(p)}

    def delete(self, key: str) -> None:
        p = self._path(key)
        if os.path.exists(p):
            os.remove(p)

    def create_presigned_get(self, key: str, ttl_seconds: int = 300) -> str:
        return "file://" + self._path(key)

    def health(self) -> dict:
        return {"ok": os.path.isdir(self._base), "backend": "local"}

    def list_keys(self, prefix: str) -> list:
        root = self._path(prefix)
        out = []
        if not os.path.isdir(root):
            # prefix may be a partial dir; walk from base and filter
            base = self._base
            for dirpath, _dirs, files in os.walk(base):
                for f in files:
                    if f.endswith(".tmp"):
                        continue
                    full = os.path.join(dirpath, f)
                    rel = os.path.relpath(full, base).replace(os.sep, "/")
                    if rel.startswith(prefix):
                        out.append(rel)
            return out
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if f.endswith(".tmp"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, f), self._base).replace(os.sep, "/")
                out.append(rel)
        return out


class S3ArtifactStore(ArtifactStore):
    """S3/MinIO. Private bucket, SSE, tenant-prefixed content-addressed keys. Requires the `artifacts`
    extra (boto3)."""

    def __init__(self, endpoint_url, bucket, access_key, secret_key, region="us-east-1", secure=True,
                 sse="AES256"):
        import boto3
        from botocore.config import Config
        self._bucket = bucket
        self._sse = sse
        self._c = boto3.client("s3", endpoint_url=endpoint_url, aws_access_key_id=access_key,
                               aws_secret_access_key=secret_key, region_name=region,
                               use_ssl=secure, config=Config(signature_version="s3v4",
                                                             retries={"max_attempts": 3}))

    def _head_raw(self, key):
        from botocore.exceptions import ClientError
        try:
            return self._c.head_object(Bucket=self._bucket, Key=key)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def put(self, key: str, data: bytes, expected_hash: str) -> dict:
        if sha256_hex(data) != expected_hash:
            raise HashMismatch("write hash mismatch")
        existing = self._head_raw(key)
        if existing is not None:
            # §2.1: an existing object is acceptable ONLY when its stored hash AND size match. Missing
            # metadata is NOT treated as a match — read the bytes and verify, else fail closed.
            meta_sha = (existing.get("Metadata", {}) or {}).get("sha256")
            size = existing.get("ContentLength")
            if meta_sha is not None:
                if meta_sha != expected_hash or int(size) != len(data):
                    raise ArtifactStoreError("content-address collision with different content")
            elif not self.verify(key, expected_hash):
                raise ArtifactStoreError("existing object failed hash verification")
            return {"size": len(data), "sha256": expected_hash, "existed": True}
        kwargs = {"Bucket": self._bucket, "Key": key, "Body": data, "ContentLength": len(data),
                  "Metadata": {"sha256": expected_hash}}
        if self._sse:                                    # SSE is configurable; MinIO w/o KMS uses none
            kwargs["ServerSideEncryption"] = self._sse
        self._c.put_object(**kwargs)
        return {"size": len(data), "sha256": expected_hash, "existed": False}

    def get(self, key: str) -> bytes:
        obj = self._c.get_object(Bucket=self._bucket, Key=key)
        return obj["Body"].read()

    def head(self, key: str) -> Optional[dict]:
        h = self._head_raw(key)
        if h is None:
            return None
        return {"size": h.get("ContentLength"), "sha256": (h.get("Metadata", {}) or {}).get("sha256")}

    def delete(self, key: str) -> None:
        self._c.delete_object(Bucket=self._bucket, Key=key)

    def list_keys(self, prefix: str) -> list:
        out = []
        token = None
        while True:
            kw = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = self._c.list_objects_v2(**kw)
            for obj in resp.get("Contents", []) or []:
                out.append(obj["Key"])
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
        return out

    def create_presigned_get(self, key: str, ttl_seconds: int = 300) -> str:
        return self._c.generate_presigned_url("get_object", Params={"Bucket": self._bucket, "Key": key},
                                              ExpiresIn=int(ttl_seconds))

    def health(self) -> dict:
        self._c.head_bucket(Bucket=self._bucket)
        return {"ok": True, "backend": "s3", "bucket": self._bucket}
