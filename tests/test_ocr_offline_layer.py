from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from deploy.ops import smartscan_ocr_layer_contract as contract
from tools import ocr_offline_layer as downloader


def _archive_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        for name, value in files.items():
            item = tarfile.TarInfo(f"models/ocr/{name}")
            item.size = len(value)
            bundle.addfile(item, io.BytesIO(value))
    return output.getvalue()


class _Response:
    def __init__(self, value: bytes, *, status: int = 206, headers: dict[str, str] | None = None):
        self._stream = io.BytesIO(value)
        self._status = status
        self.headers = headers or {}

    def getcode(self) -> int:
        return self._status

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def close(self) -> None:
        pass


def test_fixed_contract_rejects_bad_digest_size_and_corrupt_gzip(tmp_path: Path) -> None:
    archive = tmp_path / "layer.tar.gz"
    archive.write_bytes(b"not-gzip")
    with pytest.raises(contract.LayerContractError, match="layer_size_invalid"):
        contract.verify_layer_archive(archive, expected_sha256="0" * 64, expected_size=10)
    with pytest.raises(contract.LayerContractError, match="layer_digest_invalid"):
        contract.verify_layer_archive(
            archive,
            expected_sha256="0" * 64,
            expected_size=archive.stat().st_size,
        )
    with pytest.raises(contract.LayerContractError, match="gzip_header_invalid"):
        contract.verify_layer_archive(
            archive,
            expected_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            expected_size=archive.stat().st_size,
        )


def test_fixed_contract_rejects_extracted_total_over_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {
        name: (b"x" * size if size < 1024 else b"x")
        for name, size in contract.MODEL_FILE_SIZES.items()
    }
    files.update({name: b"evidence" for name in contract.EVIDENCE_FILES})
    archive = tmp_path / "layer.tar.gz"
    archive.write_bytes(_archive_bytes(files))
    monkeypatch.setattr(
        contract,
        "MODEL_FILE_SIZES",
        {name: len(value) for name, value in files.items() if name not in contract.EVIDENCE_FILES},
    )
    monkeypatch.setattr(contract, "MAX_EXTRACTED_BYTES", 1)
    with pytest.raises(contract.LayerContractError, match="tar_extracted_size_exceeded"):
        contract.inspect_layer_members(archive)


def test_download_resumes_part_and_atomically_renames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"0123456789"
    root = tmp_path / "offline"
    final = root / downloader.FINAL_NAME
    part = root / f"{downloader.FINAL_NAME}.part"
    root.mkdir()
    part.write_bytes(payload[:4])
    seen: dict[str, object] = {}

    monkeypatch.setattr(downloader, "DOWNLOAD_ROOT", root)
    monkeypatch.setattr(downloader, "FINAL_PATH", final)
    monkeypatch.setattr(downloader, "PART_PATH", part)
    monkeypatch.setattr(downloader, "LAYER_SIZE", len(payload))
    monkeypatch.setattr(downloader, "_anonymous_token", lambda: "secret-token")
    monkeypatch.setattr(downloader, "verify_registry_contract", lambda token: None)

    def response(_token: str, offset: int) -> _Response:
        seen["offset"] = offset
        return _Response(
            payload[offset:],
            headers={"Content-Range": f"bytes {offset}-{len(payload) - 1}/{len(payload)}"},
        )

    monkeypatch.setattr(downloader, "_download_response", response)
    monkeypatch.setattr(
        downloader,
        "verify_layer_archive",
        lambda path: {
            "status": "passed",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "compressed_bytes": path.stat().st_size,
        },
    )
    result = downloader.download_fixed_layer()
    assert seen["offset"] == 4
    assert final.read_bytes() == payload
    assert not part.exists()
    assert result["existing"] is False


def test_download_keeps_truncated_part_and_never_exposes_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "offline"
    final = root / downloader.FINAL_NAME
    part = root / f"{downloader.FINAL_NAME}.part"
    monkeypatch.setattr(downloader, "DOWNLOAD_ROOT", root)
    monkeypatch.setattr(downloader, "FINAL_PATH", final)
    monkeypatch.setattr(downloader, "PART_PATH", part)
    monkeypatch.setattr(downloader, "LAYER_SIZE", 8)
    monkeypatch.setattr(downloader, "_anonymous_token", lambda: "never-print-this-token")
    monkeypatch.setattr(downloader, "verify_registry_contract", lambda token: None)
    monkeypatch.setattr(
        downloader,
        "_download_response",
        lambda _token, _offset: _Response(b"short", status=200),
    )
    assert downloader.main(["download"]) == 1
    captured = capsys.readouterr()
    assert "download_truncated" in captured.err
    assert "never-print-this-token" not in captured.out + captured.err
    assert part.read_bytes() == b"short"
    assert not final.exists()


