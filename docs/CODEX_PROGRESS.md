# SmartScan 长任务进度

更新时间：2026-10-20

## 当前断点

| 项目 | 当前值 |
|---|---|
| 当前里程碑 | M0 工程基础 |
| 当前工作包 | `ARC-001` API 分层 |
| 工作包状态 | 进行中，现状边界已盘点 |
| 当前分支 | `codex/arc-001-api-layers` |
| 最后验证基线 | `91ff720`（DB-001 PR #2 已合并） |
| 工作包提交 | 待创建 |
| PR | 待创建 |
| 下一工作包 | `QA-001` 测试与 CI 基线 |

## 当前工作包进展

- 已确认当前 `services/api/app/main.py` 共 795 行，包含启动、认证、项目、上传、文件、任务和管理后台等职责。
- 已按认证、项目、上传/文件、任务、管理后台划分路由边界；公共查询与业务规则将分别进入存储层和服务层。
- 拆分必须保持既有路径、状态码、响应模型、依赖注入、统一 `404` 行为和 OpenAPI 行为不变。

## 最近一次完整验证

`DB-001` 合并前执行了以下检查，作为 `ARC-001` 的回归基线：

```text
python -m ruff check services migrations tests
python -m ruff format --check services migrations tests
python -m pytest --cov=services --cov-report=term-missing
python -m alembic check
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/admin-web/app.js
git diff --check
```

验证结果：

- Ruff 检查通过，28 个 Python 文件格式检查通过。
- 本地 Pytest 通过：`15 passed, 2 skipped`，服务端覆盖率 `79%`；新增 5 项 SQLite 迁移测试，覆盖空库、旧基线、残缺基线、版本门禁和回滚再升级。2 项本地跳过的 PostgreSQL 测试随后已由 PR CI 执行。
- PR CI 使用 PostgreSQL 17 实际执行全部迁移测试：`17 passed`、无跳过、服务端覆盖率 `79%`。
- Alembic 元数据漂移检查通过：`No new upgrade operations detected`。
- 当前本地数据库版本检查通过。
- PostgreSQL 离线迁移 SQL 生成通过，包含 `0001` 结构基线与 `0002` 保护约束。
- H5 和管理后台 JavaScript 语法检查通过。
- `git diff --check` 通过，仅有 Windows LF/CRLF 提示。
- GitHub Actions、GitLab CI 和 Compose YAML 语法解析通过。
- 当前 Windows 环境未安装 Docker；Compose 语义检查已由 PR CI 通过，真实公司环境的 PostgreSQL 迁移仍保留外部门禁。

## 外部阻塞

| 门禁 | 状态 | 解除条件 |
|---|---|---|
| 公司 staging 与目标主机负载 | 阻塞 | 提供可隔离的数据库、数据目录和域名/端口 |
| 企业微信真实身份与手机号 | 等待人工验收 | 提供 CorpId、AgentId、Secret、可信域名及测试成员权限 |
| 真实短信 | 等待人工验收 | 冻结供应商、签名、模板、密钥和限频参数 |
| Android 正式签名分发 | 等待人工验收 | 冻结包名、签名资产和 GitLab 发布位置 |
| iOS 真机与 App Store | 等待人工验收 | 冻结 Team、Bundle ID、地区、隐私与支持 URL，并使用 Mac 完成门禁 |

外部阻塞不会阻止 Mock、契约、算法、客户端和本地部署工作；模拟结果不得把上述门禁改为“完成”。

## 已完成证据

| 工作包/基线 | 提交 | 验证摘要 |
|---|---|---|
| 初始平台基线 | `f35b742` | 初始 API、Worker、客户端骨架、CI 与部署布局 |
| 中文文档规范 | `13903b3` | 中文说明文档和提交规范 |
| 分片上传与断点续传 | `38df17a` | 7 项测试通过；分片、哈希、幂等和隔离 |
| 文档透视校正 POC | `1d5a9d6` | 10 项测试通过；OpenCV 透视和保守回退 |
| 长任务治理 | `dde779e` | Ruff、格式、10 项 Pytest、H5、后台及 Compose CI 通过；PR #1 已合并 |
| 版本化数据库迁移 | `91ff720` | 本地 15 项通过；PR CI 17 项通过且 PostgreSQL 测试无跳过；PR #2 已合并 |

## 下一步

1. 先增加路由清单/OpenAPI 回归证据，再移动代码，避免拆分过程中静默改变契约。
2. 将应用装配与生命周期保留在 `main.py`，按认证、项目、上传/文件、任务和管理职责拆分路由。
3. 将跨路由业务规则移入服务层，将 SQLAlchemy 查询和锁定操作移入存储层。
4. 全量测试和 CI 通过后更新架构说明，提交并创建 `ARC-001` PR。
