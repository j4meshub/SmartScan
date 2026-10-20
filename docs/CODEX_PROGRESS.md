# SmartScan 长任务进度

更新时间：2026-10-20

## 当前断点

| 项目 | 当前值 |
|---|---|
| 当前里程碑 | M0 工程基础 |
| 当前工作包 | `DB-001` 版本化迁移 |
| 工作包状态 | 进行中，本地验证完成，待提交和 PR |
| 当前分支 | `codex/db-001-versioned-migrations` |
| 最后验证基线 | `dde779e`（GOV-001 PR #1 已合并） |
| 工作包提交 | 待创建 |
| PR | 待创建 |
| 下一工作包 | `ARC-001` API 分层 |

## 本工作包完成内容

- 引入 Alembic 初始基线，统一管理 SQLite 与 PostgreSQL 表结构。
- 空库可以升级到最新版本；旧 `create_all` 基线经完整表列校验后无损接管。
- API 开发启动使用版本化迁移；Worker 只检查版本，不再运行 `create_all`。
- 生产 Compose 先运行一次性迁移服务，再启动 API 和 Worker。
- PostgreSQL 超级管理员和审计保护约束纳入迁移版本。

## 已执行验证

本工作包执行了以下检查：

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
- 本地 Pytest 通过：`15 passed, 2 skipped`，服务端覆盖率 `79%`；新增 5 项 SQLite 迁移测试，覆盖空库、旧基线、残缺基线、版本门禁和回滚再升级。2 项 PostgreSQL 测试因本机未提供隔离测试库而跳过，将由 PR CI 的 PostgreSQL 17 服务执行。
- Alembic 元数据漂移检查通过：`No new upgrade operations detected`。
- 当前本地数据库版本检查通过。
- PostgreSQL 离线迁移 SQL 生成通过，包含 `0001` 结构基线与 `0002` 保护约束。
- H5 和管理后台 JavaScript 语法检查通过。
- `git diff --check` 通过，仅有 Windows LF/CRLF 提示。
- GitHub Actions、GitLab CI 和 Compose YAML 语法解析通过。
- 当前 Windows 环境未安装 Docker，Compose 语义检查和镜像构建等待 PR CI；真实 PostgreSQL 迁移仍保留外部门禁。

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

## 下一步

1. 提交并推送 `DB-001`，创建中文 PR 并等待 CI。
2. 在 CI 通过后合并，并从最新 `main` 创建 `codex/arc-001-api-layers`。
3. 公司 PostgreSQL 环境恢复后复核真实升级、保护约束和回滚演练；在此之前不得宣称该外部门禁通过。
