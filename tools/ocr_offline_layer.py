from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deploy.ops.smartscan_ocr_layer_contract import (
    CONFIG_DIGEST,
    CONFIG_MEDIA_TYPE,
    CONFIG_SIZE,
    INDEX_DIGEST,
    INDEX_MEDIA_TYPE,
    LAYER_DIGEST,
    LAYER_MEDIA_TYPE,
    LAYER_SIZE,
    MANIFEST_DIGEST,
    MANIFEST_MEDIA_TYPE,
    SOURCE_COMMIT,
    LayerContractError,
    verify_layer_archive,
)

REPOSITORY = "j4meshub/smartscan-ocr-models"
REGISTRY = "ghcr.io"
DOWNLOAD_ROOT = ROOT / ".smartscan-offline-transfer" / "ocr"
FINAL_NAME = "smartscan-ocr-layer-fdae8d61585e.tar.gz"
FINAL_PATH = DOWNLOAD_ROOT / FINAL_NAME
PART_PATH = DOWNLOAD_ROOT / f"{FINAL_NAME}.part"
ALLOWED_REDIRECT_HOSTS = {"ghcr.io", "pkg-containers.githubusercontent.com"}


class DownloadError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _host_allowed(host: str | None) -> bool:
    if host is None:
        return False
    value = host.lower().rstrip(".")
    return value in ALLOWED_REDIRECT_HOSTS or value.endswith(
        ".pkg-containers.githubusercontent.com"
    )


def _open_no_redirect(request: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()), _NoRedirect()
    )
    try:
        return opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        return exc


def _request_follow(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    timeout: float = 60,
):
    started = time.monotonic()
    current = url
    current_headers = dict(headers)
    for _ in range(6):
        parsed = urllib.parse.urlparse(current)
        if parsed.scheme != "https" or not _host_allowed(parsed.hostname):
            raise DownloadError("redirect_host_rejected")
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise DownloadError("request_timeout")
        response = _open_no_redirect(
            urllib.request.Request(current, method=method, headers=current_headers), remaining
        )
        if response.getcode() not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("Location")
        response.close()
        if not location:
            raise DownloadError("redirect_missing")
        next_url = urllib.parse.urljoin(current, location)
        next_host = urllib.parse.urlparse(next_url).hostname
        if not _host_allowed(next_host):
            raise DownloadError("redirect_host_rejected")
        if parsed.hostname != next_host:
            current_headers.pop("Authorization", None)
        current = next_url
    raise DownloadError("redirect_limit_exceeded")


def _anonymous_token() -> str:
    query = urllib.parse.urlencode({"service": "ghcr.io", "scope": f"repository:{REPOSITORY}:pull"})
    try:
        with _request_follow(
            f"https://ghcr.io/token?{query}",
            method="GET",
            headers={"User-Agent": "SmartScan-OCR-002D"},
            timeout=30,
        ) as response:
            if response.getcode() != 200:
                raise DownloadError("token_request_failed")
            token = json.loads(response.read().decode("utf-8"))["token"]
    except (OSError, KeyError, ValueError, urllib.error.URLError) as exc:
        raise DownloadError("token_request_failed") from exc
    if not isinstance(token, str) or not token:
        raise DownloadError("token_invalid")
    return token


def _manifest(digest: str, media_type: str, token: str) -> dict[str, object]:
    url = f"https://{REGISTRY}/v2/{REPOSITORY}/manifests/{digest}"
    response = _request_follow(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": media_type,
            "User-Agent": "SmartScan-OCR-002D",
        },
    )
    try:
        if response.getcode() != 200:
            raise DownloadError("manifest_request_failed")
        if response.headers.get("Docker-Content-Digest") != digest:
            raise DownloadError("manifest_digest_mismatch")
        if response.headers.get_content_type() != media_type:
            raise DownloadError("manifest_media_type_mismatch")
        payload = json.loads(response.read().decode("utf-8"))
    except (ValueError, OSError) as exc:
        raise DownloadError("manifest_invalid") from exc
    finally:
        response.close()
    if not isinstance(payload, dict) or payload.get("mediaType") != media_type:
        raise DownloadError("manifest_contract_invalid")
    return payload


def _verify_config_blob(token: str) -> None:
    response = _request_follow(
        f"https://{REGISTRY}/v2/{REPOSITORY}/blobs/{CONFIG_DIGEST}",
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": CONFIG_MEDIA_TYPE,
            "User-Agent": "SmartScan-OCR-002D",
        },
    )
    try:
        if response.getcode() != 200:
            raise DownloadError("config_request_failed")
        if response.headers.get("Docker-Content-Digest") != CONFIG_DIGEST:
            raise DownloadError("config_digest_mismatch")
        content_length = response.headers.get("Content-Length")
        if content_length is not None and int(content_length) != CONFIG_SIZE:
            raise DownloadError("config_size_mismatch")
        payload_bytes = response.read(CONFIG_SIZE + 1)
        if len(payload_bytes) != CONFIG_SIZE:
            raise DownloadError("config_size_mismatch")
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise DownloadError("config_invalid") from exc
    finally:
        response.close()
    labels = payload.get("config", {}).get("Labels", {}) if isinstance(payload, dict) else {}
    if (
        not isinstance(payload, dict)
        or payload.get("os") != "linux"
        or payload.get("architecture") != "amd64"
        or not isinstance(labels, dict)
        or labels.get("org.opencontainers.image.revision") != SOURCE_COMMIT
    ):
        raise DownloadError("config_contract_invalid")


