from __future__ import annotations

import importlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

AI_GATEWAY_ROOT = Path(__file__).parents[1] / "services" / "ai-gateway"
sys.path.insert(0, str(AI_GATEWAY_ROOT))

main = importlib.import_module("app.main")
network = importlib.import_module("app.network")
providers = importlib.import_module("app.providers")
tasks = importlib.import_module("app.tasks")

TASK_ID = "10000000-0000-4000-8000-000000000001"
PAGE_ID = "20000000-0000-4000-8000-000000000002"
ASSET_ID = "30000000-0000-4000-8000-000000000003"
MEDIA_SHA256 = "a" * 64
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


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


def result_payload() -> bytes:
    return json.dumps(
        {
            "schema_version": "1.0",
            "task_id": TASK_ID,
            "task_type": "classify_page",
            "confidence": 0.96,
            "label": "exam",
            "evidence_codes": ["dense_question_layout"],
        }
    ).encode()


def provider_definition(**changes):
    definition = {
        "id": "vision-main",
        "display_name": "视觉主模型",
        "kind": "public_vlm",
        "api_style": "openai_responses",
        "enabled": True,
        "base_url": "https://vision.example/v1",
        "api_key_env": "VISION_API_KEY",
        "model": "vision-1",
        "capabilities": ["document_understanding", "image_classification"],
        "media_url_prefixes": ["https://media.example/ai-media/"],
    }
    definition.update(changes)
    return providers.ProviderDefinition.model_validate(definition)


def provider_adapter(**changes):
    return providers.create_adapter(
        provider_definition(**changes), {"VISION_API_KEY": "never-return-this-secret"}
    )


def media_reference(**changes):
    payload = {
        "prefix_index": 0,
        "access_token": "AbCdEfGhIjKlMnOpQrStUvWxYz012345",
        "byte_size": 1024,
        "sha256": MEDIA_SHA256,
        "mime_type": "image/jpeg",
        "expires_at": NOW + timedelta(minutes=10),
    }
    payload.update(changes)
    return network.OutboundMediaReference.model_validate(payload)


class FakeResolver:
    def __init__(self, mapping: dict[str, tuple[str, ...]]) -> None:
        self.mapping = mapping
        self.calls: list[tuple[str, int]] = []

    def resolve(self, hostname: str, port: int):
        self.calls.append((hostname, port))
        return self.mapping[hostname]


class FakeSender:
    def __init__(self, body: bytes | None = None) -> None:
        self.body = body or result_payload()
        self.requests: list[network.PinnedRequest] = []

    def send(self, request: network.PinnedRequest, *, timeout_seconds: float):
        assert timeout_seconds == 90.0
        self.requests.append(request)
        return network.WireResponse(
            status=200,
            headers={"content-type": "application/json"},
            body=self.body,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"base_url": "https://127.0.0.1/v1"},
        {"base_url": "https://vision.example:8443/v1"},
        {"base_url": "https://vision.example/v1/../admin"},
        {"base_url": "https://vision.example/v1/./responses"},
        {"base_url": "https://vision.example/v1%2f..%2fadmin"},
        {"base_url": "https://vision.example/视觉"},
        {"base_url": "https://vision.example\\@internal.example/v1"},
        {"media_url_prefixes": ["http://media.example/ai-media/"]},
        {"media_url_prefixes": ["https://media.example/ai-media"]},
        {"media_url_prefixes": ["https://user:pass@media.example/ai-media/"]},
        {"media_url_prefixes": ["https://media.example/ai-media/?user=1"]},
        {"allowed_private_cidrs": ["127.0.0.0/8"]},
        {"allowed_private_cidrs": ["10.0.0.1/8"]},
        {"allowed_private_cidrs": ["0.0.0.0/0"]},
        {"max_response_bytes": 65 * 1024},
        {"unknown_network_option": True},
    ],
)
def test_provider_network_configuration_fails_closed(change: dict) -> None:
    with pytest.raises(ValidationError):
        provider_definition(**change)


