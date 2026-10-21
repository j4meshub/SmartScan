# 可选视觉 AI 出站网络与媒体安全

AI-003 在 AI 网关内建立真实出站前必须经过的 SSRF 门禁。Provider 仍默认关闭，网关仍不被 Nginx 暴露；只有启动配置、凭据、结构化任务、媒体引用、DNS 和请求限制全部通过后，`POST /v1/tasks/{provider_id}/execute` 才会执行一次 HTTPS 请求。

本工作包不改变核心扫描链路。AI 网关未启动、Provider 关闭、DNS 被拒绝或外部服务故障时，上传、CPU 处理、净化、扫书和导出仍独立运行。

## 固定目标而非任意 URL

- Provider 目标只能来自启动时加载的 `base_url`，调用方不能提交目标 URL、端口或路径。
- `base_url` 必须使用默认 443 端口的 HTTPS、合格 DNS 域名和无歧义路径；拒绝 IP 字面量、凭据、查询、片段、反斜杠、重复斜杠、百分号编码和目录穿越。
- 任务端点由 `api_style` 固定映射为 `/responses`、`/chat/completions` 或 `/tasks`，不会复制调用方提供的路径。
- 媒体地址不接受完整 URL。配置使用 `media_url_prefixes` 建立最多 16 个固定 HTTPS 前缀，调用方只提供前缀序号和不透明令牌；网关以“固定前缀 + 令牌”构造最终地址。

该策略遵循 [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html) 的服务端映射、允许列表、禁重定向和连接固定建议。

## DNS 与连接固定

每次请求执行以下步骤：

1. 分别解析 Provider 域名和媒体前缀域名的全部 IPv4/IPv6 地址。
2. 默认要求每个答案都是公网地址；空答案、非法地址，或公网与私网混合答案均失败关闭。
3. 永久拒绝未指定、回环、链路本地、多播和保留地址，包括云元数据常用的链路本地地址。
4. 自定义 VLM 可以通过 `allowed_private_cidrs` 显式声明受控网络；只接受 RFC1918、共享地址空间或 IPv6 ULA 内不宽于 IPv4 `/16`、IPv6 `/48` 的规范网段。公网 Provider 不能声明私网。
5. 从已校验结果中确定一个地址，底层套接字直接连接该 IP，不再按域名进行第二次 DNS 查询。
6. TLS 的 SNI、证书主机名验证和 HTTP `Host` 仍使用原始域名；最低 TLS 1.2，固定 HTTP/1.1，禁止代理隧道。

“先检查域名、HTTP 客户端再自行解析”仍存在 DNS 重绑定窗口，因此只做 DNS 预检查不能替代第 5、6 步。当前实现使用短连接，每次调用重新解析、校验和固定，不跨调用复用旧 IP。

## 媒体引用

`OutboundMediaReference` 包含：

| 字段 | 门禁 |
|---|---|
| `prefix_index` | 只能选择 Provider 配置中的固定媒体前缀 |
| `access_token` | URL-safe、不少于 128 位；仓库辅助函数实际生成 192 位随机令牌 |
| `byte_size` | 必须不超过 Provider 的 `max_media_bytes` |
| `sha256`、`mime_type` | 必须与结构化任务中的媒体摘要完全一致 |
| `expires_at` | 必须带时区，发送时至少剩余 30 秒且总剩余时间不超过 24 小时 |

令牌使用 `SecretStr` 保存，执行响应、Provider 状态和网络证据均不回显令牌或完整媒体 URL。实际提供图片的媒体服务必须使用安全随机函数签发同一令牌，并在任务/账号删除或管理员撤销时立即撤销资源；不得把用户 ID、手机号或原文件名放入固定前缀或令牌之外的路径。

对于自建 vLLM/SGLang，模型服务本身仍必须只允许这些媒体域名并禁用媒体重定向。vLLM 可使用 `--allowed-media-domains` 和 `VLLM_MEDIA_URL_ALLOW_REDIRECTS=0`；网关侧允许列表不能替代模型进程自身的出站防火墙。参见 [vLLM 多模态输入安全说明](https://docs.vllm.ai/en/stable/features/multimodal_inputs/)。

## 请求和响应限制

每个 Provider 可以配置：

| 字段 | 默认值 | 范围 |
|---|---:|---:|
| `max_media_bytes` | 20 MiB | 1 KiB～100 MiB |
| `max_request_bytes` | 512 KiB | 16 KiB～2 MiB |
| `max_response_bytes` | 64 KiB | 1 KiB～64 KiB |

请求只发送固定 `POST`、JSON、`Accept-Encoding: identity` 和 `Connection: close`；凭据只进入固定 `Authorization: Bearer` 头，控制字符、空白和非 ASCII 值会被拒绝。响应只接受 `2xx`、`application/json`、未压缩且非空的有限字节流；冲突或超限的 `Content-Length`、压缩内容、非 JSON 类型以及超过上限的分块响应均失败关闭。

任何 `3xx` 都返回 `provider_redirect_rejected`，不会读取 `Location` 或发起下一跳。底层传输不会读取系统 HTTP 代理配置。

## 配置示例

```json
[
  {
    "id": "vision-main",
    "display_name": "视觉主模型",
    "kind": "public_vlm",
    "api_style": "openai_responses",
    "enabled": true,
    "base_url": "https://vision.example/v1",
    "api_key_env": "VISION_API_KEY",
    "model": "vision-1",
    "capabilities": ["document_understanding", "image_classification"],
    "media_url_prefixes": ["https://media.example/ai-media/"],
    "max_media_bytes": 20971520,
    "max_request_bytes": 524288,
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

`GET /health` 的 `ready_count` 现在要求 Provider 已启用、凭据存在且 `base_url`/`media_url_prefixes` 出站策略完整。脱敏 Provider 描述只返回 `outbound_policy_configured`、`outbound_ready` 和稳定原因码，不返回地址、网段、前缀、密钥引用或 Secret。

## 执行与证据

`POST /v1/tasks/{provider_id}/execute` 只供内部网关调用，输入严格包含 `task` 和 `media`。成功响应包含：

- AI-002 的结构化候选证据；
- `network_ready=true`、固定连接、TLS 主机名验证、零重定向及请求/响应字节数；
- 不包含 Provider 地址、解析 IP、媒体域名、访问令牌或 API Key。

Provider 输出仍要经过 64 KiB 严格 JSON、任务身份和业务规则校验，`business_mutation_allowed` 继续固定为 `false`。AI-003 允许安全地执行单次请求，不代表结果可以覆盖基础版本。

## 仍属于后续工作包的范围

- AI-004：可配置超时、一次重试、熔断、并发/频率/日费用上限和脱敏运行日志。
- AI-005：真实 Provider、固定数据集、准确率、幻觉率、延迟、费用和版本评估。
- OPS：出口防火墙、VPN、域名/IP 允许列表、媒体服务撤销联调和供应商数据政策。

自动测试使用注入的 DNS 与传输桩，不访问真实 Provider。它证明地址分类、连接固定、SNI、禁重定向、媒体绑定和大小门禁可重复，不代表真实供应商证书、可用性、数据保留或费用已经验收。
