#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
export DEVICE_NAME="iPhone 16 Pro"
CREATED_DEVICE="false"

device_id="$({ xcrun simctl list devices available -j || true; } | python3 -c '
import json, os, sys
try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    print("")
    raise SystemExit
devices = (
    device
    for group in data.get("devices", {}).values()
    for device in group
    if device.get("name") == os.environ["DEVICE_NAME"] and device.get("isAvailable", True)
)
print(next((device.get("udid", "") for device in devices), ""))
')"

if [[ -z "$device_id" ]]; then
  runtime_id="$(xcrun simctl list runtimes available -j | python3 -c '
import json, sys
runtimes = [
    runtime
    for runtime in json.load(sys.stdin).get("runtimes", [])
    if runtime.get("isAvailable", True)
    and runtime.get("identifier", "").startswith("com.apple.CoreSimulator.SimRuntime.iOS-")
]
print(runtimes[-1].get("identifier", "") if runtimes else "")
')"
  device_type_id="$(xcrun simctl list devicetypes -j | python3 -c '
import json, os, sys
types = json.load(sys.stdin).get("devicetypes", [])
print(next((item.get("identifier", "") for item in types if item.get("name") == os.environ["DEVICE_NAME"]), ""))
')"
  if [[ -z "$runtime_id" || -z "$device_type_id" ]]; then
    echo "当前 Xcode 未提供可用 iOS Runtime 或 $DEVICE_NAME 设备类型。" >&2
    xcrun simctl list
    exit 1
  fi
  device_id="$(xcrun simctl create "SmartScan CI" "$device_type_id" "$runtime_id")"
  CREATED_DEVICE="true"
fi

cleanup() {
  if [[ "$CREATED_DEVICE" == "true" ]]; then
    xcrun simctl delete "$device_id" || true
  fi
}
trap cleanup EXIT

xcrun simctl boot "$device_id" 2>/dev/null || true
xcrun simctl bootstatus "$device_id" -b

xcodebuild \
  -project "$REPO_ROOT/apps/ios/SmartScan.xcodeproj" \
  -scheme SmartScan \
  -configuration Debug \
  -destination "platform=iOS Simulator,id=$device_id" \
  CODE_SIGNING_ALLOWED=NO \
  test
