"""Run the frozen full-loader rehearsal under the active D1.20 identity.

The D1.15 collector remains the single implementation of the scientific and
harness checks. This wrapper supplies the complete D1.20 runtime bindings in
the separate POSIX process, including readiness schema ``1.20``. It performs
no credential, provider, model, image, grader-container, or GitHub operation.
"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

import trimem_d115_loader_rehearsal as d115_collector  # noqa: E402
import trimem_development_trigger_d120 as d120  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    """Delegate while the complete inherited identity chain is D1.20-bound."""

    with d120._d120_runtime_context():
        return d115_collector.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
