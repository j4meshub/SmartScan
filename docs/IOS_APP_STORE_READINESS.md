# iOS TestFlight 与 App Store 准备说明

## 当前结论

`IOS-006` 把可版本控制的双语元数据、隐私清单、截图清单、审核说明和发布校验器放入仓库，但不把正式 Bundle ID、Apple Team、签名证书、Provisioning Profile、App Store Connect 私钥或审核账号提交到 Git。当前配置仍是不可发布的安全占位值；只有 `python tools/validate_ios_release.py --release` 通过，且人工门禁完成后，才允许上传。

Apple 的要求会变化。2026-10-21 查阅[上传构建版本](https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds/)时，Apple 已要求 2026 年提交的 iOS 构建使用 Xcode 26 或更高版本。因此，Xcode 16.4 只保留为现有 PR 的可复现 Simulator 回归基线，正式 Archive 前必须重新核对 Apple 当期要求，并使用满足要求的 Xcode；不得把两类门禁混为一谈。

## 受版本控制的资产

- `apps/ios/release/release-config.example.yml`：只保存版本、语言、占位 URL 和 Secret 环境变量名称。
- `apps/ios/release/metadata/{en-US,zh-Hans}`：名称、副标题、宣传文本、描述、关键词和版本说明草稿。
- `apps/ios/release/review-notes/`：双语审核说明模板，不含账号口令。
- `apps/ios/release/screenshots.yml`：中英文、iPhone 6.9 英寸和 iPad 13 英寸截图清单。
- `apps/ios/SmartScan/PrivacyInfo.xcprivacy`：当前代码的数据收集与不跟踪声明。
- `tools/validate_ios_release.py`：草稿和正式发布两级校验。

普通 CI 执行草稿校验，允许 `.invalid` 占位地址与空截图列表；正式模式会拒绝占位 Bundle ID、占位 URL、缺失的签名/审核账号环境变量和截图。校验器只判断 Secret 是否存在，不读取或打印其值。

## 发布前人工输入

由 Account Holder 或被授权的 Admin/App Manager 在外部密码管理器和 GitHub Environment 中完成：

1. 冻结正式 Bundle ID、SKU、App Store Connect App ID、Apple Team ID、版本号和构建号。
2. 配置生产 API、隐私政策和支持页的公开 HTTPS 地址；三个地址都必须可从公网访问。
3. 将发行证书、证书口令、描述文件和 App Store Connect API Key 保存到受保护环境，不写入仓库、日志或 PR。
4. 在 App Store Connect 安全审核字段填写普通用户审核账号和当期短信取码方式，不使用管理员或超级管理员。
5. 确认协议、税务、出口合规、年龄分级、内容版权和地区可用性。需要法务或业务所有者确认的内容不能由 CI 代签。

## Archive 与上传顺序

1. 从已通过 CI 的提交创建只用于发布的受保护分支或标签，重新核对 Apple 当前要求与 Xcode 版本。
2. 生成工程后，用外部注入的正式 Bundle ID、Team、API/隐私/支持 URL 和签名配置 Archive。禁止把这些值回写到 `project.yml`。
3. 运行 `python tools/validate_ios_release.py --release`，再检查 Xcode 生成的 Privacy Report、归档签名、Entitlements 和导出合规结果。
4. 通过 Xcode Organizer、Transporter 或 App Store Connect API 上传。构建由 Bundle ID、版本号与构建号共同标识；重复构建必须递增构建号。
5. 等待处理完成，处理警告必须逐项解释；不要通过关闭校验或删除隐私声明绕过。
6. 先进入内部 TestFlight，再进入外部 TestFlight；首个外部构建可能需要 Beta App Review。
7. 完成真机矩阵后再提交 App Review，并选择手动发布。首次正式版本不自动放量。

## TestFlight 验收矩阵

至少在一台受支持 iPhone 与一台受支持 iPad 上完成：

| 场景 | 必须证据 |
|---|---|
| 注册、登录和刷新 | 本地手机号和企业微信路径按可用环境验证；锁屏和重启后 Keychain 会话符合预期 |
| 账号冲突与合并 | 已验证手机号冲突不会静默合并；强身份确认后旧会话撤销 |
| 拍摄 | 相机权限、方向、对焦、曝光、反光提示、原图保留和多页连续拍摄 |
| 弱网与后台 | Wi-Fi/蜂窝切换、断网、系统强杀、锁屏、后台时间到期后不重复上传服务端已确认分片 |
| 编辑与导出 | 页序、旋转、四角、滤镜、复核、JPG/PDF、OCR 文本层、PDFKit 与系统分享 |
| 账号删除 | 应用内入口可发现，短信强验证、7 天冷静期、取消删除与本地数据清理符合说明 |
| 双语与辅助功能 | 系统英文/简体中文、动态字体、VoiceOver、横竖屏和 iPad 布局 |
| 外部 AI 关闭 | 完整扫描、处理、预览和导出仍可用 |

[TestFlight 官方说明](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview/)指出构建最多可测试 90 天；内部测试最多 100 人，外部测试最多 10,000 人。数量上限不是本项目的质量门槛。

## 提交审核与回滚

提交前按照[提交 App 审核](https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/submit-an-app/)逐项确认构建、元数据、截图、隐私、审核联系方式和账号。审核期间后端及审核账号必须可用，审核说明应给出无需管理员权限即可到达的完整路径。

发生阻断时：尚未发布的构建从候选版本移除并修复后递增构建号；TestFlight 构建停止测试；已发布版本优先使用 App Store Connect 允许的下架/分阶段发布控制，再提交修复版本。数据库和账号数据回滚遵守各自迁移与删除门禁，不能用客户端回滚恢复已删除数据。

## 未通过门禁

- 正式 Bundle ID、Team、App Store Connect App、签名材料与公开 URL 未冻结。
- IOS-005 已在仓库公开后通过 macOS Runner；IOS-006 的新增链接与隐私清单仍需本工作包 PR 取得编译证据。
- Archive、TestFlight、真机相机/后台/分享、真实短信与企业微信均未验收。
- 截图文件尚未生成；仓库只包含场景和尺寸清单。