def test_custom_provider_can_explicitly_allow_canonical_controlled_cidr() -> None:
    definition = provider_definition(
        kind="custom_vlm",
        allowed_private_cidrs=["10.20.0.0/16", "fc00:1234::/48"],
    )

    assert definition.allowed_private_cidrs == ("10.20.0.0/16", "fc00:1234::/48")
    assert definition.outbound_policy_configured is True


def test_descriptor_reports_outbound_readiness_without_exposing_policy() -> None:
    adapter = provider_adapter()
    descriptor = adapter.descriptor()
    serialized = descriptor.model_dump_json()

    assert descriptor.outbound_policy_configured is True
    assert descriptor.outbound_ready is True
    assert descriptor.unavailable_reason is None
    assert "vision.example" not in serialized
    assert "media.example" not in serialized
    assert "VISION_API_KEY" not in serialized


def test_enabled_provider_without_media_allowlist_is_not_outbound_ready() -> None:
    definition = provider_definition(media_url_prefixes=[])
    adapter = providers.create_adapter(definition, {"VISION_API_KEY": "secret"})

    descriptor = adapter.descriptor()
    assert descriptor.configured is True
    assert descriptor.outbound_policy_configured is False
    assert descriptor.outbound_ready is False
    assert descriptor.unavailable_reason == "network_policy_missing"


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("169.254.169.254",),
        ("fd00:ec2::254",),
        ("0.0.0.0",),
        ("224.0.0.1",),
        ("::1",),
        ("fe80::1",),
        ("8.8.8.8", "10.0.0.8"),
        ("not-an-ip",),
        (),
    ],
)
def test_dns_validation_rejects_non_public_or_mixed_answers(addresses: tuple[str, ...]) -> None:
    with pytest.raises(network.NetworkSecurityError):
        network.validate_resolved_addresses(addresses)


def test_dns_validation_accepts_public_and_explicit_controlled_addresses() -> None:
    assert network.validate_resolved_addresses(("2001:4860:4860::8888", "8.8.8.8", "8.8.8.8")) == (
        "8.8.8.8",
        "2001:4860:4860::8888",
    )
    assert network.validate_resolved_addresses(("10.20.3.4",), ("10.20.0.0/16",)) == ("10.20.3.4",)
    with pytest.raises(network.NetworkSecurityError, match="provider_destination_forbidden"):
        network.validate_resolved_addresses(("fd00:ec2::254",), ("fd00:ec2::/48",))


def test_generated_media_token_has_real_entropy_and_secret_representation() -> None:
    first = network.generate_media_access_token()
    second = network.generate_media_access_token()

    assert isinstance(first, SecretStr)
    assert first.get_secret_value() != second.get_secret_value()
    assert len(first.get_secret_value()) >= 32
    assert first.get_secret_value() not in repr(first)
    network.OutboundMediaReference.model_validate(
        {
            "access_token": first,
            "byte_size": 1,
            "sha256": MEDIA_SHA256,
            "mime_type": "image/jpeg",
            "expires_at": NOW + timedelta(minutes=1),
        }
    )


@pytest.mark.parametrize(
    "token",
    ["short", "a" * 21, "a" * 22, "not+url/safe="],
)
def test_media_reference_rejects_weak_or_ambiguous_token(token: str) -> None:
    with pytest.raises(ValidationError):
        media_reference(access_token=token)


