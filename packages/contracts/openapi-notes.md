# API 接口约定说明

FastAPI 服务在 `/openapi.json` 发布规范的 OpenAPI 文档。

仓库保存完整契约快照 `packages/contracts/openapi.json`。任何接口、字段、状态码或响应模型变更都必须先确认兼容性，再更新快照和相关客户端；仅重构内部实现不得改变该文件。测试会将运行时 OpenAPI 与快照进行结构化比较。

上一代客户端基线保存在 `openapi-baseline.json`，客户端消费矩阵和弃用登记保存在 `compatibility-policy.json`。`python tools/api_compatibility.py` 禁止删除旧操作/字段、增加必填项或修改枚举等破坏性变更。完整规则见[契约冻结与客户端兼容](../../docs/API_COMPATIBILITY.md)。

- 用户端只通过 `/v1/projects`、`/v1/pages` 和 `/v1/jobs` 访问当前登录用户的数据。
- 分片上传使用 `/v1/uploads` 创建或恢复会话，通过 `/v1/uploads/{id}/chunks/{index}` 上传分片，并通过 `/v1/uploads/{id}/complete` 幂等完成。
- 管理员跨用户读取只允许接口明确支持的资源，并且必须写入审计；跨用户写入仍使用专门管理接口或拒绝。
- 作业使用 `queued`、基础处理/就绪、可选增强、`ready`、分级失败和 `canceled` 状态；详情、取消和重试接口均按所有者隔离。
- 项目响应增量提供 `suggested_name` 及来源；页面响应增量提供与活动结果版本绑定的 OCR 状态、全文、行框、模型、置信度、方向和安全标题候选。旧客户端可忽略新增字段。
- 不存在和无权访问的对象标识统一返回 `404`。
- 未配置外部 AI 供应商时，基础处理流程仍可成功完成；AI 仅作为可选增强能力。

