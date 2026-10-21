# iOS 应用

`IOS-001` 使用 XcodeGen 从受版本控制的 `project.yml` 生成 Xcode 工程。`SmartScan.xcodeproj` 和本地工具目录不提交，避免 Xcode 自动改写造成无意义差异；工程规范、源码、资源和测试才是事实来源。

## 固定工具链

- GitHub Runner：`macos-15`
- Xcode：`16.4`
- XcodeGen：`2.46.0`
- XcodeGen 官方 ZIP SHA-256：`4d9e34b62172d645eed6457cac13fc222569974098ef4ee9c3368bedf0196806`
- 最低部署版本：iOS 17.0

生成脚本只从 XcodeGen 官方 GitHub Release 的固定版本 HTTPS 地址下载工具，并在执行前校验 SHA-256。版本文件、脚本固定版本和实际二进制版本任一不一致都会停止。

## 生成与测试

在 macOS 仓库根目录执行：

```bash
sudo xcode-select --switch /Applications/Xcode_16.4.app/Contents/Developer
sh apps/ios/scripts/generate-project.sh
xcodebuild \
  -project apps/ios/SmartScan.xcodeproj \
  -scheme SmartScan \
  -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 16 Pro,OS=latest' \
  CODE_SIGNING_ALLOWED=NO \
  test
```

生成后可用 Xcode 打开 `apps/ios/SmartScan.xcodeproj`。新增源文件、资源或 Target 时先修改 `project.yml`，重新生成并运行测试，不手工维护工程文件。

## 当前边界

- `com.j4meshub.smartscan.dev` 仅用于无签名 Simulator 门禁，不代表正式 Bundle ID 已冻结。
- 中英文 `Localizable.strings` 随应用 Target 构建；新增用户界面文案必须同时维护两个语言文件。
- GitHub macOS Runner 只证明工程可生成、Simulator 可编译且单元测试通过。
- Apple Team、正式 Bundle ID、证书、Provisioning Profile、真机、相机、后台执行、Archive、TestFlight 和 App Store 均保留后续人工门禁。

