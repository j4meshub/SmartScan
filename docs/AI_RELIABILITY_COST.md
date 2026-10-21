# 可选视觉 AI 可靠性、熔断与费用门禁

AI-004 在 AI-003 的安全出站层外增加持久化可靠性门禁。网关继续位于独立 `ai` Profile，不经 Nginx 暴露；所有 Provider 默认关闭，外部 AI 关闭、超时、熔断或达到配额都不会影响上传、CPU 处理、预览、净化、扫书和导出。

## Provider 配置

每个 Provider 可配置以下字段：

| 字段 | 默认值 | 约束与含义 |
|---|---:|---|
| `timeout_seconds` | `90` | 单次 HTTPS 网络操作超时，范围 1～300 秒 |
| `max_retries` | `1` | 只允许 0 或 1；仅超时、DNS/传输故障、`408`、`429`、`5xx` 可重试 |
| `concurrency_limit` | `2` | Provider 独立并发上限，范围 1～32 |
| `requests_per_minute` | `10` | Provider 独立滚动一分钟出站尝试上限，范围 1～600 |
| `daily_cost_limit_usd` | `10.000000` | UTC 自然日保守费用上限，最多六位小数 |
| `max_cost_per_request_usd` | `0.050000` | 每次真实出站尝试的保守费用上界，最多六位小数 |
| `circuit_failure_threshold` | `3` | 连续供应商失败多少次后打开熔断器，范围 1～20 |
| `circuit_open_seconds` | `60` | 打开后等待时间，范围 5～3600 秒 |

`daily_cost_limit_usd` 必须至少覆盖一次最坏调用，即 `(max_retries + 1) × max_cost_per_request_usd`。金额统一转为整数微美元保存，避免浮点误差。

`max_cost_per_request_usd` 必须由运维按供应商计价、最大输入和最大输出设置为足够保守的上界。当前门禁不是供应商账单对账系统；真实单价、账单差异和固定数据集成本报告仍属于 AI-005 外部门禁。

## 调用顺序

1. PostgreSQL 按 Provider 取得事务级 advisory lock，并清理超过 360 秒租约的中断调用。
2. 检查熔断、并发和 UTC 日费用。调用先预留“初次请求加一次重试”的最坏费用，避免多个 Worker 同时越过日限额。
3. 每次尝试前检查滚动一分钟频率，并写入随机调用 ID 和尝试号。
4. 执行 AI-003 的媒体、DNS、固定 IP、TLS、禁重定向和大小门禁。
5. 仅当请求已进入 HTTPS 发送阶段时按配置上界计费；媒体摘要不匹配等本地预检失败保留审计但退回费用，也不占用供应商每分钟请求数。
6. Provider 输出通过严格结构化结果校验后关闭调用；输出被拒绝计为供应商失败，但仍不能直接修改业务数据。

调用、尝试和熔断状态分别保存在 `ai_provider_calls`、`ai_provider_attempts` 和 `ai_provider_states`。两个 Uvicorn Worker、进程重启和短暂崩溃共享同一状态；租约到期会释放并发槽并记录稳定错误码，不依赖进程内计数器。

## 重试与熔断

- `408`、`429`、`5xx`、DNS 解析故障、连接/读取超时和传输故障最多重试一次。
- `401`、`403` 视为凭据拒绝，`402` 视为未付费，立即打开熔断器。
- 连续可归因于 Provider 的失败达到阈值后打开熔断器。本地媒体校验、SSRF 拒绝、危险响应头和调用方契约错误不会累积供应商失败次数。
- 冷却期后只允许一个半开探针；成功会清零连续失败，失败会重新打开。半开期间其他调用返回 `ai_circuit_open`。
- 并发、频率和费用门禁分别返回 `ai_concurrency_limit_exceeded`、`ai_rate_limit_exceeded`、`ai_daily_cost_limit_exceeded`，HTTP 状态为 `429`；熔断返回 `503`。网关附带保守的 `Retry-After: 60`，调用方仍应回退基础结果。

## 脱敏证据与运行状态

结构化运行日志只包含：Provider ID、任务类型、随机调用 ID、结果、稳定错误码、尝试数、耗时、请求/响应字节数和微美元保守费用。数据库证据采用同一最小集合。

日志和可靠性表禁止保存：用户 ID、任务 ID、页面 ID、媒体 URL、媒体令牌、API Key、密钥环境变量名、模型原始输出、手机号或文件名。Provider 地址仍由 AI-003 配置边界保护。

内部接口 `GET /v1/providers/{provider_id}/runtime` 返回脱敏运行摘要：

- `circuit_state`、`consecutive_failures`、`open_until`；
- 当前活动调用数和最近一分钟真实出站尝试数；
- 当日保守费用 `charged_cost_microusd_today`。

该接口与网关本身都不通过 Nginx 暴露。若以后暴露到管理后台，必须先增加管理员鉴权、审计和最小权限路由，不得直接转发当前内部接口。

## 部署和回滚

AI 网关现在与 API、Worker 一样连接 PostgreSQL，并等待 `migrate` 成功后启动。生产设置 `SMARTSCAN_AUTO_MIGRATE=false`；迁移只能由独立 `migrate` 服务执行。

回滚代码前先停用全部 Provider，再确认没有 `in_progress` 调用，最后将数据库降级到 `20261021_0020`。降级只删除 AI 可靠性状态和脱敏调用证据，不修改扫描、账号或导出数据。

自动测试使用注入传输和隔离数据库验证一次重试、立即/阈值熔断、半开探针、租约恢复、并发、频率、费用、跨进程持久化语义和日志脱敏。它不代表真实供应商 SLA、价格、配额、账单、通知链路或目标服务器出口策略已经验收。
