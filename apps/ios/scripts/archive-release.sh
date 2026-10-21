#!/usr/bin/env bash
set -euo pipefail

require_environment() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "缺少 iOS 发布环境变量：$name" >&2
    exit 1
  fi
}

for name in \
  RUNNER_TEMP \
  SMARTSCAN_IOS_BUNDLE_ID \
  SMARTSCAN_APPLE_TEAM_ID \
  SMARTSCAN_IOS_MARKETING_VERSION \
  SMARTSCAN_IOS_BUILD_NUMBER \
  SMARTSCAN_API_BASE_URL \
  SMARTSCAN_PRIVACY_POLICY_URL \
  SMARTSCAN_SUPPORT_URL \
  SMARTSCAN_IOS_DISTRIBUTION_CERTIFICATE_BASE64 \
  SMARTSCAN_IOS_DISTRIBUTION_CERTIFICATE_PASSWORD \
  SMARTSCAN_IOS_PROVISIONING_PROFILE_BASE64 \
  APP_STORE_CONNECT_KEY_ID \
  APP_STORE_CONNECT_ISSUER_ID \
  APP_STORE_CONNECT_PRIVATE_KEY_BASE64 \
  SMARTSCAN_IOS_UPLOAD_MODE \
  SMARTSCAN_IOS_RELEASE_REPORT; do
  require_environment "$name"
done

if [[ "$SMARTSCAN_IOS_UPLOAD_MODE" != "validate-only" && "$SMARTSCAN_IOS_UPLOAD_MODE" != "upload-testflight" ]]; then
  echo "iOS 发布模式无效" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
IOS_ROOT="$REPO_ROOT/apps/ios"
WORK_DIR="$(mktemp -d "$RUNNER_TEMP/smartscan-ios-release.XXXXXX")"
KEYCHAIN_PATH="$WORK_DIR/release.keychain-db"
CERTIFICATE_PATH="$WORK_DIR/distribution.p12"
PROFILE_PATH="$WORK_DIR/distribution.mobileprovision"
PROFILE_PLIST="$WORK_DIR/distribution.plist"
EMBEDDED_PROFILE_PLIST="$WORK_DIR/embedded-profile.plist"
ARCHIVE_PATH="$WORK_DIR/SmartScan.xcarchive"
EXPORT_PATH="$WORK_DIR/export"
EXPORT_OPTIONS="$WORK_DIR/ExportOptions.plist"
KEY_DIRECTORY="$HOME/.appstoreconnect/private_keys"
APP_STORE_KEY_PATH="$KEY_DIRECTORY/AuthKey_${APP_STORE_CONNECT_KEY_ID}.p8"
INSTALLED_PROFILE=""
KEYCHAIN_PASSWORD="$(openssl rand -hex 32)"
ORIGINAL_KEYCHAINS=()
while IFS= read -r keychain; do
  keychain="${keychain#\"}"
  keychain="${keychain%\"}"
  [[ -n "$keychain" ]] && ORIGINAL_KEYCHAINS+=("$keychain")
done < <(security list-keychains -d user | sed 's/^[[:space:]]*//')

