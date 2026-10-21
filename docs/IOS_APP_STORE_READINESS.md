# iOS TestFlight 与 App Store 准备说明

## 当前结论

`IOS-006` 把可版本控制的双语元数据、隐私清单、截图清单、审核说明和发布校验器放入仓库；`REL-002` 又增加了受保护标签、GitHub Environment、签名 Archive/IPA 实包校验和显式 TestFlight 上传工作流。正式 Bundle ID、Apple Team、签名证书、Provisioning Profile、App Store Connect 私钥或审核账号仍不得提交到 Git。

当前配置仍是不可发布的安全占位值，截图清单也尚未填入真实文件。只有正式模式校验、签名归档和全部人工门禁完成后，才允许选择上传；仓库测试或 `validate-only` 成功都不能表示 TestFlight、真机或 App Review 已通过。

Apple 的要求会变化。2026-10-21 查阅[上传构建版本](https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds/)时，Apple 已要求 2026 年提交的 iOS 构建使用 Xcode 26 或更高版本。因此，Xcode 16.4 只保留为现有 PR 的可复现 Simulator 回归基线，正式 Archive 前必须重新核对 Apple 当期要求，并使用满足要求的 Xcode；不得把两类门禁混为一谈。

## 受版本控制的资产

- `apps/ios/release/release-config.example.yml`：只保存版本、语言、占位 URL 和 Secret 环境变量名称。
- `apps/ios/release/metadata/{en-US,zh-Hans}`：名称、副标题、宣传文本、描述、关键词和版本说明草稿。
- `apps/ios/release/review-notes/`：双语审核说明模板，不含账号口令。
- `apps/ios/release/screenshots.yml`：中英文、iPhone 6.9 英寸和 iPad 13 英寸截图清单。
- `apps/ios/SmartScan/PrivacyInfo.xcprivacy`：当前代码的数据收集与不跟踪声明。
- `tools/validate_ios_release.py`：草稿和正式发布两级校验。
- `tools/validate_ios_archive.py`：核对 Archive、发行描述文件、IPA 身份、签名证据和脱敏摘要。
- `.github/workflows/ios-release.yml`：只接受人工触发的受保护标签，使用 `ios-release` Environment。
- `apps/ios/scripts/archive-release.sh`：在临时钥匙串中完成签名、导出和可选上传，结束后清理密钥材料。

普通 CI 执行草稿校验，允许 `.invalid` 占位地址与空截图列表；正式模式会拒绝占位 Bundle ID、占位 URL、缺失的签名/审核账号环境变量和截图。校验器只判断 Secret 是否存在，不读取或打印其值。

## 受保护发布工作流

正式工作流必须由 `ios-vX.Y.Z-build.N` 格式的受保护标签人工触发，并要求该提交属于 `main` 历史。仓库管理员需创建 `ios-release` GitHub Environment，配置必要审批人，限制只允许受保护标签部署，并为标签建立匹配的 Ruleset。普通分支和 PR 无法自动获得该环境的 Secret。

工作流固定使用 `macos-26`，但仍会从实际 `xcodebuild -version` 读取并验证 Xcode 主版本，不根据 Runner 标签推断上传资格。两个模式的边界如下：

| 模式 | 行为 | 能否证明发布完成 |
|---|---|---|
| `validate-only` | 校验正式参数和截图，创建签名 Archive，导出 IPA，检查 `codesign`、Bundle/版本/Team/描述文件、HTTPS 服务地址和 IPA SHA-256 | 不能；没有上传 |
| `upload-testflight` | 完成同一套实包门禁后，使用 App Store Connect API Key 上传该 IPA | 不能单独证明；还需等待 Apple 处理、检查警告并完成 TestFlight 验收 |

工作流只保留不含 Secret 的 JSON 报告，不上传 IPA、证书、描述文件、私钥或钥匙串。报告记录 Bundle ID、版本、构建号、Team、发行身份、描述文件 UUID/有效期、Xcode 版本、IPA 大小和 SHA-256，便于与 App Store Connect 构建核对。

### Environment 参数

以下 GitHub Environment Variables 是公开发布参数，不应写回仓库占位配置：

