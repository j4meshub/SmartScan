from __future__ import annotations

import argparse
import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

MAX_APK_SIZE_BYTES = 500 * 1024 * 1024


@dataclass(frozen=True)
class ManifestInput:
    apk: Path
    package_name: str
    version_code: int
    version_name: str
    minimum_supported_version_code: int
    apk_url: str
    signing_certificate_sha256: str
    published_at: str


def build_manifest(source: ManifestInput) -> bytes:
    if not source.apk.is_file():
        raise ValueError("APK 文件不存在")
    size = source.apk.stat().st_size
    if not 0 < size <= MAX_APK_SIZE_BYTES:
        raise ValueError("APK 大小超出允许范围")
    if source.version_code <= 0 or source.minimum_supported_version_code <= 0:
        raise ValueError("版本号必须为正整数")
    if source.minimum_supported_version_code > source.version_code:
        raise ValueError("最低支持版本不能高于发布版本")
    if not source.package_name or not source.version_name:
        raise ValueError("包名和版本名称不能为空")
    parsed = urlsplit(source.apk_url)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("APK 地址必须是不含凭据、查询参数和片段的 HTTPS URL")
    certificate_hash = source.signing_certificate_sha256.lower()
    if not _valid_sha256(certificate_hash):
        raise ValueError("签名证书 SHA-256 无效")
    try:
        published_at = datetime.fromisoformat(source.published_at)
    except ValueError as error:
        raise ValueError("发布时间必须为 ISO-8601") from error
    if published_at.tzinfo is None:
        raise ValueError("发布时间必须包含时区")
    payload = {
        "apk_sha256": _sha256_file(source.apk),
        "apk_signing_certificate_sha256": certificate_hash,
        "apk_size_bytes": size,
        "apk_url": source.apk_url,
        "minimum_supported_version_code": source.minimum_supported_version_code,
        "package_name": source.package_name,
        "published_at": source.published_at,
        "schema_version": 1,
        "version_code": source.version_code,
        "version_name": source.version_name,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sign_manifest(payload: bytes, private_key_pem: bytes) -> str:
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise TypeError("更新清单必须使用 ECDSA P-256 私钥")
    return base64.b64encode(key.sign(payload, ec.ECDSA(hashes.SHA256()))).decode("ascii")


def write_signed_manifest(
    source: ManifestInput,
    private_key_path: Path,
    manifest_path: Path,
    signature_path: Path,
) -> None:
    if manifest_path.resolve() == signature_path.resolve():
        raise ValueError("清单和签名输出路径不能相同")
    payload = build_manifest(source)
    signature = sign_manifest(payload, private_key_path.read_bytes())
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    signature_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(manifest_path, payload)
    _atomic_write(signature_path, f"{signature}\n".encode("ascii"))


def _atomic_write(destination: Path, data: bytes) -> None:
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成并签署 SmartScan Android 更新清单")
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--package-name", required=True)
    parser.add_argument("--version-code", type=int, required=True)
    parser.add_argument("--version-name", required=True)
    parser.add_argument("--minimum-supported-version-code", type=int, required=True)
    parser.add_argument("--apk-url", required=True)
    parser.add_argument("--signing-certificate-sha256", required=True)
    parser.add_argument("--published-at", required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--signature-output", type=Path, required=True)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    write_signed_manifest(
        ManifestInput(
            apk=arguments.apk,
            package_name=arguments.package_name,
            version_code=arguments.version_code,
            version_name=arguments.version_name,
            minimum_supported_version_code=arguments.minimum_supported_version_code,
            apk_url=arguments.apk_url,
            signing_certificate_sha256=arguments.signing_certificate_sha256,
            published_at=arguments.published_at,
        ),
        arguments.private_key,
        arguments.output,
        arguments.signature_output,
    )


if __name__ == "__main__":
    main()
