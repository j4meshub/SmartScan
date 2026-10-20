# 作业状态机、租约与恢复

## 状态语义

处理作业使用以下生命周期，页面质量和人工复核继续由页面状态独立表达：

```text
queued -> baseline_processing -> baseline_ready -> ready
                              \-> optional_enhancing -> ready
baseline_processing -> failed_retryable -> baseline_processing
baseline_processing -> failed_final
queued / processing / retryable -> canceled
```

- `queued`：已受理且等待 CPU Worker。
- `baseline_processing`：Worker 持有有效租约并执行确定性基础处理。
- `baseline_ready`：基础结果已经登记；当前外部增强默认关闭，因此同一事务立即进入 `ready`，并保留 `baseline_ready_at` 证据。
- `optional_enhancing`：为后续默认关闭的可选增强保留，核心流程不依赖它。
- `ready`：基础结果可预览和导出。
- `failed_retryable`：未达到尝试上限，经过指数退避后可重新领取。
- `failed_final`：达到自动尝试上限，需要所有者显式重试或人工调查。
- `canceled`：所有者取消，旧 Worker 的租约令牌立即失效。

## 租约与崩溃恢复

每次领取生成新的随机 `lease_token`，同时记录 `lease_owner`、`heartbeat_at` 和 `lease_until`。只有同时持有当前令牌且作业仍为 `baseline_processing` 的 Worker 才能续租、写入结果或提交失败。过期租约可由其他 Worker 使用新令牌抢占；旧 Worker 即使随后恢复，也无法提交页面版本。

Worker 在解码前和写结果前续租。处理结果文件先写入临时文件并原子落位，页面结果版本与作业 `ready` 在同一数据库事务提交。若进程在文件落位后、数据库提交前崩溃，重试仍使用数据库尚未占用的同一版本路径，收敛为一个结果记录，不重复生成页面。

租约时长由 `SMARTSCAN_JOB_LEASE_SECONDS` 配置，默认 300 秒。自动尝试次数默认 3 次；失败按 `SMARTSCAN_JOB_RETRY_BASE_SECONDS * 2^(attempts-1)` 退避，当前上限 300 秒。错误只保存稳定 `error_code` 和异常类型，不把扫描内容或完整内部路径写入响应。

## 取消、重试与接口

- `GET /v1/jobs`：列出当前所有者最近作业。
- `GET /v1/jobs/{id}`：所有者读取；管理员按既有角色矩阵只读并审计。
- `POST /v1/jobs/{id}/cancel`：所有者取消未终结作业并使当前租约失效。
- `POST /v1/jobs/{id}/retry`：所有者提前重试可重试失败，或对最终失败重置自动尝试计数后重新排队。

其他普通用户、管理员和超级管理员都不能替所有者取消或重试；无权与不存在统一返回 `404`，跨用户拒绝写入审计。`ready`、`failed_final` 和已经 `canceled` 的作业不能取消；非失败状态不能重试。

## 迁移与回滚

`20261020_0014` 将旧 PostgreSQL 原生枚举改为长度固定的状态字符串，便于以后按 expand/migrate/contract 增加阶段。旧状态映射如下：

| 旧状态 | 新状态 |
|---|---|
| `pending` | `queued` |
| `running` | `queued`，清空旧租约后重新领取 |
| `completed` / `needs_review` | `ready` |
| 未达上限的 `failed` | `failed_retryable` |
| 已达上限的 `failed` | `failed_final` |

降级到 `0013` 时，处理中和可重试状态回到 `pending`，就绪状态回到 `completed`，最终失败和取消回到 `failed`。新状态的阶段时间戳、租约令牌、错误码和结果版本关联会丢失；生产降级前必须停止全部 Worker 并导出非终结作业。
