# GitHub release validation

## Fresh virtual environment (editable install)
- `pip install -e .[dev]`: OK · `pip check`: **No broken requirements** · import smoke (`enterprise_memory`, `serving.api`, `serving.governed_view`): **OK**.
- Core tests `tests/unit tests/security tests/integration/test_api.py`: **53 passed**.
- Offline demo `scripts/demo_alice_bob.py --offline`: **DEMO_PASS true**.
- `release_check.py --manifest`: **38 files verified** · `--openapi`: **8 endpoints present** · `--secrets`: **CLEAN**.

## Package build
- `python -m build`: built sdist + wheel. Wheel installed into a second clean venv; `import enterprise_memory` + `create_app()`: **OK**. `dist/` not committed.

## Clean-clone simulation
- `git clone` of the local release into a fresh directory; install + tests + demo from the clone: **53 passed, DEMO_PASS, secret scan CLEAN, manifest OK, git status clean (0 changes)**. The release does not depend on the original worktree.
