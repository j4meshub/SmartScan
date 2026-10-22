from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

AI_GATEWAY_ROOT = Path(__file__).parents[1] / "services" / "ai-gateway"
sys.path.insert(0, str(AI_GATEWAY_ROOT))

providers = importlib.import_module("app.providers")
main = importlib.import_module("app.main")


def configured_environment(*, enabled: bool = True, credential: bool = True) -> dict[str, str]:
    environment = {
        "SMARTSCAN_AI_PROVIDERS": (
            "["
            '{"id":"vision-main","display_name":"视觉主模型",'
            '"kind":"public_vlm","api_style":"openai_responses",'
            f'"enabled":{str(enabled).lower()},'
            '"base_url":"https://vision.example/v1/",'
            '"api_key_env":"VISION_API_KEY","model":"vision-1",'
            '"media_url_prefixes":["https://media.example/ai/"],'
            '"capabilities":["document_understanding","image_classification"]}'
            "]"
        )
    }
    if credential:
        environment["VISION_API_KEY"] = "never-return-this-secret"
    return environment


def test_default_registry_registers_three_disabled_adapter_types() -> None:
    registry = providers.load_provider_registry({})
    explicit_empty_registry = providers.load_provider_registry({"SMARTSCAN_AI_PROVIDERS": "[]"})

    descriptors = registry.list_descriptors()
    assert registry.enabled_count == 0
    assert registry.ready_count == 0
    assert {item.adapter_type for item in descriptors} == {
        "professional_ocr",
        "openai_compatible",
        "custom",
    }
    assert all(item.unavailable_reason == "disabled" for item in descriptors)
    assert explicit_empty_registry.enabled_count == 0
    assert len(explicit_empty_registry.list_descriptors()) == 3


def test_openai_compatible_provider_is_ready_without_exposing_secret() -> None:
    secret = "never-return-this-secret"
    registry = providers.load_provider_registry(configured_environment())
    adapter = registry.get("vision-main")

    descriptor = adapter.descriptor()
    assert descriptor.configured is True
    assert descriptor.unavailable_reason is None
    assert descriptor.adapter_type == "openai_compatible"
    assert descriptor.model_dump()["model"] == "vision-1"
    assert secret not in repr(adapter.credential())
    assert secret not in descriptor.model_dump_json()


def test_enabled_provider_without_credential_is_not_ready() -> None:
    registry = providers.load_provider_registry(configured_environment(credential=False))
    adapter = registry.get("vision-main")

    assert registry.enabled_count == 1
    assert registry.ready_count == 0
    assert adapter.descriptor().unavailable_reason == "credential_missing"
    with pytest.raises(providers.ProviderCredentialError, match="provider_credential_missing"):
        adapter.credential()


def test_disabled_provider_cannot_resolve_credential() -> None:
    registry = providers.load_provider_registry(configured_environment(enabled=False))

    with pytest.raises(providers.ProviderDisabledError, match="provider_disabled"):
        registry.get("vision-main").credential()


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        (
            '[{"id":"duplicate","display_name":"A","kind":"custom_vlm",'
            '"api_style":"custom"},{"id":"duplicate","display_name":"B",'
            '"kind":"custom_vlm","api_style":"custom"}]'
        ),
        (
            '[{"id":"enabled-incomplete","display_name":"A","kind":"custom_vlm",'
            '"api_style":"custom","enabled":true}]'
        ),
    ],
)
def test_invalid_registry_configuration_fails_closed(raw: str) -> None:
    with pytest.raises(providers.ProviderConfigurationError):
        providers.load_provider_registry({"SMARTSCAN_AI_PROVIDERS": raw})


@pytest.mark.parametrize(
    "changes",
    [
        {"base_url": "http://vision.example/v1"},
        {"base_url": "https://user:password@vision.example/v1"},
        {"base_url": "https://vision.example/v1?token=secret"},
        {"api_key_env": "unsafe-key-name"},
        {"id": "Unsafe_ID"},
    ],
)
def test_provider_definition_rejects_unsafe_configuration(changes: dict[str, str]) -> None:
    definition = {
        "id": "safe-id",
        "display_name": "安全配置",
        "kind": "custom_vlm",
        "api_style": "custom",
        "enabled": True,
        "base_url": "https://vision.example/v1",
        "api_key_env": "VISION_API_KEY",
        "model": "vision-1",
    }
    definition.update(changes)

    with pytest.raises(ValidationError):
        providers.ProviderDefinition.model_validate(definition)


def test_registry_api_returns_only_sanitized_status(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = providers.load_provider_registry(configured_environment())
    monkeypatch.setattr(main, "get_registry", lambda: registry)

    with TestClient(main.create_app()) as client:
        health = client.get("/health")
        response = client.get("/v1/providers")
        missing = client.get("/v1/providers/not-found")

    assert health.json() == {
        "status": "ok",
        "execution_mode": "provider",
        "enabled": True,
        "provider_count": 1,
        "enabled_count": 1,
        "ready_count": 1,
    }
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["configured"] is True
    assert "api_key_env" not in payload["items"][0]
    assert "never-return-this-secret" not in response.text
    assert missing.status_code == 404


def test_check_endpoint_only_validates_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "get_registry", lambda: providers.load_provider_registry({}))
    payload = {
        "id": "check-only",
        "display_name": "仅校验",
        "kind": "professional_ocr",
        "api_style": "custom",
        "enabled": False,
        "base_url": "https://ocr.example/v1",
        "api_key_env": "OCR_API_KEY",
        "model": "ocr-1",
        "capabilities": ["ocr"],
    }

    with TestClient(main.create_app()) as client:
        response = client.post("/v1/providers/check", json=payload)

    assert response.status_code == 200
    assert response.json()["note"] == "configuration_only_no_network_request"
    assert response.json()["provider"]["configured"] is False
