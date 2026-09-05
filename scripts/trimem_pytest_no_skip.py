"""Run pytest and turn every collected or runtime skip into a CI failure."""
from __future__ import annotations

import sys

import pytest


class NoSkipPlugin:
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        skipped = reporter.stats.get("skipped", []) if reporter is not None else []
        if skipped:
            reporter.write_sep("=", f"TriMem CI forbids skips: {len(skipped)}")
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit("explicit pytest paths are required")
    return int(pytest.main(["--strict-markers", *args], plugins=[NoSkipPlugin()]))


if __name__ == "__main__":
    raise SystemExit(main())
