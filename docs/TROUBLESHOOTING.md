# Troubleshooting

- **Import error for `enterprise_memory`**: install the package (`pip install -e ".[dev]"`).
- **Mem0/Qdrant/embedding errors**: the base demo + core tests need none of these; they are the opt-in
  `mem0` extra (`RUN_MEM0_INTEGRATION=1`).
- **FastAPI test failures**: ensure `httpx` is installed (base dependency).
- **Sandbox timeouts on slow disks**: increase `sandbox_timeout_s` in `configs/local.example.yaml`.