def verify_registry_contract(token: str) -> None:
    index = _manifest(INDEX_DIGEST, INDEX_MEDIA_TYPE, token)
    descriptors = index.get("manifests")
    if not isinstance(descriptors, list) or not any(
        isinstance(item, dict)
        and item.get("digest") == MANIFEST_DIGEST
        and item.get("mediaType") == MANIFEST_MEDIA_TYPE
        and item.get("platform") == {"architecture": "amd64", "os": "linux"}
        for item in descriptors
    ):
        raise DownloadError("index_platform_descriptor_invalid")
    manifest = _manifest(MANIFEST_DIGEST, MANIFEST_MEDIA_TYPE, token)
    config = manifest.get("config")
    layers = manifest.get("layers")
    if not isinstance(config, dict) or config != {
        "mediaType": CONFIG_MEDIA_TYPE,
        "digest": CONFIG_DIGEST,
        "size": CONFIG_SIZE,
    }:
        raise DownloadError("config_descriptor_invalid")
    if not isinstance(layers, list) or layers != [
        {"mediaType": LAYER_MEDIA_TYPE, "digest": LAYER_DIGEST, "size": LAYER_SIZE}
    ]:
        raise DownloadError("layer_descriptor_invalid")
    _verify_config_blob(token)


def _download_response(token: str, offset: int):
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "SmartScan-OCR-002D",
        "Range": f"bytes={offset}-{LAYER_SIZE - 1}",
    }
    return _request_follow(
        f"https://{REGISTRY}/v2/{REPOSITORY}/blobs/{LAYER_DIGEST}",
        method="GET",
        headers=headers,
        timeout=3600,
    )


def download_fixed_layer() -> dict[str, object]:
    if DOWNLOAD_ROOT.parent.is_symlink() or DOWNLOAD_ROOT.is_symlink():
        raise DownloadError("download_directory_invalid")
    if DOWNLOAD_ROOT.exists() and not DOWNLOAD_ROOT.is_dir():
        raise DownloadError("download_directory_invalid")
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    if FINAL_PATH.exists():
        result = verify_layer_archive(FINAL_PATH)
        return {**result, "path": str(FINAL_PATH), "existing": True}
    if PART_PATH.is_symlink() or (PART_PATH.exists() and not PART_PATH.is_file()):
        raise DownloadError("part_path_invalid")
    offset = PART_PATH.stat().st_size if PART_PATH.exists() else 0
    if offset > LAYER_SIZE:
        raise DownloadError("part_size_invalid")
    token = _anonymous_token()
    verify_registry_contract(token)
    if offset < LAYER_SIZE:
        response = _download_response(token, offset)
        try:
            status = response.getcode()
            if offset and status != 206:
                raise DownloadError("range_resume_rejected")
            if not offset and status not in {200, 206}:
                raise DownloadError("layer_request_failed")
            if status == 206:
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith(f"bytes {offset}-"):
                    raise DownloadError("content_range_invalid")
            started = time.monotonic()
            written = offset
            with PART_PATH.open("ab" if offset else "xb") as stream:
                while written < LAYER_SIZE:
                    chunk = response.read(min(1024 * 1024, LAYER_SIZE - written))
                    if not chunk:
                        break
                    stream.write(chunk)
                    written += len(chunk)
                    elapsed = max(time.monotonic() - started, 0.001)
                    print(
                        f"progress_bytes={written} speed_bytes_per_second={int((written - offset) / elapsed)}",
                        flush=True,
                    )
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            response.close()
    if PART_PATH.stat().st_size != LAYER_SIZE:
        raise DownloadError("download_truncated")
    result = verify_layer_archive(PART_PATH)
    os.replace(PART_PATH, FINAL_PATH)
    return {**result, "path": str(FINAL_PATH), "existing": False}


def verify_fixed_layer() -> dict[str, object]:
    result = verify_layer_archive(FINAL_PATH)
    return {**result, "path": str(FINAL_PATH)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SmartScan固定OCR模型Layer离线传输工具")
    parser.add_argument("command", choices=("download", "verify"))
    args = parser.parse_args(argv)
    try:
        result = download_fixed_layer() if args.command == "download" else verify_fixed_layer()
    except Exception as exc:  # 只输出稳定错误码，禁止泄漏令牌或签名URL
        reason = (
            str(exc)
            if isinstance(exc, (DownloadError, LayerContractError))
            else "verification_failed"
        )
        print(f"status=failed reason={reason}", file=sys.stderr)
        return 1
    print(
        "status=passed "
        f"bytes={result['compressed_bytes']} sha256={result['sha256']} path={result['path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
