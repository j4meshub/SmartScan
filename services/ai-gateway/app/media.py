from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from .network import OutboundMediaReference


class InternalMediaError(RuntimeError):
    """内部媒体读取失败，只向调用方暴露稳定错误码。"""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class VerifiedMediaContent:
    content: bytes
    byte_size: int
    sha256: str
    mime_type: str


def validate_internal_media_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != "/v1/internal/ai-media"
    ):
        raise InternalMediaError("internal_media_url_invalid")
    return value.strip()


class InternalMediaClient:
    def __init__(
        self,
        url: str,
        internal_token: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = validate_internal_media_url(url)
        if (
            len(internal_token) < 32
            or len(internal_token) > 8192
            or any(ord(char) < 33 or ord(char) > 126 for char in internal_token)
        ):
            raise InternalMediaError("internal_media_auth_invalid")
        self._internal_token = internal_token
        self._transport = transport

    def fetch(self, media: OutboundMediaReference) -> VerifiedMediaContent:
        try:
            with (
                httpx.Client(
                    transport=self._transport,
                    timeout=httpx.Timeout(30.0),
                    follow_redirects=False,
                ) as client,
                client.stream(
                    "GET",
                    self._url,
                    headers={
                        "Authorization": f"Bearer {self._internal_token}",
                        "X-SmartScan-AI-Media-Token": media.access_token.get_secret_value(),
                        "Accept": media.mime_type,
                        "Accept-Encoding": "identity",
                    },
                ) as response,
            ):
                if 300 <= response.status_code < 400:
                    raise InternalMediaError("internal_media_redirect_rejected")
                if response.status_code == 404:
                    raise InternalMediaError("internal_media_not_found")
                if response.status_code != 200:
                    raise InternalMediaError(
                        "internal_media_unavailable",
                        retryable=response.status_code >= 500,
                    )
                content_type = response.headers.get("content-type", "").partition(";")[0].strip()
                if content_type != media.mime_type:
                    raise InternalMediaError("internal_media_mime_mismatch")
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    if not content_length.isascii() or not content_length.isdigit():
                        raise InternalMediaError("internal_media_length_invalid")
                    if int(content_length) != media.byte_size:
                        raise InternalMediaError("internal_media_size_mismatch")
                chunks: list[bytes] = []
                size = 0
                digest = hashlib.sha256()
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > media.byte_size:
                        raise InternalMediaError("internal_media_size_mismatch")
                    chunks.append(chunk)
                    digest.update(chunk)
        except InternalMediaError:
            raise
        except httpx.TimeoutException as exc:
            raise InternalMediaError("internal_media_timeout", retryable=True) from exc
        except httpx.TransportError as exc:
            raise InternalMediaError("internal_media_unavailable", retryable=True) from exc
        content = b"".join(chunks)
        if size != media.byte_size:
            raise InternalMediaError("internal_media_size_mismatch")
        if not secrets.compare_digest(digest.hexdigest(), media.sha256):
            raise InternalMediaError("internal_media_sha256_mismatch")
        return VerifiedMediaContent(
            content=content,
            byte_size=size,
            sha256=digest.hexdigest(),
            mime_type=content_type,
        )
