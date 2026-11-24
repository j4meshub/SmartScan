#!/usr/bin/env python3
"""SmartScan UAT 固定镜像的可审计离线交付工具。

普通用户命令只读取仓库内已审核发布清单，不接受 URL、Tag、digest、路径、
服务器或服务名参数。CI 使用 ``ci-build`` 生成独立 Docker image archive；Windows 使用
``download`` 从成功的 GitHub Actions 运行取得归档，随后离线 ``verify``。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

ROOT = Path(__file__).resolve().parents[1]
RELEASE_MANIFEST = ROOT / "deploy" / "releases" / "uat-2026-11-24.json"
DOWNLOAD_ROOT = ROOT / ".smartscan-offline-transfer" / "images"
WORKFLOW_FILE = "uat-offline-images.yml"
GITHUB_REPOSITORY = "j4meshub/SmartScan"
ALLOWED_REGISTRY_PREFIX = "ghcr.io/j4meshub/smartscan-"
ALLOWED_PLATFORM = "linux/amd64"
SERVER_ALIAS = "smartscan-server"
SERVER_UPLOAD_ROOT = PurePosixPath("/home/szhzx/smartscan-uat-offline-images")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
LOCAL_TAG = re.compile(r"^smartscan-uat-[a-z0-9-]+:sha256-[0-9a-f]{12}$")
ARCHIVE_NAME = re.compile(r"^smartscan-[a-z0-9-]+-[0-9a-f]{12}-linux-amd64\.docker\.tar$")
INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
MANIFEST_MEDIA_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
ACCEPT = ", ".join(sorted(INDEX_MEDIA_TYPES | MANIFEST_MEDIA_TYPES))
REDIRECT_SUFFIXES = (
    ".githubusercontent.com",
    ".github.com",
    ".azureedge.net",
    ".blob.core.windows.net",
    ".actions.githubusercontent.com",
)


class OfflineImageError(RuntimeError):
    """离线镜像交付契约失败。"""


@dataclass(frozen=True)
class ImageSpec:
    service: str
    deploy_key: str
    runtime_key: str
    source: str
    repository: str
    source_digest: str
    local_tag: str
    archive_name: str
    expected_revision: str | None


@dataclass(frozen=True)
class ReleaseSpec:
    release_id: str
    platform: str
    accepted_at: str
    accepted_by: str
    images: tuple[ImageSpec, ...]
    raw_sha256: str


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise OfflineImageError(reason)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_json(raw: bytes, reason: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfflineImageError(reason) from exc
    _require(isinstance(value, dict), reason)
    return value


def _safe_json_list(raw: bytes, reason: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfflineImageError(reason) from exc
    _require(isinstance(value, list) and all(isinstance(item, dict) for item in value), reason)
    return value


def load_release(path: Path = RELEASE_MANIFEST) -> ReleaseSpec:
    raw = path.read_bytes()
    document = _safe_json(raw, "release_manifest_invalid")
    _require(document.get("schema_version") == "1.0", "release_schema_invalid")
    _require(document.get("platform") == ALLOWED_PLATFORM, "release_platform_invalid")
    _require(
        document.get("registry_prefix") == ALLOWED_REGISTRY_PREFIX,
        "release_registry_prefix_invalid",
    )
    _require(document.get("server_alias") == SERVER_ALIAS, "release_server_alias_invalid")
    _require(
        document.get("server_upload_root") == str(SERVER_UPLOAD_ROOT),
        "release_server_upload_root_invalid",
    )
    images = document.get("images")
    _require(isinstance(images, list) and len(images) == 6, "release_image_count_invalid")
    result: list[ImageSpec] = []
    seen: set[str] = set()
    for item in images:
        _require(isinstance(item, dict), "release_image_invalid")
        source = str(item.get("source", ""))
        _require(source.startswith(ALLOWED_REGISTRY_PREFIX), "release_source_not_allowed")
        _require("@sha256:" in source and ":latest" not in source, "release_digest_required")
        repository, digest = source.rsplit("@sha256:", 1)
        _require(SHA256.fullmatch(digest) is not None, "release_digest_invalid")
        service = str(item.get("service", ""))
        _require(re.fullmatch(r"[a-z0-9-]+", service) is not None, "release_service_invalid")
        _require(service not in seen, "release_service_duplicate")
        seen.add(service)
        local_tag = str(item.get("local_tag", ""))
        archive_name = str(item.get("archive_name", ""))
        _require(LOCAL_TAG.fullmatch(local_tag) is not None, "release_local_tag_invalid")
        _require(ARCHIVE_NAME.fullmatch(archive_name) is not None, "release_archive_name_invalid")
        _require(digest[:12] in local_tag and digest[:12] in archive_name, "release_name_unbound")
        revision = item.get("expected_revision")
        if revision is not None:
            _require(GIT_SHA.fullmatch(str(revision)) is not None, "release_revision_invalid")
        result.append(
            ImageSpec(
                service=service,
                deploy_key=str(item.get("deploy_key", "")),
                runtime_key=str(item.get("runtime_key", "")),
                source=source,
                repository=repository,
                source_digest=f"sha256:{digest}",
                local_tag=local_tag,
                archive_name=archive_name,
                expected_revision=str(revision) if revision else None,
            )
        )
    return ReleaseSpec(
        release_id=str(document.get("release_id", "")),
        platform=ALLOWED_PLATFORM,
        accepted_at=str(document.get("accepted_at", "")),
        accepted_by=str(document.get("accepted_by", "")),
        images=tuple(result),
        raw_sha256=hashlib.sha256(raw).hexdigest(),
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _allowed_redirect(url: str, *, github: bool) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.casefold()
    if github:
        return host == "api.github.com" or any(host.endswith(item) for item in REDIRECT_SUFFIXES)
    return host == "ghcr.io" or any(host.endswith(item) for item in REDIRECT_SUFFIXES)


def _open_follow(request: urllib.request.Request, *, github: bool, timeout: int = 120):
    opener = urllib.request.build_opener(_NoRedirect)
    current = request
    for _ in range(6):
        try:
            return opener.open(current, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                raise
            location = exc.headers.get("Location", "")
            _require(_allowed_redirect(location, github=github), "redirect_host_rejected")
            headers = {key: value for key, value in current.header_items() if key.lower() != "host"}
            if (
                urllib.parse.urlparse(location).hostname
                != urllib.parse.urlparse(current.full_url).hostname
            ):
                headers.pop("Authorization", None)
            current = urllib.request.Request(
                location,
                headers=headers,
                method=current.get_method(),
            )
    raise OfflineImageError("redirect_limit_exceeded")


class RegistryClient:
    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}

    def token(self, repository: str) -> str:
        if repository in self._tokens:
            return self._tokens[repository]
        name = repository.removeprefix("ghcr.io/")
        query = urllib.parse.urlencode({"service": "ghcr.io", "scope": f"repository:{name}:pull"})
        request = urllib.request.Request(f"https://ghcr.io/token?{query}")
        with _open_follow(request, github=False, timeout=60) as response:
            document = _safe_json(response.read(), "registry_token_response_invalid")
        token = str(document.get("token", ""))
        _require(bool(token), "registry_token_missing")
        self._tokens[repository] = token
        return token

    def request(
        self,
        repository: str,
        path: str,
        *,
        accept: str | None = None,
        range_start: int | None = None,
    ):
        name = repository.removeprefix("ghcr.io/")
        headers = {"Authorization": f"Bearer {self.token(repository)}"}
        if accept:
            headers["Accept"] = accept
        if range_start is not None:
            headers["Range"] = f"bytes={range_start}-"
        request = urllib.request.Request(
            f"https://ghcr.io/v2/{name}/{path}", headers=headers, method="GET"
        )
        return _open_follow(request, github=False, timeout=180)


def _descriptor_digest(response, raw: bytes) -> str:
    calculated = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    header = response.headers.get("Docker-Content-Digest")
    if header:
        _require(header == calculated, "registry_digest_header_mismatch")
    return calculated


def _fetch_manifest(
    client: RegistryClient, spec: ImageSpec
) -> tuple[dict[str, Any], bytes, str, bytes, str]:
    with client.request(
        spec.repository, f"manifests/{spec.source_digest}", accept=ACCEPT
    ) as response:
        raw = response.read()
        source_raw = raw
        digest = _descriptor_digest(response, raw)
        media_type = response.headers.get("Content-Type", "").split(";", 1)[0]
    _require(digest == spec.source_digest, "source_manifest_digest_mismatch")
    document = _safe_json(raw, "source_manifest_invalid")
    media_type = str(document.get("mediaType") or media_type)
    if media_type in INDEX_MEDIA_TYPES:
        descriptors = [
            item
            for item in document.get("manifests", [])
            if isinstance(item, dict)
            and item.get("platform", {}).get("os") == "linux"
            and item.get("platform", {}).get("architecture") == "amd64"
            and item.get("platform", {}).get("variant") in {None, ""}
        ]
        _require(len(descriptors) == 1, "linux_amd64_descriptor_invalid")
        platform_digest = str(descriptors[0].get("digest", ""))
        with client.request(
            spec.repository, f"manifests/{platform_digest}", accept=ACCEPT
        ) as response:
            raw = response.read()
            actual = _descriptor_digest(response, raw)
        _require(actual == platform_digest, "platform_manifest_digest_mismatch")
        document = _safe_json(raw, "platform_manifest_invalid")
        return document, raw, platform_digest, source_raw, media_type
    _require(media_type in MANIFEST_MEDIA_TYPES, "manifest_media_type_invalid")
    return document, raw, spec.source_digest, source_raw, media_type


def _download_blob(
    client: RegistryClient, repository: str, digest: str, size: int, destination: Path
) -> None:
    _require(
        digest.startswith("sha256:") and SHA256.fullmatch(digest[7:]) is not None,
        "blob_digest_invalid",
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    _require(not destination.is_symlink(), "blob_destination_symlink")
    if destination.exists():
        _require(destination.is_file(), "blob_destination_type_invalid")
        if destination.stat().st_size == size and _sha256_file(destination) == digest[7:]:
            return
        raise OfflineImageError("existing_blob_invalid")
    part = destination.with_suffix(destination.suffix + ".part")
    _require(not part.is_symlink(), "blob_part_symlink")
    offset = part.stat().st_size if part.exists() else 0
    _require(offset <= size, "blob_part_too_large")
    with client.request(repository, f"blobs/{digest}", range_start=offset or None) as response:
        status = response.getcode()
        if offset:
            _require(status == 206, "blob_resume_not_supported")
        else:
            _require(status in {200, 206}, "blob_download_status_invalid")
        mode = "ab" if offset else "wb"
        with part.open(mode) as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
    _require(part.stat().st_size == size, "blob_download_truncated")
    _require(_sha256_file(part) == digest[7:], "blob_download_digest_mismatch")
    os.replace(part, destination)


def _tar_bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _add_bytes(bundle: tarfile.TarFile, name: str, value: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(value)
    info.mode = 0o444
    info.mtime = 0
    bundle.addfile(info, io.BytesIO(value))


def _add_file(bundle: tarfile.TarFile, name: str, source: Path) -> None:
    info = tarfile.TarInfo(name)
    info.size = source.stat().st_size
    info.mode = 0o444
    info.mtime = 0
    with source.open("rb") as stream:
        bundle.addfile(info, stream)


def _build_one(client: RegistryClient, release: ReleaseSpec, spec: ImageSpec) -> dict[str, Any]:
    root = DOWNLOAD_ROOT / release.release_id / spec.service
    blobs = root / "blobs" / "sha256"
    manifest, manifest_raw, platform_digest, source_raw, source_media_type = _fetch_manifest(
        client, spec
    )
    _require(
        str(manifest.get("mediaType", "")) in MANIFEST_MEDIA_TYPES, "platform_media_type_invalid"
    )
    config = manifest.get("config")
    layers = manifest.get("layers")
    _require(
        isinstance(config, dict) and isinstance(layers, list) and layers,
        "manifest_descriptors_invalid",
    )
    config_digest, config_size = str(config.get("digest", "")), int(config.get("size", -1))
    config_path = blobs / config_digest.removeprefix("sha256:")
    _download_blob(client, spec.repository, config_digest, config_size, config_path)
    config_document = _safe_json(config_path.read_bytes(), "config_blob_invalid")
    _require(config_document.get("os") == "linux", "config_os_invalid")
    _require(config_document.get("architecture") == "amd64", "config_architecture_invalid")
    labels = config_document.get("config", {}).get("Labels") or {}
    revision = str(labels.get("org.opencontainers.image.revision", ""))
    if spec.expected_revision:
        _require(revision == spec.expected_revision, "config_revision_mismatch")
    layer_records: list[dict[str, Any]] = []
    for layer in layers:
        _require(isinstance(layer, dict), "layer_descriptor_invalid")
        digest, size = str(layer.get("digest", "")), int(layer.get("size", -1))
        path = blobs / digest.removeprefix("sha256:")
        _download_blob(client, spec.repository, digest, size, path)
        layer_records.append(
            {"digest": digest, "size": size, "media_type": str(layer.get("mediaType", ""))}
        )
    manifest_actual = f"sha256:{hashlib.sha256(manifest_raw).hexdigest()}"
    _require(manifest_actual == platform_digest, "platform_manifest_hash_invalid")
    manifest_path = blobs / platform_digest.removeprefix("sha256:")
    manifest_path.write_bytes(manifest_raw)
    source_path = blobs / spec.source_digest.removeprefix("sha256:")
    if source_path != manifest_path:
        source_path.write_bytes(source_raw)
    diff_ids = config_document.get("rootfs", {}).get("diff_ids")
    _require(
        isinstance(diff_ids, list)
        and len(diff_ids) == len(layer_records)
        and all(
            isinstance(value, str) and value.startswith("sha256:") and SHA256.fullmatch(value[7:])
            for value in diff_ids
        ),
        "config_diff_ids_invalid",
    )
    for record, diff_id in zip(layer_records, diff_ids, strict=True):
        record["diff_id"] = diff_id
    config_name = f"{config_digest[7:]}.json"
    layer_names = [f"layers/{item['digest'][7:]}.tar.gz" for item in layer_records]
    docker_manifest = [{"Config": config_name, "RepoTags": [spec.local_tag], "Layers": layer_names}]
    archive = DOWNLOAD_ROOT / release.release_id / spec.archive_name
    temporary = archive.with_suffix(archive.suffix + ".part")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(temporary, "w") as bundle:
        _add_bytes(bundle, "manifest.json", _tar_bytes(docker_manifest))
        _add_file(bundle, config_name, config_path)
        _add_file(bundle, "smartscan-evidence/source.json", source_path)
        _add_file(bundle, "smartscan-evidence/platform-manifest.json", manifest_path)
        for layer, name in zip(layer_records, layer_names, strict=True):
            _add_file(bundle, name, blobs / layer["digest"][7:])
    os.replace(temporary, archive)
    return {
        "service": spec.service,
        "archive_format": "docker-image-archive-v1",
        "source": spec.source,
        "source_object_media_type": source_media_type,
        "source_object_size": len(source_raw),
        "platform_manifest": platform_digest,
        "config_digest": config_digest,
        "layers": layer_records,
        "revision": revision,
        "version": str(labels.get("org.opencontainers.image.version", "")),
        "config_user": str(config_document.get("config", {}).get("User", "")),
        "image_id": config_digest,
        "local_tag": spec.local_tag,
        "archive_name": spec.archive_name,
        "archive_size": archive.stat().st_size,
        "archive_sha256": _sha256_file(archive),
    }


def build_archives() -> dict[str, Any]:
    _require(os.environ.get("GITHUB_ACTIONS") == "true", "ci_build_only")
    release = load_release()
    client = RegistryClient()
    images = [_build_one(client, release, spec) for spec in release.images]
    mapping = {
        "schema_version": "1.0",
        "release_id": release.release_id,
        "release_manifest_sha256": release.raw_sha256,
        "platform": release.platform,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "github_sha": os.environ.get("GITHUB_SHA", ""),
        "images": images,
        "secrets_included": False,
    }
    output = DOWNLOAD_ROOT / release.release_id / "release-map.json"
    output.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.copyfile(RELEASE_MANIFEST, output.parent / "release-manifest.json")
    return {"status": "passed", "release_id": release.release_id, "images": images}


def _safe_tar_members(bundle: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for item in bundle.getmembers():
        path = PurePosixPath(item.name)
        _require(not path.is_absolute() and ".." not in path.parts, "archive_path_invalid")
        _require(item.isfile(), "archive_special_member_rejected")
        _require(item.name not in members, "archive_duplicate_member")
        members[item.name] = item
    return members


def _verify_archive(path: Path, spec: ImageSpec, record: dict[str, Any]) -> None:
    _require(path.is_file() and not path.is_symlink(), "archive_file_invalid")
    _require(path.stat().st_size == int(record.get("archive_size", -1)), "archive_size_mismatch")
    _require(_sha256_file(path) == record.get("archive_sha256"), "archive_digest_mismatch")
    _require(record.get("archive_format") == "docker-image-archive-v1", "archive_format_invalid")
    with tarfile.open(path, "r") as bundle:
        members = _safe_tar_members(bundle)
        config_digest = str(record.get("config_digest", ""))
        config_name = f"{config_digest.removeprefix('sha256:')}.json"
        recorded_layers = record.get("layers")
        _require(
            isinstance(recorded_layers, list) and recorded_layers, "archive_layer_records_invalid"
        )
        layer_names = [
            f"layers/{str(item.get('digest', ''))[7:]}.tar.gz" for item in recorded_layers
        ]
        expected = {
            "manifest.json",
            config_name,
            "smartscan-evidence/source.json",
            "smartscan-evidence/platform-manifest.json",
            *layer_names,
        }
        _require(set(members) == expected, "archive_member_set_invalid")
        docker_manifest = _safe_json_list(
            bundle.extractfile(members["manifest.json"]).read(), "archive_docker_manifest_invalid"
        )
        _require(
            len(docker_manifest) == 1
            and docker_manifest[0].get("Config") == config_name
            and docker_manifest[0].get("RepoTags") == [spec.local_tag]
            and docker_manifest[0].get("Layers") == layer_names,
            "archive_docker_manifest_unbound",
        )
        source_digest = spec.source_digest
        source_stream = bundle.extractfile(members["smartscan-evidence/source.json"])
        _require(source_stream is not None, "archive_source_object_missing")
        source_raw = source_stream.read()
        _require(
            hashlib.sha256(source_raw).hexdigest() == source_digest[7:],
            "archive_source_object_digest_mismatch",
        )
        _require(
            len(source_raw) == int(record.get("source_object_size", -1)),
            "archive_source_object_size_mismatch",
        )
        source_document = _safe_json(source_raw, "archive_source_object_invalid")
        source_media_type = str(source_document.get("mediaType", ""))
        _require(
            source_media_type == record.get("source_object_media_type"),
            "archive_source_media_type_mismatch",
        )
        if source_digest != record.get("platform_manifest"):
            _require(source_media_type in INDEX_MEDIA_TYPES, "archive_source_index_required")
            platform_descriptors = [
                item
                for item in source_document.get("manifests", [])
                if isinstance(item, dict)
                and item.get("digest") == record.get("platform_manifest")
                and item.get("platform", {}).get("os") == "linux"
                and item.get("platform", {}).get("architecture") == "amd64"
                and item.get("platform", {}).get("variant") in {None, ""}
            ]
            _require(len(platform_descriptors) == 1, "archive_source_platform_unbound")
        else:
            _require(source_media_type in MANIFEST_MEDIA_TYPES, "archive_source_manifest_invalid")
        platform_stream = bundle.extractfile(members["smartscan-evidence/platform-manifest.json"])
        _require(platform_stream is not None, "archive_platform_manifest_missing")
        platform_raw = platform_stream.read()
        _require(
            hashlib.sha256(platform_raw).hexdigest()
            == str(record.get("platform_manifest", ""))[7:],
            "archive_platform_manifest_digest_mismatch",
        )
        platform_document = _safe_json(platform_raw, "archive_platform_manifest_invalid")
        _require(
            platform_document.get("config", {}).get("digest") == record.get("config_digest"),
            "archive_config_unbound",
        )
        platform_layers = platform_document.get("layers")
        _require(isinstance(platform_layers, list), "archive_layers_invalid")
        _require(
            [
                (item.get("digest"), item.get("size"), item.get("mediaType"))
                for item in platform_layers
            ]
            == [
                (item.get("digest"), item.get("size"), item.get("media_type"))
                for item in recorded_layers
            ],
            "archive_layers_unbound",
        )
        config_stream = bundle.extractfile(members[config_name])
        _require(config_stream is not None, "archive_config_missing")
        config_raw = config_stream.read()
        _require(
            hashlib.sha256(config_raw).hexdigest() == config_digest[7:],
            "archive_config_digest_mismatch",
        )
        config_document = _safe_json(config_raw, "archive_config_invalid")
        _require(
            config_document.get("os") == "linux" and config_document.get("architecture") == "amd64",
            "archive_config_platform_invalid",
        )
        diff_ids = config_document.get("rootfs", {}).get("diff_ids")
        _require(
            diff_ids == [item.get("diff_id") for item in recorded_layers],
            "archive_diff_ids_unbound",
        )
        for item, name in zip(recorded_layers, layer_names, strict=True):
            stream = bundle.extractfile(members[name])
            _require(stream is not None, "archive_layer_missing")
            _require(members[name].size == int(item.get("size", -1)), "archive_layer_size_mismatch")
            _require(
                hashlib.sha256(stream.read()).hexdigest() == str(item.get("digest"))[7:],
                "archive_layer_digest_mismatch",
            )


def verify_archives() -> dict[str, Any]:
    release = load_release()
    root = DOWNLOAD_ROOT / release.release_id
    map_path = root / "release-map.json"
    _require(map_path.is_file() and not map_path.is_symlink(), "release_map_missing")
    mapping = _safe_json(map_path.read_bytes(), "release_map_invalid")
    _require(mapping.get("release_id") == release.release_id, "release_map_id_mismatch")
    _require(
        mapping.get("release_manifest_sha256") == release.raw_sha256,
        "release_map_manifest_mismatch",
    )
    records = mapping.get("images")
    _require(isinstance(records, list) and len(records) == 6, "release_map_images_invalid")
    by_service = {str(item.get("service")): item for item in records if isinstance(item, dict)}
    _require(
        set(by_service) == {item.service for item in release.images}, "release_map_services_invalid"
    )
    total = 0
    for spec in release.images:
        record = by_service[spec.service]
        _require(record.get("source") == spec.source, "release_map_source_mismatch")
        _require(record.get("local_tag") == spec.local_tag, "release_map_tag_mismatch")
        _require(
            record.get("image_id") == record.get("config_digest"), "release_map_image_id_invalid"
        )
        _verify_archive(root / spec.archive_name, spec, record)
        total += int(record["archive_size"])
    return {
        "status": "passed",
        "release_id": release.release_id,
        "archive_count": 6,
        "total_bytes": total,
        "secrets_included": False,
    }


def _git_credential() -> str:
    process = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        capture_output=True,
        check=True,
    )
    values = dict(line.split("=", 1) for line in process.stdout.splitlines() if "=" in line)
    token = values.get("password", "")
    _require(bool(token), "github_credential_missing")
    return token


def _github_json(path: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SmartScan-offline-images",
        },
    )
    with _open_follow(request, github=True, timeout=90) as response:
        return _safe_json(response.read(), "github_response_invalid")


def _download_github_file(url: str, token: str, target: Path) -> None:
    part = target.with_suffix(target.suffix + ".part")
    offset = part.stat().st_size if part.exists() else 0
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "SmartScan-offline-images",
    }
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    with _open_follow(request, github=True, timeout=180) as response:
        if offset:
            _require(response.getcode() == 206, "artifact_resume_not_supported")
        with part.open("ab" if offset else "wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
    os.replace(part, target)


def download_artifacts() -> dict[str, Any]:
    release = load_release()
    token = _git_credential()
    runs = _github_json(
        f"/repos/{GITHUB_REPOSITORY}/actions/workflows/{WORKFLOW_FILE}/runs?branch=main&status=success&per_page=20",
        token,
    ).get("workflow_runs", [])
    _require(isinstance(runs, list) and runs, "offline_workflow_run_missing")
    run = next((item for item in runs if item.get("event") == "workflow_dispatch"), None)
    _require(isinstance(run, dict), "accepted_offline_workflow_run_missing")
    run_id = int(run["id"])
    artifacts = _github_json(
        f"/repos/{GITHUB_REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100", token
    ).get("artifacts", [])
    by_name = {item.get("name"): item for item in artifacts if isinstance(item, dict)}
    expected = [f"smartscan-uat-offline-{item.service}" for item in release.images]
    expected.append("smartscan-uat-offline-release-map")
    _require(all(name in by_name for name in expected), "offline_artifacts_incomplete")
    root = DOWNLOAD_ROOT / release.release_id
    root.mkdir(parents=True, exist_ok=True)
    for name in expected:
        item = by_name[name]
        _require(item.get("expired") is False, "offline_artifact_expired")
        zip_path = root / f".{name}.zip"
        _download_github_file(str(item["archive_download_url"]), token, zip_path)
        with zipfile.ZipFile(zip_path) as archive:
            files = [value for value in archive.infolist() if not value.is_dir()]
            _require(
                files and all(".." not in PurePosixPath(value.filename).parts for value in files),
                "artifact_zip_invalid",
            )
            for value in files:
                name_only = Path(value.filename).name
                _require(
                    name_only in {"release-map.json", "release-manifest.json"}
                    or ARCHIVE_NAME.fullmatch(name_only),
                    "artifact_file_unexpected",
                )
                destination = root / name_only
                temporary = destination.with_suffix(destination.suffix + ".part")
                with archive.open(value) as source, temporary.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                os.replace(temporary, destination)
        zip_path.unlink()
    result = verify_archives()
    result["github_run_id"] = run_id
    return result


def _run_checked(arguments: list[str], *, input_stream: BinaryIO | None = None) -> str:
    process = subprocess.run(
        arguments,
        stdin=input_stream,
        capture_output=True,
        text=input_stream is None,
        check=False,
    )
    if process.returncode != 0:
        raise OfflineImageError(f"command_failed:{arguments[0]}")
    output = process.stdout if isinstance(process.stdout, str) else process.stdout.decode()
    return output.strip()


def upload_archives() -> dict[str, Any]:
    release = load_release()
    verify_archives()
    identity = _run_checked(
        [
            "ssh",
            SERVER_ALIAS,
            "sh",
            "-c",
            'printf \'%s:%s:%s\' "$(hostname -s)" "$(whoami)" "$(id -u)"',
        ]
    )
    _require(identity == "ctiecaiserver:szhzx:1000", "server_identity_mismatch")
    _run_checked(
        [
            "ssh",
            SERVER_ALIAS,
            "sh",
            "-c",
            f'umask 077; test ! -L {SERVER_UPLOAD_ROOT}; mkdir -p {SERVER_UPLOAD_ROOT}; chmod 700 {SERVER_UPLOAD_ROOT}; test "$(stat -c %U:%a {SERVER_UPLOAD_ROOT})" = szhzx:700',
        ]
    )
    root = DOWNLOAD_ROOT / release.release_id
    names = [item.archive_name for item in release.images] + [
        "release-map.json",
        "release-manifest.json",
    ]
    for name in names:
        path = root / name
        size, digest = path.stat().st_size, _sha256_file(path)
        remote_part = SERVER_UPLOAD_ROOT / f"{name}.part"
        remote_final = SERVER_UPLOAD_ROOT / name
        state = _run_checked(
            [
                "ssh",
                SERVER_ALIAS,
                "sh",
                "-c",
                f"test ! -L {remote_part} && test ! -L {remote_final}; if test -f {remote_final}; then stat -c 'final:%s' {remote_final}; elif test -f {remote_part}; then stat -c 'part:%s' {remote_part}; else echo missing:0; fi",
            ]
        )
        kind, current_text = state.split(":", 1)
        current = int(current_text)
        if kind == "final":
            remote_hash = _run_checked(
                ["ssh", SERVER_ALIAS, "sha256sum", str(remote_final)]
            ).split()[0]
            _require(current == size and remote_hash == digest, "remote_archive_existing_invalid")
            continue
        _require(current <= size, "remote_part_too_large")
        with path.open("rb") as stream:
            stream.seek(current)
            _run_checked(
                [
                    "ssh",
                    SERVER_ALIAS,
                    "python3",
                    "-c",
                    "import os,sys; p=sys.argv[1]; n=int(sys.argv[2]); f=open(p,'ab' if n else 'xb'); f.write(sys.stdin.buffer.read()); f.flush(); os.fsync(f.fileno()); f.close(); os.chmod(p,0o600)",
                    str(remote_part),
                    str(current),
                ],
                input_stream=stream,
            )
        remote_hash = _run_checked(["ssh", SERVER_ALIAS, "sha256sum", str(remote_part)]).split()[0]
        _require(remote_hash == digest, "remote_part_digest_mismatch")
        _run_checked(
            [
                "ssh",
                SERVER_ALIAS,
                "sh",
                "-c",
                f"test ! -e {remote_final}; mv {remote_part} {remote_final}; chmod 600 {remote_final}",
            ]
        )
    return {"status": "passed", "uploaded_files": len(names), "secrets_included": False}


def plan() -> dict[str, Any]:
    release = load_release()
    return {
        "status": "passed",
        "release_id": release.release_id,
        "platform": release.platform,
        "release_manifest_sha256": release.raw_sha256,
        "images": [
            {
                "service": item.service,
                "source": item.source,
                "local_tag": item.local_tag,
                "archive_name": item.archive_name,
            }
            for item in release.images
        ],
        "secrets_included": False,
    }


def status() -> dict[str, Any]:
    release = load_release()
    root = DOWNLOAD_ROOT / release.release_id
    files = {}
    for item in release.images:
        archive = root / item.archive_name
        files[item.service] = (
            "complete"
            if archive.is_file() and not archive.is_symlink()
            else "partial"
            if archive.with_suffix(archive.suffix + ".part").exists()
            else "missing"
        )
    return {
        "status": "passed",
        "release_id": release.release_id,
        "archives": files,
        "secrets_included": False,
    }


def _print(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    arguments = list(sys.argv[1:] if argv is None else argv)
    allowed = {"plan", "download", "verify", "upload", "status", "ci-build"}
    if len(arguments) != 1 or arguments[0] not in allowed:
        print(
            "用法：smartscan_offline_images.py {plan|download|verify|upload|status}",
            file=sys.stderr,
        )
        return 64
    try:
        command = arguments[0]
        if command == "plan":
            result = plan()
        elif command == "download":
            result = download_artifacts()
        elif command == "verify":
            result = verify_archives()
        elif command == "upload":
            result = upload_archives()
        elif command == "ci-build":
            result = build_archives()
        else:
            result = status()
    except (OfflineImageError, OSError, urllib.error.URLError, subprocess.SubprocessError) as exc:
        _print({"status": "failed", "reason": str(exc), "secrets_included": False})
        return 1
    _print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
