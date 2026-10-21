import plistlib
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
IOS_ROOT = ROOT / "apps" / "ios"
XCODEGEN_VERSION = "2.46.0"
XCODEGEN_SHA256 = "4d9e34b62172d645eed6457cac13fc222569974098ef4ee9c3368bedf0196806"
LOCALIZATION_KEY = re.compile(r'^\s*"([^"]+)"\s*=')


def test_ios_project_has_reproducible_targets_and_test_scheme() -> None:
    project = yaml.safe_load((IOS_ROOT / "project.yml").read_text(encoding="utf-8"))

    assert project["name"] == "SmartScan"
    assert project["options"]["xcodeVersion"] == "16.4"
    assert project["options"]["deploymentTarget"]["iOS"] == "17.0"
    assert set(project["targets"]) == {"SmartScan", "SmartScanTests"}
    assert project["targets"]["SmartScanTests"]["dependencies"] == [{"target": "SmartScan"}]
    assert project["schemes"]["SmartScan"]["test"]["targets"] == [
        {"name": "SmartScanTests", "parallelizable": True}
    ]
    app_settings = project["targets"]["SmartScan"]["settings"]["base"]
    assert app_settings["PRODUCT_BUNDLE_IDENTIFIER"].endswith(".dev")
    assert app_settings["SMARTSCAN_API_BASE_URL"] == "https://api.invalid/"
    assert app_settings["GENERATE_INFOPLIST_FILE"] is False
    assert app_settings["INFOPLIST_FILE"] == "SmartScan/Info.plist"
    assert project["targets"]["SmartScan"]["sources"] == [
        {"path": "SmartScan", "excludes": ["Info.plist"]}
    ]


def test_xcodegen_download_is_versioned_and_digest_pinned() -> None:
    script = (IOS_ROOT / "scripts" / "generate-project.sh").read_text(encoding="utf-8")

    assert (IOS_ROOT / ".xcodegen-version").read_text(encoding="utf-8").strip() == XCODEGEN_VERSION
    assert f'EXPECTED_VERSION="{XCODEGEN_VERSION}"' in script
    assert f'XCODEGEN_SHA256="{XCODEGEN_SHA256}"' in script
    assert 'TOOL_PATH="$TOOL_DIR/bin/xcodegen"' in script
    assert "shasum -a 256 --check" in script
    assert 'cp -R "$TEMP_DIR/extracted/xcodegen/." "$TOOL_DIR/"' in script
    assert "generate --spec project.yml" in script


def test_ios_ci_uses_fixed_runner_xcode_and_disables_signing() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    ios_job = workflow["jobs"]["ios"]
    run_commands = "\n".join(step.get("run", "") for step in ios_job["steps"])

    assert ios_job["runs-on"] == "macos-15"
    assert "/Applications/Xcode_16.4.app/Contents/Developer" in run_commands
    assert "sh apps/ios/scripts/generate-project.sh" in run_commands
    assert "CODE_SIGNING_ALLOWED=NO" in run_commands
    assert "SmartScanTests" not in run_commands  # Scheme 负责选择测试 Target。


def test_ios_localization_keys_match() -> None:
    resources = IOS_ROOT / "SmartScan" / "Resources"
    english = _localization_keys(resources / "en.lproj" / "Localizable.strings")
    chinese = _localization_keys(resources / "zh-Hans.lproj" / "Localizable.strings")

    assert english
    assert english == chinese


def test_ios_identity_sources_cover_secure_session_and_user_partition() -> None:
    source_root = IOS_ROOT / "SmartScan"
    keychain = (source_root / "Security" / "KeychainSessionStore.swift").read_text(encoding="utf-8")
    api = (source_root / "Network" / "SmartScanAPI.swift").read_text(encoding="utf-8")
    cache = (source_root / "Storage" / "UserScopedProjectCache.swift").read_text(encoding="utf-8")

    assert "kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly" in keychain
    assert 'static let deviceID = "device-identifier-v1"' in keychain
    assert 'forHTTPHeaderField: "X-Device-ID"' in api
    assert 'forHTTPHeaderField: "X-Device-Platform"' in api
    assert 'request.setValue("Bearer \\(token)"' in api
    assert 'scheme == "https" || (scheme == "http" && loopback)' in api
    storage_paths = (source_root / "Storage" / "UserStoragePaths.swift").read_text(encoding="utf-8")
    assert "UserStoragePaths.digest" in cache
    assert "SHA256.hash" in storage_paths
    assert 'appendingPathComponent("projects.json")' in cache


def test_ios_capture_sources_preserve_original_and_direction_evidence() -> None:
    source_root = IOS_ROOT / "SmartScan"
    controller = (source_root / "Capture" / "CameraController.swift").read_text(encoding="utf-8")
    store = (source_root / "Capture" / "CaptureStore.swift").read_text(encoding="utf-8")
    with (source_root / "Info.plist").open("rb") as handle:
        info = plistlib.load(handle)

    assert "AVCaptureVideoDataOutputSampleBufferDelegate" in controller
    assert "VNDetectRectanglesRequest" in controller
    assert "photo.fileDataRepresentation()" in controller
    assert 'appendingPathComponent("captures"' in store
    assert '"\\(identifier).original.jpg"' in store
    assert '"\\(identifier).evidence.json"' in store
    assert "completeFileProtectionUntilFirstUserAuthentication" in store
    assert "NSCameraUsageDescription" in info


def test_ios_info_plist_localization_keys_match() -> None:
    resources = IOS_ROOT / "SmartScan" / "Resources"
    english = _localization_keys(resources / "en.lproj" / "InfoPlist.strings")
    chinese = _localization_keys(resources / "zh-Hans.lproj" / "InfoPlist.strings")

    assert english == chinese == {"NSCameraUsageDescription"}


def test_ios_background_upload_is_permitted_and_server_confirmed() -> None:
    source_root = IOS_ROOT / "SmartScan"
    with (source_root / "Info.plist").open("rb") as handle:
        info = plistlib.load(handle)
    scheduler = (source_root / "Upload" / "BackgroundUploadScheduler.swift").read_text(
        encoding="utf-8"
    )
    processor = (source_root / "Upload" / "UploadProcessor.swift").read_text(encoding="utf-8")
    queue = (source_root / "Upload" / "FileUploadQueueStore.swift").read_text(encoding="utf-8")

    assert info["BGTaskSchedulerPermittedIdentifiers"] == ["com.j4meshub.smartscan.upload"]
    assert "processing" in info["UIBackgroundModes"]
    assert "BGProcessingTaskRequest" in scheduler
    assert "requiresNetworkConnectivity = true" in scheduler
    assert "remote.receivedChunks" in processor
    upload_api = (source_root / "Upload" / "UploadAPI.swift").read_text(encoding="utf-8")
    assert 'forHTTPHeaderField: "X-Chunk-Sha256"' in upload_api
    assert "UserStoragePaths.isDescendant" in queue


def _localization_keys(path: Path) -> set[str]:
    return {
        match.group(1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if (match := LOCALIZATION_KEY.match(line))
    }
