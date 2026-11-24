from __future__ import annotations

import hashlib
import io
import json
import tarfile
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from tools import smartscan_offline_images as offline


class Response:
    def __init__(self, value: bytes, status: int = 200):
        self.value = io.BytesIO(value)
        self.status = status
        self.headers: dict[str, str] = {}

    def read(self, size: int = -1) -> bytes:
        return self.value.read(size)

    def getcode(self) -> int:
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class BlobClient:
    def __init__(self, value: bytes):
        self.value = value
        self.offsets: list[int | None] = []

    def request(self, _repository: str, _path: str, *, range_start=None, **_kwargs):
        self.offsets.append(range_start)
        offset = range_start or 0
        return Response(self.value[offset:], 206 if offset else 200)


def _release_document() -> dict:
    return json.loads(offline.RELEASE_MANIFEST.read_text(encoding="utf-8"))


def test_release_manifest_fixes_six_digests_platform_and_local_tags() -> None:
    release = offline.load_release()

    assert release.platform == "linux/amd64"
    assert len(release.images) == 6
    assert {item.service for item in release.images} == {
        "postgres",
        "api",
        "worker",
        "ai-gateway",
        "web",
        "ops",
    }
    for item in release.images:
        assert item.source.startswith("ghcr.io/j4meshub/smartscan-")
        assert "@sha256:" in item.source
        assert ":latest" not in item.source
        assert item.source_digest[7:][:12] in item.local_tag
        assert item.source_digest[7:][:12] in item.archive_name


def test_release_rejects_tag_wrong_platform_and_path_injection(tmp_path: Path) -> None:
    document = _release_document()
    document["platform"] = "linux/arm64"
    path = tmp_path / "release.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(offline.OfflineImageError, match="release_platform_invalid"):
        offline.load_release(path)

    document = _release_document()
    document["images"][0]["source"] = "ghcr.io/j4meshub/smartscan-postgres:latest"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(offline.OfflineImageError, match="release_digest_required"):
        offline.load_release(path)

    document = _release_document()
    document["images"][0]["archive_name"] = "../escape.docker.tar"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(offline.OfflineImageError, match="release_archive_name_invalid"):
        offline.load_release(path)


def test_blob_download_resumes_part_and_checks_length_and_digest(tmp_path: Path) -> None:
    value = b"fixed-layer-content"
    digest = f"sha256:{hashlib.sha256(value).hexdigest()}"
    destination = tmp_path / digest[7:]
    part = destination.with_suffix(destination.suffix + ".part")
    part.write_bytes(value[:5])
    client = BlobClient(value)

    offline._download_blob(
        client, "ghcr.io/j4meshub/smartscan-api", digest, len(value), destination
    )

    assert client.offsets == [5]
    assert destination.read_bytes() == value
    assert not part.exists()


def test_blob_download_keeps_truncated_part_and_rejects_tamper(tmp_path: Path) -> None:
    value = b"short"
    expected = b"longer-than-short"
    digest = f"sha256:{hashlib.sha256(expected).hexdigest()}"
    destination = tmp_path / digest[7:]
    client = BlobClient(value)

    with pytest.raises(offline.OfflineImageError, match="blob_download_truncated"):
        offline._download_blob(
            client, "ghcr.io/j4meshub/smartscan-api", digest, len(expected), destination
        )
    assert destination.with_suffix(destination.suffix + ".part").read_bytes() == value

    destination.with_suffix(destination.suffix + ".part").write_bytes(b"x" * len(expected))
    with pytest.raises(offline.OfflineImageError, match="blob_download_digest_mismatch"):
        offline._download_blob(
            client, "ghcr.io/j4meshub/smartscan-api", digest, len(expected), destination
        )


