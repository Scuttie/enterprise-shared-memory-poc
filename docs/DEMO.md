# Demo

`python scripts/demo_alice_bob.py --offline` runs a deterministic, no-network scenario: Alice solves a
task privately; Bob cannot read Alice's private trace; a contract is promoted through the gates; Bob
retrieves the governed contract, passes hidden tests in the sandbox; out-of-scope/expired injection is
blocked; the audit shows provenance without Alice's raw trace. Exit is a JSON summary with `DEMO_PASS`.