cleanup() {
  if [[ -n "$INSTALLED_PROFILE" ]]; then
    rm -f "$INSTALLED_PROFILE"
  fi
  rm -f "$APP_STORE_KEY_PATH"
  security list-keychains -d user -s "${ORIGINAL_KEYCHAINS[@]}" >/dev/null 2>&1 || true
  security delete-keychain "$KEYCHAIN_PATH" >/dev/null 2>&1 || true
  if [[ -n "$WORK_DIR" && "$WORK_DIR" == "$RUNNER_TEMP"/smartscan-ios-release.* ]]; then
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT HUP INT TERM
umask 077

printf '%s' "$SMARTSCAN_IOS_DISTRIBUTION_CERTIFICATE_BASE64" | base64 -D > "$CERTIFICATE_PATH"
printf '%s' "$SMARTSCAN_IOS_PROVISIONING_PROFILE_BASE64" | base64 -D > "$PROFILE_PATH"
mkdir -p "$KEY_DIRECTORY"
printf '%s' "$APP_STORE_CONNECT_PRIVATE_KEY_BASE64" | base64 -D > "$APP_STORE_KEY_PATH"
grep -q "BEGIN PRIVATE KEY" "$APP_STORE_KEY_PATH"

security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security import "$CERTIFICATE_PATH" \
  -k "$KEYCHAIN_PATH" \
  -P "$SMARTSCAN_IOS_DISTRIBUTION_CERTIFICATE_PASSWORD" \
  -f pkcs12 \
  -T /usr/bin/codesign \
  -T /usr/bin/security
security set-key-partition-list \
  -S apple-tool:,apple: \
  -s \
  -k "$KEYCHAIN_PASSWORD" \
  "$KEYCHAIN_PATH" >/dev/null
security list-keychains -d user -s "$KEYCHAIN_PATH" "${ORIGINAL_KEYCHAINS[@]}"

security cms -D -i "$PROFILE_PATH" > "$PROFILE_PLIST"
PROFILE_UUID="$(/usr/libexec/PlistBuddy -c 'Print :UUID' "$PROFILE_PLIST")"
PROFILE_NAME="$(/usr/libexec/PlistBuddy -c 'Print :Name' "$PROFILE_PLIST")"
PROFILE_TEAM="$(/usr/libexec/PlistBuddy -c 'Print :TeamIdentifier:0' "$PROFILE_PLIST")"
PROFILE_APP_IDENTIFIER="$(/usr/libexec/PlistBuddy -c 'Print :Entitlements:application-identifier' "$PROFILE_PLIST")"
PROFILE_DEBUGGABLE="$(/usr/libexec/PlistBuddy -c 'Print :Entitlements:get-task-allow' "$PROFILE_PLIST")"
[[ "$PROFILE_TEAM" == "$SMARTSCAN_APPLE_TEAM_ID" ]]
[[ "$PROFILE_APP_IDENTIFIER" == "$SMARTSCAN_APPLE_TEAM_ID.$SMARTSCAN_IOS_BUNDLE_ID" ]]
[[ "$PROFILE_DEBUGGABLE" == "false" ]]
PROFILE_DIRECTORY="$HOME/Library/MobileDevice/Provisioning Profiles"
mkdir -p "$PROFILE_DIRECTORY"
INSTALLED_PROFILE="$PROFILE_DIRECTORY/$PROFILE_UUID.mobileprovision"
cp "$PROFILE_PATH" "$INSTALLED_PROFILE"

plutil -create xml1 "$EXPORT_OPTIONS"
/usr/libexec/PlistBuddy -c 'Add :method string app-store-connect' "$EXPORT_OPTIONS"
/usr/libexec/PlistBuddy -c 'Add :destination string export' "$EXPORT_OPTIONS"
/usr/libexec/PlistBuddy -c 'Add :signingStyle string manual' "$EXPORT_OPTIONS"
/usr/libexec/PlistBuddy -c "Add :teamID string $SMARTSCAN_APPLE_TEAM_ID" "$EXPORT_OPTIONS"
/usr/libexec/PlistBuddy -c 'Add :stripSwiftSymbols bool true' "$EXPORT_OPTIONS"
/usr/libexec/PlistBuddy -c 'Add :uploadSymbols bool true' "$EXPORT_OPTIONS"
/usr/libexec/PlistBuddy -c 'Add :manageAppVersionAndBuildNumber bool false' "$EXPORT_OPTIONS"
/usr/libexec/PlistBuddy -c 'Add :provisioningProfiles dict' "$EXPORT_OPTIONS"
/usr/libexec/PlistBuddy -c "Add :provisioningProfiles:$SMARTSCAN_IOS_BUNDLE_ID string $PROFILE_NAME" "$EXPORT_OPTIONS"

sh "$SCRIPT_DIR/generate-project.sh"
xcodebuild \
  -project "$IOS_ROOT/SmartScan.xcodeproj" \
  -scheme SmartScan \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath "$ARCHIVE_PATH" \
  PRODUCT_BUNDLE_IDENTIFIER="$SMARTSCAN_IOS_BUNDLE_ID" \
  DEVELOPMENT_TEAM="$SMARTSCAN_APPLE_TEAM_ID" \
  MARKETING_VERSION="$SMARTSCAN_IOS_MARKETING_VERSION" \
  CURRENT_PROJECT_VERSION="$SMARTSCAN_IOS_BUILD_NUMBER" \
  SMARTSCAN_API_BASE_URL="$SMARTSCAN_API_BASE_URL" \
  SMARTSCAN_PRIVACY_POLICY_URL="$SMARTSCAN_PRIVACY_POLICY_URL" \
  SMARTSCAN_SUPPORT_URL="$SMARTSCAN_SUPPORT_URL" \
  SMARTSCAN_BACKGROUND_TASK_IDENTIFIER="$SMARTSCAN_IOS_BUNDLE_ID.upload" \
  CODE_SIGN_STYLE=Manual \
  CODE_SIGN_IDENTITY='Apple Distribution' \
  PROVISIONING_PROFILE_SPECIFIER="$PROFILE_NAME" \
  archive

APP_PATH="$ARCHIVE_PATH/Products/Applications/SmartScan.app"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"
security cms -D -i "$APP_PATH/embedded.mobileprovision" > "$EMBEDDED_PROFILE_PLIST"
xcodebuild \
  -exportArchive \
  -archivePath "$ARCHIVE_PATH" \
  -exportPath "$EXPORT_PATH" \
  -exportOptionsPlist "$EXPORT_OPTIONS"

IPA_COUNT="$(find "$EXPORT_PATH" -maxdepth 1 -type f -name '*.ipa' -print | wc -l | tr -d '[:space:]')"
if [[ "$IPA_COUNT" != "1" ]]; then
  echo "导出目录必须只包含一个 IPA" >&2
  exit 1
fi
IPA_PATH="$(find "$EXPORT_PATH" -maxdepth 1 -type f -name '*.ipa' -print)"
XCODE_VERSION="$(xcodebuild -version | tr '\n' ' ')"
python3 "$REPO_ROOT/tools/validate_ios_archive.py" \
  --archive "$ARCHIVE_PATH" \
  --ipa "$IPA_PATH" \
  --embedded-profile-plist "$EMBEDDED_PROFILE_PLIST" \
  --bundle-id "$SMARTSCAN_IOS_BUNDLE_ID" \
  --marketing-version "$SMARTSCAN_IOS_MARKETING_VERSION" \
  --build-number "$SMARTSCAN_IOS_BUILD_NUMBER" \
  --team-id "$SMARTSCAN_APPLE_TEAM_ID" \
  --api-base-url "$SMARTSCAN_API_BASE_URL" \
  --privacy-policy-url "$SMARTSCAN_PRIVACY_POLICY_URL" \
  --support-url "$SMARTSCAN_SUPPORT_URL" \
  --xcode-version "$XCODE_VERSION" \
  --minimum-xcode-major 26 \
  --codesign-verified \
  --report "$SMARTSCAN_IOS_RELEASE_REPORT"

if [[ "$SMARTSCAN_IOS_UPLOAD_MODE" == "upload-testflight" ]]; then
  xcrun altool \
    --upload-app \
    --type ios \
    --file "$IPA_PATH" \
    --apiKey "$APP_STORE_CONNECT_KEY_ID" \
    --apiIssuer "$APP_STORE_CONNECT_ISSUER_ID"
else
  echo "Archive 与 IPA 校验通过；未请求上传 TestFlight。"
fi
