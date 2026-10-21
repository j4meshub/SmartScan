#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
IOS_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
XCODEGEN_VERSION=$(tr -d '[:space:]' < "$IOS_ROOT/.xcodegen-version")
EXPECTED_VERSION="2.46.0"
XCODEGEN_SHA256="4d9e34b62172d645eed6457cac13fc222569974098ef4ee9c3368bedf0196806"
TOOL_DIR="$IOS_ROOT/.tools/xcodegen/$XCODEGEN_VERSION"
TOOL_PATH="$TOOL_DIR/xcodegen"

if [ "$XCODEGEN_VERSION" != "$EXPECTED_VERSION" ]; then
  echo "XcodeGen 版本文件与安装脚本不一致" >&2
  exit 1
fi

if [ ! -x "$TOOL_PATH" ]; then
  TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/smartscan-xcodegen.XXXXXX")
  trap 'rm -rf "$TEMP_DIR"' EXIT HUP INT TERM
  ARCHIVE_PATH="$TEMP_DIR/xcodegen.zip"
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    "https://github.com/yonaskolb/XcodeGen/releases/download/$XCODEGEN_VERSION/xcodegen.zip" \
    --output "$ARCHIVE_PATH"
  printf '%s  %s\n' "$XCODEGEN_SHA256" "$ARCHIVE_PATH" | shasum -a 256 --check
  unzip -q "$ARCHIVE_PATH" -d "$TEMP_DIR/extracted"
  mkdir -p "$TOOL_DIR"
  install -m 0755 "$TEMP_DIR/extracted/xcodegen" "$TOOL_PATH"
fi

ACTUAL_VERSION=$($TOOL_PATH --version)
if [ "$ACTUAL_VERSION" != "Version: $XCODEGEN_VERSION" ] && [ "$ACTUAL_VERSION" != "$XCODEGEN_VERSION" ]; then
  echo "XcodeGen 实际版本不符合固定版本：$ACTUAL_VERSION" >&2
  exit 1
fi

cd "$IOS_ROOT"
"$TOOL_PATH" generate --spec project.yml