def _write_archive(path: Path, spec, blobs: dict[str, bytes]) -> tuple[object, dict]:
    layer_digest = f"sha256:{hashlib.sha256(blobs['layer']).hexdigest()}"
    diff_id = f"sha256:{hashlib.sha256(b'uncompressed-layer').hexdigest()}"
    config = json.dumps(
        {
            "architecture": "amd64",
            "os": "linux",
            "config": {"User": "10001:10001"},
            "rootfs": {"type": "layers", "diff_ids": [diff_id]},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    config_digest = f"sha256:{hashlib.sha256(config).hexdigest()}"
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {
            "mediaType": "application/vnd.oci.image.config.v1+json",
            "digest": config_digest,
            "size": len(blobs["config"]),
        },
        "layers": [
            {
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "digest": layer_digest,
                "size": len(blobs["layer"]),
            }
        ],
    }
    manifest_raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest_digest = f"sha256:{hashlib.sha256(manifest_raw).hexdigest()}"
    index = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {
                "mediaType": manifest["mediaType"],
                "digest": manifest_digest,
                "size": len(manifest_raw),
                "platform": {"os": "linux", "architecture": "amd64"},
                "annotations": {"org.opencontainers.image.ref.name": spec.local_tag},
            }
        ],
    }
    source_raw = json.dumps(index, sort_keys=True, separators=(",", ":")).encode()
    source_digest = f"sha256:{hashlib.sha256(source_raw).hexdigest()}"
    spec = replace(
        spec,
        source=f"{spec.repository}@{source_digest}",
        source_digest=source_digest,
    )
    config_name = f"{config_digest[7:]}.json"
    layer_name = f"layers/{layer_digest[7:]}.tar.gz"
    docker_manifest = [
        {"Config": config_name, "RepoTags": [spec.local_tag], "Layers": [layer_name]}
    ]
    with tarfile.open(path, "w") as bundle:
        offline._add_bytes(bundle, "manifest.json", offline._tar_bytes(docker_manifest))
        offline._add_bytes(bundle, config_name, config)
        offline._add_bytes(bundle, "smartscan-evidence/source.json", source_raw)
        offline._add_bytes(bundle, "smartscan-evidence/platform-manifest.json", manifest_raw)
        offline._add_bytes(bundle, layer_name, blobs["layer"])
    record = {
        "service": spec.service,
        "archive_format": "docker-image-archive-v1",
        "source": spec.source,
        "source_object_media_type": "application/vnd.oci.image.index.v1+json",
        "source_object_size": len(source_raw),
        "platform_manifest": manifest_digest,
        "config_digest": config_digest,
        "layers": [
            {
                "digest": layer_digest,
                "size": len(blobs["layer"]),
                "media_type": "application/vnd.oci.image.layer.v1.tar+gzip",
                "diff_id": diff_id,
            }
        ],
        "image_id": config_digest,
        "local_tag": spec.local_tag,
        "archive_name": spec.archive_name,
        "archive_size": path.stat().st_size,
        "archive_sha256": offline._sha256_file(path),
    }
    return spec, record


def test_verify_detects_missing_layer_extra_member_and_tamper(tmp_path: Path) -> None:
    spec = offline.load_release().images[0]
    archive = tmp_path / spec.archive_name
    spec, record = _write_archive(archive, spec, {"config": b"{}", "layer": b"layer"})
    offline._verify_archive(archive, spec, record)

    tampered = bytearray(archive.read_bytes())
    tampered[-1] ^= 1
    archive.write_bytes(tampered)
    with pytest.raises(offline.OfflineImageError, match="archive_digest_mismatch"):
        offline._verify_archive(archive, spec, record)


def _rewrite_archive(
    source: Path, target: Path, *, omit: str | None = None, extra: tarfile.TarInfo | None = None
) -> None:
    with tarfile.open(source, "r") as original, tarfile.open(target, "w") as output:
        for member in original.getmembers():
            if member.name == omit:
                continue
            stream = original.extractfile(member)
            output.addfile(member, stream)
        if extra is not None:
            output.addfile(extra, io.BytesIO(b"x") if extra.isfile() else None)


