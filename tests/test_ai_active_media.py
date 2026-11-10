from __future__ import annotations

import base64
import hashlib
import importlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

AI_GATEWAY_ROOT = Path(__file__).parents[1] / "services" / "ai-gateway"
sys.path.insert(0, str(AI_GATEWAY_ROOT))

gateway_media = importlib.import_module("app.media")
network = importlib.import_module("app.network")
providers = importlib.import_module("app.providers")
tasks = importlib.import_module("app.tasks")

NOW = datetime(2026, 11, 10, 4, 0, tzinfo=UTC)
TASK_ID = "10000000-0000-4000-8000-000000000001"
PAGE_ID = "20000000-0000-4000-8000-000000000002"
ASSET_ID = "30000000-0000-4000-8000-000000000003"
MEDIA_CONTENT = b"smartscan-active-media"
MEDIA_SHA256 = hashlib.sha256(MEDIA_CONTENT).hexdigest()
RESULT = json.dumps(
    {
        "schema_version": "1.0",
        "task_id": TASK_ID,
        "task_type": "classify_page",
        "confidence": 0.96,
        "label": "exam",
        "evidence_codes": ["dense_question_layout"],
    }
).encode()


def task_payload() -> dict:
    return {
        "schema_version": "1.0",
        "task_id": TASK_ID,
        "task_type": "classify_page",
        "context": {
            "page_id": PAGE_ID,
            "source_result_version": 2,
            "media": {
                "asset_id": ASSET_ID,
                "sha256": MEDIA_SHA256,
                "mime_type": "image/jpeg",
                "width": 1200,
                "height": 1800,
            },
            "locale": "zh-CN",
        },
        "constraints": {"temperature": 0.0, "max_output_tokens": 1024},
    }


def adapter(mode: str, *, api_style: str = "openai_responses"):
    definition = providers.ProviderDefinition.model_validate(
        {
            "id": "company-ai",
            "display_name": "公司视觉模型",
            "kind": "custom_vlm",
            "api_style": api_style,
            "enabled": True,
            "base_url": "https://vision.corp.example/v1",
            "api_key_env": "COMPANY_AI_KEY",
            "model": "company-vlm-1",
            "capabilities": ["image_classification"],
            "media_transfer_mode": mode,
            "allowed_private_cidrs": ["10.20.0.0/16"],
            "max_request_bytes": 64 * 1024,
        }
    )
    return providers.create_adapter(definition, {"COMPANY_AI_KEY": "company-secret"})


def media_reference(**changes):
    payload = {
        "access_token": "AbCdEfGhIjKlMnOpQrStUvWxYz012345",
        "byte_size": len(MEDIA_CONTENT),
        "sha256": MEDIA_SHA256,
        "mime_type": "image/jpeg",
        "expires_at": NOW + timedelta(minutes=10),
    }
    payload.update(changes)
    return network.OutboundMediaReference.model_validate(payload)


class Resolver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def resolve(self, hostname: str, port: int):
        self.calls.append((hostname, port))
        return ("10.20.1.10",)


class Sender:
    def __init__(self, responses: list[bytes] | None = None) -> None:
        self.responses = list(responses or [RESULT])
        self.requests: list[network.PinnedRequest] = []

    def send(self, request: network.PinnedRequest, *, timeout_seconds: float):
        assert timeout_seconds == 90.0
        self.requests.append(request)
        return network.WireResponse(
            status=200,
            headers={"content-type": "application/json"},
            body=self.responses.pop(0),
        )


class FailOnTaskSender(Sender):
    def send(self, request: network.PinnedRequest, *, timeout_seconds: float):
        if len(self.requests) == 1:
            self.requests.append(request)
            raise network.NetworkSecurityError("provider_request_failed", request_sent=True)
        return super().send(request, timeout_seconds=timeout_seconds)


def execute(mode: str, sender: Sender, *, api_style: str = "openai_responses"):
    selected = adapter(mode, api_style=api_style)
    structured_task = tasks.validate_task(task_payload())
    plan = tasks.build_provider_request_plan(selected, structured_task)
    transport = network.SecureProviderTransport(Resolver(), sender, clock=lambda: NOW)
    return transport.execute(
        selected,
        structured_task,
        plan,
        media_reference(),
        media_content=MEDIA_CONTENT,
    )


