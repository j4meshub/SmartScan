import base64
from collections.abc import Sequence
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from tools.android_update_manifest import ManifestInput, build_manifest, sign_manifest
from tools.validate_android_release import (
    AndroidReleaseError,
    validate_build_configuration,
    validate_candidate,
    validate_channel_files,
    validate_draft,
)

CERTIFICATE = "ab" * 32


def _apk_runner(versions: dict[str, tuple[str, int, str]], certificate: str = CERTIFICATE):
    def run(command: Sequence[str]) -> str:
        name = Path(command[-1]).name
        package_name, version_code, version_name = versions[name]
        if command[0] == "apkanalyzer":
            return {
                "application-id": package_name,
                "version-code": str(version_code),
                "version-name": version_name,
            }[command[2]]
        return (
            "Verifies\n"
            f"Signer #1 certificate SHA-256 digest: {certificate}\n"
            "Verified using v2 scheme (APK Signature Scheme v2): true\n"
            "Verified using v3 scheme (APK Signature Scheme v3): true\n"
        )

    return run


def _write_apks(tmp_path: Path) -> tuple[Path, Path]:
    current = tmp_path / "current.apk"
    previous = tmp_path / "previous.apk"
    current.write_bytes(b"current-release-apk")
    previous.write_bytes(b"previous-release-apk")
    return current, previous


def test_android_release_draft_contains_fail_closed_gates() -> None:
    assert validate_draft() == []


def test_build_configuration_requires_safe_paired_channel_urls() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    public_key = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode("ascii")

    report = validate_build_configuration(
        version_code=12,
        version_name="1.2.0",
        previous_version_name="1.1.0",
        minimum_supported_version_code=11,
        api_base_url="https://api.smartscan.example/",
        manifest_url="https://download.smartscan.example/android/latest.json",
        signature_url="https://download.smartscan.example/android/latest.json.sig",
        public_key_base64=public_key,
    )

    assert report["channel_host"] == "download.smartscan.example"
    with pytest.raises(AndroidReleaseError, match="路径不匹配"):
        validate_build_configuration(
            version_code=12,
            version_name="1.2.0",
            previous_version_name="1.1.0",
            minimum_supported_version_code=11,
            api_base_url="https://api.smartscan.example/",
            manifest_url="https://download.smartscan.example/android/latest.json",
            signature_url="https://evil.example/latest.json.sig",
            public_key_base64=public_key,
        )


def test_candidate_requires_same_package_certificate_and_higher_version(tmp_path: Path) -> None:
    current, previous = _write_apks(tmp_path)
    runner = _apk_runner(
        {
            current.name: ("com.smartscan.app", 12, "1.2.0"),
            previous.name: ("com.smartscan.app", 11, "1.1.0"),
        }
    )

    report = validate_candidate(
        current,
        [previous],
        expected_version_code=12,
        expected_version_name="1.2.0",
        expected_certificate_sha256=CERTIFICATE,
        runner=runner,
    )

    assert report["candidate"]["version_code"] == 12
    assert report["previous_versions"][0]["version_code"] == 11
    assert report["secrets_included"] is False


@pytest.mark.parametrize(
    "previous_identity, message",
    [
        (("another.package", 11, "1.1.0"), "包名"),
        (("com.smartscan.app", 12, "1.2.0"), "高于"),
    ],
)
def test_candidate_rejects_incompatible_previous_apk(
    tmp_path: Path, previous_identity: tuple[str, int, str], message: str
) -> None:
    current, previous = _write_apks(tmp_path)
    runner = _apk_runner(
        {
            current.name: ("com.smartscan.app", 12, "1.2.0"),
            previous.name: previous_identity,
        }
    )

    with pytest.raises(AndroidReleaseError, match=message):
        validate_candidate(
            current,
            [previous],
            expected_version_code=12,
            expected_version_name="1.2.0",
            expected_certificate_sha256=CERTIFICATE,
            runner=runner,
        )


def test_candidate_rejects_missing_previous_apk(tmp_path: Path) -> None:
    current, _ = _write_apks(tmp_path)

    with pytest.raises(AndroidReleaseError, match="上一稳定"):
        validate_candidate(
            current,
            [],
            expected_version_code=12,
            expected_version_name="1.2.0",
            expected_certificate_sha256=CERTIFICATE,
        )


def test_candidate_rejects_apk_without_v3_signature(tmp_path: Path) -> None:
    current, previous = _write_apks(tmp_path)

    def runner(command: Sequence[str]) -> str:
        if command[0] == "apkanalyzer":
            name = Path(command[-1]).name
            return {
                "application-id": "com.smartscan.app",
                "version-code": "12" if name == current.name else "11",
                "version-name": "1.2.0" if name == current.name else "1.1.0",
            }[command[2]]
        return (
            "Signer #1 certificate SHA-256 digest: "
            f"{CERTIFICATE}\n"
            "Verified using v2 scheme (APK Signature Scheme v2): true\n"
            "Verified using v3 scheme (APK Signature Scheme v3): false\n"
        )

    with pytest.raises(AndroidReleaseError, match="v3"):
        validate_candidate(
            current,
            [previous],
            expected_version_code=12,
            expected_version_name="1.2.0",
            expected_certificate_sha256=CERTIFICATE,
            runner=runner,
        )


def test_signed_channel_must_match_real_candidate_apk(tmp_path: Path) -> None:
    current, _ = _write_apks(tmp_path)
    runner = _apk_runner({current.name: ("com.smartscan.app", 12, "1.2.0")})
    key = ec.generate_private_key(ec.SECP256R1())
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_key = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode("ascii")
    manifest = tmp_path / "latest.json"
    signature = tmp_path / "latest.json.sig"
    payload = build_manifest(
        ManifestInput(
            apk=current,
            package_name="com.smartscan.app",
            version_code=12,
            version_name="1.2.0",
            minimum_supported_version_code=11,
            apk_url="https://gitlab.example.test/api/v4/projects/1/packages/generic/"
            "smartscan-android/1.2.0/SmartScan-release.apk",
            signing_certificate_sha256=CERTIFICATE,
            published_at="2026-10-22T00:00:00Z",
        )
    )
    manifest.write_bytes(payload)
    signature.write_text(sign_manifest(payload, private_pem), encoding="ascii")

    report = validate_channel_files(current, manifest, signature, public_key, runner=runner)

    assert report["candidate_apk_sha256"]
    assert report["secrets_included"] is False

    current.write_bytes(b"tampered-release-apk")
    with pytest.raises(AndroidReleaseError, match="apk_sha256"):
        validate_channel_files(current, manifest, signature, public_key, runner=runner)


def test_channel_rejects_tampered_manifest(tmp_path: Path) -> None:
    current, _ = _write_apks(tmp_path)
    runner = _apk_runner({current.name: ("com.smartscan.app", 12, "1.2.0")})
    key = ec.generate_private_key(ec.SECP256R1())
    public_key = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode("ascii")
    manifest = tmp_path / "latest.json"
    signature = tmp_path / "latest.json.sig"
    manifest.write_bytes(b'{"schema_version":1}')
    signature.write_text(
        base64.b64encode(key.sign(b"different", ec.ECDSA(hashes.SHA256()))).decode("ascii"),
        encoding="ascii",
    )

    with pytest.raises(AndroidReleaseError, match="签名无效"):
        validate_channel_files(current, manifest, signature, public_key, runner=runner)