def test_secure_transport_pins_provider_and_binds_only_allowed_media_prefix() -> None:
    resolver = FakeResolver(
        {
            "vision.example": ("8.8.8.8",),
            "media.example": ("1.1.1.1",),
        }
    )
    sender = FakeSender()
    transport = network.SecureProviderTransport(resolver, sender, clock=lambda: NOW)
    adapter = provider_adapter()
    task = tasks.validate_task(task_payload())
    plan = tasks.build_provider_request_plan(adapter, task)
    media = media_reference()

    result = transport.execute(adapter, task, plan, media)

    assert result.provider_output == result_payload()
    assert resolver.calls == [("vision.example", 443), ("media.example", 443)]
    assert len(sender.requests) == 1
    request = sender.requests[0]
    assert request.host == "vision.example"
    assert request.pinned_address == "8.8.8.8"
    assert request.target == "/v1/responses"
    assert request.headers["Host"] == "vision.example"
    assert request.headers["Authorization"] == "Bearer never-return-this-secret"
    decoded_body = request.body.decode()
    token = media.access_token.get_secret_value()
    assert f"https://media.example/ai-media/{token}" in decoded_body
    assert "$SMARTSCAN_MEDIA" not in decoded_body
    assert PAGE_ID not in decoded_body
    serialized_evidence = result.evidence.model_dump_json()
    assert result.evidence.destination_pinned is True
    assert result.evidence.redirects_followed == 0
    assert "vision.example" not in serialized_evidence
    assert "media.example" not in serialized_evidence
    assert token not in serialized_evidence
    assert "never-return-this-secret" not in serialized_evidence


@pytest.mark.parametrize(
    ("changes", "error_code"),
    [
        ({"prefix_index": 1}, "media_prefix_not_allowed"),
        ({"prefix_sha256": "0" * 64}, "media_prefix_mismatch"),
        ({"byte_size": 30 * 1024 * 1024}, "media_too_large"),
        ({"sha256": "b" * 64}, "media_sha256_mismatch"),
        ({"mime_type": "image/png"}, "media_mime_type_mismatch"),
        ({"expires_at": NOW + timedelta(seconds=10)}, "media_url_expired_or_too_short"),
        ({"expires_at": NOW + timedelta(hours=25)}, "media_url_lifetime_too_long"),
    ],
)
def test_secure_transport_rejects_invalid_media_before_network(
    changes: dict, error_code: str
) -> None:
    resolver = FakeResolver({})
    sender = FakeSender()
    transport = network.SecureProviderTransport(resolver, sender, clock=lambda: NOW)
    adapter = provider_adapter()
    task = tasks.validate_task(task_payload())
    plan = tasks.build_provider_request_plan(adapter, task)

    with pytest.raises(network.NetworkSecurityError, match=error_code):
        transport.execute(adapter, task, plan, media_reference(**changes))
    assert resolver.calls == []
    assert sender.requests == []


def test_secure_transport_rejects_rebound_dns_before_connecting() -> None:
    resolver = FakeResolver(
        {
            "vision.example": ("8.8.8.8", "10.0.0.8"),
            "media.example": ("1.1.1.1",),
        }
    )
    sender = FakeSender()
    transport = network.SecureProviderTransport(resolver, sender, clock=lambda: NOW)
    adapter = provider_adapter()
    task = tasks.validate_task(task_payload())

    with pytest.raises(network.NetworkSecurityError, match="provider_destination_forbidden"):
        transport.execute(
            adapter,
            task,
            tasks.build_provider_request_plan(adapter, task),
            media_reference(),
        )
    assert sender.requests == []


def test_secure_transport_accepts_explicit_private_custom_network() -> None:
    adapter = provider_adapter(
        kind="custom_vlm",
        api_style="custom",
        base_url="https://vision.internal.example/v1",
        media_url_prefixes=["https://media.internal.example/ai/"],
        allowed_private_cidrs=["10.20.0.0/16"],
    )
    resolver = FakeResolver(
        {
            "vision.internal.example": ("10.20.1.10",),
            "media.internal.example": ("10.20.1.20",),
        }
    )
    sender = FakeSender()
    transport = network.SecureProviderTransport(resolver, sender, clock=lambda: NOW)
    task = tasks.validate_task(task_payload())

    transport.execute(
        adapter,
        task,
        tasks.build_provider_request_plan(adapter, task),
        media_reference(),
    )

    assert sender.requests[0].pinned_address == "10.20.1.10"


def test_same_provider_and_media_host_is_resolved_once_and_pinned() -> None:
    adapter = provider_adapter(media_url_prefixes=["https://vision.example/media/"])
    resolver = FakeResolver({"vision.example": ("8.8.8.8",)})
    sender = FakeSender()
    transport = network.SecureProviderTransport(resolver, sender, clock=lambda: NOW)
    task = tasks.validate_task(task_payload())

    transport.execute(
        adapter,
        task,
        tasks.build_provider_request_plan(adapter, task),
        media_reference(),
    )

    assert resolver.calls == [("vision.example", 443)]
    assert sender.requests[0].pinned_address == "8.8.8.8"


