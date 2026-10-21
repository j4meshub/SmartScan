"""离线验证 SmartScan staging TLS 证书、域名、私钥与权限。"""

from __future__ import annotations

import argparse
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

try:
    from tools.render_staging_edge import TLS_ROOT, EdgeConfigError, validate_host
except ModuleNotFoundError as exc:
    if exc.name != "tools":
        raise
    from render_staging_edge import TLS_ROOT, EdgeConfigError, validate_host


class TlsMaterialError(ValueError):
    """TLS 材料不能安全用于 staging。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TlsMaterialError(message)


def _validate_real_path(path: Path, label: str, *, ci_fixture: bool) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise TlsMaterialError(f"{label}不存在：{path}") from exc
    _require(path.is_file() and not path.is_symlink(), f"{label}必须是普通文件且不能是符号链接")
    if not ci_fixture:
        try:
            resolved.relative_to(Path(str(TLS_ROOT)).resolve())
        except ValueError as exc:
            raise TlsMaterialError(f"{label}必须位于 staging TLS 目录") from exc
    return resolved


def _validate_permissions(certificate: Path, certificate_key: Path, *, ci_fixture: bool) -> None:
    if os.name == "nt":
        return
    certificate_mode = stat.S_IMODE(certificate.stat().st_mode)
    key_mode = stat.S_IMODE(certificate_key.stat().st_mode)
    _require(certificate_mode & 0o022 == 0, "TLS 证书禁止组或其他用户写入")
    _require(key_mode & 0o077 == 0, "TLS 私钥权限必须为 0600 或更严格")
    if not ci_fixture:
        _require(certificate_key.stat().st_uid == 0, "真实 staging TLS 私钥必须由 root 持有")


def validate_tls_material(
    *,
    host: str,
    certificate_path: Path,
    certificate_key_path: Path,
    minimum_days: int = 14,
    now: datetime | None = None,
    ci_fixture: bool = False,
) -> dict[str, object]:
    try:
        host = validate_host(host, ci_fixture=ci_fixture)
    except EdgeConfigError as exc:
        raise TlsMaterialError(str(exc)) from exc
    _require(1 <= minimum_days <= 90, "证书剩余天数门禁必须在 1 至 90 天之间")
    certificate_path = _validate_real_path(certificate_path, "TLS 证书", ci_fixture=ci_fixture)
    certificate_key_path = _validate_real_path(
        certificate_key_path, "TLS 私钥", ci_fixture=ci_fixture
    )
    _validate_permissions(certificate_path, certificate_key_path, ci_fixture=ci_fixture)
    try:
        certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise TlsMaterialError("无法解析 PEM TLS 证书") from exc
    try:
        private_key = serialization.load_pem_private_key(
            certificate_key_path.read_bytes(), password=None
        )
    except (OSError, ValueError, TypeError) as exc:
        raise TlsMaterialError("无法解析无口令 PEM TLS 私钥") from exc

    try:
        sans = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound as exc:
        raise TlsMaterialError("TLS 证书缺少 Subject Alternative Name") from exc
    dns_names = {item.casefold().rstrip(".") for item in sans.get_values_for_type(x509.DNSName)}
    _require(host in dns_names, "TLS 证书 SAN 必须精确包含 staging 域名")

    public_key = certificate.public_key()
    if isinstance(public_key, rsa.RSAPublicKey):
        _require(public_key.key_size >= 2048, "TLS RSA 公钥必须至少为 2048 位")
    elif isinstance(public_key, ec.EllipticCurvePublicKey):
        _require(public_key.key_size >= 256, "TLS 椭圆曲线公钥强度不足")
    else:
        raise TlsMaterialError("TLS 证书公钥类型不在当前审核基线内")
    cert_public = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_public = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _require(cert_public == key_public, "TLS 证书与私钥不匹配")

    current = now or datetime.now(UTC)
    not_before = certificate.not_valid_before_utc
    not_after = certificate.not_valid_after_utc
    _require(not_before <= current < not_after, "TLS 证书当前不在有效期内")
    _require(not_after - current >= timedelta(days=minimum_days), "TLS 证书剩余有效期不足")
    algorithm = certificate.signature_hash_algorithm
    _require(
        algorithm is not None and algorithm.name.casefold() not in {"md5", "sha1"},
        "TLS 证书签名摘要算法过弱",
    )
    return {
        "host": host,
        "not_before": not_before.isoformat(),
        "not_after": not_after.isoformat(),
        "minimum_days": minimum_days,
        "san_exact_match": True,
        "certificate_key_match": True,
        "private_key_included": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="离线验证 SmartScan staging TLS 材料")
    parser.add_argument("--host", required=True)
    parser.add_argument("--certificate", required=True, type=Path)
    parser.add_argument("--certificate-key", required=True, type=Path)
    parser.add_argument("--minimum-days", type=int, default=14)
    parser.add_argument("--ci-fixture", action="store_true")
    args = parser.parse_args()
    result = validate_tls_material(
        host=args.host,
        certificate_path=args.certificate,
        certificate_key_path=args.certificate_key,
        minimum_days=args.minimum_days,
        ci_fixture=args.ci_fixture,
    )
    print("TLS 材料校验通过；以下摘要不包含私钥：")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
