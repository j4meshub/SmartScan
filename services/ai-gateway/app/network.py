from __future__ import annotations

import base64
import hashlib
import http.client
import ipaddress
import json
import re
import secrets
import socket
import ssl
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .providers import BaseProviderAdapter
from .tasks import ProviderRequestPlan, StructuredTask

MEDIA_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{22,128}")
MIN_MEDIA_TOKEN_BYTES = 16
MAX_MEDIA_URL_LIFETIME = timedelta(hours=24)
MIN_MEDIA_URL_REMAINING = timedelta(seconds=30)
PROVIDER_TIMEOUT_SECONDS = 90.0
PERMANENTLY_FORBIDDEN_ADDRESSES = frozenset(
    {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254")}
)


class NetworkSecurityError(RuntimeError):
    """出站请求失败或没有通过网络安全门禁，仅携带稳定错误码。"""

    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        immediate_circuit_open: bool = False,
        counts_toward_circuit: bool = False,
        request_sent: bool = False,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.immediate_circuit_open = immediate_circuit_open
        self.counts_toward_circuit = counts_toward_circuit or immediate_circuit_open
        self.request_sent = request_sent


class OutboundMediaReference(BaseModel):
    """由可信媒体服务签发、但不会在响应或日志中回显的资源引用。"""

    model_config = ConfigDict(extra="forbid")

    prefix_index: int = Field(default=0, ge=0, le=15)
    prefix_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    access_token: SecretStr
    byte_size: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    expires_at: datetime

    @field_validator("access_token", mode="before")
    @classmethod
    def validate_access_token(cls, value: object) -> object:
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw, str) or not MEDIA_TOKEN_PATTERN.fullmatch(raw):
            raise ValueError("media access token must be URL-safe and at least 128 bits")
        try:
            decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except ValueError as exc:
            raise ValueError("media access token must be URL-safe and at least 128 bits") from exc
        canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
        if len(decoded) < MIN_MEDIA_TOKEN_BYTES or canonical != raw:
            raise ValueError("media access token must be URL-safe and at least 128 bits")
        return raw

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("media expiry must include a timezone")
        return value.astimezone(UTC)


class NetworkSecurityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network_ready: Literal[True] = True
    provider_id: str
    request_body_bytes: int = Field(ge=1)
    response_body_bytes: int = Field(ge=1)
    redirects_followed: Literal[0] = 0
    tls_hostname_verified: Literal[True] = True
    destination_pinned: Literal[True] = True


@dataclass(frozen=True)
class PinnedRequest:
    host: str
    port: int
    pinned_address: str
    target: str
    headers: Mapping[str, str]
    body: bytes
    max_response_bytes: int


@dataclass(frozen=True)
class WireResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class SecureNetworkResult:
    provider_output: bytes
    evidence: NetworkSecurityEvidence


class HostResolver(Protocol):
    def resolve(self, hostname: str, port: int) -> Sequence[str]: ...


class PinnedRequestSender(Protocol):
    def send(self, request: PinnedRequest, *, timeout_seconds: float) -> WireResponse: ...


