# SmartScan 长任务进度

更新时间：2026-10-20

## 当前断点

| 项目 | 当前值 |
|---|---|
| 当前里程碑 | M0 工程基础 |
| 当前工作包 | `SEC-001` 现有资源 IDOR 测试 |
| 工作包状态 | 进行中，本地实现与验证完成，待提交和 PR |
| 当前分支 | `codex/sec-001-idor-tests` |
| 最后验证基线 | `11d0a1c`（QA-001 PR #4 已合并） |
| 工作包提交 | 待创建 |
| PR | 待创建 |
| 下一工作包 | `POC-001` 企业微信适配器与 Mock |

## 当前工作包进展

- 普通用户跨用户访问项目详情、页面列表、页面文件和上传会话统一返回 `404`。
- 普通用户不能向其他用户项目直接上传、创建分片会话、写入分片或完成上传。
- 未登录访问受保护资源返回 `401`，不存在资源与无权限资源保持统一 `404`。
- 普通用户进入后台返回 `403`；管理员可读取普通用户资源但不能读取其他管理员或超级管理员资源，超级管理员可读取管理员资源。
- 管理员跨用户查看项目、页面列表、下载页面和后台列出项目均验证产生审计事件。
- 本地完整回归为 `23 passed, 2 skipped`，应用代码覆盖率 `80.97%`。

## 已执行验证

`SEC-001` 执行了以下检查：

```text
python -m ruff check services migrations tests
python -m ruff format --check services migrations tests
python -m pytest --cov=services --cov-report=term-missing --cov-fail-under=77
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/admin-web/app.js
git diff --check
```

验证结果：

- Ruff 与格式检查通过，37 个 Python 文件纳入检查。
- IDOR 专项测试 `4 passed`，覆盖普通用户、管理员、超级管理员和未登录边界。
- 全量本地测试 `23 passed, 2 skipped`，应用代码覆盖率 `80.97%`，达到 `77%` 门禁。
- 两项 PostgreSQL 测试等待 PR CI 执行。
- Alembic 元数据漂移检查通过：`No new upgrade operations detected`。
- 当前本地数据库版本检查通过。
- H5 和管理后台 JavaScript 语法检查通过。
- `git diff --check` 通过。

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
| 隔离测试与契约基线 | `11d0a1c` | PR CI 21 项通过、覆盖率 77.67%；隔离、快照与漂移门禁通过；PR #4 已合并 |

## 下一步

1. 提交并推送 `SEC-001`，创建中文 PR。
2. PR CI 通过后合并，并从最新 `main` 创建 `codex/poc-001-wecom-adapter`。
3. 重跑、导出和删除接口尚不存在；对应工作包实现时必须追加同一 IDOR 与审计矩阵。
