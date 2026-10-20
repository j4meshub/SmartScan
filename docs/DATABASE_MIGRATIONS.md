# 数据库迁移说明

SmartScan 使用 Alembic 管理数据库结构。生产环境不得使用 `Base.metadata.create_all()` 代替迁移，也不得由多个 API 或 Worker 进程并发修改结构。

## 常用命令

将当前配置的数据库升级到最新版本：

```bash
python -m services.api.app.migrations upgrade
```

确认数据库已经位于最新版本：

```bash
python -m services.api.app.migrations check
```

检查 SQLAlchemy 模型是否存在尚未生成的迁移：

```bash
python -m alembic check
```

开发环境默认设置 `SMARTSCAN_AUTO_MIGRATE=true`，API 启动时会执行同一版本化升级入口。生产 Compose 强制设置为 `false`，由独立 `migrate` 服务先完成升级，API 和 Worker 只有在该服务成功后才启动。

## 旧基线接管

提交 `1d5a9d6` 及更早的可执行基线使用 `create_all` 建表，没有 `alembic_version`。迁移入口发现这种数据库时，会核对预期表集合以及每张表的全部列：

- 完全匹配时，将数据库标记为 `20261020_0001`，保留现有数据，再继续执行 `20261020_0002` 的 PostgreSQL 保护及后续迁移。
- 缺表、多表、缺列或多列时立即停止，不创建版本标记，也不自动删改未知结构。

接管前仍应备份数据库。自动校验是防误操作门禁，不替代备份和恢复演练。

## 新增迁移

1. 先按 expand/migrate/contract 设计兼容变更，确保当前及上一客户端可以共存。
2. 修改 SQLAlchemy 模型。
3. 运行 `python -m alembic revision --autogenerate -m "中文变更说明"`。
4. 人工审查生成脚本，特别检查数据回填、锁表、索引、枚举和 PostgreSQL 专属语句。
5. 补充空库升级、上一版本升级、数据保留和失败回滚测试。
6. 运行 Ruff、全量 Pytest、`python -m alembic check` 和 Compose 配置检查。

迁移脚本必须可重复部署；数据回填量较大时拆成独立步骤，不在长事务中一次处理全部数据。

## 回滚与生产门禁

生产迁移前必须完成加密备份并验证恢复路径。优先采用向前修复；需要执行 `downgrade` 时，先在隔离 staging 用生产备份副本演练，并确认不会丢失新客户端已经写入的数据。

当前公司服务器不可用，因此真实 PostgreSQL 的升级、保护触发器、备份恢复和回滚演练仍是外部门禁。SQLite 自动测试通过不能替代这些验收。
