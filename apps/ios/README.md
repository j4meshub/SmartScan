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
sh apps/ios/scripts/run-simulator-tests.sh
```

测试脚本优先使用 Runner 已有的 iPhone 16 Pro；若设备集为空，则从所选 Xcode 的可用 iOS Runtime 创建临时 Simulator，等待启动后按 UDID 测试，并只删除本次创建的设备。生成后可用 Xcode 打开 `apps/ios/SmartScan.xcodeproj`。新增源文件、资源或 Target 时先修改 `project.yml`，重新生成并运行测试，不手工维护工程文件。

## 当前边界

- `com.j4meshub.smartscan.dev` 仅用于无签名 Simulator 门禁，不代表正式 Bundle ID 已冻结。
- 中英文 `Localizable.strings` 随应用 Target 构建；新增用户界面文案必须同时维护两个语言文件。
- GitHub macOS Runner 只证明工程可生成、Simulator 可编译且单元测试通过。
- Apple Team、正式 Bundle ID、证书、Provisioning Profile、真机、相机、后台执行、Archive、TestFlight 和 App Store 均保留后续人工门禁。

## 审核与发布草稿

`release/` 保存双语元数据、审核说明、截图清单和只含环境变量名称的发布配置模板。普通开发检查执行：

```bash
python tools/validate_ios_release.py
```

正式候选还必须执行 `python tools/validate_ios_release.py --release`。该模式要求替换 `.invalid` 地址与开发 Bundle ID、提供截图，并确认签名和审核账号 Secret 环境变量存在；脚本不会读取或输出 Secret 值。当前 Apple 上传工具链要求与固定 Xcode 16.4 Simulator 回归基线不同，Archive 前必须按[《iOS TestFlight 与 App Store 准备说明》](../../docs/IOS_APP_STORE_READINESS.md)重新核对。

## API 环境与身份

应用默认使用 `https://api.invalid/`，不会意外连接任何真实服务。开发或 CI 需要联调时，通过构建设置覆盖地址，例如：

```bash
xcodebuild \
  -project apps/ios/SmartScan.xcodeproj \
  -scheme SmartScan \
  -destination 'platform=iOS Simulator,name=iPhone 16 Pro,OS=latest' \
  SMARTSCAN_API_BASE_URL=https://staging.example.invalid/ \
  CODE_SIGNING_ALLOWED=NO \
  test
```

地址必须使用 HTTPS；仅回环测试地址允许 HTTP。令牌和稳定设备 ID 分项保存到 Keychain，项目缓存按用户隔离。详细边界见[《iOS 身份、Keychain 与网络》](../../docs/IOS_AUTH_AND_NETWORK.md)。

## 相机与 Vision

登录后从三个扫描模式进入统一 AVFoundation 后摄页面。实时亮度、清晰度、高光和 Vision 矩形仅作提示，手动快门不会因低质量判断被禁用；JPEG 原图与方向证据按用户隔离保存。Simulator 只执行编译和纯逻辑测试，真实相机验收清单见[《iOS AVFoundation 拍摄与 Vision 提示》](../../docs/IOS_CAMERA_CAPTURE.md)。

## 离线队列与后台恢复

拍照后原图进入用户分区持久队列。前台和系统授予的 `BGProcessingTask` 都只补传服务端尚未确认的分片；任务过期、断网和进程恢复不会把本地进度当作服务端事实。详细协议和真机门禁见[《iOS 本地队列、后台恢复与分片续传》](../../docs/IOS_BACKGROUND_UPLOAD.md)。

## 工作区、分享与账号删除

登录后的工作区支持页序、旋转、四角、滤镜、复核和 JPG/PDF 导出。导出文件校验服务端大小与 SHA-256 后才能进入 PDFKit 预览或系统分享；账户页使用短信强验证申请删除并按用户清理本地数据。详细安全边界见[《iOS 工作区、导出分享与账号删除》](../../docs/IOS_WORKSPACE_AND_ACCOUNT.md)。

账户页仅在注入了有效公网 HTTPS 地址时显示隐私政策和支持链接，`.invalid` 或非 HTTPS 占位值不会出现在界面。应用隐私清单声明当前收集类型并明确不跟踪；生产日志、第三方服务和未来 SDK 仍需在每次发布前重新核对。

