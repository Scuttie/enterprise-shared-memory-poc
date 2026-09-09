"""Small dependency-free primitives for durable atomic evidence publication.

Writers first finish and fsync a mode-0600 temporary file in the destination
directory.  Only then may ``os.replace`` make those complete bytes visible at
the final path.  The containing directory is fsynced where the platform
supports opening directory descriptors (POSIX); Windows does not expose that
operation through ``os.open``.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from typing import BinaryIO


class AtomicEvidenceError(OSError):
    """Raised when evidence cannot be published without weakening atomicity."""


def _fsync_directory(directory: Path) -> None:
    """Durably commit directory-entry changes when supported by the OS."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        if os.name == "nt":
            # CPython on Windows cannot open a directory for ``os.fsync``.
            return
        raise
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(stream: BinaryIO, raw: bytes) -> None:
    """Handle a conforming binary stream that performs short writes."""

    view = memoryview(raw)
    offset = 0
    while offset < len(view):
        written = stream.write(view[offset:])
        if not isinstance(written, int) or written <= 0:
            raise AtomicEvidenceError("atomic evidence temporary write made no progress")
        offset += written


def _lock_path(path: Path) -> Path:
    identity = hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:16]
    return path.parent / f".trimem-publish-{identity}.lock"


def atomic_write_bytes(
    path: Path,
    raw: bytes,
    *,
    replace_existing: bool = False,
) -> None:
    """Publish complete bytes at *path* with same-directory atomic replace.

    An exclusive sibling lock preserves create-only callers' no-overwrite
    contract while still allowing the final publication itself to use the
    portable atomic ``os.replace`` primitive.  A failure before replacement
    leaves the prior valid target untouched (or the target absent).
    """

    if not isinstance(path, Path):
        path = Path(path)
    if not isinstance(raw, bytes):
        raise TypeError("atomic evidence payload must be bytes")
    path.parent.mkdir(parents=True, exist_ok=True)
    parent = path.parent.resolve(strict=True)
    target = parent / path.name
    lock = _lock_path(target)
    lock_descriptor: int | None = None
    lock_owned = False
    temporary: Path | None = None
    published = False
    try:
        try:
            lock_descriptor = os.open(
                lock,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise FileExistsError(
                f"atomic evidence publication is already locked: {target.name}"
            ) from exc
        lock_owned = True
        os.fsync(lock_descriptor)
        os.close(lock_descriptor)
        lock_descriptor = None

        if not replace_existing and os.path.lexists(target):
            raise FileExistsError(f"refusing to overwrite evidence: {target.name}")
        if target.is_symlink():
            raise AtomicEvidenceError("refusing to replace an evidence symlink")

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".trimem-",
            suffix=".tmp",
            dir=parent,
        )
        temporary = Path(temporary_name)
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(descriptor, "wb", buffering=0) as stream:
                descriptor = -1
                _write_all(stream, raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)

        os.replace(temporary, target)
        temporary = None
        published = True
        _fsync_directory(parent)
    finally:
        if lock_descriptor is not None:
            os.close(lock_descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        if lock_owned:
            try:
                lock.unlink()
            except FileNotFoundError:
                pass
        # Persist cleanup of transient names.  When publication succeeded this
        # is a second harmless fsync; when it failed the final path was never
        # changed.
        try:
            _fsync_directory(parent)
        except OSError:
            if published:
                raise


__all__ = [
    "AtomicEvidenceError",
    "atomic_write_bytes",
]