class SystemHostResolver:
    def resolve(self, hostname: str, port: int) -> Sequence[str]:
        try:
            records = socket.getaddrinfo(
                hostname,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except OSError as exc:
            raise NetworkSecurityError(
                "provider_dns_resolution_failed",
                retryable=True,
                counts_toward_circuit=True,
            ) from exc
        return tuple(record[4][0] for record in records)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """连接固定 IP，同时继续用原始域名执行 SNI 与证书校验。"""

    def __init__(
        self,
        hostname: str,
        pinned_address: str,
        port: int,
        *,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(hostname, port=port, timeout=timeout, context=context)
        self._pinned_address = pinned_address

    def connect(self) -> None:
        if self._tunnel_host:
            raise NetworkSecurityError("provider_proxy_tunnel_forbidden")
        raw_socket = self._create_connection(
            (self._pinned_address, self.port),
            self.timeout,
            self.source_address,
        )
        try:
            raw_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        try:
            self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
        except Exception:
            raw_socket.close()
            raise


ConnectionFactory = Callable[[str, str, int, float, ssl.SSLContext], http.client.HTTPSConnection]


def _default_connection_factory(
    hostname: str,
    pinned_address: str,
    port: int,
    timeout_seconds: float,
    context: ssl.SSLContext,
) -> http.client.HTTPSConnection:
    return PinnedHTTPSConnection(
        hostname,
        pinned_address,
        port,
        timeout=timeout_seconds,
        context=context,
    )


class StdlibPinnedRequestSender:
    def __init__(self, connection_factory: ConnectionFactory = _default_connection_factory) -> None:
        self._connection_factory = connection_factory

    def send(self, request: PinnedRequest, *, timeout_seconds: float) -> WireResponse:
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        context.set_alpn_protocols(["http/1.1"])
        connection = self._connection_factory(
            request.host,
            request.pinned_address,
            request.port,
            timeout_seconds,
            context,
        )
        try:
            connection.request(
                "POST",
                request.target,
                body=request.body,
                headers=dict(request.headers),
            )
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise NetworkSecurityError("provider_redirect_rejected")
            if response.status in {401, 403}:
                raise NetworkSecurityError("provider_auth_rejected", immediate_circuit_open=True)
            if response.status == 402:
                raise NetworkSecurityError("provider_payment_required", immediate_circuit_open=True)
            if response.status == 408:
                raise NetworkSecurityError(
                    "provider_timeout", retryable=True, counts_toward_circuit=True
                )
            if response.status == 429:
                raise NetworkSecurityError(
                    "provider_rate_limited", retryable=True, counts_toward_circuit=True
                )
            if response.status >= 500:
                raise NetworkSecurityError(
                    "provider_http_5xx", retryable=True, counts_toward_circuit=True
                )
            if not 200 <= response.status < 300:
                raise NetworkSecurityError("provider_http_error")
            content_encoding = (response.getheader("Content-Encoding") or "identity").lower()
            if content_encoding != "identity":
                raise NetworkSecurityError("provider_content_encoding_rejected")
            content_type = (response.getheader("Content-Type") or "").lower()
            media_type = content_type.partition(";")[0].strip()
            if media_type != "application/json":
                raise NetworkSecurityError("provider_content_type_rejected")
            raw_content_lengths = response.msg.get_all("Content-Length", failobj=[]) or []
            content_lengths = [
                item.strip()
                for value in raw_content_lengths
                for item in value.split(",")
                if item.strip()
            ]
            transfer_encoding = (response.getheader("Transfer-Encoding") or "").lower().strip()
            if transfer_encoding not in {"", "chunked"}:
                raise NetworkSecurityError("provider_transfer_encoding_rejected")
            if transfer_encoding and content_lengths:
                raise NetworkSecurityError("provider_content_length_invalid")
            if len(set(content_lengths)) > 1:
                raise NetworkSecurityError("provider_content_length_invalid")
            if content_lengths:
                try:
                    if not all(item.isascii() and item.isdigit() for item in content_lengths):
                        raise ValueError
                    declared_length = int(content_lengths[0])
                except ValueError as exc:
                    raise NetworkSecurityError("provider_content_length_invalid") from exc
                if declared_length < 0 or declared_length > request.max_response_bytes:
                    raise NetworkSecurityError("provider_response_too_large")
            body = response.read(request.max_response_bytes + 1)
            if len(body) > request.max_response_bytes:
                raise NetworkSecurityError("provider_response_too_large")
            if not body:
                raise NetworkSecurityError("provider_response_empty")
            headers = {key.lower(): value for key, value in response.getheaders()}
            return WireResponse(status=response.status, headers=headers, body=body)
        except NetworkSecurityError as exc:
            if exc.request_sent:
                raise
            raise NetworkSecurityError(
                exc.code,
                retryable=exc.retryable,
                immediate_circuit_open=exc.immediate_circuit_open,
                counts_toward_circuit=exc.counts_toward_circuit,
                request_sent=True,
            ) from exc
        except TimeoutError as exc:
            raise NetworkSecurityError(
                "provider_timeout",
                retryable=True,
                counts_toward_circuit=True,
                request_sent=True,
            ) from exc
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise NetworkSecurityError(
                "provider_transport_failed",
                retryable=True,
                counts_toward_circuit=True,
                request_sent=True,
            ) from exc
        finally:
            connection.close()


def generate_media_access_token() -> SecretStr:
    return SecretStr(secrets.token_urlsafe(24))


def _controlled_networks(
    values: Sequence[str],
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(ipaddress.ip_network(value, strict=True) for value in values)


def validate_resolved_addresses(
    addresses: Sequence[str],
    allowed_private_cidrs: Sequence[str] = (),
) -> tuple[str, ...]:
    if not addresses:
        raise NetworkSecurityError("provider_dns_no_addresses")
    controlled = _controlled_networks(allowed_private_cidrs)
    normalized: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for raw in addresses:
        try:
            address = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise NetworkSecurityError("provider_dns_invalid_address") from exc
        explicitly_controlled = any(
            address.version == network.version and address in network for network in controlled
        )
        always_forbidden = (
            address in PERMANENTLY_FORBIDDEN_ADDRESSES
            or address.is_unspecified
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
        )
        if always_forbidden or not (address.is_global or explicitly_controlled):
            raise NetworkSecurityError("provider_destination_forbidden")
        normalized.add(address)
    return tuple(
        str(item) for item in sorted(normalized, key=lambda item: (item.version, int(item)))
    )


def _replace_media_placeholder(value: object, media_url: str) -> tuple[object, int]:
    if value == "$SMARTSCAN_MEDIA":
        return media_url, 1
    if isinstance(value, dict):
        replaced: dict[object, object] = {}
        count = 0
        for key, item in value.items():
            new_value, item_count = _replace_media_placeholder(item, media_url)
            replaced[key] = new_value
            count += item_count
        return replaced, count
    if isinstance(value, list):
        replaced_items = []
        count = 0
        for item in value:
            new_value, item_count = _replace_media_placeholder(item, media_url)
            replaced_items.append(new_value)
            count += item_count
        return replaced_items, count
    return value, 0


class SecureProviderTransport:
    def __init__(
        self,
        resolver: HostResolver | None = None,
        sender: PinnedRequestSender | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        timeout_seconds: float = PROVIDER_TIMEOUT_SECONDS,
    ) -> None:
        self._resolver = resolver or SystemHostResolver()
        self._sender = sender or StdlibPinnedRequestSender()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timeout_seconds = timeout_seconds

    def execute(
        self,
        adapter: BaseProviderAdapter,
        task: StructuredTask,
        plan: ProviderRequestPlan,
        media: OutboundMediaReference,
        timeout_seconds: float | None = None,
    ) -> SecureNetworkResult:
        definition = adapter.definition
        if not definition.outbound_policy_configured or not definition.base_url:
            raise NetworkSecurityError("provider_network_policy_missing")
        if media.prefix_index >= len(definition.media_url_prefixes):
            raise NetworkSecurityError("media_prefix_not_allowed")
        if media.byte_size > definition.max_media_bytes:
            raise NetworkSecurityError("media_too_large")
        if media.sha256 != task.context.media.sha256:
            raise NetworkSecurityError("media_sha256_mismatch")
        if media.mime_type != task.context.media.mime_type:
            raise NetworkSecurityError("media_mime_type_mismatch")

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise NetworkSecurityError("network_clock_invalid")
        now = now.astimezone(UTC)
        remaining = media.expires_at - now
        if remaining < MIN_MEDIA_URL_REMAINING:
            raise NetworkSecurityError("media_url_expired_or_too_short")
        if remaining > MAX_MEDIA_URL_LIFETIME:
            raise NetworkSecurityError("media_url_lifetime_too_long")

        prefix = definition.media_url_prefixes[media.prefix_index]
        if media.prefix_sha256 is not None and not secrets.compare_digest(
            media.prefix_sha256,
            hashlib.sha256(prefix.encode()).hexdigest(),
        ):
            raise NetworkSecurityError("media_prefix_mismatch")
        media_url = prefix + quote(media.access_token.get_secret_value(), safe="")
        provider_url = urlsplit(definition.base_url)
        media_url_parts = urlsplit(prefix)
        provider_host = provider_url.hostname or ""
        media_host = media_url_parts.hostname or ""
        port = provider_url.port or 443
        controlled_cidrs = definition.allowed_private_cidrs

        credential = adapter.credential().get_secret_value()
        if (
            not credential
            or len(credential) > 8192
            or any(ord(char) < 33 or ord(char) > 126 for char in credential)
        ):
            raise NetworkSecurityError("provider_credential_header_invalid")

        provider_addresses = validate_resolved_addresses(
            self._resolver.resolve(provider_host, port), controlled_cidrs
        )
        if media_host == provider_host:
            media_addresses = provider_addresses
        else:
            media_addresses = validate_resolved_addresses(
                self._resolver.resolve(media_host, 443), controlled_cidrs
            )
        if not media_addresses:
            raise NetworkSecurityError("media_dns_no_addresses")

        request_body, replacements = _replace_media_placeholder(plan.request_body, media_url)
        if replacements != 1:
            raise NetworkSecurityError("media_placeholder_count_invalid")
        body = json.dumps(
            request_body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > definition.max_request_bytes:
            raise NetworkSecurityError("provider_request_too_large")

        target = f"{provider_url.path.rstrip('/')}{plan.endpoint_path}"
        if not target.startswith("/") or "?" in target or "#" in target:
            raise NetworkSecurityError("provider_request_target_invalid")
        pinned_address = provider_addresses[0]
        response = self._sender.send(
            PinnedRequest(
                host=provider_host,
                port=port,
                pinned_address=pinned_address,
                target=target,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "Authorization": f"Bearer {credential}",
                    "Connection": "close",
                    "Content-Type": "application/json; charset=utf-8",
                    "Host": provider_host,
                    "User-Agent": "SmartScan-AI-Gateway/0.3",
                },
                body=body,
                max_response_bytes=definition.max_response_bytes,
            ),
            timeout_seconds=timeout_seconds or self._timeout_seconds,
        )
        if not 200 <= response.status < 300:
            raise NetworkSecurityError("provider_http_error", request_sent=True)
        if len(response.body) > definition.max_response_bytes:
            raise NetworkSecurityError("provider_response_too_large")
        return SecureNetworkResult(
            provider_output=response.body,
            evidence=NetworkSecurityEvidence(
                provider_id=definition.id,
                request_body_bytes=len(body),
                response_body_bytes=len(response.body),
            ),
        )
