# 可选视觉 AI 出站网络与媒体安全

AI-003 在 AI 网关内建立真实出站前必须经过的 SSRF 门禁，AI-013 在该边界内把默认媒体路径改为“网关内部取图后主动上传”。Provider 仍默认关闭，网关仍不被 Nginx 暴露；只有部署配置、内部鉴权、媒体摘要、DNS、TLS 和请求限制全部通过后，`POST /v1/tasks/{provider_id}/execute` 才会产生真实 Provider 请求。

本工作包不改变核心扫描链路。AI 网关未启动、Provider 关闭、DNS 被拒绝或外部服务故障时，上传、CPU 处理、净化、扫书和导出仍独立运行。

## 固定目标而非任意 URL

- Provider 目标只能来自启动时加载的 `base_url`，调用方不能提交目标 URL、端口或路径。
- `base_url` 必须使用默认 443 端口的 HTTPS、合格 DNS 域名和无歧义路径；拒绝 IP 字面量、凭据、查询、片段、反斜杠、重复斜杠、百分号编码和目录穿越。
- 任务端点由 `api_style` 固定映射为 `/responses`、`/chat/completions` 或 `/tasks`，不会复制调用方提供的路径。
- 默认主动上传不向 Provider 发送 SmartScan 媒体 URL 或媒体授权令牌。只有显式选择 `signed_url` 时，才使用 `media_url_prefixes` 的固定 HTTPS 前缀加不透明令牌。

该策略遵循 [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html) 的服务端映射、允许列表、禁重定向和连接固定建议。

## DNS 与连接固定

每次请求执行以下步骤：

1. 解析 Provider 域名的全部 IPv4/IPv6 地址；只有 `signed_url` 兼容模式还解析媒体前缀域名。
2. 默认要求每个答案都是公网地址；空答案、非法地址，或公网与私网混合答案均失败关闭。
3. 永久拒绝未指定、回环、链路本地、多播和保留地址，包括云元数据常用的链路本地地址。
4. 自定义 VLM 可以通过 `allowed_private_cidrs` 显式声明受控网络；只接受 RFC1918、共享地址空间或 IPv6 ULA 内不宽于 IPv4 `/16`、IPv6 `/48` 的规范网段。公网 Provider 不能声明私网。
5. 从已校验结果中确定一个地址，底层套接字直接连接该 IP，不再按域名进行第二次 DNS 查询。
6. TLS 的 SNI、证书主机名验证和 HTTP `Host` 仍使用原始域名；最低 TLS 1.2，固定 HTTP/1.1，禁止代理隧道。

“先检查域名、HTTP 客户端再自行解析”仍存在 DNS 重绑定窗口，因此只做 DNS 预检查不能替代第 5、6 步。当前实现使用短连接，每次调用重新解析、校验和固定，不跨调用复用旧 IP。

## 主动媒体传输与内部取图

| 模式 | 使用条件 | 行为与证据 |
|---|---|---|
| `inline_data_url` | 默认；OpenAI Chat/Responses 或兼容服务接受内联图片 | 将已验证字节编码为 `data:<mime>;base64,...`；授权令牌不离开网关 |
| `multipart` | 仅 `custom` 协议 | 同一 HTTPS 请求发送受限 JSON `payload` 和二进制 `media` |
| `files_api` | 仅 OpenAI Responses 风格 | 先上传 `/files`，任务请求只使用受限文件 ID，并在 `finally` 中删除临时文件；删除失败会使调用失败 |
| `signed_url` | 默认关闭的兼容兜底 | 使用固定 `media_url_prefixes` 加高熵令牌；需单独审批可达性和暴露边界 |

主动模式下，AI 网关使用部署级内部 Bearer Token 和单页媒体授权调用固定的 `GET /v1/internal/ai-media`。API 会重新校验任务、项目授权、所有者、页面活动版本、有效期和撤销状态；网关拒绝重定向、非成功状态和错误 MIME，并将实际字节数和 SHA-256 与媒体授权及结构化任务再次比对。该内部路径不进入 OpenAPI，Nginx 对用户入口明确返回 `404`。

`OutboundMediaReference` 始终携带 URL-safe 且不少于 128 位的授权令牌、字节数、SHA-256、MIME 和带时区有效期；发送时至少剩余 30 秒且不超过 24 小时。只有 `signed_url` 使用 `prefix_index` 和前缀摘要。令牌只出现在内部请求头，不进入 Provider 请求、执行响应、网络证据或日志路径。

