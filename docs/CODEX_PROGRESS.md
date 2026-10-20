# SmartScan 长任务进度

更新时间：2026-10-20

## 当前断点

| 项目 | 当前值 |
|---|---|
| 当前里程碑 | M1 阶段 0 风险 POC |
| 当前工作包 | `POC-003` 文档透视真实样本评估框架 |
| 工作包状态 | 进行中，评估框架与本地全量验证已完成，待提交、PR 与 CI |
| 当前分支 | `codex/poc-003-perspective-evaluation` |
| 最后验证基线 | `fd82c30`（POC-002 PR #7 已合并） |
| 工作包提交 | 待创建 |
| PR | 待创建 |
| 下一工作包 | `POC-004` 基础试卷检测与净化 |

## 当前工作包进展

- 当前透视算法在缩放副本上执行 Canny、形态学闭运算和轮廓筛选，选取面积最大的凸四边形并映射回原图。
- 置信度当前仅按四边形面积比例计算；未检测到可信边缘时保留完整画面并进入复核。
- 已增加授权固定数据集清单及 JSON Schema，强制检查授权、脱敏、用途、审批引用、SHA-256、路径边界和人工四角标注；图片与预览目录均不进入 Git。
- 已实现批量评估器，报告检测召回、透视可用率、负样本误检率、归一化角点误差、P50/P95/最大耗时和进程峰值 RSS，且报告不包含原始路径。
- 默认门禁要求至少 `100` 个正样本且可用率 `≥95%`；合成样本即使全部可用，也会因数量不足保持门禁关闭。
- 已增加合成数据回归，覆盖成功报告、角点质量未达标、样本数不足、授权/哈希错误、路径穿越和现有保守回退。
- 仓库目前仍没有授权真实样本；在固定数据集评估和人工复核前，不得宣称达到 v1.4 指标。

## 已执行验证

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

本地结果：`41 passed, 2 skipped`，覆盖率 `82.81%`；Ruff、格式、迁移漂移、当前数据库版本、H5 `8 passed`、JavaScript 语法和差异检查均通过。两项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务验证。当前 Windows 未安装 Docker，Compose 继续由 PR CI 验证。

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

## 下一步

1. 完成 POC-003 全量验证、自审、中文提交、PR 和 CI。
2. CI 通过后将评估框架合并，并把真实数据集结论保持为“等待人工验收”。
3. 在不虚构真实指标的前提下继续 `POC-004` 基础试卷检测与净化；真实样本到位后再运行固定数据集并记录结论。
