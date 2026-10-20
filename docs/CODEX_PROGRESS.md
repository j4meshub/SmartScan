# SmartScan 长任务进度

更新时间：2026-10-20

## 当前断点

| 项目 | 当前值 |
|---|---|
| 当前里程碑 | M0 工程基础 |
| 当前工作包 | `GOV-001` 长任务治理 |
| 工作包状态 | 完成，等待 PR |
| 当前分支 | `codex/gov-001-long-task-docs` |
| 最后验证基线 | `1d5a9d6` |
| PR | 待创建 |
| 下一工作包 | `DB-001` 版本化迁移 |

## 本工作包完成内容

- 扩展仓库规则，加入事实来源、目录职责、续接流程、安全边界、验证命令和完成定义。
- 建立完整工作包路线、依赖关系、状态和里程碑门禁。
- 建立断点进度与决策记录，使后续任务不依赖单次对话上下文。
- 明确 Mock、真实外部验收、Windows/Mac 分工、服务器阻塞和 PR 工作流。

## 已执行验证

本工作包执行了以下检查：

```text
python -m ruff check services
python -m ruff format --check services
python -m pytest -q
node --check apps/h5/app.js
node --check apps/admin-web/app.js
git diff --check
```

验证结果：

- Ruff 检查通过，22 个 Python 文件格式检查通过。
- Pytest 通过：`10 passed`；存在 1 条 FastAPI TestClient 上游弃用警告，不影响本工作包。
- H5 和管理后台 JavaScript 语法检查通过。
- `git diff --check` 通过，仅有 Windows LF/CRLF 提示。
- 当前 Windows 环境未安装 Docker，Compose 配置检查未执行；GOV-001 不修改 Compose，后续涉及部署的工作包必须在具备 Docker 的 CI 或环境中验证。

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

## 下一步

1. 完成 `GOV-001` 验证、中文提交、推送和 PR。
2. 合并后从最新 `main` 创建 `codex/db-001-versioned-migrations`。
3. `DB-001` 先盘点当前 SQLite/PostgreSQL 差异，再引入 Alembic 基线和升级测试。
