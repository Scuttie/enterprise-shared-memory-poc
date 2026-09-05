"""Dependency-free frozen protocol for the TriMem grader discrimination smoke."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Sequence


MATRIX_KIND = "single_serial_six_instance_gold_noop_campaign"
NOOP_BASELINE_PATH = ".trimem_grader_noop"
NOOP_BASELINE_CONTENT = b"trimem grader discrimination noop\n"
NOOP_BASELINE_PATCH = (
    b"diff --git a/.trimem_grader_noop b/.trimem_grader_noop\n"
    b"new file mode 100644\n"
    b"--- /dev/null\n"
    b"+++ b/.trimem_grader_noop\n"
    b"@@ -0,0 +1 @@\n"
    b"+trimem grader discrimination noop\n"
)
NOOP_BASELINE_PATCH_SHA256 = "0f4fb705a73dd7e804773b35e2ab0e4e2f17248c571e69333e9b8de7c2025775"
NOOP_BASELINE_LOCK = {
    "changed_paths": [NOOP_BASELINE_PATH],
    "format": "GIT_UNIFIED_DIFF_NEW_FILE_ONLY_V1",
    "patch_bytes": 165,
    "patch_sha256": NOOP_BASELINE_PATCH_SHA256,
}
PROBE_SEQUENCE = ("GOLD", "NOOP_BASELINE") * 6


class SmokeProtocolError(ValueError):
    pass


def validate_serial_targets(
    *,
    matrix_kind: Any,
    noop_baseline: Any,
    targets: Sequence[Mapping[str, Any]],
) -> None:
    if matrix_kind != MATRIX_KIND:
        raise SmokeProtocolError("grader-smoke serial campaign kind mismatch")
    if noop_baseline != NOOP_BASELINE_LOCK:
        raise SmokeProtocolError("frozen NOOP_BASELINE patch lock mismatch")
    if len(targets) != 12 or any(not isinstance(target, Mapping) for target in targets):
        raise SmokeProtocolError("grader-smoke target matrix must contain exactly 12 rows")
    if tuple(target.get("probe") for target in targets) != PROBE_SEQUENCE:
        raise SmokeProtocolError("grader-smoke must run GOLD then NOOP_BASELINE per instance")
    if any(
        type(target.get("order_index")) is not int
        or target.get("order_index") != position
        for position, target in enumerate(targets)
    ):
        raise SmokeProtocolError("grader-smoke order_index sequence mismatch")
    identity_fields = (
        "base_commit", "benchmark_id", "dataset_revision", "instance_id", "language",
        "repository", "source_row_sha256",
    )
    identities: set[tuple[Any, ...]] = set()
    for pair_index, (gold, noop) in enumerate(zip(targets[0::2], targets[1::2])):
        for target in (gold, noop):
            if any(
                not isinstance(target.get(field), str) or not target.get(field)
                for field in identity_fields
            ):
                raise SmokeProtocolError(
                    f"grader-smoke identity field is invalid at pair {pair_index}"
                )
            if (
                re.fullmatch(r"[0-9a-f]{40}", target["base_commit"]) is None
                or re.fullmatch(r"[0-9a-f]{40}", target["dataset_revision"]) is None
                or re.fullmatch(r"[0-9a-f]{64}", target["source_row_sha256"]) is None
            ):
                raise SmokeProtocolError(
                    f"grader-smoke identity digest/revision is invalid at pair {pair_index}"
                )
        identity = tuple(gold.get(field) for field in identity_fields)
        if identity in identities:
            raise SmokeProtocolError("grader-smoke identity is duplicated")
        identities.add(identity)
        if identity != tuple(noop.get(field) for field in identity_fields):
            raise SmokeProtocolError(f"grader-smoke probe identity drift at pair {pair_index}")
        base = f"{gold.get('benchmark_id')}--{gold.get('instance_id')}"
        if (
            gold.get("expected_resolved") is not True
            or noop.get("expected_resolved") is not False
            or gold.get("target_id") != base + "--gold"
            or noop.get("target_id") != base + "--noop-baseline"
        ):
            raise SmokeProtocolError(f"grader-smoke probe protocol drift at pair {pair_index}")
    if len(identities) != 6:
        raise SmokeProtocolError("grader-smoke must contain exactly six distinct identities")


if (
    len(NOOP_BASELINE_PATCH) != NOOP_BASELINE_LOCK["patch_bytes"]
    or hashlib.sha256(NOOP_BASELINE_PATCH).hexdigest() != NOOP_BASELINE_PATCH_SHA256
):
    raise RuntimeError("frozen NOOP_BASELINE protocol constant drift")


__all__ = [
    "MATRIX_KIND", "NOOP_BASELINE_CONTENT", "NOOP_BASELINE_LOCK",
    "NOOP_BASELINE_PATCH", "NOOP_BASELINE_PATCH_SHA256", "NOOP_BASELINE_PATH",
    "PROBE_SEQUENCE", "SmokeProtocolError", "validate_serial_targets",
]
