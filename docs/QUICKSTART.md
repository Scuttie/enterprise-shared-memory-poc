# Quickstart

```bash
python -m venv .venv && . .venv/bin/activate
python -m pip install -e ".[dev]"
python scripts/demo_alice_bob.py --offline
python -m pytest -q tests/unit tests/security tests/integration/test_api.py
```
Live Solar/Mem0: copy `.env.example` to `.env`, set `UPSTAGE_API_KEY`, then `python scripts/mem0_validate.py`
with `RUN_MEM0_INTEGRATION=1`. Never commit a real key.
