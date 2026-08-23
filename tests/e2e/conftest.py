"""P5 end-to-end harness (§9). Credential-free: a local RSA key ring signs OIDC tokens and writes a JWKS
file the API reads; PostgreSQL/Qdrant/MinIO are real (digest-pinned in ci-e2e); the repository provider,
execution backend and sandbox are deterministic fakes. The API and the solve worker run as SEPARATE
processes (started by the workflow); tests talk to the API over real HTTP. Skipped unless E2E_API_URL +
DATABASE_URL are set."""
import os
import sys
import json
import time
import uuid
import asyncio
import hashlib
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

jwt = pytest.importorskip("jwt")
pytest.importorskip("cryptography")
httpx = pytest.importorskip("httpx")
from jwt.algorithms import RSAAlgorithm                                   # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa                # noqa: E402
from cryptography.hazmat.primitives import serialization                 # noqa: E402
from sqlalchemy import text                                              # noqa: E402
from enterprise_memory.persistence.database import make_engine            # noqa: E402

ISSUER = os.environ.get("OIDC_ISSUER", "https://idp.e2e.local/")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "esm-api")
API_URL = os.environ.get("E2E_API_URL", "")
DIM = int(os.environ.get("INDEX_DIM", "64"))


def _require():
    if not (API_URL and os.environ.get("DATABASE_URL")):
        pytest.skip("E2E requires E2E_API_URL + DATABASE_URL (ci-e2e only)")


@pytest.fixture(autouse=True)
def _guard():
    _require()


def run(coro):
    return asyncio.run(coro)


def su():
    return make_engine("postgres", "postgres")


@pytest.fixture(scope="session")
def keyring():
    """Generate an RSA keypair, publish its JWKS to OIDC_JWKS_FILE, and return a token signer."""
    _require()
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption())
    jwk = json.loads(RSAAlgorithm.to_jwk(k.public_key()))
    jwk.update(kid="e2e-1", alg="RS256", use="sig")
    jwks_file = os.environ["OIDC_JWKS_FILE"]
    with open(jwks_file, "w", encoding="utf-8") as f:
        json.dump({"keys": [jwk]}, f)

    def sign(sub, org_id, scopes, **over):
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": str(sub), "org_id": str(org_id),
                  "scope": " ".join(scopes), "iat": now, "nbf": now - 5, "exp": now + 600}
        claims.update(over)
        return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": "e2e-1"})

    return sign


def chash(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True).encode()).hexdigest()


def _typed_contract(org, repo):
    from enterprise_memory.contracts import schema as SS
    c = SS.MemoryContract(
        contract_id=str(uuid.uuid4()), schema_version=SS.SCHEMA_VERSION, title="Return one",
        canonical_summary="make f return 1 with a governed fix",
        scope=SS.ContractScope(org_id=str(org), team_ids=[], repo_ids=[str(repo)], path_globs=[],
                               language="python", framework="none", dependency_version_constraints={},
                               branch_or_release_constraints=["main"], error_signatures=["E_RET"],
                               applies_when=["f returns 0"], does_not_apply_when=["unrelated"]),
        action=SS.ContractAction(ordered_steps=["change return to 1"], code_pattern="return 1",
                                 forbidden_patterns=[], required_inputs=[], operation_order=[]),
        validity=SS.ContractValidity(valid_from="2020-01-01", valid_until="", environment_constraints={},
                                     version_constraints={}, invalidation_events=[], supersedes_contract_ids=[],
                                     superseded_by_contract_id=""),
        verification=SS.ContractVerification(test_commands=["pytest"], expected_observations=["pass"],
                                             regression_checks=["noreg"], failure_observations=["fail"]),
        provenance=SS.ContractProvenance(source_episode_ids=["ep0"], contributor_user_ids_pseudonymized=["u0"],
                                         source_commit_shas=["sha0"], source_test_results=["r0"],
                                         extractor_version="x/1"),
        evidence=SS.ContractEvidence(),
        governance=SS.ContractGovernance(state="promoted", visibility="shared")).stamp()
    return c


