from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, SecretStr, TypeAdapter, field_validator, model_validator

PROVIDER_ID_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?")
ENVIRONMENT_NAME_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,127}")


class ProviderConfigurationError(ValueError):
    """Provider 配置整体不可用。"""


class ProviderDisabledError(RuntimeError):
    """调用了未启用的 Provider。"""


class ProviderCredentialError(RuntimeError):
    """Provider 已启用，但运行环境没有对应凭据。"""


class ProviderKind(StrEnum):
    PROFESSIONAL_OCR = "professional_ocr"
    PUBLIC_VLM = "public_vlm"
    CUSTOM_VLM = "custom_vlm"


class ApiStyle(StrEnum):
    OPENAI_CHAT = "openai_chat"
    OPENAI_RESPONSES = "openai_responses"
    CUSTOM = "custom"


ProviderCapability = Literal[
    "ocr",
    "document_understanding",
    "image_classification",
    "layout_analysis",
]


class ProviderDefinition(BaseModel):
    id: str
    display_name: str = Field(min_length=1, max_length=100)
    kind: ProviderKind
    api_style: ApiStyle
    enabled: bool = False
    base_url: str | None = None
    api_key_env: str | None = None
    model: str | None = Field(default=None, max_length=200)
    supports_images: bool = True
    capabilities: frozenset[ProviderCapability] = Field(default_factory=frozenset)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not PROVIDER_ID_PATTERN.fullmatch(value):
            raise ValueError("provider id must use lowercase letters, digits and hyphens")
        return value

    @field_validator("api_key_env")
    @classmethod
    def validate_api_key_env(cls, value: str | None) -> str | None:
        if value is not None and not ENVIRONMENT_NAME_PATTERN.fullmatch(value):
            raise ValueError("api_key_env must be a safe environment variable name")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("base_url must use HTTPS and include a host")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base_url must not include credentials, query or fragment")
        path = parsed.path.rstrip("/")
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))

    @model_validator(mode="after")
    def validate_enabled_definition(self) -> ProviderDefinition:
        if self.enabled and not all((self.base_url, self.api_key_env, self.model)):
            raise ValueError("enabled provider requires base_url, api_key_env and model")
        if self.capabilities and not self.supports_images:
            raise ValueError("visual capabilities require supports_images=true")
        return self


class ProviderDescriptor(BaseModel):
    id: str
    display_name: str
    kind: ProviderKind
    api_style: ApiStyle
    enabled: bool
    configured: bool
    adapter_type: str
    model: str | None
    supports_images: bool
    capabilities: list[ProviderCapability]
    unavailable_reason: Literal["disabled", "credential_missing"] | None = None


class ProviderAdapter(Protocol):
    definition: ProviderDefinition

    @property
    def adapter_type(self) -> str: ...

    def credential(self) -> SecretStr: ...


class BaseProviderAdapter:
    adapter_type = "base"

    def __init__(
        self,
        definition: ProviderDefinition,
        environment: Mapping[str, str],
    ) -> None:
        self.definition = definition
        self._environment = environment

    @property
    def configured(self) -> bool:
        key_name = self.definition.api_key_env
        return bool(key_name and self._environment.get(key_name, "").strip())

    def credential(self) -> SecretStr:
        if not self.definition.enabled:
            raise ProviderDisabledError("provider_disabled")
        key_name = self.definition.api_key_env
        value = self._environment.get(key_name or "", "").strip()
        if not value:
            raise ProviderCredentialError("provider_credential_missing")
        return SecretStr(value)

    def descriptor(self) -> ProviderDescriptor:
        reason: Literal["disabled", "credential_missing"] | None = None
        if not self.definition.enabled:
            reason = "disabled"
        elif not self.configured:
            reason = "credential_missing"
        return ProviderDescriptor(
            id=self.definition.id,
            display_name=self.definition.display_name,
            kind=self.definition.kind,
            api_style=self.definition.api_style,
            enabled=self.definition.enabled,
            configured=self.configured,
            adapter_type=self.adapter_type,
            model=self.definition.model,
            supports_images=self.definition.supports_images,
            capabilities=sorted(self.definition.capabilities),
            unavailable_reason=reason,
        )


