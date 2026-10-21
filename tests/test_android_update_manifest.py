import base64
import json
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from tools.android_update_manifest import ManifestInput, build_manifest, sign_manifest


def manifest_input(tmp_path: Path) -> ManifestInput:
    apk = tmp_path / "SmartScan.apk"
    apk.write_bytes(b"signed-apk-fixture")
    return ManifestInput(
        apk=apk,
        package_name="com.smartscan.app",
        version_code=12,
        version_name="1.2.0",
        minimum_supported_version_code=11,
        apk_url="https://updates.example.com/SmartScan.apk",
        signing_certificate_sha256="ab" * 32,
        published_at="2026-10-21T00:00:00Z",
    )


def test_manifest_is_canonical_and_ecdsa_signature_rejects_tampering(tmp_path: Path) -> None:
    source = manifest_input(tmp_path)
    payload = build_manifest(source)
    key = ec.generate_private_key(ec.SECP256R1())
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    signature = base64.b64decode(sign_manifest(payload, private_pem))

    assert json.loads(payload)["apk_size_bytes"] == len(b"signed-apk-fixture")
    key.public_key().verify(signature, payload, ec.ECDSA(hashes.SHA256()))
    with pytest.raises(InvalidSignature):
        key.public_key().verify(signature, payload + b" ", ec.ECDSA(hashes.SHA256()))


@pytest.mark.parametrize(
    "change, message",
    [
        ({"apk_url": "http://updates.example.com/app.apk"}, "HTTPS"),
        ({"apk_url": "https://updates.example.com/app.apk?token=secret"}, "查询参数"),
        ({"minimum_supported_version_code": 13}, "最低支持版本"),
        ({"signing_certificate_sha256": "bad"}, "SHA-256"),
        ({"published_at": "2026-10-21T00:00:00"}, "时区"),
    ],
)
def test_manifest_rejects_unsafe_release_metadata(
    tmp_path: Path, change: dict, message: str
) -> None:
    values = manifest_input(tmp_path).__dict__ | change
    with pytest.raises(ValueError, match=message):
        build_manifest(ManifestInput(**values))