| 变量 | 说明 |
|---|---|
| `SMARTSCAN_IOS_BUNDLE_ID` | 正式 Bundle ID |
| `SMARTSCAN_APP_STORE_ID` | App Store Connect 数字 App ID |
| `SMARTSCAN_APP_STORE_SKU` | 不可复用的 SKU |
| `SMARTSCAN_APPLE_TEAM_ID` | 10 位 Apple Team ID |
| `SMARTSCAN_IOS_MARKETING_VERSION` | 与标签一致的 `X.Y.Z` |
| `SMARTSCAN_IOS_BUILD_NUMBER` | 与标签一致的正整数构建号，每次上传递增 |
| `SMARTSCAN_API_BASE_URL` | 生产 API HTTPS 根地址 |
| `SMARTSCAN_PRIVACY_POLICY_URL` | 公网隐私政策 HTTPS 地址 |
| `SMARTSCAN_SUPPORT_URL` | 公网支持 HTTPS 地址 |

以下值必须配置为 GitHub Environment Secrets：

| Secret | 说明 |
|---|---|
| `SMARTSCAN_IOS_DISTRIBUTION_CERTIFICATE_BASE64` | Base64 编码的发行 P12 |
| `SMARTSCAN_IOS_DISTRIBUTION_CERTIFICATE_PASSWORD` | P12 口令 |
| `SMARTSCAN_IOS_PROVISIONING_PROFILE_BASE64` | Base64 编码的 App Store 描述文件 |
| `APP_STORE_CONNECT_KEY_ID` | App Store Connect API Key ID |
| `APP_STORE_CONNECT_ISSUER_ID` | Issuer ID |
| `APP_STORE_CONNECT_PRIVATE_KEY_BASE64` | Base64 编码的 `.p8` 私钥 |
| `SMARTSCAN_REVIEW_USERNAME` | 普通审核账号 |
| `SMARTSCAN_REVIEW_PASSWORD` | 审核账号口令 |
| `SMARTSCAN_REVIEW_SMS_CODE` | 当次审核可用的取码说明或受控验证码值 |

Secret 不应出现在工作流输入、仓库变量、Artifact、日志或 PR 描述中。运行审批者需先核对标签、提交、版本和构建号；如果任一值需要变化，创建新构建号和新标签，不复用已上传构建。

## 发布前人工输入

由 Account Holder 或被授权的 Admin/App Manager 在外部密码管理器和 GitHub Environment 中完成：

1. 冻结正式 Bundle ID、SKU、App Store Connect App ID、Apple Team ID、版本号和构建号。
2. 配置生产 API、隐私政策和支持页的公开 HTTPS 地址；三个地址都必须可从公网访问。
3. 将发行证书、证书口令、描述文件和 App Store Connect API Key 保存到受保护环境，不写入仓库、日志或 PR。
4. 在 App Store Connect 安全审核字段填写普通用户审核账号和当期短信取码方式，不使用管理员或超级管理员。
5. 确认协议、税务、出口合规、年龄分级、内容版权和地区可用性。需要法务或业务所有者确认的内容不能由 CI 代签。

## Archive 与上传顺序

1. 从 `main` 上已通过普通 CI 的提交创建 `ios-vX.Y.Z-build.N` 受保护标签，重新核对 Apple 当前要求与 Xcode 版本。
2. 先人工触发 `iOS 正式发布` 工作流的 `validate-only`，审批 `ios-release` Environment；修复正式参数、截图、签名或实包错误后必须重新运行。
3. 下载脱敏报告，核对 IPA SHA-256、Bundle ID、版本、构建号、Team、发行描述文件有效期和 Xcode 版本；同时检查 Privacy Report、Entitlements 和导出合规结果。
4. 对同一受保护标签人工触发 `upload-testflight`。构建由 Bundle ID、版本号与构建号共同标识；重复构建必须递增构建号。
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

`validate-only` 没有外部副作用，可以在修复后重跑。已经上传的构建不能用同一构建号覆盖；不要删除标签后用同名标签指向其他提交。发现签名材料泄露时应立即撤销证书或 API Key、轮换 Environment Secret，并把相关构建停止测试。脱敏报告只能帮助定位构建，不能替代 Apple 的处理状态和人工验收记录。

## 未通过门禁

- 正式 Bundle ID、Team、App Store Connect App、签名材料、GitHub `ios-release` Environment、受保护标签规则与公开 URL 未冻结。
- IOS-005 与 IOS-006 已在仓库公开后通过 macOS Runner；该证据仅覆盖 Simulator 编译、单元测试和隐私清单打包。
- REL-002 的工作流、归档脚本和合成实包校验已有仓库测试；真实签名 Archive、Apple 处理、TestFlight、真机相机/后台/分享、真实短信与企业微信均未验收。
- 截图文件尚未生成；仓库只包含场景和尺寸清单。
