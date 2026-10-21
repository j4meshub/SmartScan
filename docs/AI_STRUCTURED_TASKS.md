# 可选视觉 AI 结构化任务与结果契约

AI-002 把视觉模型输入、输出和业务校验固定为版本化契约。模型只能返回候选证据，不能用自由文本直接修改项目、页面、原图、处理结果或导出。

请求计划本身继续保持 `network_ready=false`，不能被直接发送。AI-003 的执行接口只有在固定媒体前缀、限时令牌、DNS、公网/受控网段、连接固定、TLS、禁重定向和大小门禁全部通过后，才生成独立的 `network_ready=true` 网络证据并执行一次请求。

## 七类任务

| `task_type` | 所需能力 | 结构化结果 | 保守边界 |
|---|---|---|---|
| `classify_page` | `image_classification` | 普通文档、试卷、书页或封面及证据码 | 结果只能是调用方允许的标签 |
| `detect_orientation` | `image_classification` | `0/90/180/270` 和证据码 | 低置信只进入复核 |
| `extract_title` | `document_understanding` | 最多五个标题候选、来源和置信度 | 只作为候选，不覆盖用户标题 |
| `extract_page_number` | `ocr` | 检出状态、规范页码、原标签和样式 | 未检出时禁止携带猜测页码 |
| `ocr_formula` | `ocr` | 公式、表格单元格和版面块 | 只接受任务明确请求的块类型 |
| `review_cleanup_mask` | `document_understanding` | 每个候选区域的类型、动作和置信度 | 印刷内容/未知区域禁止删除；删除阈值至少 `0.9` |
| `review_book_split` | `document_understanding` | 单页/双页/不确定、书脊和左右框 | 阅读顺序必须与项目一致；不确定时禁止生成拆分几何 |

## 任务信封

每个任务包含：

- 固定 `schema_version=1.0`、不可预测 `task_id` 和枚举 `task_type`。
- `page_id`、基础结果版本、媒体资产 ID、媒体 SHA-256、MIME、像素尺寸和界面语言。
- 类型化参数，不接受任意 Prompt。
- 固定 `temperature=0.0`，输出上限限制在 64～4096 token。

媒体资产 ID 是内部引用，不是外部 URL。请求计划使用字面占位符 `$SMARTSCAN_MEDIA`；AI-003 在实际发送前把它替换为“Provider 固定媒体前缀 + 至少 128 位令牌”，并核对媒体大小、摘要、MIME 和过期时间。请求体不会包含用户 ID、原文件名、`base_url`、页面 ID 或媒体资产 ID；Provider 密钥只进入固定授权头。

## Provider 请求计划

注册表根据 `api_style` 生成三种确定性计划：

- `openai_responses`：`/responses`，使用严格 `json_schema` 文本格式。
- `openai_chat`：`/chat/completions`，使用严格 `response_format.json_schema`。
- `custom`：`/tasks`，携带任务类型、参数和结果 Schema。

计划生成前必须满足 Provider 已启用、凭据存在、支持图片且声明了任务所需能力。计划记录 Provider ID、模型版本、任务 ID、协议、路径、能力和 Schema，但 `network_ready=false`，不包含可直接出站的完整请求。

## 严格输出校验

Provider 原始输出必须是最大 64 KiB 的 UTF-8 JSON 对象。以下情况直接拒绝：

- Markdown 代码围栏、前后解释或其他非 JSON 文本；
- 重复 JSON 键、`NaN`/`Infinity`、数组顶层或非法 UTF-8；
- 未声明字段、错误类型、越界置信度、错误 Schema 版本；
- 任务 ID/类型与原请求不一致；
- 候选区域、阅读顺序、允许标签或请求块类型与任务不一致；
- 印刷内容/未知区域删除、低置信删除或虚构页码/拆分几何。

低置信、未检出、不确定、需要人工处理的结果返回 `disposition=review`；其余有效结果也只返回 `candidate`。两种状态的 `business_mutation_allowed` 都固定为 `false`。

通过校验后生成可追溯证据信封，包含 Provider ID/类型、API 风格、模型版本、结果 Schema SHA-256、任务 ID/类型、页面 ID、基础结果版本、媒体 SHA-256、处置状态和规范化结果。证据信封不包含密钥或 Provider 地址，后续 Worker 必须再次核对页面活动版本后才能保存新的增强结果版本，不能覆盖基础结果。

## 内部接口

- `GET /v1/task-schemas`：返回七类任务和结果的 JSON Schema、所需能力及结果 Schema SHA-256。
- `POST /v1/tasks/validate`：只校验并规范化任务，不联网。
- `POST /v1/tasks/{provider_id}/plan`：生成无网络请求计划。
- `POST /v1/tasks/{provider_id}/execute`：通过 AI-003 安全门禁执行一次请求，严格验证输出并返回候选与网络证据。
- `POST /v1/results/{provider_id}/validate`：接收原始 Provider JSON 字符串，返回规范化证据信封。

AI 网关只在内部 Compose 网络使用，当前未由 Nginx 暴露。以上接口不是面向客户端的 `/v1` 业务 API，不进入 H5、Android 或 iOS 的兼容快照。

## Schema 版本与快照

当前契约快照保存在 `packages/contracts/ai-tasks-v1.json`。CI 执行：

```bash
python tools/export_ai_schemas.py --check
```

修改模型导致快照变化时，必须先判断兼容性。兼容增加仍需更新快照和中文说明；删除字段、收紧既有合法值或改变语义时必须建立新 Schema 版本，不能在 `1.0` 下静默替换。

## 出站与后续边界

- AI-003 的地址、媒体、DNS 固定、TLS、禁重定向和大小门禁见[可选视觉 AI 出站网络与媒体安全](AI_NETWORK_SECURITY.md)。计划与执行仍分离，避免绕过传输门禁。
- AI-004：超时、一次重试、熔断、并发/频率/费用上限和脱敏调用日志。
- AI-005：固定数据集上的准确率、幻觉率、结构化成功率、延迟和成本报告。

当前测试使用合成任务和 Mock Provider，只证明契约与保守规则可重复，不代表任何真实模型质量、许可证、数据政策、价格或可用性已经验收。
