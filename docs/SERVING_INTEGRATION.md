# Serving integration

Insert the framework into an existing LLM serving path:

```python
private_candidates = private_store.search(user, task)          # user-isolated
shared_candidates  = shared_store.search(task)

valid_contracts = gate(shared_candidates, user_context, repo_context, dependency_versions)
canonical_contracts = registry.reload(valid_contracts)         # SQLite is the source of truth

execution_views = compile_compact_literal(canonical_contracts) # invalid -> REFUSED (skipped)

prompt  = inject(task_prompt, private_candidates, execution_views)   # <=2 views
result  = coding_model.generate(prompt)
tests   = execute(result.patch)                                # controlled sandbox
feedback.record(result, tests, injected_contract_ids)          # outcome_observations
```

- **Authentication / repo permission**: enforced in `gate(...)` (permission + scope gates) before any
  contract is eligible.
- **Invalid contracts rejected**: expired/out-of-scope fail the gates and the compiler refuses.
- **Private isolation**: `private_store.search` is per-user; shared retrieval never returns another user's
  raw private trace.
- **Outcome evidence**: written to `outcome_observations` (feedback), feeding governed promotion.
