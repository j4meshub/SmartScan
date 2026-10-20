# API 接口约定说明

FastAPI 服务在 `/openapi.json` 发布规范的 OpenAPI 文档。

仓库保存完整契约快照 `packages/contracts/openapi.json`。任何接口、字段、状态码或响应模型变更都必须先确认兼容性，再更新快照和相关客户端；仅重构内部实现不得改变该文件。测试会将运行时 OpenAPI 与快照进行结构化比较。

- 用户端只通过 `/v1/projects`、`/v1/pages` 和 `/v1/jobs` 访问当前登录用户的数据。
- 分片上传使用 `/v1/uploads` 创建或恢复会话，通过 `/v1/uploads/{id}/chunks/{index}` 上传分片，并通过 `/v1/uploads/{id}/complete` 幂等完成。
- 跨用户访问仅允许通过 `/v1/admin/*`，并且必须写入审计日志。
- 不存在和无权访问的对象标识统一返回 `404`。
- 未配置外部 AI 供应商时，基础处理流程仍可成功完成；AI 仅作为可选增强能力。

