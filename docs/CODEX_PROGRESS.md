# SmartScan 长任务进度

更新时间：2026-10-20

## 当前断点

| 项目 | 当前值 |
|---|---|
| 当前里程碑 | M0 工程基础 |
| 当前工作包 | `QA-001` 测试与 CI 基线 |
| 工作包状态 | 完成，PR CI 已通过，等待合并 |
| 当前分支 | `codex/qa-001-test-ci-baseline` |
| 最后验证基线 | `f711e47`（ARC-001 PR #3 已合并） |
| 工作包提交 | `d5211e7` |
| PR | [#4 建立隔离测试与契约基线](https://github.com/j4meshub/SmartScan/pull/4) |
| 下一工作包 | `SEC-001` 现有资源 IDOR 测试 |

## 当前工作包进展

- 根级 `conftest.py` 在收集测试前强制使用系统临时目录中的 SQLite 数据库和文件存储，并在会话结束时清理。
- 新增隔离环境断言，阻止测试回退到仓库数据库或数据目录。
- 保存完整 `packages/contracts/openapi.json`，运行时 OpenAPI 与快照进行结构化全量比较。
- 覆盖率排除测试代码后最终 CI 基线为 `77.67%`，GitHub/GitLab 统一设置 `77%` 最低门禁。
- 本地完整回归为 `19 passed, 2 skipped`；两项跳过仍是由 PR CI PostgreSQL 17 服务执行的迁移测试。

## 已执行验证

`QA-001` 执行了以下检查：

```text
python -m ruff check services migrations tests
python -m ruff format --check services migrations tests
python -m pytest --cov=services --cov-report=term-missing
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/admin-web/app.js
git diff --check
```

验证结果：

- Ruff 检查通过，36 个 Python 文件纳入检查。
- 本地 Pytest 通过：`19 passed, 2 skipped`，排除测试代码后的应用覆盖率 `77.77%`，达到 `77%` 门禁。
- OpenAPI 完整快照与隔离测试环境断言通过。
- 两项 PostgreSQL 迁移测试等待本工作包 PR CI 的 PostgreSQL 17 服务执行。
- PR 首轮 API 测试为 `21 passed` 且覆盖率门禁通过，但后续 `alembic check` 因隔离测试正确清理数据库而失败；CI 已改为显式升级独立 `ci-smartscan.db` 后再检查漂移，等待复验。
- 第二轮确认直接调用 Alembic 未读取 `SMARTSCAN_DATABASE_URL`；已新增应用级 `migrations drift` 命令，使升级和漂移检查使用同一数据库配置，等待复验。
- 第三轮 PR CI 通过：PostgreSQL 环境下 `21 passed`、无跳过、应用覆盖率 `77.67%`，迁移漂移、Web 与 Compose 检查全部通过。
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
| API 路由职责拆分 | `f711e47` | 入口缩减至 56 行；PR CI 19 项通过且覆盖率 81%；PR #3 已合并 |
| 隔离测试与契约基线 | `d5211e7`、`9779b8e`、`93b3bd3` | PR CI 21 项通过、覆盖率 77.67%；隔离、快照与漂移门禁通过；PR #4 |

## 下一步

1. 合并 `QA-001` PR #4。
2. 从最新 `main` 创建 `codex/sec-001-idor-tests`。
3. 从最新 `main` 创建 `codex/sec-001-idor-tests`。
