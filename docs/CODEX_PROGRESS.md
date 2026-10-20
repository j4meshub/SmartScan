# SmartScan 长任务进度

更新时间：2026-10-20

## 当前断点

| 项目 | 当前值 |
|---|---|
| 当前里程碑 | M5 Android |
| 当前工作包 | `AND-001` 分层工程与 API 客户端 |
| 工作包状态 | 进行中，本机可执行门禁通过，Android 编译等待 CI |
| 当前分支 | `codex/and-001-layered-foundation` |
| 最后验证基线 | `6d20db5`（H5-005 PR #30 已合并） |
| 工作包提交 | `3cc567e`（实现提交） |
| PR | `#31`，等待 CI |
| 下一工作包 | `AND-002` 身份与缓存 |

## 当前工作包进展

- H5-005 已由 PR #30 合并到主线，中文 squash 提交为 `6d20db5`；M4 桌面自动化门禁完成，真实企微、短信、相机、弱网、系统分享和屏幕阅读器继续保留人工验收。
- Android 工程已拆分 `:core:model`、`:core:network`、`:data:repository` 和 `:app`，依赖方向保持从应用到仓储/网络再到领域模型。
- Compose 已建立首页、项目和设置三个稳定导航入口；项目与设置业务页由后续工作包接入，不以占位界面宣称功能完成。
- Retrofit/OkHttp 客户端已建模项目、页面、任务和导出读取接口，项目仓储完成 DTO 到领域模型映射及稳定错误分类。
- 远端 API 根地址强制 HTTPS，禁止凭据、查询与片段；HTTP 仅能在测试显式允许回环地址。默认使用不可解析的 `.invalid` 域名，不携带真实令牌。
- `MockWebServer` 验证项目请求路径、设备头、Bearer 头和新增可选字段兼容；兼容矩阵只登记已进入仓储产品链路的项目列表接口。
- 提交前自审发现通用 `data/` 忽略规则误伤 Android 仓储模块，已增加仅针对 `apps/android/data` 的例外并核对实现提交包含全部 34 个预期文件。

`AND-001` 计划门禁：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python tools/api_compatibility.py
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/auth-client.js
node --check apps/h5/camera.js
node --check apps/h5/i18n.js
node --check apps/h5/page-editor.js
node --check apps/h5/project-files.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
npm --prefix apps/h5 ci
npm --prefix apps/h5 test
npm --prefix apps/h5 run test:e2e
gradle -p apps/android :core:network:test :data:repository:test :app:testDebugUnitTest :app:lintDebug
git diff --check
```

本机结果：`156 passed, 5 skipped`，应用代码覆盖率 `88.28%`；133 个 Python 文件格式、Ruff、OpenAPI 兼容、迁移升级/漂移/版本、H5 `33 passed`、Chromium E2E 与 axe `3 passed`、JavaScript 语法、CI YAML、Android Manifest、兼容策略 JSON、密钥模式和差异检查均通过。5 项 PostgreSQL 专属测试及 Android 编译等待 PR CI 复核。本机未安装 JDK、Gradle 与 Android SDK，Android JVM 单元测试、应用单元测试和 Lint 将由固定 JDK 17、Gradle 8.9 与 Android 35 SDK 的 GitHub CI 执行；这不等同于模拟器或真机验收。

PR #31 CI 结果：等待 PostgreSQL、Web/Chromium、Android 与容器门禁。

`H5-005` 本地结果：`156 passed, 5 skipped`，应用代码覆盖率 `88.28%`；132 个 Python 文件格式、Ruff、OpenAPI 兼容、迁移升级/漂移/版本、H5 `33 passed`、Chromium E2E 与 axe `3 passed`、JavaScript 语法和差异检查均通过。PR #30 CI 在 PostgreSQL 17 环境 `161 passed`，覆盖率 `88.54%`；Web 的 33 项单元测试和 3 项 Chromium E2E/axe、容器门禁全部通过。

`H5-004` 本地结果：`156 passed, 5 skipped`，覆盖率 `88.28%`，H5 `29 passed`。PR #29 CI 在 PostgreSQL 17 环境 `161 passed`，覆盖率 `88.54%`；Web 与容器门禁全部通过。

`H5-003` 本地结果：`156 passed, 5 skipped`，应用代码覆盖率 `88.28%`；H5 `25 passed`，OpenAPI、迁移、JavaScript 和差异检查通过。PR #28 CI 在 PostgreSQL 17 环境 `161 passed`，覆盖率 `88.54%`；Web 与容器门禁全部通过。

- API-001 已由 PR #25 合并到主线，中文 squash 提交为 `4a76fb9`；当前与上一代契约继续由 CI 双门禁保护。
- H5 登录请求现在发送稳定设备标识，获得短期访问令牌和单次轮换刷新令牌；并发 `401` 共用一次刷新，失败后清理会话。
- 凭据只原子保存在标签页 `sessionStorage`，设备 ID 单独保存在 `localStorage`；旧版长期访问令牌键会被清理。
- 企业微信授权、回调、可信手机号直接登录、缺手机号短信绑定、冲突错误和安全退出已接入双语界面。
- 企微回调增量返回完整设备会话，契约修订为 `2026-10-20.2`；H5 实际消费的认证操作已登记到兼容矩阵。
- Mock 和自动测试只证明本地契约；真实企微租户、真实短信、HTTPS Cookie 与 Android 企业微信内置浏览器保持人工验收。

`H5-001` 本地门禁：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python tools/api_compatibility.py
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/auth-client.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
npm test  # apps/h5
git diff --check
```

