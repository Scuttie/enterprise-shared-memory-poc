"""Credential-free D1.6 authentication control-plane contract tests."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import sys

import pytest

from enterprise_memory.providers.base import AuthError, ModelRequest
from enterprise_memory.providers.openai_credential import (
    OpenAICredentialValidationError,
    build_openai_headers,
    compute_openai_key_commitment,
    validate_openai_api_key,
    verify_openai_key_commitment,
)
from enterprise_memory.providers.openai_responses import OpenAIResponsesProvider


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from trimem_openai_model_access_check import (  # noqa: E402
    MODEL_ID,
    check_model_access,
)
import trimem_development_trigger_d15 as d15  # noqa: E402
import trimem_exec_approval as approval_contract  # noqa: E402


KEY = "DUMMY-VISIBLE-ASCII-CREDENTIAL-00000001"


class Response:
    def __init__(self, status: int, body: object, request_id: str = "request-private"):
        self.status_code = status
        self.content = json.dumps(body, separators=(",", ":")).encode()
        self.headers = {"x-request-id": request_id}


class Client:
    def __init__(self, response: Response):
        self.response = response
        self.calls = []

    def get(self, url, *, headers, timeout):
        self.calls.append((url, headers, timeout))
        return self.response


class AsyncClient:
    def __init__(self, response: Response):
        self.response = response
        self.calls = []

    async def post(self, url, *, json, headers, timeout):
        self.calls.append((url, headers, timeout))
        return self.response


def binding(**changes):
    value = {
        "request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_007",
        "execution_head": "a" * 40,
        "source_head": "b" * 40,
        "workflow_run_id": "123",
        "workflow_run_attempt": "1",
        "model_id": MODEL_ID,
        "approval_nonce": "nonce-credential-free-0001",
    }
    value.update(changes)
    return value


def approval(key=KEY, **changes):
    bound = binding(**changes)
    return {
        "request_id": bound["request_id"],
        "approval": {
            "approved_git_commit": bound["execution_head"],
            "approved_source_git_commit": bound["source_head"],
            "approved_workflow_run_id": int(bound["workflow_run_id"]),
            "approved_workflow_run_attempt": int(bound["workflow_run_attempt"]),
            "approval_nonce": bound["approval_nonce"],
            "approved_openai_key_commitment": compute_openai_key_commitment(
                key, bound
            ),
        },
    }


@pytest.mark.parametrize(
    ("value", "classification"),
    [
        ("", "OPENAI_KEY_EMPTY"),
        ("\ufeff" + KEY, "OPENAI_KEY_NON_ASCII"),
        (KEY + "\r", "OPENAI_KEY_CONTROL_CHARACTER"),
        (KEY + "\n", "OPENAI_KEY_CONTROL_CHARACTER"),
        (KEY + "\t", "OPENAI_KEY_CONTROL_CHARACTER"),
        (KEY + " ", "OPENAI_KEY_CONTROL_CHARACTER"),
        (KEY + "\x00", "OPENAI_KEY_CONTROL_CHARACTER"),
        ('"' + KEY + '"', "OPENAI_KEY_SURROUNDING_QUOTES"),
        ("short", "OPENAI_KEY_LENGTH_INVALID"),
    ],
)
def test_invalid_credentials_are_rejected_without_repair(value, classification):
    with pytest.raises(OpenAICredentialValidationError) as caught:
        validate_openai_api_key(value)
    assert caught.value.classification == classification
    assert not value or value not in str(caught.value)


def test_visible_ascii_credential_is_accepted_without_modification():
    assert validate_openai_api_key(KEY) == KEY.encode("ascii")
    assert build_openai_headers(KEY) == {
        "Authorization": "Bearer " + KEY,
        "Content-Type": "application/json",
    }


def test_provider_uses_shared_header_validator(monkeypatch):
    calls = []

    def shared(value):
        calls.append(value)
        return {"Authorization": "fixture", "Content-Type": "application/json"}

    monkeypatch.setattr(
        "enterprise_memory.providers.openai_responses.build_openai_headers", shared
    )

    class Secrets:
        def get(self, _name):
            return KEY

    provider = OpenAIResponsesProvider(
        "https://fixture/v1", MODEL_ID, Secrets(), family="gpt5.4", http_client=object()
    )
    assert provider._headers()["Authorization"] == "fixture"
    assert calls == [KEY]


def test_provider_exception_never_contains_secret():
    class Secrets:
        def get(self, _name):
            return KEY + "\n"

    provider = OpenAIResponsesProvider(
        "https://fixture/v1", MODEL_ID, Secrets(), family="gpt5.4", http_client=object()
    )
    with pytest.raises(AuthError) as caught:
        provider._headers()
    assert KEY not in str(caught.value)


def test_commitment_is_key_and_run_bound():
    value = binding()
    commitment = compute_openai_key_commitment(KEY, value)
    assert verify_openai_key_commitment(KEY, value, commitment)
    assert not verify_openai_key_commitment(KEY + "x", value, commitment)
    assert not verify_openai_key_commitment(
        KEY, binding(execution_head="c" * 40), commitment
    )
    assert not verify_openai_key_commitment(
        KEY, binding(workflow_run_id="124"), commitment
    )


def test_d15_approval_builder_embeds_only_the_run_bound_commitment():
    document = approval_contract.build_external_approval_document(
        request_id=d15.REQUEST_ID,
        request_sha256="1" * 64,
        git_commit="a" * 40,
        source_git_commit="b" * 40,
        freeze_sha256="2" * 64,
        phase="DEVELOPMENT_TUNING",
        task_arm_runs=72,
        paid_model_call_cap=1873,
        input_token_cap=36_004_096,
        output_token_cap=4_720_640,
        currency_hard_cap=50.0,
        grader_containers=72,
        workflow_run_id=123,
        workflow_run_attempt=1,
        legal_terms_acceptance=True,
        approval_actor="fixture-actor",
        approval_timestamp="2026-09-05T00:00:00Z",
        openai_api_key=KEY,
        approval_nonce="nonce-credential-free-0001",
        model_id=MODEL_ID,
    )
    raw = json.dumps(document, sort_keys=True)
    assert document["schema"] == "trimem/external-exec-approval/1.2"
    assert KEY not in raw
    assert document["approval"]["approved_openai_key_commitment"] == (
        compute_openai_key_commitment(KEY, binding())
    )
    assert d15.SENTINEL_PATH.endswith("DEVELOPMENT_TUNING_EXEC_REQUEST_007.json")


def test_historical_sentinel_is_hash_bound_but_not_a_freeze_member():
    freeze = json.loads((ROOT / "artifacts/trimem_v1/freeze.json").read_text())
    path = d15.PREVIOUS_SENTINEL_PATH
    assert path not in freeze["files"]
    assert d15.BOUND_PATHS["previous_dev_request_sha256"] == path
    assert path in d15.FREEZE_MEMBERSHIP_EXEMPT_PATHS
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == (
        d15.PREVIOUS_SENTINEL_SHA256
    )


def test_exact_model_metadata_passes_without_generation_or_ledger():
    client = Client(Response(200, {"object": "model", "id": MODEL_ID}))
    result = check_model_access(
        api_key=KEY, approval_document=approval(), http_client=client
    )
    assert result["status"] == "PASS"
    assert result["credential_binding"] == "PASS"
    assert result["provider_control_plane_requests"] == 1
    assert result["model_generation_requests"] == result["model_tokens"] == 0
    assert result["task_arm_reservations"] == 0
    assert client.calls[0][0].endswith("/models/" + MODEL_ID)


@pytest.mark.parametrize(
    ("status", "failure", "http_classification"),
    [
        (401, "OPENAI_CREDENTIAL_REJECTED", "HTTP_401_AUTHENTICATION_FAILED"),
        (
            403,
            "OPENAI_PROJECT_OR_MODEL_PERMISSION_DENIED",
            "HTTP_403_PERMISSION_DENIED",
        ),
        (
            404,
            "OPENAI_MODEL_NOT_AVAILABLE_TO_PROJECT",
            "HTTP_404_MODEL_NOT_AVAILABLE",
        ),
        (
            429,
            "OPENAI_ACCOUNT_RATE_OR_QUOTA_BLOCK",
            "HTTP_429_RATE_OR_QUOTA_LIMIT",
        ),
    ],
)
def test_model_access_failures_remain_exact(status, failure, http_classification):
    private = "private provider message"
    client = Client(
        Response(
            status,
            {
                "error": {
                    "type": "fixture_type",
                    "code": "fixture_code",
                    "param": "model",
                    "message": private,
                }
            },
        )
    )
    result = check_model_access(
        api_key=KEY, approval_document=approval(), http_client=client
    )
    assert result["failure_classification"] == failure
    assert result["http_classification"] == http_classification
    assert result["http_status"] == status
    assert result["provider_error_type"] == "fixture_type"
    assert result["provider_error_code"] == "fixture_code"
    assert result["provider_error_param"] == "model"
    assert result["provider_error_message_bytes"] == len(private.encode())
    assert result["provider_error_message_sha256"] == hashlib.sha256(
        private.encode()
    ).hexdigest()
    assert private not in json.dumps(result)
    assert result["benchmark_image_pulls"] == 0
    assert result["task_arm_reservations"] == 0
    assert len(client.calls) == 1


def test_binding_failure_stops_before_network():
    client = Client(Response(200, {"object": "model", "id": MODEL_ID}))
    result = check_model_access(
        api_key=KEY + "x", approval_document=approval(), http_client=client
    )
    assert result["failure_classification"] == "OPENAI_CREDENTIAL_BINDING_MISMATCH"
    assert result["provider_control_plane_requests"] == 0
    assert result["benchmark_image_pulls"] == 0
    assert client.calls == []


@pytest.mark.parametrize(
    ("status", "classification", "error_class"),
    [
        (401, "HTTP_401_AUTHENTICATION_FAILED", AuthError),
        (403, "HTTP_403_PERMISSION_DENIED", AuthError),
        (404, "HTTP_404_MODEL_NOT_AVAILABLE", Exception),
        (429, "HTTP_429_RATE_OR_QUOTA_LIMIT", Exception),
    ],
)
def test_generation_provider_preserves_exact_http_classification(
    status, classification, error_class
):
    response = Response(
        status,
        {
            "error": {
                "type": "fixture_type",
                "code": "fixture_code",
                "param": "model",
                "message": "private provider message",
            }
        },
    )
    provider = OpenAIResponsesProvider(
        "https://fixture/v1",
        MODEL_ID,
        type("Secrets", (), {"get": lambda self, _name: KEY})(),
        family="gpt5.4",
        max_retries=1,
        http_client=AsyncClient(response),
    )
    with pytest.raises(error_class) as caught:
        asyncio.run(
            provider.generate(
                ModelRequest([{"role": "user", "content": "fixture"}], 32),
                logical_request_id="fixture-call",
                org_id="fixture-org",
            )
        )
    envelope = caught.value.record.response_envelope
    public = envelope.to_public_dict()
    assert envelope.terminal_classification == classification
    assert public["response_error_type"] == "fixture_type"
    assert public["response_error_code"] == "fixture_code"
    assert public["response_error_param"] == "model"
    assert public["response_error_message_bytes"] == len(b"private provider message")
    assert "private provider message" not in json.dumps(public)
    assert len(provider._client.calls) == 1


def test_workflow_checks_access_before_images_and_continues_to_runner():
    workflow = (ROOT / ".github/workflows/trimem-benchmark.yml").read_text(
        encoding="utf-8"
    )
    positions = [
        workflow.index("Validate exact OpenAI credential format before network access"),
        workflow.index("Verify run-bound OpenAI credential commitment"),
        workflow.index("Retrieve exact model metadata before image materialization"),
        workflow.index("Execute one native-action protocol canary before benchmark images"),
        workflow.index("Apply exact migration head"),
        workflow.index("Pull committed images by digest and verify local observations"),
        workflow.index("Execute frozen serial streams with one atomic phase ledger"),
    ]
    assert positions == sorted(positions)


def test_d14_scientific_locks_and_historical_evidence_are_unchanged():
    expected = {
        "artifacts/trimem_v1/development_tuning_exec/exec-005/http-auth-error-receipt.json": "951f99472bdca153878f48ce1b18b11990e8125c15b47d529df508760939d42d",
        "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_005.json": "97e2ce227418ace0db1edbf816391cdf0fda4f8d29359da4a3f81687f1aa19de",
        "configs/trimem_v1/arms.json": "7ecc15277cc9a9041befd4ae32f99b65da63009383b22701e0aecb407fe3906c",
        "configs/trimem_v1/development_manifest.json": "44e52137dad68618396c15d6b3c2221a683f89988e361efb2966e244ba230900",
        "configs/trimem_v1/grader_lock.json": "853d42e86c2caf1449f28bba9143741e3ccff5e75bbe790115a0d9c746014fbb",
        "configs/trimem_v1/model_lock.json": "a0a4811590d396c2bea4f0454c18c912d11579858947540a355407009a975922",
        "configs/trimem_v1/selection_plan.json": "dddc421120d16f241a2941afbd67190df4b3be6cefeab99e37437abf7133dcf4",
        "configs/trimem_v1/solve_output_budget_contract.json": "49943aa6527bd8192c051ac72b2798f36976f66fa5aaff0d62525398494156e4",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