def test_archive_rejects_missing_extra_traversal_and_symbolic_members(tmp_path: Path) -> None:
    original_spec = offline.load_release().images[0]
    original = tmp_path / "original.tar"
    spec, record = _write_archive(original, original_spec, {"config": b"{}", "layer": b"layer"})
    layer_name = f"layers/{record['layers'][0]['digest'][7:]}.tar.gz"

    missing = tmp_path / "missing.tar"
    _rewrite_archive(original, missing, omit=layer_name)
    missing_record = {**record, "archive_size": missing.stat().st_size}
    missing_record["archive_sha256"] = offline._sha256_file(missing)
    with pytest.raises(offline.OfflineImageError, match="archive_member_set_invalid"):
        offline._verify_archive(missing, spec, missing_record)

    extra = tarfile.TarInfo("unexpected")
    extra.size = 1
    extra_archive = tmp_path / "extra.tar"
    _rewrite_archive(original, extra_archive, extra=extra)
    extra_record = {**record, "archive_size": extra_archive.stat().st_size}
    extra_record["archive_sha256"] = offline._sha256_file(extra_archive)
    with pytest.raises(offline.OfflineImageError, match="archive_member_set_invalid"):
        offline._verify_archive(extra_archive, spec, extra_record)

    for name, member_type, reason in (
        ("../escape", tarfile.REGTYPE, "archive_path_invalid"),
        ("link", tarfile.SYMTYPE, "archive_special_member_rejected"),
    ):
        bad_member = tarfile.TarInfo(name)
        bad_member.type = member_type
        bad_member.size = 1 if member_type == tarfile.REGTYPE else 0
        bad_archive = tmp_path / f"bad-{reason}.tar"
        _rewrite_archive(original, bad_archive, extra=bad_member)
        bad_record = {**record, "archive_size": bad_archive.stat().st_size}
        bad_record["archive_sha256"] = offline._sha256_file(bad_archive)
        with pytest.raises(offline.OfflineImageError, match=reason):
            offline._verify_archive(bad_archive, spec, bad_record)


def test_redirect_allowlist_rejects_unapproved_hosts() -> None:
    assert offline._allowed_redirect("https://objects.githubusercontent.com/blob", github=True)
    assert offline._allowed_redirect(
        "https://pkg-containers.githubusercontent.com/blob", github=False
    )
    assert not offline._allowed_redirect("http://objects.githubusercontent.com/blob", github=True)
    assert not offline._allowed_redirect("https://evil.invalid/blob", github=False)


def test_open_follow_preserves_method_and_drops_cross_host_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[urllib.request.Request] = []

    class Opener:
        def open(self, request: urllib.request.Request, *, timeout: int):
            requests.append(request)
            assert timeout == 120
            if len(requests) == 1:
                raise urllib.error.HTTPError(
                    request.full_url,
                    302,
                    "Found",
                    {"Location": "https://objects.githubusercontent.com/fixed-artifact"},
                    None,
                )
            return Response(b"artifact")

    monkeypatch.setattr(offline.urllib.request, "build_opener", lambda *_args: Opener())
    request = urllib.request.Request(
        "https://api.github.com/repos/j4meshub/SmartScan/actions/artifacts/1/zip",
        headers={"Authorization": "Bearer secret", "Accept": "application/octet-stream"},
        method="GET",
    )

    with offline._open_follow(request, github=True) as response:
        assert response.read() == b"artifact"

    assert len(requests) == 2
    assert requests[1].get_method() == "GET"
    redirected_headers = {key.casefold(): value for key, value in requests[1].header_items()}
    assert "authorization" not in redirected_headers
    assert redirected_headers["accept"] == "application/octet-stream"


def test_ci_build_refuses_non_actions_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(offline.OfflineImageError, match="ci_build_only"):
        offline.build_archives()


def test_cli_rejects_extra_arguments_and_does_not_echo_credentials(capsys) -> None:
    assert offline.main(["download", "--url", "https://evil.invalid"]) == 64
    output = capsys.readouterr()
    assert "evil.invalid" not in output.out + output.err


def test_gitignore_excludes_archives_and_parts() -> None:
    text = (offline.ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".smartscan-offline-transfer/" in text