本地结果：`152 passed, 5 skipped`，应用代码覆盖率 `88.29%`；128 个 Python 文件格式、Ruff、当前/上一代 OpenAPI 兼容检查、迁移升级/漂移/版本、H5 `17 passed`、JavaScript 语法和差异检查均通过。5 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 复核。

PR #26 CI 结果：PostgreSQL 17 环境 `157 passed`，应用代码覆盖率 `88.56%`；H5 `17 passed`，OpenAPI 兼容、数据库漂移、Web 和容器门禁均通过。该结果不替代真实企微租户、短信、HTTPS Cookie 或 Android 企业微信内置浏览器验收。

- FILE-001 已由 PR #24 合并到主线，中文 squash 提交为 `d8025b8`；生产 TLS、大文件并发、磁盘满和备份恢复继续保留 OPS staging 门禁。
- API-001 使用 `openapi.json` 固定当前运行时契约，并以独立 `openapi-baseline.json` 固定仍受支持的上一代客户端基线。
- 机器可读兼容策略只登记 H5 和管理后台当前实际消费的 `operationId`；Android/iOS 仍是骨架，不虚报已接通接口。
- 兼容检查允许新增端点和可选字段，禁止删除旧能力、增加必填项、修改类型/引用/枚举或静默缩短支持窗口。
- 弃用必须同时更新 OpenAPI 与策略，提供替代方案并保留至少 90 天；当前没有登记弃用。
- API 响应新增 `X-SmartScan-API-Version` 和契约修订号，GitHub/GitLab CI 都显式运行兼容检查器。

`API-001` 本地门禁：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python tools/api_compatibility.py
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm test  # apps/h5
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`152 passed, 5 skipped`，应用代码覆盖率 `88.28%`；127 个 Python 文件格式、Ruff、当前/上一代 OpenAPI 兼容检查、删除端点/新增必填字段/枚举变化反例、运行时精确快照、版本响应头、迁移升级/漂移/版本、H5 `8 passed`、JavaScript 语法和差异检查均通过。5 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 复核。

PR #25 CI 结果：PostgreSQL 17 环境 `157 passed`，应用代码覆盖率 `88.55%`；OpenAPI 当前契约兼容上一代客户端基线，数据库未检测到遗漏迁移，Web 与容器门禁均通过。

