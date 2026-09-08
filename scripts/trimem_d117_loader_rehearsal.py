"""Run the frozen full-loader rehearsal under the active D1.17 identity.

The D1.15 collector remains the single implementation of the scientific and
harness checks.  This wrapper supplies the complete D1.17 runtime bindings in
the separate POSIX process so D1.17 runner-readiness evidence is never parsed
under a stale generation schema.
"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

import trimem_d115_loader_rehearsal as d115_collector  # noqa: E402
import trimem_development_trigger_d117 as d117  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    """Delegate while the complete inherited identity chain is D1.17-bound."""

    with d117._d117_runtime_context():
        return d115_collector.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
