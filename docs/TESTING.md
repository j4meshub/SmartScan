# 测试与 CI 基线

SmartScan 的测试基线覆盖 Python 静态检查、数据库迁移、API 契约、权限与上传集成测试、视觉算法、前端语法和 Compose 配置。GitHub Actions 与 GitLab CI 使用相同的核心 Python 门禁。

CI 的迁移漂移检查使用独立 `ci-smartscan.db`：先显式执行版本化升级，再运行应用级 `migrations drift` 命令。升级与漂移检查通过同一配置入口读取 `SMARTSCAN_DATABASE_URL`，且不能依赖 Pytest 留下数据库文件，因为测试会话必须在结束时完整清理隔离资源。

## 隔离资源

根目录 `tests/conftest.py` 在测试模块导入前设置独立环境：

- SQLite 数据库位于系统临时目录，不读取或写入仓库的 `smartscan.db`。
- 文件存储位于同一测试临时目录，不写入仓库 `data/`。
- 测试结束时先释放数据库连接，再删除整个临时目录。
- PostgreSQL 测试只允许连接数据库名以 `_test` 结尾的实例，并在每项测试前后重建 `public` schema。

## OpenAPI 契约

完整运行时契约保存在 `packages/contracts/openapi.json`。测试同时检查公开路径、HTTP 方法、成功状态码、核心响应模型和整份结构化快照。

内部重构不得更新快照。确需增量兼容变更时，应先检查当前 H5、Android、iOS 和上一客户端版本，再重新生成快照并在 PR 中文说明中列出字段、状态码和兼容性影响。

## 覆盖率门禁

覆盖率统计 `services/` 下的应用代码并排除测试文件。建立基线时实际覆盖率为 `77.77%`，CI 最低门禁固定为 `77%`。新增功能应补充测试并保持或提高门禁，不得通过把测试代码计入覆盖率、扩大排除目录或删除断言来绕过。

## 本地完整检查

```bash
python -m ruff check services migrations tests
python -m ruff format --check services migrations tests
python -m pytest --cov=services --cov-report=term-missing --cov-fail-under=77
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/admin-web/app.js
docker compose -f deploy/compose/docker-compose.yml config
```

本机没有 Docker 或隔离 PostgreSQL 时，对应结果必须记录为等待 CI 或人工环境验证，不能标为本地通过。