async def _seed(with_modify=True, with_read=True):
    from enterprise_memory.contracts import codec
    org, user, repo = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    cid, vid = uuid.uuid4(), uuid.uuid4()
    e = su()
    contract = _typed_contract(org, repo)
    canonical = codec.encode_memory_contract(contract)
    async with e.begin() as c:
        await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                        {"i": org, "k": "org-e2e-%s" % org})
        await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                        {"i": user, "o": org, "s": "u-" + str(user)})
        await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                        {"i": repo, "o": org, "r": "repo-e2e"})
        if with_read or with_modify:
            await c.execute(text(
                "INSERT INTO repository_permissions(org_id,repository_id,subject_type,subject_id,can_read,"
                "can_modify) VALUES(:o,:r,'user',:u,:cr,:cm)"),
                {"o": org, "r": repo, "u": user, "cr": with_read, "cm": with_modify})
        await c.execute(text(
            "INSERT INTO task_execution_policies(org_id,repository_id,task_key,editable_paths,target_symbol,"
            "exact_signature,test_bundle_ref,maximum_changed_lines,allowed_refs,version,active) VALUES"
            "(:o,:r,'fix-return',:ep,'f','def f()','tests/test_app.py',12,:refs,1,true)"),
            {"o": org, "r": repo, "ep": ["src/**"], "refs": ["refs/heads/main", "main"]})
        # promoted shared contract
        await c.execute(text("INSERT INTO memory_contracts(id,org_id,repository_id) VALUES(:i,:o,:r)"),
                        {"i": cid, "o": org, "r": repo})
        await c.execute(text(
            "INSERT INTO memory_contract_versions(id,contract_id,org_id,version_number,canonical_json,"
            "content_hash,governance_state) VALUES(:i,:c,:o,1,cast(:j as jsonb),:h,'promoted')"),
            {"i": vid, "c": cid, "o": org, "j": json.dumps(canonical), "h": contract.content_hash})
        await c.execute(text("UPDATE memory_contracts SET current_version_id=:v WHERE id=:c"),
                        {"v": vid, "c": cid})
    await e.dispose()
    # index the promoted contract into Qdrant (same DIM/embedder the worker uses)
    from enterprise_memory.indexing.qdrant_indexes import QdrantIndex
    from enterprise_memory.indexing.embeddings import DeterministicTestEmbedder
    from enterprise_memory.indexing.projection import build_record
    from enterprise_memory.indexing.models import SHARED
    idx = QdrantIndex.from_env(DIM); await idx.ensure_ready()
    emb = DeterministicTestEmbedder(DIM)
    row = {"contract_id": str(cid), "object_id": str(vid), "version_number": 1,
           "content_hash": contract.content_hash, "org_id": str(org), "canonical": canonical,
           "repository_id": str(repo), "governance_state": "promoted", "valid_from": None, "valid_until": None}
    rec = build_record(SHARED, row)
    await idx.upsert([rec], emb.embed([rec.text]))
    await idx.close()
    return {"org": str(org), "user": str(user), "repo": str(repo), "contract_id": str(cid),
            "version_id": str(vid)}


@pytest.fixture
def seed():
    return lambda **kw: run(_seed(**kw))


@pytest.fixture
def client():
    with httpx.Client(base_url=API_URL, timeout=30.0) as c:
        yield c


def poll_job(client, token, job_id, target="SUCCEEDED", tries=120, interval=0.5):
    for _ in range(tries):
        r = client.get("/v1/jobs/%s" % job_id, headers={"authorization": "Bearer " + token})
        if r.status_code == 200 and r.json().get("state") in (target, "FAILED", "DEAD_LETTER", "CANCELLED"):
            return r.json()
        time.sleep(interval)
    return client.get("/v1/jobs/%s" % job_id, headers={"authorization": "Bearer " + token}).json()
