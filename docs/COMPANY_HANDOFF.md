# Company handoff

**Recommended first pilot:** internal API and private configuration rules (bounded, contract-shaped).
Avoid broad repository-level coding as the first pilot.

**User cohort:** 5-10 developers.

**First metrics:** hidden-test success, private/shared leakage, invalid-contract injection, stale
adoption, retrieval precision, memory token cost.

**Rollout:** shadow mode -> opt-in read-only suggestions -> reviewed promotion -> limited write access ->
wider rollout after audit.

**Add a collaborator** (run only with a real GitHub username):
```bash
gh api --method PUT \
  repos/Scuttie/enterprise-shared-memory-poc/collaborators/<GITHUB_USERNAME> \
  -f permission=push
```
