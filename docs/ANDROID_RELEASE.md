# Android 正式签名与发布

## 范围与当前状态

`REL-001` 在仓库侧建立 Android 正式候选、不可变制品、签名更新频道、上一稳定版本证据和回滚流程。普通 GitHub CI 只验证代码、契约和 Android Debug 构建，不持有正式密钥；正式 APK 只能由 GitLab 受保护标签流水线生成。

仓库实现可自动证明：

- 标签、`versionCode`、`versionName` 和 APK 实包元数据一致；
- 当前 APK 与至少一个上一稳定 APK 使用相同包名和发布证书，且版本单调递增；
- APK 的包名、大小、SHA-256、单一当前证书和更新清单逐字段一致；
- 更新清单由独立 ECDSA P-256 私钥签名，并能用编入 APK 的公钥复验；
- APK 和该版本的清单、签名、候选报告永久写入 GitLab Generic Package Registry，`latest.json` 频道只发布已验证字节；
- 回滚只能重新发布一组已签名且与保存 APK 匹配的旧清单，不能现场改写版本或重新签署未知内容。

真实 GitLab 项目、受保护变量、正式 APK 证书、下载域名、目标手机升级、数据保留和系统安装器仍是人工门禁。仓库或 GitHub Actions 绿灯不能替代这些证据。

## 信任边界

发布使用两套彼此独立的密钥：

1. Android APK keystore 证明应用身份。客户端要求下载 APK 的当前签名证书与已安装应用一致。
2. ECDSA P-256 清单私钥证明当前更新频道授权了哪个不可变 APK。对应 DER SubjectPublicKeyInfo 的 Base64 公钥在构建时写入客户端。

任一私钥都不得进入仓库、普通作业制品、日志或 Pages。清单签名密钥泄露不能伪造 APK 签名；APK keystore 泄露也不能修改现有频道而不持有清单私钥。证书或清单公钥轮换不属于本基线，必须另行设计签名谱系和双信任过渡。

## 发布拓扑

```text
受保护标签 android-vX.Y.Z
  -> 固定 digest 的 Android 构建镜像
  -> 正式签名 APK
  -> 实包/上一版本/证书/版本校验
  -> 生成并签署 latest.json
  -> 用公开 P-256 公钥复验
  -> GitLab Generic Package Registry（不可变版本制品）
  -> GitLab Pages /android/latest.json 与 .sig（可变当前频道）
```

客户端先从固定 HTTPS 地址读取清单原始字节和签名，验签后再下载清单中的不可变 APK URL。`latest.json` 不携带临时令牌、查询参数或重定向地址。

## GitLab 受保护配置

所有私密变量必须设为 Protected 和 Masked；文件材料使用 GitLab File 类型。发布标签格式固定为 `android-vX.Y.Z`，且标签本身必须受保护。

| 变量 | 类型 | 用途 |
|---|---|---|
| `SMARTSCAN_ANDROID_BUILD_IMAGE` | 普通受保护变量 | 同时具备 JDK 17、Gradle 8.9、Android 35/Build Tools 35、Python 3.12、`apkanalyzer`、`apksigner`、`curl`、PyYAML 和 cryptography 的内部镜像；必须使用 digest，不能使用浮动标签 |
| `SMARTSCAN_ANDROID_KEYSTORE_FILE` | File Secret | 正式 APK keystore |
| `SMARTSCAN_ANDROID_KEYSTORE_PASSWORD` | Secret | keystore 密码 |
| `SMARTSCAN_ANDROID_KEY_ALIAS` | Secret | 正式签名别名 |
| `SMARTSCAN_ANDROID_KEY_PASSWORD` | Secret | 正式签名私钥密码 |
| `SMARTSCAN_ANDROID_MANIFEST_PRIVATE_KEY_FILE` | File Secret | ECDSA P-256 PEM 清单私钥 |
| `SMARTSCAN_UPDATE_PUBLIC_KEY` | 受保护公开参数 | 对应 P-256 公钥的 DER Base64；会编入 APK |
| `SMARTSCAN_ANDROID_PREVIOUS_VERSION_NAME` | 受保护公开参数 | 已保存在同一 Generic Package Registry 的上一稳定版本号；流水线按版本下载实包，不通过 CI 变量传递 APK |
| `SMARTSCAN_ANDROID_VERSION_CODE` | 受保护公开参数 | 正整数，必须高于上一稳定 APK |
| `SMARTSCAN_ANDROID_VERSION_NAME` | 受保护公开参数 | 与标签一致的 `X.Y.Z` 版本名 |
| `SMARTSCAN_ANDROID_MINIMUM_SUPPORTED_VERSION_CODE` | 受保护公开参数 | 正整数且不高于当前版本 |
| `SMARTSCAN_ANDROID_SIGNING_CERTIFICATE_SHA256` | 受保护公开参数 | 正式 APK 当前证书的 64 位小写十六进制 SHA-256 |
| `SMARTSCAN_API_BASE_URL` | 受保护公开参数 | 以 `/` 结尾的生产 HTTPS API 地址 |
| `SMARTSCAN_UPDATE_MANIFEST_URL` | 受保护公开参数 | 固定以 `/android/latest.json` 结尾的 Pages HTTPS 地址 |
| `SMARTSCAN_UPDATE_SIGNATURE_URL` | 受保护公开参数 | 与清单同源且路径为 `latest.json.sig` 的 HTTPS 地址 |