def test_invalid_header_credential_is_rejected_before_dns() -> None:
    definition = provider_definition()
    adapter = providers.create_adapter(definition, {"VISION_API_KEY": "bad secret"})
    resolver = FakeResolver({})
    transport = network.SecureProviderTransport(resolver, FakeSender(), clock=lambda: NOW)
    task = tasks.validate_task(task_payload())

    with pytest.raises(network.NetworkSecurityError, match="provider_credential_header_invalid"):
        transport.execute(
            adapter,
            task,
            tasks.build_provider_request_plan(adapter, task),
            media_reference(),
        )
    assert resolver.calls == []


def test_secure_transport_enforces_request_and_response_size_limits() -> None:
    resolver = FakeResolver({"vision.example": ("8.8.8.8",), "media.example": ("1.1.1.1",)})
    task = tasks.validate_task(task_payload())

    small_request_adapter = provider_adapter(max_request_bytes=16 * 1024)
    plan = tasks.build_provider_request_plan(small_request_adapter, task)
    oversized_plan = plan.model_copy(
        update={"request_body": plan.request_body | {"padding": "x" * 20_000}}
    )
    sender = FakeSender()
    transport = network.SecureProviderTransport(resolver, sender, clock=lambda: NOW)
    with pytest.raises(network.NetworkSecurityError, match="provider_request_too_large"):
        transport.execute(small_request_adapter, task, oversized_plan, media_reference())
    assert sender.requests == []

    oversized_sender = FakeSender(b"x" * 1025)
    response_adapter = provider_adapter(max_response_bytes=1024)
    response_transport = network.SecureProviderTransport(
        resolver, oversized_sender, clock=lambda: NOW
    )
    with pytest.raises(network.NetworkSecurityError, match="provider_response_too_large"):
        response_transport.execute(
            response_adapter,
            task,
            tasks.build_provider_request_plan(response_adapter, task),
            media_reference(),
        )


class FakeHttpResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b'{"ok":true}',
        headers: list[tuple[str, str]] | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self._headers = headers or [("Content-Type", "application/json")]
        values: dict[str, list[str]] = {}
        for key, value in self._headers:
            values.setdefault(key.lower(), []).append(value)
        self.msg = SimpleNamespace(
            get_all=lambda name, failobj=None: values.get(name.lower(), failobj)
        )

    def getheader(self, name: str):
        values = [value for key, value in self._headers if key.lower() == name.lower()]
        return values[-1] if values else None

    def getheaders(self):
        return self._headers

    def read(self, amount: int):
        return self._body[:amount]


class FakeHttpConnection:
    def __init__(self, response: FakeHttpResponse) -> None:
        self.response = response
        self.request_args = None
        self.closed = False

    def request(self, *args, **kwargs):
        self.request_args = (args, kwargs)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def pinned_request(max_response_bytes: int = 1024) -> network.PinnedRequest:
    return network.PinnedRequest(
        host="vision.example",
        port=443,
        pinned_address="8.8.8.8",
        target="/v1/responses",
        headers={"Host": "vision.example", "Content-Type": "application/json"},
        body=b"{}",
        max_response_bytes=max_response_bytes,
    )


def test_stdlib_sender_preserves_hostname_for_tls_and_never_follows_redirects() -> None:
    created = []
    connection = FakeHttpConnection(FakeHttpResponse(status=302))

    def factory(host, address, port, timeout, context):
        created.append((host, address, port, timeout, context))
        return connection

    sender = network.StdlibPinnedRequestSender(factory)
    with pytest.raises(network.NetworkSecurityError, match="provider_redirect_rejected"):
        sender.send(pinned_request(), timeout_seconds=12.0)

    assert created[0][:4] == ("vision.example", "8.8.8.8", 443, 12.0)
    assert created[0][4].check_hostname is True
    assert created[0][4].verify_mode.name == "CERT_REQUIRED"
    assert connection.request_args[0][0] == "POST"
    assert connection.closed is True


