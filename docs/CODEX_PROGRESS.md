# SmartScan 长任务进度

更新时间：2026-10-20

## 当前断点

| 项目 | 当前值 |
|---|---|
| 当前里程碑 | M2 统一账号与安全 |
| 当前工作包 | `ADMIN-001` 完整管理与审计 |
| 工作包状态 | 完成，PR #19 全部 CI 已通过，等待合并 |
| 当前分支 | `codex/admin-001-management-audit` |
| 最后验证基线 | `495576b`（ACC-005 PR #18 已合并） |
| 工作包提交 | `30d6f1b`（实现与本地验证） |
| PR | [#19](https://github.com/j4meshub/SmartScan/pull/19) |
| 下一工作包 | `SCAN-001` 页面版本与复核 |

## 当前工作包进展

- 已完成用户、删除请求和审计列表的角色范围、分页与过滤，并通过 `X-Total-Count` 暴露过滤后总数。
- 已补充跨用户会话撤销、受控删除申请与撤销接口；删除继续复用 ACC-005 的 7 天冷静期和可重入 Worker，不提供直接物理删除捷径。
- 管理员只管理普通用户，超级管理员可管理非超级管理员目标；自操作、同级越权和不可见目标统一返回 `404` 并写入失败审计。
- 已增加 `0011` 管理删除元数据和 `0012` 撤销原因迁移。后加字段使用新迁移，未修改本地已应用的迁移历史。
- 已固定管理 API 的 OpenAPI 快照，并补齐成功、拒绝、会话撤销、删除状态机和审计过滤集成测试。

`ADMIN-001` 提交前全量检查：

```text
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm test  # apps/h5
git diff --check
```

本地结果：`117 passed, 4 skipped`，应用代码覆盖率 `87.75%`；Ruff、迁移向前升级至 `0012`、模型漂移、迁移版本、OpenAPI 快照、H5 `8 passed` 和差异检查均通过。4 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核。

PR #19 CI 结果：PostgreSQL 17 环境 `121 passed`，应用代码覆盖率 `87.75%`；两组 API、Web/H5 和 Compose/容器检查共 6 项全部通过。该绿灯证明管理权限、审计和迁移可在隔离 PostgreSQL 上运行，不代表生产备份恢复或真实 staging 门禁已经通过。

`ACC-002` 提交前 Python 与迁移检查：

```text
python -m ruff check services migrations tests tools
python -m ruff format --check services migrations tests tools
python -m pytest --cov=services --cov-report=term --cov-fail-under=77 -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
```

本地结果：`89 passed, 2 skipped`，应用代码覆盖率 `87.18%`；Ruff、54 个 Python 文件格式、迁移升级/漂移/版本、H5 `8 passed`、JavaScript 语法和差异检查均通过。手机号保护专项 32 项通过；两项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核。

PR #13 CI 结果：PostgreSQL 17 环境 `91 passed`，应用代码覆盖率 `87.18%`；Ruff、54 个 Python 文件格式、迁移升级/漂移、H5 `8 passed`、Web 与 Compose/容器检查全部通过。该绿灯证明加密结构、命名枚举和迁移可以在隔离 PostgreSQL 上运行，不代表真实 Secret 管理、备份恢复或生产轮换演练已经通过。

`ACC-001` 提交前全量检查：

```text
python -m ruff check services migrations tests tools
python -m ruff format --check services migrations tests tools
python -m pytest --cov=services --cov-report=term --cov-fail-under=77 -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --test apps/h5/tests/*.test.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`80 passed, 2 skipped`，应用代码覆盖率 `87.24%`；Ruff、50 个 Python 文件格式、迁移升级/漂移/版本、H5 `8 passed`、JavaScript 语法和差异检查均通过。两项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核。

PR #12 CI 结果：PostgreSQL 17 环境 `82 passed`，应用代码覆盖率 `87.24%`；Ruff、50 个 Python 文件格式、迁移升级/漂移、H5 `8 passed`、Web 与 Compose/容器检查全部通过。该绿灯证明统一身份拆分及迁移在隔离 PostgreSQL 上可运行，不代表真实短信、企业微信租户或生产备份回滚门禁已经通过。

## 已执行验证

`POC-006` 提交前全量检查：

```text
python -m ruff check services migrations tests tools
python -m ruff format --check services migrations tests tools
python -m pytest --cov=services --cov-report=term-missing --cov-fail-under=77
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --test apps/h5/tests/*.test.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`75 passed, 2 skipped`，应用代码覆盖率 `85.50%`；Ruff、47 个 Python 文件格式、迁移漂移、当前数据库版本、H5 `8 passed`、JavaScript 语法和差异检查均通过。两项 PostgreSQL 专属测试按本地环境预期跳过，当前 Windows 未安装 Docker；两者由 PR CI 复核。目标服务器不可用，未运行 30 分钟正式负载。

PR #11 CI 结果：PostgreSQL 17 环境 `77 passed`，应用代码覆盖率 `85.50%`；Ruff、47 个 Python 文件格式、迁移升级/漂移、Web、H5 `8 passed` 和 Compose/容器检查全部通过。该绿灯验证负载工具，不代表 8 vCPU/16 GB 目标服务器已通过 30 分钟容量门禁。

`POC-005` 提交前全量检查：

```text
python -m ruff check services migrations tests tools
python -m ruff format --check services migrations tests tools
python -m pytest --cov=services --cov-report=term-missing --cov-fail-under=77
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --test apps/h5/tests/*.test.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`64 passed, 2 skipped`，覆盖率 `85.50%`；Ruff、45 个 Python 文件格式、迁移漂移、当前数据库版本、H5 `8 passed`、JavaScript 语法和差异检查均通过。两项 PostgreSQL 专属测试按本地环境预期跳过，当前 Windows 未安装 Docker；两者由 PR CI 复核。

PR #10 CI 结果：PostgreSQL 17 环境 `66 passed`，覆盖率 `85.50%`；Ruff、45 个 Python 文件格式、迁移升级/漂移、Web、H5 `8 passed` 和 Compose/容器检查全部通过。真实书籍固定集不存在，自动化绿灯只证明几何策略和回退可重复，不代表拆分率、顺序或文字去弯曲质量达到 v1.4 指标。

`POC-004` 提交前全量检查：

```text
python -m ruff check services migrations tests tools
python -m ruff format --check services migrations tests tools
python -m pytest --cov=services --cov-report=term-missing --cov-fail-under=77
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --test apps/h5/tests/*.test.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`53 passed, 2 skipped`，覆盖率 `84.35%`；Ruff、43 个 Python 文件格式、迁移漂移、当前数据库版本、H5 `8 passed`、JavaScript 语法和差异检查均通过。两项 PostgreSQL 专属测试按本地环境预期跳过，当前 Windows 未安装 Docker；两者由 PR CI 复核。

PR #9 CI 结果：PostgreSQL 17 环境 `55 passed`，覆盖率 `84.35%`；Ruff、43 个 Python 文件格式、迁移升级/漂移、Web、H5 `8 passed` 和 Compose/容器检查全部通过。真实试卷固定集不存在，自动化绿灯只证明保守边界和回退逻辑可重复，不代表试卷检出召回率或印刷内容保持率达到 v1.4 指标。

`POC-003` 专项检查已执行：

```text
python -m ruff check services/worker/app/vision.py services/worker/tests/test_vision.py tools/evaluate_perspective.py tests/test_perspective_evaluation.py
python -m ruff format --check services/worker/app/vision.py services/worker/tests/test_vision.py tools/evaluate_perspective.py tests/test_perspective_evaluation.py
python -m pytest services/worker/tests/test_vision.py tests/test_perspective_evaluation.py -q
```

专项结果：Ruff 与格式检查通过，透视处理和评估器 `8 passed`。

提交前全量检查已执行：

```text
python -m ruff check services migrations tests tools
python -m ruff format --check services migrations tests tools
python -m pytest --cov=services --cov-report=term-missing --cov-fail-under=77
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --test apps/h5/tests/*.test.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`41 passed, 2 skipped`，覆盖率 `82.81%`；Ruff、格式、迁移漂移、当前数据库版本、H5 `8 passed`、JavaScript 语法和差异检查均通过。两项 PostgreSQL 专属测试按本地环境预期跳过。当前 Windows 未安装 Docker。

PR #8 CI 结果：PostgreSQL 17 环境 `43 passed`，覆盖率 `82.81%`；Ruff、格式、迁移升级/漂移、Web、H5 `8 passed` 及 Compose/容器检查全部通过。真实数据集不存在，因此自动化绿灯只证明评估框架可运行，不代表文档透视真实可用率已达到 `95%`。

最近已验证的合并基线仍为 POC-002 PR #7：

```text
python -m ruff check services migrations tests
python -m ruff format --check services migrations tests
python -m pytest --cov=services --cov-report=term-missing --cov-fail-under=77
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --test apps/h5/tests/*.test.js
node --check apps/admin-web/app.js
docker compose --env-file .env.example -f deploy/compose/docker-compose.yml config
git diff --check
```

验证结果：

- Ruff 与格式检查通过，39 个 Python 文件纳入检查。
- H5 相机与弱网专项自动测试 `8 passed`。
- 全量本地测试 `36 passed, 2 skipped`，应用代码覆盖率 `82.80%`，达到 `77%` 门禁。
- 本地跳过的两项 PostgreSQL 测试已由 PR CI 的 PostgreSQL 17 服务执行并通过。
- Alembic 元数据漂移检查通过：`No new upgrade operations detected`。
- 当前本地数据库版本检查通过。
- H5 应用、相机模块、续传模块和管理后台 JavaScript 语法检查通过。
- `git diff --check` 通过。
- 当前 Windows 未安装 Docker；PR CI 的 Compose 语义检查已通过。
- PR CI 通过：PostgreSQL 环境 `38 passed`、覆盖率 `82.80%`，Node.js 22 环境 H5 `8 passed`，Web 与 Compose/容器检查全部通过。

## 外部阻塞

| 门禁 | 状态 | 解除条件 |
|---|---|---|
| 公司 staging 与目标主机负载 | 阻塞 | 提供可隔离的数据库、数据目录和域名/端口 |
| 企业微信真实身份与手机号 | 等待人工验收 | 提供 CorpId、AgentId、Secret、可信域名及测试成员权限 |
| H5 相机与真实弱网 | 等待人工验收 | 提供至少 3 款 Android 手机、2 个企业微信版本及 Wi-Fi/4G/5G 网络切换条件 |
| 文档透视真实样本 | 等待人工验收 | 提供已授权、脱敏且具有人工期望标注的固定文档照片集 |
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
| 现有资源越权矩阵 | `1b0e3dd` | PR CI 25 项通过、覆盖率 80.97%；角色、IDOR、审计、Web 与 Compose/容器检查通过；PR #5 已合并 |
| 企业微信可信身份 POC | `a766af5` | PR CI 38 项通过、覆盖率 82.80%；适配器、Mock、账号决策、Web 与 Compose/容器检查通过；PR #6 已合并，真实租户待人工验收 |
| H5 相机与弱网 POC | `fd82c30` | PR CI API 38 项、H5 8 项通过，覆盖率 82.80%；相机兜底、续传、Web 与 Compose/容器检查通过；PR #7 已合并，真机弱网待人工验收 |
| 文档透视评估框架 | `2371cd7` | PR CI 43 项通过、覆盖率 82.81%；授权清单、指标、性能报告、Web 与 Compose/容器检查通过；PR #8 已合并，真实数据集指标待人工验收 |
| 基础试卷净化 POC | `6ff0f2a` | PR CI 55 项通过、覆盖率 84.35%；三级建议、保守净化、原图回退、Web 与 Compose/容器检查通过；PR #9 已合并，真实试卷指标待人工验收 |
| 双页拆分与去弯曲 POC | `6a6301a` | PR CI 66 项通过、覆盖率 85.50%；非中心书脊、阅读顺序、去弯曲回退、Web 与 Compose/容器检查通过；PR #10 已合并，真实书籍指标待人工验收 |
| 16 用户混合负载工具 | `4fa566a` | PR CI 77 项通过、覆盖率 85.50%；16 会话 Mock、目标防护、资源门禁、Web 与 Compose/容器检查通过；PR #11 已合并，目标服务器 30 分钟正式容量仍阻塞 |
| 统一身份模型 | `d097a17` | PR CI 82 项通过、覆盖率 87.24%；用户主体、登录身份、已验证手机号、旧库回填、降级、Web 与 Compose/容器检查通过；PR #12 已合并 |
| 手机号数据保护 | `9041001` | PR CI 91 项通过、覆盖率 87.18%；AES-GCM、版本化 HMAC、旧数据状态、轮换、迁移、Web 与 Compose/容器检查通过；PR #13 已合并 |
| 短信验证码服务 | `4a1e8fc` | PR CI 96 项通过、覆盖率 87.53%；一次性挑战、尝试上限、并发限频、Provider、迁移、Web 与 Compose/容器检查通过；PR #14 已合并，真实短信待人工验收 |
| 企业微信 OAuth 登录 | `05141aa` | PR CI 在 PostgreSQL 17 环境 99 项通过、覆盖率 87.32%；浏览器绑定 state、可信手机号唯一绑定、短信回退、迁移、Web 与 Compose/容器检查通过；PR #15 已合并，真实租户待人工验收 |
| 账号合并与冲突处理 | `5f07000` | PR CI 在 PostgreSQL 17 环境 103 项通过、覆盖率 87.36%；强身份、canonical user、资源与文件补偿、幂等、跨用户阻断、不可变审计、Web 与 Compose/容器检查通过；PR #16 已合并 |
| 设备会话与刷新令牌 | `0d617f2` | PR CI 在 PostgreSQL 17 环境 109 项通过、覆盖率 87.75%；短期访问令牌、一次性刷新轮换、重放整族吊销、设备撤销、旧客户端兼容、迁移、Web 与 Compose/容器检查通过；PR #17 已合并 |
| 账号删除与手机号隔离 | `495576b` | PR CI 在 PostgreSQL 17 环境 117 项通过、覆盖率 86.86%；强验证、7 天冷静期、可重入清理、文件补偿、30 天复用隔离、并发 Worker、Web 与 Compose/容器检查通过；PR #18 已合并 |
| 完整管理与审计 | `30d6f1b` | PR CI 在 PostgreSQL 17 环境 121 项通过、覆盖率 87.75%；角色层级、分页过滤、会话撤销、受控删除、失败审计、迁移、Web 与 Compose/容器检查通过；PR #19 待合并 |

## 下一步

1. 合并已经通过全部 CI 的 PR #19。
2. 从 `SCAN-001` 开始建立页面原图、处理版本、质量、旋转和独立复核状态。
3. 保持原图不可覆盖，并为旧 `needs_review` 数据设计兼容迁移。