`FILE-001` 本地门禁：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm test  # apps/h5
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
python -c "解析 Compose 并断言 X-Accel 前缀与 Nginx 只读存储卷"
git diff --check
```

本地结果：`149 passed, 5 skipped`，应用代码覆盖率 `88.23%`；124 个 Python 文件格式、Ruff、`0017` 空库/旧版本升级与降级、上传取消降级映射、模型漂移、迁移版本、OpenAPI 快照、H5 `8 passed`、JavaScript 语法、Compose X-Accel 映射和差异检查均通过。5 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核；本机无 Docker，完整 `docker compose config` 由 PR CI 执行。

PR #24 CI 结果：PostgreSQL 17 环境 `154 passed`，应用代码覆盖率 `88.49%`；API、Web/H5 和 Compose/容器 3 项全部通过，迁移模型漂移为 `No new upgrade operations detected`。该绿灯证明 `0017` 原生枚举转换、PostgreSQL 项目清理状态、Nginx 配置和只读存储卷通过，不替代真实 TLS、大文件 Range 并发、磁盘满或备份恢复验收。

上一工作包完成摘要：

`EXPORT-001` 本地门禁：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm test  # apps/h5
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`143 passed, 5 skipped`，应用代码覆盖率 `88.46%`；118 个 Python 文件格式、Ruff、`0016` 空库升级与降级、模型漂移、迁移版本、OpenAPI 快照、H5 `8 passed`、JavaScript 语法和差异检查均通过。5 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核。首次 Web 命令误在仓库根目录执行，因根目录无 `package.json` 返回 `ENOENT`；切换到 `apps/h5` 后同一测试命令 8 项全部通过，这不是产品回归。

PR #23 CI 结果：PostgreSQL 17 环境 `148 passed`，应用代码覆盖率 `88.75%`；API、Web/H5 和 Compose/容器 3 项全部通过，迁移模型漂移为 `No new upgrade operations detected`。该绿灯证明 `0016` 在 PostgreSQL、ReportLab 依赖安装、导出契约和容器配置下通过；不替代真实 PDF 视觉、超大项目内存峰值或真实中文文本复制验收。

上一工作包完成摘要：

- JOB-001 已由 PR #21 合并到主线，合并提交为 `1f5094b`。
- OCR-001 使用固定 `paddleocr==3.7.0`、`paddlepaddle==3.3.1` 的 CPU 本地适配器；模型包从只读目录加载并按版本与全部文件 SHA-256 校验，生产启动禁止关闭或首次请求联网下载。
- 已实现 0°、90°、180°、270° 四方向识别与置信/版式融合，每次推理后续租；非零方向没有明确优势时保持 0°，自动方向只作用于处理图，原图继续不可变。
- `0015` 已增加与活动页面结果版本关联的 OCR 全文、行框、模型、置信度、方向和状态；手动旋转会使旧 OCR 失效，旧 `ocr_text` 兼容迁移为 `legacy`。
- 标题候选过滤手机号、18 位证件号、页码、非法字符、重复扩展名和 Windows 保留名；建议名称不覆盖用户标题，无可信标题时按 locale 回退日期名称。
- 已覆盖离线模型适配参数/结果解析、清单篡改、方向阈值、敏感标题、Worker 失败重试、原图保留、页面 IDOR/管理员审计、迁移降级和 OpenAPI 增量契约。

`OCR-001` 提交前全量检查：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm test  # apps/h5
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`140 passed, 5 skipped`，应用代码覆盖率 `88.80%`；114 个 Python 文件格式、Ruff、`0015` 空库/旧版本升级与降级、模型漂移、迁移版本、OpenAPI 快照、H5 `8 passed`、JavaScript 语法、Compose YAML/只读挂载解析和差异检查均通过。5 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核。本机未安装 Docker，`docker compose config` 等待 PR CI 执行；本地 PyYAML 已验证锚点展开前的 YAML 结构与 OCR 只读挂载。

首次聚焦门禁曾发现全角中文冒号未清理、一个布尔表达式和未使用变量问题；补齐全角非法字符后重跑为 `31 passed`。首次全量门禁的唯一失败是新增测试误把既有审计成功值断言成 `success`，保持仓库统一的 `allowed` 契约后，OCR 专项 `3 passed`、最终全量 `140 passed`。失败均已定位修复，没有放宽方向、隐私、权限或迁移断言。

真实 PP-OCRv6 模型包、已授权固定数据集、文字方向正确率 `≥98%`、CPU 耗时/内存和双 Worker 容量仍等待人工验收；自动化假引擎和适配器契约绿灯不得替代这些外部门禁。

PR #22 CI 结果：PostgreSQL 17 环境 `145 passed`，应用代码覆盖率 `89.11%`；两组 API、Web/H5 和 Compose/容器检查共 6 项全部通过，迁移模型漂移为 `No new upgrade operations detected`。该绿灯证明 `0015` 可在 PostgreSQL 升级、离线适配契约、四方向规则、敏感命名、页面权限和 Compose 只读模型挂载通过，不代表真实模型质量、容量或发布模型包已经验收。

上一工作包完成摘要：

- `0014` 已把旧作业状态兼容迁移为排队、基础处理、基础就绪、可选增强、就绪、分级失败和取消，并新增租约、心跳、退避、阶段时间戳和结果版本关联。
- Worker 现在通过随机租约令牌领取及续租；过期抢占、取消和重试都会使旧令牌失效，写结果时再次锁行校验，页面结果与作业终态在同一事务提交。
- 已新增所有者作业详情、取消和手动重试接口；管理员只读遵循既有角色矩阵，跨用户修改统一返回 `404` 并写审计。
- 已覆盖租约过期恢复、旧 Worker 拒绝、指数退避、最终失败、取消竞态、单结果幂等、接口 IDOR、旧库迁移/降级和 PostgreSQL 双 Worker 单次领取。

`JOB-001` 提交前全量检查：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm test  # apps/h5
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`125 passed, 5 skipped`，应用代码覆盖率 `88.66%`；108 个 Python 文件格式、Ruff、`0014` 空库/旧版本升级与降级、模型漂移、迁移版本、OpenAPI 快照、H5 `8 passed`、JavaScript 语法和差异检查均通过。5 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核。

首次聚焦回归曾出现 2 项失败：一项测试未先升级隔离数据库，另一项仍断言 `0013` 中间态；补齐测试数据库升级并按 `0014` 终态断言后重跑为 `31 passed`。随后发现 PostgreSQL 专项测试 import 排序问题，修复后 Ruff 与全量门禁通过。这些失败均为测试装配问题，未通过放宽业务断言规避。

PR #21 CI 结果：PostgreSQL 17 环境 `130 passed`，应用代码覆盖率 `89.00%`；两组 API、Web/H5 和 Compose/容器检查共 6 项全部通过，迁移模型漂移为 `No new upgrade operations detected`。该绿灯证明 `0014` PostgreSQL 枚举迁移、双 Worker 单次领取、崩溃恢复语义和回归门禁通过，不代表真实进程强杀、磁盘满或目标服务器多 Worker 压力已经验收。

`SCAN-001` 提交前全量检查：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm test  # apps/h5
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`121 passed, 4 skipped`，应用代码覆盖率 `88.57%`；104 个 Python 文件格式、Ruff、`0013` 空库/旧版本升级与降级测试、模型漂移、迁移版本、OpenAPI 快照、H5 `8 passed`、JavaScript 语法和差异检查均通过。4 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核。

PR #20 CI 结果：PostgreSQL 17 环境 `125 passed`，应用代码覆盖率 `88.63%`；两组 API、Web/H5 和 Compose/容器检查共 6 项全部通过。该绿灯证明页面版本、复核语义和 `0013` 迁移可在隔离 PostgreSQL 上运行，不代表真实相机质量、授权固定数据集或生产存储门禁已经通过。

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
| H5 真机与真实弱网 | 等待人工验收 | 提供至少 3 款 Android 手机、2 个企业微信版本、Wi-Fi/4G/5G 切换、系统分享目标和屏幕阅读器条件 |
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
| 完整管理与审计 | `5d73afa` | PR CI 在 PostgreSQL 17 环境 121 项通过、覆盖率 87.75%；角色层级、分页过滤、会话撤销、受控删除、失败审计、迁移、Web 与 Compose/容器检查通过；PR #19 已合并 |
| 页面版本与独立复核 | `7e501ff` | PR CI 在 PostgreSQL 17 环境 125 项通过、覆盖率 88.63%；原图保护、追加式结果、质量/旋转/复核、旧状态迁移、IDOR、Web 与 Compose/容器检查通过；PR #20 已合并 |
| 完整任务状态机 | `1f5094b` | PR CI 在 PostgreSQL 17 环境 130 项通过、覆盖率 89.00%；租约、心跳、过期抢占、指数退避、取消/重试、单结果幂等、IDOR、迁移、Web 与 Compose/容器检查通过；PR #21 已合并 |
| 基础 OCR 与安全命名 | `cff564c` | PR CI 在 PostgreSQL 17 环境 145 项通过、覆盖率 89.11%；固定离线适配、四方向融合、版本关联结果、敏感命名过滤、IDOR、迁移、Web 与 Compose/容器检查通过；PR #22 已合并，真实模型指标待人工验收 |
| JPG/PDF 多格式导出 | `4e10b2e` | 本地 143 项通过、覆盖率 88.46%；PR CI 在 PostgreSQL 17 环境 148 项通过、覆盖率 88.75%；多页制品、三档质量、当前 OCR 文本层、过期回退、IDOR、账号合并/删除、迁移、Web 与容器检查通过；PR #23 已合并 |
| 文件生命周期管理 | `d8025b8` | 本地 149 项通过、覆盖率 88.23%；PR CI 在 PostgreSQL 17 环境 154 项通过、覆盖率 88.49%；鉴权下载、Range/X-Accel、上传取消、过期回收、项目清理重试、IDOR、迁移、Web 与容器检查通过；PR #24 已合并 |
| v1 API 契约冻结 | `4a76fb9` | 本地 152 项通过、覆盖率 88.28%；PR CI 在 PostgreSQL 17 环境 157 项通过、覆盖率 88.55%；双快照兼容检查、破坏性反例、版本响应头、Web 与容器检查通过；PR #25 已合并 |
| H5 登录与企业微信绑定 | `10ab33e` | 本地 152 项通过、覆盖率 88.29%，H5 17 项通过；PR CI 在 PostgreSQL 17 环境 157 项通过、覆盖率 88.56%；设备会话、刷新轮换、企微回调、短信绑定、兼容契约、Web 与容器检查通过；PR #26 已合并 |
| H5 拍摄入口 | `3cd4511` | 本地 152 项通过、覆盖率 88.29%，H5 20 项通过；PR CI 在 PostgreSQL 17 环境 157 项通过、覆盖率 88.56%；后摄、ImageCapture/帧回退、后台释放、系统相机、预览、Web 与容器检查通过；PR #27 已合并 |
| H5 页面编辑 | `1868eea` | 本地 156 项通过、覆盖率 88.28%，H5 25 项通过；PR CI 在 PostgreSQL 17 环境 161 项通过、覆盖率 88.54%；四角裁切、滤镜、旋转、页序、复核、IDOR、OpenAPI、Web 与容器检查通过；PR #28 已合并 |
| H5 项目恢复与文件分享 | `a43deb9` | 本地 156 项通过、覆盖率 88.28%，H5 29 项通过；PR CI 在 PostgreSQL 17 环境 161 项通过、覆盖率 88.54%；项目恢复、任务轮询、导出、鉴权下载、Web Share 回退、Web 与容器检查通过；PR #29 已合并 |
| H5 双语与浏览器 E2E | `6d20db5` | 本地 156 项通过、覆盖率 88.28%，H5 33 项、Chromium E2E/axe 3 项通过；PR CI 在 PostgreSQL 17 环境 161 项通过、覆盖率 88.54%；中英文、键盘编辑、真实模块加载、分享回退、无障碍、Web 与容器检查通过；PR #30 已合并 |

## 下一步

1. 完成 `AND-001` 本机可执行门禁并提交，创建中文 PR。
2. 由 GitHub CI 的固定 Android 工具链执行 JVM 单元测试、应用单元测试与 Lint；失败时先定位、修复并重跑。
3. CI 通过且自审完成后合并，回填最终提交与验证证据，再从 `AND-002` 身份与缓存继续。
4. Android 模拟器、真机、正式签名，以及真实企业微信、短信、相机和弱网继续保留人工验收门禁，不以 Mock 结果代替。