def test_inline_data_url_embeds_verified_media_without_grant_token() -> None:
    sender = Sender()

    result = execute("inline_data_url", sender)

    request = sender.requests[0]
    expected = "data:image/jpeg;base64," + base64.b64encode(MEDIA_CONTENT).decode()
    assert expected in request.body.decode()
    assert media_reference().access_token.get_secret_value() not in request.body.decode()
    assert result.evidence.media_transfer_mode == "inline_data_url"
    assert result.evidence.temporary_file_deleted is None


def test_custom_multipart_sends_binary_and_structured_payload() -> None:
    sender = Sender()

    result = execute("multipart", sender, api_style="custom")

    request = sender.requests[0]
    assert request.headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert MEDIA_CONTENT in request.body
    assert b'name="payload"' in request.body
    assert b'"image":"cid:media"' in request.body
    assert result.evidence.media_transfer_mode == "multipart"


def test_files_api_uploads_uses_file_id_and_deletes_temporary_file() -> None:
    sender = Sender([b'{"id":"file_safe_123"}', RESULT, b'{"deleted":true}'])

    result = execute("files_api", sender)

    assert [request.method for request in sender.requests] == ["POST", "POST", "DELETE"]
    assert [request.target for request in sender.requests] == [
        "/v1/files",
        "/v1/responses",
        "/v1/files/file_safe_123",
    ]
    assert MEDIA_CONTENT in sender.requests[0].body
    assert '"file_id":"file_safe_123"' in sender.requests[1].body.decode()
    assert result.evidence.temporary_file_deleted is True
    assert "file_safe_123" not in result.evidence.model_dump_json()


def test_files_api_deletes_temporary_file_when_task_request_fails() -> None:
    sender = FailOnTaskSender([b'{"id":"file_safe_123"}', b'{"deleted":true}'])

    with pytest.raises(network.NetworkSecurityError, match="provider_request_failed"):
        execute("files_api", sender)

    assert [request.method for request in sender.requests] == ["POST", "POST", "DELETE"]
    assert sender.requests[-1].target == "/v1/files/file_safe_123"


def test_files_api_rejects_invalid_upload_response() -> None:
    sender = Sender([b'{"unexpected":"value"}'])

    with pytest.raises(network.NetworkSecurityError, match="provider_file_upload_invalid"):
        execute("files_api", sender)

    assert len(sender.requests) == 1


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(302, headers={"location": "http://evil.invalid"}), "redirect"),
        (httpx.Response(200, content=MEDIA_CONTENT, headers={"content-type": "image/png"}), "mime"),
        (httpx.Response(200, content=b"changed", headers={"content-type": "image/jpeg"}), "size"),
    ],
)
def test_internal_media_client_fails_closed(response: httpx.Response, code: str) -> None:
    client = gateway_media.InternalMediaClient(
        "http://api:8000/v1/internal/ai-media",
        "i" * 32,
        transport=httpx.MockTransport(lambda _: response),
    )

    with pytest.raises(gateway_media.InternalMediaError, match=code):
        client.fetch(media_reference())


def test_internal_media_client_authenticates_and_verifies_hash() -> None:
    captured: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["media_token"] = request.headers.get("x-smartscan-ai-media-token")
        return httpx.Response(
            200,
            content=MEDIA_CONTENT,
            headers={
                "content-type": "image/jpeg",
                "content-length": str(len(MEDIA_CONTENT)),
            },
        )

    client = gateway_media.InternalMediaClient(
        "http://api:8000/v1/internal/ai-media",
        "i" * 32,
        transport=httpx.MockTransport(handler),
    )

    verified = client.fetch(media_reference())

    assert verified.content == MEDIA_CONTENT
    assert verified.sha256 == MEDIA_SHA256
    assert captured["authorization"] == f"Bearer {'i' * 32}"
    assert captured["media_token"] == media_reference().access_token.get_secret_value()


def test_internal_media_client_rejects_invalid_auth_header_value() -> None:
    with pytest.raises(gateway_media.InternalMediaError, match="internal_media_auth_invalid"):
        gateway_media.InternalMediaClient(
            "http://api:8000/v1/internal/ai-media",
            ("i" * 31) + " ",
        )


def test_transfer_mode_combinations_fail_closed() -> None:
    with pytest.raises(ValidationError, match="multipart"):
        adapter("multipart", api_style="openai_chat")
    with pytest.raises(ValidationError, match="files_api"):
        adapter("files_api", api_style="openai_chat")
