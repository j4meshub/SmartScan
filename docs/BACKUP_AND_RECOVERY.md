# 加密异机备份与恢复演练

## 状态与目标

OPS-004 已提供仓库内可自动验证的备份、保留和恢复基线。目标为 RPO 不超过 24 小时、RTO 不超过 8 小时：PostgreSQL 连续归档 WAL 并每日生成经 `pg_verifybackup` 校验的物理全备，数据库全备、WAL 和用户文件分别进入 Restic 加密异机仓库；日快照至少保留 7 份、周快照至少保留 4 份。每月从证据中的三个精确快照 ID 恢复到独立目录和内部网络，并核对迁移版本、账号/身份/项目所有权、审计表、文件大小与 SHA-256。

公司服务器和异机仓库当前不可用，因此真实定时任务、仓库不可变策略、告警、首份全量备份与月度演练均保持“等待人工验收”。CI 的本地 Restic 仓库回环只证明 PostgreSQL 物理恢复和文件恢复链路可运行，不能冒充异机、带宽、RPO 或 RTO 验收。

## 安全边界

- 真实 `deploy.env`、`backup.env` 和 Restic 密码文件必须位于仓库外、为普通文件、不是符号链接，权限为 `0600`；密码至少 32 个无空白字符。
- 仓库端点只允许标准 HTTPS 的 S3/REST 或 SFTP，禁止 URL 内凭据、查询参数、非标准 HTTP 端口、本机地址和 staging 主机本身。云访问密钥只放在 `backup.env`，证据和日志不得包含密钥、完整仓库 URL、用户名、手机号、对象 ID 或文件路径。
- `backup-restic` 只读挂载数据库备份、WAL、用户文件和密码；恢复数据库只加入 `internal` 网络，不发布端口。恢复目录在演练结束后清除，证据单独以 `0600` 原子写入。
- Restic 密码和仓库访问凭据必须分别托管、轮换并保存在公司批准的 Secret 管理系统；丢失密码无法恢复数据。仓库应启用对象版本/保留锁和独立账号，staging 主机凭据不得拥有缩短服务端保留期或删除历史版本的权限。

## PostgreSQL 与文件策略

`docker-compose.staging.yml` 对 PostgreSQL 启用 `wal_level=replica`、`archive_mode=on` 和最多 15 分钟的 WAL 归档超时，归档命令拒绝覆盖已存在的 WAL。每日任务执行：

1. 使用与运行库相同的固定 PostgreSQL 镜像，通过仅 Compose 内共享的 Unix Socket 执行 `pg_basebackup --wal-method=stream`，随后运行 `pg_verifybackup`；备份容器禁用网络，不新增远程复制规则。
2. 分别创建 `database`、`files`、`wal` 三类 Restic 快照，解析并保存完整 64 位快照 ID。
3. 对每类快照独立执行“7 日、4 周”保留和 `prune`，再以 `restic check --read-data-subset=5%` 抽查仓库数据。
4. 写入不含 Secret 的成功/失败阶段证据，并清理主机上的明文数据库工作副本。失败不会产生成功证据。

WAL 目录不是独立可恢复备份；恢复点由同一次成功证据中的数据库、文件和 WAL 三个快照共同定义。日常恢复先验证基线全备，时间点恢复方案必须先在 staging 演练，禁止直接在生产库试错。

## 配置与校验

从模板创建仓库外文件，不得提交真实值：

```bash
sudo install -m 0600 deploy/compose/backup.env.example /etc/smartscan/staging/backup.env
sudo install -m 0600 /dev/null /etc/smartscan/staging/restic-password
sudoedit /etc/smartscan/staging/backup.env
sudoedit /etc/smartscan/staging/restic-password
```

准备互不重叠且不含符号链接的 `wal`、`backup-work`、`backup-evidence` 和 `restore-drills` 目录后，执行失败关闭校验：

```bash
python tools/validate_backup_config.py \
  --deploy-env /etc/smartscan/staging/deploy.env \
  --backup-env /etc/smartscan/staging/backup.env \
  --password-file /etc/smartscan/staging/restic-password \
  --require-host-paths
```

首次仓库初始化必须由双人核对端点、仓库 ID、加密密码托管和服务端保留策略后单独执行。`run_backup.py` 不会静默初始化空仓库。手工执行一次备份：

```bash
python tools/run_backup.py \
  --deploy-env /etc/smartscan/staging/deploy.env \
  --backup-env /etc/smartscan/staging/backup.env \
  --password-file /etc/smartscan/staging/restic-password \
  --execute
```

## 定时任务与告警

`deploy/systemd/` 提供每日 02:15 备份和每月 1 日 03:30 恢复演练模板。安装前必须把运行用户、仓库版本目录、Python 虚拟环境、Docker 权限和写目录与目标主机实际值逐项核对。监控系统必须针对服务失败、最近成功备份超过 24 小时、仓库检查失败、月度演练缺失及恢复超过 8 小时告警。日志只保存退出状态和证据 ID，严禁输出环境变量或完整命令展开。

## 恢复演练与证据

月度任务选择最新一份结构完整的成功证据，而不是 Restic 的 `latest` 别名；它逐一按精确快照 ID 恢复，并在隔离数据库中验证：

- Alembic 版本等于当前迁移头，关键表均存在并记录行数。
- 登录身份与已验证手机号指向存在的统一用户，页面/结果/导出/制品所有者与上级资源一致。
- 页面原图、处理结果和导出制品路径位于对应 `users/<owner>/` 下，不能是符号链接；有记录的大小和 SHA-256 必须完全一致。
- 审计表可读，证据仅输出计数；恢复目录和临时数据库不对外开放，结束后删除。
- 总耗时不超过配置的 8 小时 RTO，并在独立证据中关联备份运行 ID 和三个快照 ID。

```bash
python tools/run_restore_drill.py \
  --deploy-env /etc/smartscan/staging/deploy.env \
  --backup-env /etc/smartscan/staging/backup.env \
  --password-file /etc/smartscan/staging/restic-password \
  --backup-evidence /srv/smartscan/staging/backup-evidence/backup-<运行ID>.json \
  --execute
```

## 验收与回滚

OPS-004 只有在真实 staging 连续产生成功备份、从异机仓库完成至少一次整库与文件恢复、所有一致性检查通过、证据证明 RPO/RTO 达标、告警送达且恢复目录无残留后，才可标为完成。恢复失败时不得覆盖原数据库或文件目录；保留原服务，修正配置后创建新的隔离演练。应用回滚仍使用上一组固定镜像和迁移说明，数据库回退必须从已验证快照恢复到新目录后再切换，禁止对原卷执行破坏性降级。
