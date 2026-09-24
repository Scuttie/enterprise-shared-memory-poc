"""Run the frozen full-loader rehearsal under the active D1.16 identity.

The D1.15 collector is intentionally reused byte-for-byte for its scientific
and harness behavior.  This wrapper supplies the D1.16 runtime bindings in the
separate POSIX process so the D1.16 runner-readiness schema is not interpreted
as a stale D1.15 record.
"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

import trimem_d115_loader_rehearsal as d115_collector  # noqa: E402
import trimem_development_trigger_d116 as d116  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    """Delegate while the complete inherited identity chain is D1.16-bound."""

    with d116._d116_runtime_context():
        return d115_collector.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
