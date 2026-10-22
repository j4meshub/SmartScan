# 可选视觉 AI Provider 注册与配置

AI-001 为专业 OCR、OpenAI-compatible 视觉模型和自定义视觉模型建立统一注册边界。AI-003 在该边界上增加安全出站传输，AI-004 增加持久化可靠性与费用门禁；网关仍不参与基础扫描、净化、扫书或导出流程。

## 默认关闭

未设置 `SMARTSCAN_AI_PROVIDERS` 或设置为空数组时，注册表包含三个关闭的内置定义：

| ID | 类型 | 适配器 | 默认能力 |
|---|---|---|---|
| `professional-ocr` | 专业 OCR | 自定义 OCR 协议 | OCR、版面分析 |
| `openai-compatible` | 公共 VLM | OpenAI-compatible Responses | 文档理解、图像分类、版面分析 |
| `custom-vlm` | 自定义 VLM | 自定义协议 | 文档理解、图像分类、版面分析 |

三项的 `enabled` 均为 `false`，不需要密钥，也不会产生出站请求。业务 API、CPU Worker 和客户端不依赖 AI 网关，因此不启动网关或全部 Provider 不可用时，核心流程保持原样。

## 配置格式

`SMARTSCAN_AI_PROVIDERS` 是 JSON 数组。示例只引用密钥环境变量名，不包含密钥值：

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
    "supports_images": true,
    "capabilities": ["document_understanding", "image_classification"],
    "media_url_prefixes": ["https://media.example/ai-media/"],
    "max_media_bytes": 20971520,
    "max_request_bytes": 524288,
    "max_response_bytes": 65536,
    "timeout_seconds": 90,
    "max_retries": 1,
    "concurrency_limit": 2,
    "requests_per_minute": 10,
    "daily_cost_limit_usd": "10.000000",
    "max_cost_per_request_usd": "0.050000",
    "circuit_failure_threshold": 3,
    "circuit_open_seconds": 60
  }
]
```

| 字段 | 约束 |
|---|---|
| `id` | 小写字母、数字和连字符，1～64 字符；同一注册表内唯一 |
| `kind` | `professional_ocr`、`public_vlm` 或 `custom_vlm` |
| `api_style` | `openai_chat`、`openai_responses` 或 `custom` |
| `enabled` | 默认 `false`；启用时必须同时提供地址、模型和密钥环境变量名 |
| `base_url` | 默认 443 端口、无凭据/查询/片段/歧义路径的 HTTPS DNS 地址；拒绝 IP 字面量 |
| `api_key_env` | 只保存安全的环境变量名；实际值由运行环境 Secret 注入 |
| `capabilities` | 当前可声明 OCR、文档理解、图像分类和版面分析能力 |
| `media_url_prefixes` | 固定媒体 HTTPS 前缀允许列表；不接受调用方提供完整 URL |
| `allowed_private_cidrs` | 仅 `custom_vlm` 可用的显式受控网段；公网 Provider 禁止设置 |
| `max_media_bytes` | 单个媒体声明大小，默认 20 MiB、最高 100 MiB |
| `max_request_bytes` | JSON 请求体，默认 512 KiB、最高 2 MiB |
| `max_response_bytes` | JSON 响应体，默认且最高 64 KiB |
| `timeout_seconds` | 单次 HTTPS 网络操作超时，默认 90 秒，范围 1～300 秒 |
| `max_retries` | 可重试供应商故障的重试次数，只允许 0 或 1 |
| `concurrency_limit` | Provider 独立并发上限，默认 2 |
| `requests_per_minute` | Provider 独立滚动一分钟真实出站上限，默认 10 |
| `daily_cost_limit_usd` | UTC 自然日保守费用上限，最多六位小数 |
| `max_cost_per_request_usd` | 单次真实出站尝试费用上界，必须按最坏计价设置 |
| `circuit_failure_threshold` | 打开熔断器前的连续供应商失败数，默认 3 |
| `circuit_open_seconds` | 熔断冷却时间，默认 60 秒 |

OpenAI Chat/Responses 风格统一选择 `openai_compatible` 适配器；专业 OCR 的自定义协议选择 `professional_ocr`；其余自定义协议选择 `custom`。业务任务以后只依赖 Provider ID 和能力，不直接依赖具体供应商名称。

## 状态接口

- `GET /health`：返回注册、启用和出站就绪的数量；`ready_count` 要求凭据与网络策略均完整。
- `GET /v1/providers`：返回所有 Provider 的脱敏描述。
- `GET /v1/providers/{provider_id}`：返回单个脱敏描述；不存在时返回 `404 provider_not_found`。
- `GET /v1/providers/{provider_id}/runtime`：返回内部使用的熔断、活动调用、频率和当日保守费用摘要；不返回业务标识或 Secret。
- `POST /v1/providers/check`：只校验一份定义并返回适配器选择，不解析 DNS、不连接供应商、不发送媒体。

响应不会包含 `api_key_env`、地址、网段、媒体前缀或 Secret 值。`configured=true` 只表示被引用的环境变量非空；`outbound_policy_configured=true` 只表示固定地址和媒体允许列表完整；`outbound_ready=true` 才表示配置与凭据都已具备，但仍不代表供应商可访问、模型存在或账号配额充足。

## 容器运行

AI 网关位于可选 Compose Profile，不通过 Nginx 暴露：

```bash
docker compose --profile ai -f deploy/compose/docker-compose.yml up --build ai-gateway
```

生产环境应通过编排平台注入 `SMARTSCAN_AI_PROVIDERS` 与各 Provider 的密钥环境变量。不得把真实密钥写入 `.env.example`、Compose 文件、日志、PR 或文档。容器默认只读、删除全部 Linux capabilities、启用 `no-new-privileges`，并只提供受限临时目录。

## 当前边界与后续门禁

当前注册表、结构化任务、安全传输、可靠性和评估能力属于 AI 基础设施。API、Worker 与客户端尚未创建或消费页面 AI 增强任务，不能据此宣称 SmartScan 已提供 AI 产品功能。后续业务闭环见[可选视觉 AI 业务接入架构](AI_BUSINESS_INTEGRATION.md)。

- AI-002 已提供七类任务/结果 JSON Schema、无网络请求计划和带 Provider/模型版本的候选证据信封；AI 网关仍不直接修改业务数据，增强版本保存必须经过后续 Worker 活动版本核对。
- AI-003 已实现 HTTPS 固定目标、全部 DNS 答案校验、解析后连接固定、TLS 原主机名验证、公网/受控网段策略、禁重定向、固定媒体前缀和请求/响应大小限制。完整说明见[可选视觉 AI 出站网络与媒体安全](AI_NETWORK_SECURITY.md)。
- AI-004 已实现可配置网络超时、一次重试、PostgreSQL 共享熔断/租约、并发/频率/UTC 日费用门禁和脱敏调用证据。完整说明见[可选视觉 AI 可靠性、熔断与费用门禁](AI_RELIABILITY_COST.md)。
- 固定数据集、准确率、幻觉率、延迟和成本报告属于 AI-005。

因此，自动化只证明注册、密钥隔离和安全传输边界可运行，不代表任何真实外部 AI 已经启用或验收。
