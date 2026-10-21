from __future__ import annotations

import plistlib
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tools.validate_ios_archive import IOSArchiveError, validate_archive

BUNDLE_ID = "com.example.smartscan"
TEAM_ID = "ABCDE12345"
VERSION = "1.2.0"
BUILD = "12"
API_URL = "https://api.smartscan.example/"
PRIVACY_URL = "https://www.smartscan.example/privacy"
SUPPORT_URL = "https://www.smartscan.example/support"


def _release_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    archive = tmp_path / "SmartScan.xcarchive"
    application = archive / "Products" / "Applications" / "SmartScan.app"
    application.mkdir(parents=True)
    app_info = {
        "BGTaskSchedulerPermittedIdentifiers": [f"{BUNDLE_ID}.upload"],
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": BUILD,
        "SMARTSCAN_API_BASE_URL": API_URL,
        "SMARTSCAN_BACKGROUND_TASK_IDENTIFIER": f"{BUNDLE_ID}.upload",
        "SMARTSCAN_PRIVACY_POLICY_URL": PRIVACY_URL,
        "SMARTSCAN_SUPPORT_URL": SUPPORT_URL,
    }
    (application / "Info.plist").write_bytes(plistlib.dumps(app_info))
    (application / "embedded.mobileprovision").write_bytes(b"signed-profile")
    archive_info = {
        "ApplicationProperties": {
            "ApplicationPath": "Products/Applications/SmartScan.app",
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": BUILD,
            "SigningIdentity": f"Apple Distribution: SmartScan ({TEAM_ID})",
            "Team": TEAM_ID,
        },
        "ArchiveVersion": 2,
        "Name": "SmartScan",
        "SchemeName": "SmartScan",
    }
    (archive / "Info.plist").write_bytes(plistlib.dumps(archive_info))

    profile = tmp_path / "embedded-profile.plist"
    profile.write_bytes(
        plistlib.dumps(
            {
                "Entitlements": {
                    "application-identifier": f"{TEAM_ID}.{BUNDLE_ID}",
                    "com.apple.developer.team-identifier": TEAM_ID,
                    "get-task-allow": False,
                },
                "ExpirationDate": datetime.now(UTC).replace(tzinfo=None) + timedelta(days=90),
                "Name": "SmartScan App Store",
                "TeamIdentifier": [TEAM_ID],
                "UUID": "00000000-0000-0000-0000-000000000001",
            }
        )
    )
    ipa = tmp_path / "SmartScan.ipa"
    with zipfile.ZipFile(ipa, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("Payload/SmartScan.app/Info.plist", plistlib.dumps(app_info))
        package.writestr("Payload/SmartScan.app/embedded.mobileprovision", b"signed-profile")
        package.writestr("Payload/SmartScan.app/SmartScan", b"signed-binary")
    return archive, ipa, profile


def _validate(tmp_path: Path) -> dict:
    archive, ipa, profile = _release_fixture(tmp_path)
    return validate_archive(
        archive=archive,
        ipa=ipa,
        embedded_profile_plist=profile,
        bundle_id=BUNDLE_ID,
        marketing_version=VERSION,
        build_number=BUILD,
        team_id=TEAM_ID,
        api_base_url=API_URL,
        privacy_policy_url=PRIVACY_URL,
        support_url=SUPPORT_URL,
        xcode_version="Xcode 26.4 Build version 17A123",
        minimum_xcode_major=26,
        codesign_verified=True,
    )


def test_archive_and_ipa_identity_match_release_configuration(tmp_path: Path) -> None:
    report = _validate(tmp_path)

    assert report["status"] == "success"
    assert report["bundle_id"] == BUNDLE_ID
    assert report["ipa_sha256"]
    assert report["codesign_verified"] is True
    assert report["secrets_included"] is False


def test_archive_rejects_development_or_enterprise_profile(tmp_path: Path) -> None:
    archive, ipa, profile = _release_fixture(tmp_path)
    value = plistlib.loads(profile.read_bytes())
    value["ProvisionedDevices"] = ["test-device"]
    profile.write_bytes(plistlib.dumps(value))

    with pytest.raises(IOSArchiveError, match="不得绑定测试设备"):
        validate_archive(
            archive=archive,
            ipa=ipa,
            embedded_profile_plist=profile,
            bundle_id=BUNDLE_ID,
            marketing_version=VERSION,
            build_number=BUILD,
            team_id=TEAM_ID,
            api_base_url=API_URL,
            privacy_policy_url=PRIVACY_URL,
            support_url=SUPPORT_URL,
            xcode_version="Xcode 26.4",
            minimum_xcode_major=26,
            codesign_verified=True,
        )


def test_archive_rejects_unverified_signature_and_old_xcode(tmp_path: Path) -> None:
    archive, ipa, profile = _release_fixture(tmp_path)
    common = {
        "archive": archive,
        "ipa": ipa,
        "embedded_profile_plist": profile,
        "bundle_id": BUNDLE_ID,
        "marketing_version": VERSION,
        "build_number": BUILD,
        "team_id": TEAM_ID,
        "api_base_url": API_URL,
        "privacy_policy_url": PRIVACY_URL,
        "support_url": SUPPORT_URL,
        "minimum_xcode_major": 26,
    }

    with pytest.raises(IOSArchiveError, match="Xcode"):
        validate_archive(**common, xcode_version="Xcode 16.4", codesign_verified=True)
    with pytest.raises(IOSArchiveError, match="codesign"):
        validate_archive(**common, xcode_version="Xcode 26.4", codesign_verified=False)


def test_ipa_rejects_path_traversal(tmp_path: Path) -> None:
    archive, ipa, profile = _release_fixture(tmp_path)
    with zipfile.ZipFile(ipa, "a") as package:
        package.writestr("../outside", b"unsafe")

    with pytest.raises(IOSArchiveError, match="越界路径"):
        validate_archive(
            archive=archive,
            ipa=ipa,
            embedded_profile_plist=profile,
            bundle_id=BUNDLE_ID,
            marketing_version=VERSION,
            build_number=BUILD,
            team_id=TEAM_ID,
            api_base_url=API_URL,
            privacy_policy_url=PRIVACY_URL,
            support_url=SUPPORT_URL,
            xcode_version="Xcode 26.4",
            minimum_xcode_major=26,
            codesign_verified=True,
        )


def test_ipa_rejects_profile_that_differs_from_archive(tmp_path: Path) -> None:
    archive, ipa, profile = _release_fixture(tmp_path)
    with zipfile.ZipFile(ipa, "w", compression=zipfile.ZIP_DEFLATED) as package:
        app_info = plistlib.loads(
            (archive / "Products" / "Applications" / "SmartScan.app" / "Info.plist").read_bytes()
        )
        package.writestr("Payload/SmartScan.app/Info.plist", plistlib.dumps(app_info))
        package.writestr("Payload/SmartScan.app/embedded.mobileprovision", b"other-profile")

    with pytest.raises(IOSArchiveError, match="嵌入描述文件不一致"):
        validate_archive(
            archive=archive,
            ipa=ipa,
            embedded_profile_plist=profile,
            bundle_id=BUNDLE_ID,
            marketing_version=VERSION,
            build_number=BUILD,
            team_id=TEAM_ID,
            api_base_url=API_URL,
            privacy_policy_url=PRIVACY_URL,
            support_url=SUPPORT_URL,
            xcode_version="Xcode 26.4",
            minimum_xcode_major=26,
            codesign_verified=True,
        )
