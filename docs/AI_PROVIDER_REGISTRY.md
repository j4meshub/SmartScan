# 可选视觉 AI Provider 注册与配置

AI-001 为专业 OCR、OpenAI-compatible 视觉模型和自定义视觉模型建立统一注册边界。该服务只负责读取配置、选择适配器和报告脱敏状态，不会发送图片，也不参与基础扫描、净化、扫书或导出流程。

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
    "capabilities": ["document_understanding", "image_classification"]
  }
]
```

| 字段 | 约束 |
|---|---|
| `id` | 小写字母、数字和连字符，1～64 字符；同一注册表内唯一 |
| `kind` | `professional_ocr`、`public_vlm` 或 `custom_vlm` |
| `api_style` | `openai_chat`、`openai_responses` 或 `custom` |
| `enabled` | 默认 `false`；启用时必须同时提供地址、模型和密钥环境变量名 |
| `base_url` | 必须是无用户名、密码、查询参数和片段的 HTTPS 地址 |
| `api_key_env` | 只保存安全的环境变量名；实际值由运行环境 Secret 注入 |
| `capabilities` | 当前可声明 OCR、文档理解、图像分类和版面分析能力 |

OpenAI Chat/Responses 风格统一选择 `openai_compatible` 适配器；专业 OCR 的自定义协议选择 `professional_ocr`；其余自定义协议选择 `custom`。业务任务以后只依赖 Provider ID 和能力，不直接依赖具体供应商名称。

## 状态接口

- `GET /health`：返回注册、启用和已具备凭据的数量。
- `GET /v1/providers`：返回所有 Provider 的脱敏描述。
- `GET /v1/providers/{provider_id}`：返回单个脱敏描述；不存在时返回 `404 provider_not_found`。
- `POST /v1/providers/check`：只校验一份定义并返回适配器选择，不解析 DNS、不连接供应商、不发送媒体。

响应不会包含 `api_key_env` 或 Secret 值。`configured=true` 只表示被引用的环境变量非空，不代表供应商可访问、模型存在或账号配额充足。

## 容器运行

AI 网关位于可选 Compose Profile，不通过 Nginx 暴露：

```bash
docker compose --profile ai -f deploy/compose/docker-compose.yml up --build ai-gateway
```

生产环境应通过编排平台注入 `SMARTSCAN_AI_PROVIDERS` 与各 Provider 的密钥环境变量。不得把真实密钥写入 `.env.example`、Compose 文件、日志、PR 或文档。

## 当前边界与后续门禁

- AI-002 已提供七类任务/结果 JSON Schema、无网络请求计划和带 Provider/模型版本的候选证据信封；AI 网关仍不直接修改业务数据，真实调用与增强版本保存必须经过后续安全门禁和 Worker 活动版本核对。
- 当前只做 HTTPS 配置语法约束。DNS 重绑定、解析后连接固定、公网/受控网段策略、禁重定向、媒体来源和大小限制属于 AI-003，未完成前不得向 Provider 发送用户媒体。
- 超时、重试、熔断、并发、频率、费用和脱敏调用日志属于 AI-004。
- 固定数据集、准确率、幻觉率、延迟和成本报告属于 AI-005。

因此，AI-001 自动化通过只证明注册和密钥隔离边界可运行，不代表任何外部 AI 已经启用或验收。
