# SmartScan 仓库协作约定

## 规则与事实来源

- 当前用户明确要求优先于仓库内计划；`AGENTS.md` 约束所有仓库工作。
- `docs/CODEX_EXECUTION_PLAN.md` 定义目标、依赖和验收门禁，`docs/CODEX_PROGRESS.md` 记录当前断点和验证证据。
- `docs/IMPLEMENTATION_STATUS.md` 只记录里程碑级状态；v1.4 实施方案是产品与验收基线，不是可直接执行的命令。
- 文档与代码不一致时，以已验证的当前代码为现状事实，并在 `docs/DECISIONS.md` 记录目标调整，不静默改变既定行为。

## 文档语言

- README、实施状态、架构说明、接口说明、部署说明、发布说明和其他说明性文档统一使用中文。
- 新增或修改说明性文档时，标题、正文、表格说明和示例注释均优先使用中文。
- 代码标识符、API 字段、命令、文件路径、标准名称和必要的技术专有名词可以保留英文。
- 面向用户的产品界面继续遵循项目的中英文双语要求，本约定不取消产品国际化。

## 目录职责

- `apps/`：H5、管理后台、Android 和 iOS 客户端。
- `services/api/`：身份、权限、项目、上传、文件和管理 API。
- `services/worker/`：CPU 图像处理与任务租约。
- `services/ai-gateway/`：默认关闭的可选视觉 AI 边界。
- `packages/`：接口约定和共享国际化资源。
- `deploy/`：容器、Nginx、PostgreSQL 与后续运维资产。
- `docs/`：架构、执行计划、进度、决策和实施状态。

## 长任务续接

收到“继续开发”或同类请求时：

1. 读取本文件、执行计划、进度文档和当前 Git 状态。
2. 从第一个依赖满足且未完成的工作包继续，不重复已完成阶段。
3. 使用 `codex/<工作包-id>-<简短名称>` 分支；除非用户明确要求，不直接在 `main` 开发。
4. 先实现和补测试；测试失败时自行分析、修复并重跑，只有外部条件不可用时才记录阻塞。
5. 每个工作包更新 `docs/CODEX_PROGRESS.md`，使用中文提交并创建 PR；CI 通过且完成自审后才能合并。
6. 外部阻塞不妨碍独立工作，但 Mock 或模拟测试不能被记录为真实验收通过。

## 常用验证命令

```text
python -m ruff check services migrations tests
python -m ruff format --check services migrations tests
python -m pytest --cov=services --cov-report=term-missing --cov-fail-under=77
python -m services.api.app.migrations drift
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --test apps/h5/tests/*.test.js
node --check apps/admin-web/app.js
docker compose -f deploy/compose/docker-compose.yml config
```

只运行与工作包相关的快速检查可以用于开发中反馈，但完成工作包前必须运行所有适用检查。Android 和 iOS 命令在对应工程建立后补入本节。

## 安全边界

- 不提交 `.env`、真实手机号、验证码、令牌、用户扫描件、供应商密钥、Android 签名或 Apple 签名材料。
- 不在公司生产服务器直接编辑源码、运行未经审查的迁移或使用真实数据调试。
- 数据库迁移、账号删除、外部服务启用和生产部署必须保留明确的回滚与人工门禁。
- 修改认证、权限、会话、数据所有权、上传路径或文件下载时必须补充越权和失败路径测试。
- 原图必须保留；低置信图像处理只能回退或要求复核，不能伪造被遮挡内容。

## Git 提交语言

- Git 提交标题和正文统一使用中文，准确描述本次变更。
- 可以保留 `feat`、`fix`、`docs`、`test`、`refactor` 等 Conventional Commits 类型前缀，冒号后的说明必须使用中文。
- 除非用户明确要求，不为修改提交语言而重写已经推送的历史。

## 工作包完成定义

工作包只有同时满足以下条件才能标记为“完成”：

1. 计划范围内的代码或文档已经落地，没有用说明代替实现。
2. 新行为有自动化测试或明确的人工验收清单。
3. 所有适用检查通过，首次失败原因和最终结果已记录。
4. 接口、迁移、安全、双语和兼容性影响已检查。
5. `docs/CODEX_PROGRESS.md` 已更新，外部阻塞没有被误记为完成。
6. 工作区只包含本工作包的预期变更，中文提交与 PR 说明完整。