@pytest.mark.parametrize(
    ("status", "code", "retryable", "immediate_open"),
    [
        (401, "provider_auth_rejected", False, True),
        (402, "provider_payment_required", False, True),
        (408, "provider_timeout", True, False),
        (429, "provider_rate_limited", True, False),
        (503, "provider_http_5xx", True, False),
    ],
)
def test_stdlib_sender_classifies_provider_failures_for_retry_and_circuit(
    status: int,
    code: str,
    retryable: bool,
    immediate_open: bool,
) -> None:
    connection = FakeHttpConnection(FakeHttpResponse(status=status))
    sender = network.StdlibPinnedRequestSender(lambda *_: connection)

    with pytest.raises(network.NetworkSecurityError, match=code) as raised:
        sender.send(pinned_request(), timeout_seconds=12.0)

    assert raised.value.retryable is retryable
    assert raised.value.immediate_circuit_open is immediate_open
    assert raised.value.counts_toward_circuit is True
    assert raised.value.request_sent is True


@pytest.mark.parametrize(
    ("response", "error_code"),
    [
        (
            FakeHttpResponse(headers=[("Content-Type", "text/plain")]),
            "provider_content_type_rejected",
        ),
        (
            FakeHttpResponse(headers=[("Content-Type", "application/jsonp")]),
            "provider_content_type_rejected",
        ),
        (
            FakeHttpResponse(
                headers=[("Content-Type", "application/json"), ("Content-Encoding", "gzip")]
            ),
            "provider_content_encoding_rejected",
        ),
        (
            FakeHttpResponse(
                headers=[
                    ("Content-Type", "application/json"),
                    ("Content-Length", "10"),
                    ("Content-Length", "11"),
                ]
            ),
            "provider_content_length_invalid",
        ),
        (
            FakeHttpResponse(
                headers=[
                    ("Content-Type", "application/json"),
                    ("Content-Length", "10"),
                    ("Transfer-Encoding", "chunked"),
                ]
            ),
            "provider_content_length_invalid",
        ),
        (
            FakeHttpResponse(
                headers=[("Content-Type", "application/json"), ("Transfer-Encoding", "gzip")]
            ),
            "provider_transfer_encoding_rejected",
        ),
        (
            FakeHttpResponse(
                body=b"x" * 1025,
                headers=[("Content-Type", "application/json")],
            ),
            "provider_response_too_large",
        ),
    ],
)
def test_stdlib_sender_rejects_unsafe_or_oversized_response(
    response: FakeHttpResponse, error_code: str
) -> None:
    connection = FakeHttpConnection(response)
    sender = network.StdlibPinnedRequestSender(lambda *_: connection)

    with pytest.raises(network.NetworkSecurityError, match=error_code):
        sender.send(pinned_request(), timeout_seconds=12.0)
    assert connection.closed is True