class ProfessionalOcrAdapter(BaseProviderAdapter):
    adapter_type = "professional_ocr"


class OpenAICompatibleAdapter(BaseProviderAdapter):
    adapter_type = "openai_compatible"


class CustomProviderAdapter(BaseProviderAdapter):
    adapter_type = "custom"


def create_adapter(
    definition: ProviderDefinition,
    environment: Mapping[str, str],
) -> BaseProviderAdapter:
    if definition.api_style in {ApiStyle.OPENAI_CHAT, ApiStyle.OPENAI_RESPONSES}:
        return OpenAICompatibleAdapter(definition, environment)
    if definition.kind == ProviderKind.PROFESSIONAL_OCR:
        return ProfessionalOcrAdapter(definition, environment)
    return CustomProviderAdapter(definition, environment)


def default_provider_definitions() -> list[ProviderDefinition]:
    return [
        ProviderDefinition(
            id="professional-ocr",
            display_name="专业 OCR",
            kind=ProviderKind.PROFESSIONAL_OCR,
            api_style=ApiStyle.CUSTOM,
            capabilities=frozenset({"ocr", "layout_analysis"}),
        ),
        ProviderDefinition(
            id="openai-compatible",
            display_name="OpenAI-compatible VLM",
            kind=ProviderKind.PUBLIC_VLM,
            api_style=ApiStyle.OPENAI_RESPONSES,
            capabilities=frozenset(
                {"document_understanding", "image_classification", "layout_analysis"}
            ),
        ),
        ProviderDefinition(
            id="custom-vlm",
            display_name="自定义 VLM",
            kind=ProviderKind.CUSTOM_VLM,
            api_style=ApiStyle.CUSTOM,
            capabilities=frozenset(
                {"document_understanding", "image_classification", "layout_analysis"}
            ),
        ),
    ]


class ProviderRegistry:
    def __init__(
        self,
        definitions: list[ProviderDefinition],
        environment: Mapping[str, str],
    ) -> None:
        duplicate_ids = sorted(
            provider_id
            for provider_id in {item.id for item in definitions}
            if sum(item.id == provider_id for item in definitions) > 1
        )
        if duplicate_ids:
            raise ProviderConfigurationError(f"duplicate provider ids: {', '.join(duplicate_ids)}")
        self._adapters = {
            definition.id: create_adapter(definition, environment) for definition in definitions
        }

    def list_descriptors(self) -> list[ProviderDescriptor]:
        return [self._adapters[key].descriptor() for key in sorted(self._adapters)]

    def get(self, provider_id: str) -> BaseProviderAdapter:
        try:
            return self._adapters[provider_id]
        except KeyError as exc:
            raise KeyError("provider_not_found") from exc

    @property
    def enabled_count(self) -> int:
        return sum(item.definition.enabled for item in self._adapters.values())

    @property
    def ready_count(self) -> int:
        return sum(item.definition.enabled and item.configured for item in self._adapters.values())


def load_provider_registry(
    environment: Mapping[str, str] | None = None,
) -> ProviderRegistry:
    environment = environment if environment is not None else os.environ
    raw = environment.get("SMARTSCAN_AI_PROVIDERS", "").strip()
    if not raw:
        definitions = default_provider_definitions()
    else:
        try:
            decoded = json.loads(raw)
            definitions = TypeAdapter(list[ProviderDefinition]).validate_python(decoded)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise ProviderConfigurationError("SMARTSCAN_AI_PROVIDERS is invalid") from exc
        if not definitions:
            definitions = default_provider_definitions()
    return ProviderRegistry(definitions, environment)
