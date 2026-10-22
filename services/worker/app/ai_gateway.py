from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from services.api.app.ai_media import IssuedMediaGrant
from services.api.app.config import Settings, get_settings


class AiGatewayError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class AiGatewayResult:
    evidence: dict[str, Any]
    network: dict[str, Any]


class AiGatewayClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport

    def _configuration(self) -> tuple[str, str, str, str]:
        base_url = self._settings.ai_gateway_url.rstrip("/")
        token = self._settings.ai_internal_token.get_secret_value()
        provider_id = self._settings.ai_provider_id
        media_base_url = self._settings.ai_media_base_url
        parsed = urlsplit(base_url)
        media_parsed = urlsplit(media_base_url)
        if (
            not base_url
            or len(token) < 32
            or re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", provider_id) is None
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or media_parsed.scheme != "https"
            or not media_parsed.hostname
            or media_parsed.username
            or media_parsed.password
            or media_parsed.query
            or media_parsed.fragment
            or not media_base_url.endswith("/")
        ):
            raise AiGatewayError("ai_gateway_not_configured", retryable=False)
        return base_url, token, provider_id, media_base_url

    def execute(
        self,
        *,
        enhancement_task_id: str,
        task: dict[str, Any],
        media: IssuedMediaGrant,
    ) -> AiGatewayResult:
        base_url, token, provider_id, media_base_url = self._configuration()
        grant = media.grant
        payload = {
            "enhancement_task_id": enhancement_task_id,
            "task": task,
            "media": {
                "prefix_index": 0,
                "prefix_sha256": hashlib.sha256(media_base_url.encode()).hexdigest(),
                "access_token": media.access_token,
                "byte_size": grant.byte_size,
                "sha256": grant.sha256,
                "mime_type": grant.mime_type,
                "expires_at": grant.expires_at.isoformat(),
            },
        }
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=httpx.Timeout(95.0),
                follow_redirects=False,
            ) as client:
                response = client.post(
                    f"{base_url}/v1/tasks/{quote(provider_id, safe='')}/execute",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise AiGatewayError("ai_gateway_timeout", retryable=True) from exc
        except httpx.TransportError as exc:
            raise AiGatewayError("ai_gateway_unavailable", retryable=True) from exc
        if response.status_code != 200:
            retryable = response.status_code in {429, 502, 503, 504}
            raise AiGatewayError("ai_gateway_request_failed", retryable=retryable)
        try:
            body = response.json()
            evidence = body["evidence"]
            network = body["network"]
        except (ValueError, KeyError, TypeError) as exc:
            raise AiGatewayError("ai_gateway_response_invalid", retryable=False) from exc
        if not isinstance(evidence, dict) or not isinstance(network, dict):
            raise AiGatewayError("ai_gateway_response_invalid", retryable=False)
        return AiGatewayResult(evidence=evidence, network=network)