def test_redirect_allowlist_rejects_non_github_host(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _Response(b"", status=307, headers={"Location": "https://evil.invalid/blob"})
    monkeypatch.setattr(downloader, "_open_no_redirect", lambda _request, _timeout: first)
    with pytest.raises(downloader.DownloadError, match="redirect_host_rejected"):
        downloader._request_follow(
            "https://ghcr.io/v2/repository/blobs/digest", method="GET", headers={}
        )


def test_download_rejects_symlink_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("当前平台不允许创建测试符号链接")
    monkeypatch.setattr(downloader, "DOWNLOAD_ROOT", link)
    with pytest.raises(downloader.DownloadError, match="download_directory_invalid"):
        downloader.download_fixed_layer()


def test_offline_verify_uses_fixed_path_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layer = tmp_path / downloader.FINAL_NAME
    layer.write_bytes(b"verified")
    monkeypatch.setattr(downloader, "FINAL_PATH", layer)
    monkeypatch.setattr(
        downloader,
        "verify_layer_archive",
        lambda path: {
            "status": "passed",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "compressed_bytes": path.stat().st_size,
        },
    )
    result = downloader.verify_fixed_layer()
    assert result["path"] == str(layer)


def test_registry_contract_requires_exact_platform_config_and_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = {
        "mediaType": contract.INDEX_MEDIA_TYPE,
        "manifests": [
            {
                "mediaType": contract.MANIFEST_MEDIA_TYPE,
                "digest": contract.MANIFEST_DIGEST,
                "platform": {"architecture": "amd64", "os": "linux"},
            }
        ],
    }
    manifest = {
        "mediaType": contract.MANIFEST_MEDIA_TYPE,
        "config": {
            "mediaType": contract.CONFIG_MEDIA_TYPE,
            "digest": contract.CONFIG_DIGEST,
            "size": contract.CONFIG_SIZE,
        },
        "layers": [
            {
                "mediaType": contract.LAYER_MEDIA_TYPE,
                "digest": contract.LAYER_DIGEST,
                "size": contract.LAYER_SIZE,
            }
        ],
    }
    monkeypatch.setattr(
        downloader,
        "_manifest",
        lambda digest, _media_type, _token: index if digest == contract.INDEX_DIGEST else manifest,
    )
    monkeypatch.setattr(downloader, "_verify_config_blob", lambda _token: None)
    downloader.verify_registry_contract("memory-only-token")
    manifest["layers"][0]["size"] = 1
    with pytest.raises(downloader.DownloadError, match="layer_descriptor_invalid"):
        downloader.verify_registry_contract("memory-only-token")


def test_config_blob_binds_platform_and_source_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.dumps(
        {
            "architecture": "amd64",
            "os": "linux",
            "config": {
                "Labels": {
                    "org.opencontainers.image.revision": contract.SOURCE_COMMIT,
                }
            },
        },
        separators=(",", ":"),
    ).encode()
    monkeypatch.setattr(downloader, "CONFIG_SIZE", len(payload))
    config_digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    monkeypatch.setattr(downloader, "CONFIG_DIGEST", config_digest)
    response = _Response(
        payload,
        status=200,
        headers={
            "Docker-Content-Digest": config_digest,
            "Content-Length": str(len(payload)),
        },
    )
    monkeypatch.setattr(downloader, "_request_follow", lambda *_args, **_kwargs: response)
    downloader._verify_config_blob("memory-only-token")

    payload = payload.replace(contract.SOURCE_COMMIT.encode(), b"0" * 40)
    config_digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    monkeypatch.setattr(downloader, "CONFIG_DIGEST", config_digest)
    response = _Response(
        payload,
        status=200,
        headers={
            "Docker-Content-Digest": config_digest,
            "Content-Length": str(len(payload)),
        },
    )
    with pytest.raises(downloader.DownloadError, match="config_contract_invalid"):
        downloader._verify_config_blob("memory-only-token")


def test_download_script_has_no_url_digest_or_repository_arguments() -> None:
    parser_source = Path(downloader.__file__).read_text(encoding="utf-8")
    assert 'choices=("download", "verify")' in parser_source
    for forbidden in ("--url", "--digest", "--tag", "--repository", "docker pull"):
        assert forbidden not in parser_source
    assert ".smartscan-offline-transfer" in (downloader.ROOT / ".gitignore").read_text(
        encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(downloader.__file__), "--help"],
        cwd=downloader.ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0
    assert "download" in result.stdout and "verify" in result.stdout
