# Android 安全更新

## 信任模型

`AND-006` 为自有 GitLab APK 分发建立客户端安全边界，但不在仓库保存正式签名材料，也不把 Mock 或调试包当作正式发布验收。

更新信任链按以下顺序执行：

1. 客户端只从构建时固定的不含凭据、查询和片段的 HTTPS 地址读取原始 JSON 清单及独立签名文件，禁止重定向。
2. 使用构建时固定的 ECDSA P-256 公钥和 SHA-256 验证清单原始字节，验签失败时不解析或下载 APK。
3. 校验清单版本、包名、发布版本、最低支持版本、APK 地址、大小、SHA-256 和签名证书摘要。
4. APK 下载到应用私有 `cache/updates/` 临时文件，流式限制最大 500 MiB，并同时校验响应大小、实际大小和 SHA-256。
5. 使用 Android `PackageManager` 读取 APK 实包，校验包名、精确 `versionCode`、单一当前签名证书以及已安装应用的签名证书。
6. 文件提交到稳定缓存名后，用户仍须主动点击安装；打开系统安装器前再次校验文件大小、SHA-256 和 APK 元数据。
7. Android 未授权“安装未知应用”时只打开该应用的系统授权页；授权后用户返回并再次点击安装。应用不执行静默安装。

清单私钥与 APK 签名密钥是两套独立密钥。攻击者必须同时绕过固定清单公钥和 Android 已安装包签名约束，才能让篡改包进入系统安装界面。当前实现固定 APK 签名证书，不支持静默证书轮换；如需轮换，必须先设计 Android 签名谱系和上一稳定版本兼容流程。

## 清单格式

清单采用 UTF-8 紧凑 JSON，签名文件只包含 Base64 编码的 ECDSA DER 签名。当前 `schema_version` 固定为 `1`：

```json
{
  "apk_sha256": "64 位小写十六进制",
  "apk_signing_certificate_sha256": "64 位小写十六进制",
  "apk_size_bytes": 12345678,
  "apk_url": "https://updates.example.com/packages/SmartScan.apk",
  "minimum_supported_version_code": 10,
  "package_name": "com.smartscan.app",
  "published_at": "2026-10-21T00:00:00Z",
  "schema_version": 1,
  "version_code": 12,
  "version_name": "1.2.0"
}
```

清单生成器会直接从 APK 计算大小和 SHA-256，并拒绝 HTTP、URL 凭据、查询参数、片段、无时区发布时间、无效证书摘要及矛盾版本。它不会读取 APK 包名或签名证书，因此发布流水线仍必须先用 Android 官方构建工具核对 APK，再把实际证书摘要传入：

```text
python tools/android_update_manifest.py \
  --apk SmartScan-release.apk \
  --package-name com.smartscan.app \
  --version-code 12 \
  --version-name 1.2.0 \
  --minimum-supported-version-code 11 \
  --apk-url https://updates.example.com/packages/SmartScan-release.apk \
  --signing-certificate-sha256 <发布证书摘要> \
  --published-at 2026-10-21T00:00:00Z \
  --private-key <CI临时私钥路径> \
  --output latest.json \
  --signature-output latest.json.sig
```

私钥路径必须来自 CI 密钥文件变量并在作业结束后销毁；禁止提交私钥、keystore、密码、带令牌 URL、真实签名清单或正式 APK。

## Android 构建配置

以下 Gradle 属性全部为空时更新功能保持关闭，不访问任何默认服务器：

```text
SMARTSCAN_UPDATE_MANIFEST_URL=https://updates.example.com/latest.json
SMARTSCAN_UPDATE_SIGNATURE_URL=https://updates.example.com/latest.json.sig
SMARTSCAN_UPDATE_PUBLIC_KEY=<X.509 SubjectPublicKeyInfo 的 Base64>
```

三项必须同时存在且两个地址必须为安全 HTTPS URL，否则 `AndroidUpdateManager` 不创建。公钥可以进入客户端，但正式值、GitLab 项目、更新域名、APK 包名和证书仍需在 `REL-001` 前冻结。

## 检查与安装体验

- 登录后的设置页在启动时检查；上次成功检查不足 24 小时时不重复访问网络。
- 用户可以手动强制检查。网络失败和验签失败不更新时间戳，因此下次仍可重试。
- `minimum_supported_version_code` 高于当前版本时显示“必须更新”，但安装仍交由 Android 系统和用户确认。
- 下载、校验和安装为三个明确阶段；未通过任何校验时不暴露 FileProvider URI。
- `FileProvider` 只新增应用私有 `cache/updates/`，不开放其他缓存或文件目录。

## 验证与外部门禁

自动测试覆盖清单篡改、包名、版本、最低版本、URL 凭据、证书摘要、APK 哈希、APK 身份规则、24 小时检查策略和生成器签名。GitHub CI 负责 Android 编译、单元测试和 Lint。

以下仍需 `REL-001` 或真机人工验收：GitLab Generic Package Registry、正式清单公钥、正式 APK keystore、CI 受保护变量、系统未知来源授权、Android 安装器、升级后数据保留、上一稳定版本兼容及回滚。没有这些证据时不得声明正式签名分发通过。