系统没有 Provider 自动故障切换。公司 Provider 失败时保留基础结果，不会自动把页面发送给外部供应商。Files API 上传响应若不能提供合法文件 ID会失败关闭；真实验收还必须确认 Provider 对这类无法定位对象的自动过期策略。

## 请求和响应限制

每个 Provider 可以配置：

| 字段 | 默认值 | 范围 |
|---|---:|---:|
| `max_media_bytes` | 20 MiB | 1 KiB～100 MiB |
| `max_request_bytes` | 32 MiB | 16 KiB～140 MiB |
| `max_response_bytes` | 64 KiB | 1 KiB～64 KiB |

提高请求上限是为了容纳 base64 膨胀和 multipart 边界，不改变单页媒体上限。请求只发送固定目标、`Accept-Encoding: identity` 和 `Connection: close`；Files API 只额外使用固定 `/files` 上传和删除路径。凭据只进入固定 `Authorization: Bearer` 头，控制字符、空白和非 ASCII 值会被拒绝。响应只接受 `2xx`、`application/json`、未压缩且非空的有限字节流；冲突或超限的 `Content-Length`、压缩内容、非 JSON 类型以及超过上限的分块响应均失败关闭。

任何 `3xx` 都返回 `provider_redirect_rejected`，不会读取 `Location` 或发起下一跳。底层传输不会读取系统 HTTP 代理配置。

## 配置示例

```json
[
  {
    "id": "company-vision",
    "display_name": "公司视觉模型",
    "kind": "custom_vlm",
    "api_style": "openai_responses",
    "enabled": true,
    "base_url": "https://vision.corp.example/v1",
    "api_key_env": "COMPANY_VISION_API_KEY",
    "model": "company-vlm-1",
    "capabilities": ["document_understanding", "image_classification"],
    "media_transfer_mode": "inline_data_url",
    "allowed_private_cidrs": ["10.20.0.0/16"],
    "max_media_bytes": 20971520,
    "max_request_bytes": 33554432,
    "max_response_bytes": 65536
  }
]
```

自定义受控网络示例只展示网段字段，实际地址和密钥不得进入仓库：

```json
{
  "kind": "custom_vlm",
  "allowed_private_cidrs": ["10.20.0.0/16", "fc00:1234::/48"]
}
```

`GET /health` 的 `ready_count` 要求 Provider 已启用、凭据存在且对应传输策略完整。主动模式不需要媒体前缀；`signed_url` 必须配置固定前缀。脱敏 Provider 描述只返回 `outbound_policy_configured`、`outbound_ready` 和稳定原因码，不返回地址、网段、前缀、密钥引用或 Secret。

## 执行与证据

`POST /v1/tasks/{provider_id}/execute` 只供内部网关调用，输入严格包含 `task` 和 `media`。成功响应包含：

- AI-002 的结构化候选证据；
- `network_ready=true`、固定连接、TLS 主机名验证、零重定向及请求/响应字节数；
- 传输模式、请求/响应字节数，以及 Files API 是否完成临时文件删除；
- 不包含 Provider 地址、解析 IP、远端文件 ID、媒体域名、访问令牌或 API Key。

Provider 输出仍要经过 64 KiB 严格 JSON、任务身份和业务规则校验，`business_mutation_allowed` 继续固定为 `false`。AI-003 允许安全地执行单次请求，不代表结果可以覆盖基础版本。

## 仍属于后续工作包的范围

- AI-004 已完成：可配置网络超时、一次重试、持久化熔断、并发/频率/日费用上限和脱敏运行证据，见[可选视觉 AI 可靠性、熔断与费用门禁](AI_RELIABILITY_COST.md)。
- AI-005/AI-012：真实 Provider、固定数据集、准确率、幻觉率、延迟、费用、临时文件过期和数据政策评估。
- OPS：出口防火墙、VPN、域名/IP 允许列表、内部媒体鉴权联调和供应商数据政策。

自动测试使用注入的内部媒体、DNS 与传输桩，不访问真实 Provider。它覆盖 data URL、multipart、Files API 成功与失败清理、签名兼容、地址分类、连接固定、SNI、禁重定向、MIME/大小/哈希和响应门禁；不代表真实供应商证书、协议兼容、数据保留或费用已经验收。
