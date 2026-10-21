from __future__ import annotations

import ipaddress
import json
import os
import re
from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Protocol
from urllib.parse import unquote, urlsplit, urlunsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

PROVIDER_ID_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?")
ENVIRONMENT_NAME_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,127}")
HOST_LABEL_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
URL_PATH_PATTERN = re.compile(r"/[A-Za-z0-9._~/-]*")
MAX_MEDIA_BYTES = 100 * 1024 * 1024
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
CONTROLLED_NETWORKS = tuple(
    ipaddress.ip_network(item)
    for item in (
        "10.0.0.0/8",
        "100.64.0.0/10",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "fc00::/7",
    )
)


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


def canonicalize_network_hostname(value: str) -> str:
    if not value or value.endswith(".") or CONTROL_CHARACTER_PATTERN.search(value):
        raise ValueError("network host must be a canonical DNS name")
    try:
        canonical = value.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("network host must be a canonical DNS name") from exc
    if len(canonical) > 253 or "." not in canonical:
        raise ValueError("network host must be a qualified DNS name")
    if any(not HOST_LABEL_PATTERN.fullmatch(label) for label in canonical.split(".")):
        raise ValueError("network host must be a canonical DNS name")
    try:
        ipaddress.ip_address(canonical)
    except ValueError:
        return canonical
    raise ValueError("network host must not be an IP literal")


def validate_https_base_url(value: str, *, require_trailing_slash: bool) -> str:
    if CONTROL_CHARACTER_PATTERN.search(value) or "\\" in value:
        raise ValueError("network URL contains ambiguous characters")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("network URL must use HTTPS and include a host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("network URL must not include credentials, query or fragment")
    canonical_host = canonicalize_network_hostname(parsed.hostname)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("network URL port is invalid") from exc
    if port not in {None, 443}:
        raise ValueError("network URL must use the default HTTPS port")
    decoded_path = unquote(parsed.path)
    if (
        "%" in parsed.path
        or "//" in parsed.path
        or "\\" in decoded_path
        or not URL_PATH_PATTERN.fullmatch(parsed.path or "/")
        or any(segment in {".", ".."} for segment in decoded_path.split("/"))
    ):
        raise ValueError("network URL path must not contain traversal")
    path = parsed.path
    if require_trailing_slash:
        if not path.endswith("/"):
            raise ValueError("media URL prefix must end with a slash")
        if path == "//":
            raise ValueError("media URL prefix path is invalid")
    else:
        path = path.rstrip("/")
    netloc = canonical_host
    return urlunsplit(("https", netloc, path, "", ""))


class ProviderDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    media_url_prefixes: tuple[str, ...] = Field(default=(), max_length=16)
    allowed_private_cidrs: tuple[str, ...] = Field(default=(), max_length=16)
    max_media_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=MAX_MEDIA_BYTES)
    max_request_bytes: int = Field(default=512 * 1024, ge=16 * 1024, le=MAX_REQUEST_BYTES)
    max_response_bytes: int = Field(default=MAX_RESPONSE_BYTES, ge=1024, le=MAX_RESPONSE_BYTES)
    timeout_seconds: float = Field(default=90.0, ge=1.0, le=300.0)
    max_retries: int = Field(default=1, ge=0, le=1)
    concurrency_limit: int = Field(default=2, ge=1, le=32)
    requests_per_minute: int = Field(default=10, ge=1, le=600)
    daily_cost_limit_usd: Decimal = Field(default=Decimal("10.000000"), gt=0, decimal_places=6)
    max_cost_per_request_usd: Decimal = Field(default=Decimal("0.050000"), gt=0, decimal_places=6)
    circuit_failure_threshold: int = Field(default=3, ge=1, le=20)
    circuit_open_seconds: int = Field(default=60, ge=5, le=3600)

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
        return validate_https_base_url(value, require_trailing_slash=False)

    @field_validator("media_url_prefixes")
    @classmethod
    def validate_media_url_prefixes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(
            validate_https_base_url(value, require_trailing_slash=True) for value in values
        )
        if len(normalized) != len(set(normalized)):
            raise ValueError("media URL prefixes must be unique")
        return normalized

    @field_validator("allowed_private_cidrs")
    @classmethod
    def validate_allowed_private_cidrs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            try:
                network = ipaddress.ip_network(value, strict=True)
            except ValueError as exc:
                raise ValueError("allowed private CIDR must be canonical") from exc
            if not any(
                network.version == controlled.version and network.subnet_of(controlled)
                for controlled in CONTROLLED_NETWORKS
            ):
                raise ValueError("allowed private CIDR must be an explicit controlled network")
            minimum_prefix = 16 if network.version == 4 else 48
            if network.prefixlen < minimum_prefix:
                raise ValueError("allowed private CIDR is broader than the safety limit")
            normalized.append(str(network))
        if len(normalized) != len(set(normalized)):
            raise ValueError("allowed private CIDRs must be unique")
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_enabled_definition(self) -> ProviderDefinition:
        if self.enabled and not all((self.base_url, self.api_key_env, self.model)):
            raise ValueError("enabled provider requires base_url, api_key_env and model")
        if self.capabilities and not self.supports_images:
            raise ValueError("visual capabilities require supports_images=true")
        if self.allowed_private_cidrs and self.kind != ProviderKind.CUSTOM_VLM:
            raise ValueError("private CIDRs are only allowed for custom VLM providers")
        maximum_call_cost = self.max_cost_per_request_usd * (self.max_retries + 1)
        if self.daily_cost_limit_usd < maximum_call_cost:
            raise ValueError("daily cost limit must cover one worst-case call")
        return self

    @property
    def outbound_policy_configured(self) -> bool:
        return bool(self.base_url and self.media_url_prefixes)

    @property
    def daily_cost_limit_microusd(self) -> int:
        return int(self.daily_cost_limit_usd * 1_000_000)

    @property
    def max_cost_per_request_microusd(self) -> int:
        return int(self.max_cost_per_request_usd * 1_000_000)


class ProviderDescriptor(BaseModel):
    id: str
    display_name: str
    kind: ProviderKind
    api_style: ApiStyle
    enabled: bool
    configured: bool
    outbound_policy_configured: bool
    reliability_policy_configured: bool
    outbound_ready: bool
    adapter_type: str
    model: str | None
    supports_images: bool
    capabilities: list[ProviderCapability]
    unavailable_reason: (
        Literal["disabled", "credential_missing", "network_policy_missing"] | None
    ) = None


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
        reason: Literal["disabled", "credential_missing", "network_policy_missing"] | None = None
        if not self.definition.enabled:
            reason = "disabled"
        elif not self.configured:
            reason = "credential_missing"
        elif not self.definition.outbound_policy_configured:
            reason = "network_policy_missing"
        outbound_ready = bool(
            self.definition.enabled
            and self.configured
            and self.definition.outbound_policy_configured
        )
        return ProviderDescriptor(
            id=self.definition.id,
            display_name=self.definition.display_name,
            kind=self.definition.kind,
            api_style=self.definition.api_style,
            enabled=self.definition.enabled,
            configured=self.configured,
            outbound_policy_configured=self.definition.outbound_policy_configured,
            reliability_policy_configured=True,
            outbound_ready=outbound_ready,
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
        return sum(item.descriptor().outbound_ready for item in self._adapters.values())


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
