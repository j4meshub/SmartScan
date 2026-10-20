# SmartScan 长任务进度

更新时间：2026-10-20

## 当前断点

| 项目 | 当前值 |
|---|---|
| 当前里程碑 | M1 阶段 0 风险 POC |
| 当前工作包 | `POC-002` H5 相机与弱网续传自动测试 |
| 工作包状态 | 进行中，本地实现与验证完成，等待 PR CI |
| 当前分支 | `codex/poc-002-h5-camera-network` |
| 最后验证基线 | `a766af5`（POC-001 PR #6 已合并） |
| 工作包提交 | `c3dffba` |
| PR | [#7 验证 H5 相机与弱网续传](https://github.com/j4meshub/SmartScan/pull/7) |
| 下一工作包 | `POC-003` 文档透视真实样本评估框架 |

## 当前工作包进展

- 新增用户触发的实时后置相机入口，优先 `ImageCapture`，不可用时从 video 帧生成 JPEG。
- 实时相机不支持、授权失败或拍摄失败时保留 `capture=environment` 系统相机/文件选择兜底。
- 拍摄完成、关闭相机或关闭对话框时停止全部媒体轨道，避免后台继续占用摄像头。
- 将分片上传抽取为可测试模块；恢复时以服务端 `received_chunks` 为事实来源。
- 自动模拟第 2 片断网并重新提交，确认项目与幂等键复用、已确认第 1 片不重传、完成后清除断点。
- GitHub Actions 与 GitLab CI 已加入 H5 相机和弱网 Node.js 测试。

## 已执行验证

`POC-002` 执行了以下检查：

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
- 本地跳过的两项 PostgreSQL 测试等待本工作包 PR CI 执行。
- Alembic 元数据漂移检查通过：`No new upgrade operations detected`。
- 当前本地数据库版本检查通过。
- H5 应用、相机模块、续传模块和管理后台 JavaScript 语法检查通过。
- `git diff --check` 通过。
- 当前 Windows 未安装 Docker；Compose 语义检查等待 PR CI 执行。

## 外部阻塞

| 门禁 | 状态 | 解除条件 |
|---|---|---|
| 公司 staging 与目标主机负载 | 阻塞 | 提供可隔离的数据库、数据目录和域名/端口 |
| 企业微信真实身份与手机号 | 等待人工验收 | 提供 CorpId、AgentId、Secret、可信域名及测试成员权限 |
| H5 相机与真实弱网 | 等待人工验收 | 提供至少 3 款 Android 手机、2 个企业微信版本及 Wi-Fi/4G/5G 网络切换条件 |
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

## 下一步

1. 等待 `POC-002` PR #7 CI，失败时定位、修复并重跑。
2. PR CI 通过后合并，并从最新 `main` 创建 `codex/poc-003-perspective-evaluation`。
3. 使用真实 Android/企业微信设备及 Wi-Fi、4G、5G 网络切换执行人工验收；条件未提供前保持“等待人工验收”。