def test_pinned_https_connection_connects_to_ip_but_uses_hostname_for_sni(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_socket = SimpleNamespace(setsockopt=lambda *_: None, close=lambda: None)
    calls = []

    class FakeTlsContext:
        verify_mode = __import__("ssl").CERT_REQUIRED
        check_hostname = True

        def wrap_socket(self, sock, server_hostname):
            calls.append((sock, server_hostname))
            return "tls"

    context = FakeTlsContext()
    connection = network.PinnedHTTPSConnection(
        "vision.example", "8.8.8.8", 443, timeout=12.0, context=context
    )
    monkeypatch.setattr(
        connection,
        "_create_connection",
        lambda address, timeout, source: calls.append((address, timeout, source)) or raw_socket,
    )

    connection.connect()

    assert calls[0][0] == ("8.8.8.8", 443)
    assert calls[1] == (raw_socket, "vision.example")
    assert connection.sock == "tls"


def test_execute_endpoint_returns_validated_evidence_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = provider_adapter()
    registry = providers.ProviderRegistry(
        [adapter.definition], {"VISION_API_KEY": "never-return-this-secret"}
    )
    resolver = FakeResolver({"vision.example": ("8.8.8.8",), "media.example": ("1.1.1.1",)})
    sender = FakeSender()
    transport = network.SecureProviderTransport(resolver, sender, clock=lambda: NOW)
    monkeypatch.setattr(main, "get_registry", lambda: registry)
    monkeypatch.setattr(main, "get_network_transport", lambda: transport)
    token = "AbCdEfGhIjKlMnOpQrStUvWxYz012345"

    with TestClient(main.create_app()) as client:
        response = client.post(
            f"/v1/tasks/{adapter.definition.id}/execute",
            json={
                "task": task_payload(),
                "media": {
                    "prefix_index": 0,
                    "access_token": token,
                    "byte_size": 1024,
                    "sha256": MEDIA_SHA256,
                    "mime_type": "image/jpeg",
                    "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["evidence"]["disposition"] == "candidate"
    assert payload["evidence"]["business_mutation_allowed"] is False
    assert payload["network"]["network_ready"] is True
    assert payload["network"]["destination_pinned"] is True
    assert payload["network"]["redirects_followed"] == 0
    assert token not in response.text
    assert "never-return-this-secret" not in response.text
    assert "vision.example" not in response.text
    assert "media.example" not in response.text


def test_gateway_v1_requires_internal_bearer_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "_internal_security", lambda: ("production", "s" * 32))
    with TestClient(main.create_app()) as client:
        missing = client.get("/v1/task-schemas")
        wrong = client.get("/v1/task-schemas", headers={"Authorization": f"Bearer {'x' * 32}"})
        accepted = client.get("/v1/task-schemas", headers={"Authorization": f"Bearer {'s' * 32}"})
        health = client.get("/health")

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert accepted.status_code == 200
    assert health.status_code == 200


def test_execute_endpoint_maps_network_security_failure_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = provider_adapter()
    registry = providers.ProviderRegistry(
        [adapter.definition], {"VISION_API_KEY": "never-return-this-secret"}
    )

    class RejectingTransport:
        def execute(self, *_):
            raise network.NetworkSecurityError("provider_redirect_rejected")

    monkeypatch.setattr(main, "get_registry", lambda: registry)
    monkeypatch.setattr(main, "get_network_transport", lambda: RejectingTransport())
    outbound_media = media_reference().model_dump(mode="json")
    outbound_media["access_token"] = "AbCdEfGhIjKlMnOpQrStUvWxYz012345"

    with TestClient(main.create_app()) as client:
        response = client.post(
            f"/v1/tasks/{adapter.definition.id}/execute",
            json={
                "task": task_payload(),
                "media": outbound_media,
            },
        )

    assert response.status_code == 502
    assert response.json() == {"detail": "provider_redirect_rejected"}
    assert "never-return-this-secret" not in response.text


def test_execute_endpoint_treats_invalid_provider_output_as_upstream_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = provider_adapter()
    registry = providers.ProviderRegistry(
        [adapter.definition], {"VISION_API_KEY": "never-return-this-secret"}
    )
    resolver = FakeResolver({"vision.example": ("8.8.8.8",), "media.example": ("1.1.1.1",)})
    sender = FakeSender(b'{"unexpected":"do not reflect this"}')
    transport = network.SecureProviderTransport(resolver, sender, clock=lambda: NOW)
    monkeypatch.setattr(main, "get_registry", lambda: registry)
    monkeypatch.setattr(main, "get_network_transport", lambda: transport)

    with TestClient(main.create_app()) as client:
        response = client.post(
            f"/v1/tasks/{adapter.definition.id}/execute",
            json={
                "task": task_payload(),
                "media": {
                    "access_token": "AbCdEfGhIjKlMnOpQrStUvWxYz012345",
                    "byte_size": 1024,
                    "sha256": MEDIA_SHA256,
                    "mime_type": "image/jpeg",
                    "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
                },
            },
        )

    assert response.status_code == 502
    assert response.json() == {"detail": "provider_output_rejected"}
    assert "do not reflect this" not in response.text