`CI_JOB_TOKEN` 由 GitLab 提供，仅用于当前作业上传 Generic Package，不写入清单或 APK URL。项目必须确认匿名目标客户端能读取公开包；若 GitLab 实例不允许匿名包下载，应使用不携带客户端凭据的独立 HTTPS 制品域名，不能把令牌放入 URL。

项目 Owner 还必须在 Package Registry 设置中关闭 Generic Package 的重复包名/版本。流水线会在上传前要求目标 APK 返回 `404`，因此同版本重跑和半成品会失败关闭；出现部分上传时先由有权限的维护者核对并清理该失败版本，禁止覆盖后继续。Pages 根目录包含非空中文 `index.html`，实际客户端只读取 `/android/latest.json` 和 `/android/latest.json.sig`。

## 正式发布步骤

1. 在隔离环境完成迁移、核心扫描、外部 AI 全关闭和上一客户端兼容回归。
2. 确认上一稳定 APK 已保存在同一 Generic Package Registry，并在真机确认它可安装、包名和证书正确；把已核对的版本号写入受保护变量。首个对外版本也必须先准备一个使用正式证书的内部稳定基线，不能跳过上一版本门禁。
3. 冻结版本、最低支持版本、API/频道 URL、APK 证书摘要与清单公钥；四眼复核两套私钥来源和备份。
4. 创建并保护 `android-vX.Y.Z` 标签。流水线必须完整通过 `android-release-candidate` 与 `android-release-pages`，不能手工上传替代校验失败的制品。
5. 从 Generic Package Registry 下载刚发布 APK，核对作业报告和 SHA-256；在至少一台从上一稳定版本升级的目标手机验证登录、离线队列、原图、项目、导出和再次检查更新。
6. 先小范围分发并观察崩溃、登录、上传、处理和存储指标；只有外部验收记录完成后才扩大分发。

构建前门禁会拒绝 HTTP、带凭据/查询参数/片段的地址、不同源清单和签名、非 P-256 公钥、无效版本以及会静默关闭更新能力的频道路径。构建后门禁使用 `apkanalyzer` 和 `apksigner` 读取实包，不相信文件名或流水线输入值。

## 回滚与前滚修复

Android 不允许用更低 `versionCode` 覆盖已经安装的新版本。因此这里的“回滚”只把 `latest` 频道恢复到一个已保存、已签名且验证匹配的旧稳定版本，用于阻止尚未升级的设备继续取得问题版本。

回滚时在受保护分支启动手工作业 `android-rollback-pages`，显式设置 `SMARTSCAN_ANDROID_ROLLBACK=true`，并提供 `SMARTSCAN_ANDROID_ROLLBACK_VERSION_NAME`。作业从该版本的 Generic Package 原样下载以下三项：

- `SmartScan-release.apk`：旧频道清单指向的不可变 APK；
- `latest.json`：当时发布的原始清单字节；
- `latest.json.sig`：当时发布的原始签名。

`SMARTSCAN_UPDATE_PUBLIC_KEY` 继续使用客户端当前信任公钥。

作业先验签并逐字段核对 APK，再原样发布清单和签名。不得编辑旧 JSON 后复用签名，不得把 Debug APK 当作回滚版本。已经安装问题版本的设备必须发布更高 `versionCode` 的修复版；若涉及数据格式变更，修复版需验证向前迁移和旧数据读取，不能依赖应用降级。

## 本地与普通 CI 校验

无需正式密钥即可执行：

```text
python tools/validate_android_release.py
python -m pytest tests/test_android_release.py tests/test_android_update_manifest.py -q
python -m ruff check tools/validate_android_release.py tests/test_android_release.py
python -m ruff format --check tools/validate_android_release.py tests/test_android_release.py
```

测试使用伪 APK 字节、模拟 Android SDK 元数据输出和临时 P-256 密钥，只验证失败关闭逻辑，不能被记录为正式签名或真机升级通过。

## 人工验收记录

解除 `REL-001` 门禁至少要保存以下不含 Secret 的证据：

- GitLab 项目、受保护标签和成功流水线 URL；
- Generic Package 重复版本已关闭的设置截图或审计记录；
- 固定 digest 构建镜像及工具版本；
- 当前和上一 APK 的版本、包名、证书 SHA-256、APK SHA-256 与大小；
- Generic Package 与 Pages 的无凭据 HTTPS 下载结果；
- 上一稳定版到当前版的目标真机升级、数据保留、系统安装器和更新轮询结果；
- 当前频道回滚对未升级设备的阻断结果，以及更高版本前滚修复演练；
- 发布批准人、时间、观察窗口、异常与处置。

任何一项缺失时，状态保持“等待人工验收”，生产发布总状态保持红色。
