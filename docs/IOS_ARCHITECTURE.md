# iOS 可复现工程与 CI 基线

## 工程事实来源

iOS 工程以 `apps/ios/project.yml` 为唯一工程规范，固定 XcodeGen `2.46.0` 生成 `SmartScan.xcodeproj`。生成目录和本地 `.tools` 被 Git 忽略，开发者不得通过提交生成文件代替修改规范。

```text
apps/ios/
├─ .xcodegen-version             固定 XcodeGen 版本
├─ project.yml                   Target、Scheme、构建配置与资源规范
├─ scripts/generate-project.sh   下载、哈希校验、版本校验和工程生成
├─ SmartScan/                    SwiftUI 应用与中英文资源
└─ SmartScanTests/               Simulator 单元测试
```

当前只有 `SmartScan` 应用 Target 和 `SmartScanTests` 单元测试 Target。源码已按 `Authentication`、`Capture`、`Domain`、`Network`、`Security`、`Storage`、`Upload` 和 `Workspace` 职责拆分；审核元数据与截图登记位于独立 `release/` 目录，不与运行时源码或签名材料混放。

## 可复现边界

- CI 固定 `macos-15` 和 `/Applications/Xcode_16.4.app/Contents/Developer`，不依赖 `macos-latest` 的默认 Xcode。
- XcodeGen ZIP 来自官方固定版本 Release，执行前校验发布资产 SHA-256，下载失败或摘要不一致立即停止。
- `project.yml` 固定 iOS 17.0、Swift 5 模式、版本号、应用/测试 Target、Scheme 和资源路径。
- Simulator 使用开发占位 Bundle ID `com.j4meshub.smartscan.dev`，并通过 `CODE_SIGNING_ALLOWED=NO` 禁止 CI 误用签名材料。
- 正式 Bundle ID、Team 和签名不会进入当前工程规范；冻结后须单独记录迁移与回滚决策。
- `PrivacyInfo.xcprivacy` 随应用 Target 打包；隐私和支持 URL 通过构建设置注入，开发占位域名不会在账户界面显示。

## CI 门禁

每次 push 和 PR 都在 GitHub macOS Runner 执行：

1. 选择固定 Xcode 16.4。
2. 下载并校验固定 XcodeGen 2.46.0。
3. 从 `project.yml` 重新生成工程。
4. 在 iPhone 16 Pro Simulator 上编译应用并执行 `SmartScanTests`。

Swift 单元测试固定三种扫描模式的稳定标识与顺序，并覆盖身份模型、Keychain 信封、设备请求头、刷新恢复、注销清理和用户缓存隔离。中英文资源覆盖首页及登录注册界面的用户可见文案；后续界面必须补齐双语资源和测试。

身份与网络实现、安全边界和环境配置见[iOS 身份、Keychain 与网络](IOS_AUTH_AND_NETWORK.md)。

AVFoundation 拍摄状态机、Vision 提示、原图和方向证据见[iOS AVFoundation 拍摄与 Vision 提示](IOS_CAMERA_CAPTURE.md)。

用户分区队列、服务端确认分片和 BackgroundTasks 恢复边界见[iOS 本地队列、后台恢复与分片续传](IOS_BACKGROUND_UPLOAD.md)。

项目工作区、版本化页面编辑、导出完整性、PDFKit、系统分享和账号删除见[iOS 工作区、导出分享与账号删除](IOS_WORKSPACE_AND_ACCOUNT.md)。

商店元数据、隐私披露、截图、审核账号和 TestFlight 人工门禁见[iOS TestFlight 与 App Store 准备说明](IOS_APP_STORE_READINESS.md)。

## 外部门禁

Runner 不能替代以下验收：AVFoundation 相机、Vision 方向与矩形检测、Keychain 真机行为、BackgroundTasks、内存压力、系统分享、签名、Archive、TestFlight 和 App Store 审核。IOS-005 已在仓库公开后通过两套 macOS Simulator 门禁；IOS-006 的新增链接与隐私清单仍需本工作包 PR 的 macOS CI。Mac 只在无法由 Simulator 证明的门禁中使用，日常源码和规范仍可在 Windows 开发。
