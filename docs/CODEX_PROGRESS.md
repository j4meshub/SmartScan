# SmartScan 长任务进度

更新时间：2026-10-20

## 当前断点

| 项目 | 当前值 |
|---|---|
| 当前里程碑 | M2 统一账号与安全 |
| 当前工作包 | `SMS-001` 验证码挑战、限频与 Provider |
| 工作包状态 | 进行中，挑战、尝试上限、并发限频、Provider 和本地门禁已通过，待提交、PR 与 CI |
| 当前分支 | `codex/sms-001-verification-service` |
| 最后验证基线 | `9041001`（ACC-002 PR #13 已合并） |
| 工作包提交 | 待创建 |
| PR | 待创建 |
| 下一工作包 | `WECOM-001` 企业微信正式登录与绑定 |

## 当前工作包进展

- 验证码仅保存绑定挑战 ID 的 HMAC；挑战 5 分钟有效、最多 5 次尝试，成功后原子消费。
- 手机号和直接连接 IP 使用唯一伪名窗口计数与行锁，默认 15 分钟分别限制 3 次和 10 次。
- 新增 challenge 申请接口与注册消费；development 暂留旧固定码兼容，生产继续拒绝。
- Provider 提供 development Mock 和默认关闭模式，真实短信供应商仍保持人工验收。

本地全量结果：`94 passed, 2 skipped`，应用代码覆盖率 `87.53%`；Ruff、58 个 Python 文件格式、迁移升级/漂移/版本、OpenAPI 契约、H5 `8 passed`、JavaScript 语法和差异检查均通过。两项 PostgreSQL 专属测试等待 PR CI 复核。

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

## 下一步

1. 冻结验证码申请/验证契约、挑战状态、验证码 HMAC 和限频键。
2. 实现开发 Mock、默认关闭 Provider、注册消费和并发/重放测试。
3. 补充中文接口与运维说明，通过全量门禁后创建 PR；真实短信继续等待人工验收。
