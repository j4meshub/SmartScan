# 隔离 staging 部署基线

## 状态与边界

OPS-001 在仓库内提供可审查、可重复的 staging 部署基线，但不会连接或修改公司服务器。当前交付可以验证环境隔离、固定镜像、配置和启动顺序；真实域名、主机目录、镜像仓库、Secret、OCR 模型、数据库迁移及业务验收仍需在公司服务器恢复后执行，因此工作包保持“等待人工验收”。

禁止把本文件当成生产上线授权。staging 不能挂载生产数据库、生产文件目录、生产备份或真实用户扫描件，也不能直接在生产主机修改源码或现场构建镜像。

## 隔离模型

`deploy/compose/docker-compose.staging.yml` 与普通开发 Compose 分离，并强制以下边界：

- Compose 项目名必须明确以 `-staging` 结尾。
- PostgreSQL、业务数据和 OCR 模型分别位于 `/srv/smartscan/staging/` 下互不重叠的主机目录；严格检查可拒绝符号链接逃逸。
- PostgreSQL 和 API 不发布主机端口；Web 入口只绑定 `127.0.0.1` 的独立非特权端口，后续由 OPS-002 的主机 TLS 反向代理接入。
- PostgreSQL/Worker、Web 入口和必要出站分别使用 `data`、`edge` 与 `egress` 网络；Nginx 不加入数据网络，CPU Worker 不加入出站网络。
- API、Worker、AI 网关和 Web 均从受控仓库拉取固定 `sha256` digest，目标服务器没有 `build` 配置。
- 应用在 staging 继续使用 `SMARTSCAN_ENV=production`，启用生产 Secret、手机号保护和 OCR 安全检查；数据库迁移只能由一次性 `migrate` 服务显式执行。
- 短信、企业微信和外部 AI 在 OPS-001 基线中全部关闭。真实联调属于各自人工门禁，不能用 Mock 开启。

AI 网关仍位于显式 `ai` Profile，默认不启动。即使未来启用，也不经过 Web 入口暴露。

## 镜像构建与固定

API、Worker、AI 网关和 Web 镜像必须由 CI 从同一个已验证提交构建并推送到受控仓库。Web 镜像使用 `deploy/nginx/Dockerfile` 将 Nginx 配置、H5 和管理后台打包，目标服务器不挂载仓库源码。

发布候选记录至少包括：Git 提交、镜像仓库、平台、基础镜像、许可证、生成时间和最终 RepoDigest。部署文件只接受 `仓库@sha256:<64 位摘要>`，拒绝 tag、`latest`、全零摘要和简单占位摘要。

本地或 CI 使用 tag 构建 Web 冒烟镜像只证明 Dockerfile 可构建，不能作为 staging 固定镜像证据。

## 配置文件

仓库只保存无密钥模板：

- `deploy/compose/staging.env.example`：Compose 插值、目录、域名、端口、镜像 digest 和 staging 数据库密码。
- `deploy/compose/staging.runtime.env.example`：应用运行配置、手机号 Keyring、超级管理员初始密码和外部服务关闭状态。

真实文件建议放在：

```text
/etc/smartscan/staging/deploy.env
/etc/smartscan/staging/runtime.env
```

两者必须位于仓库外且权限为 `0600`。数据库密码只使用 URL 与 Compose 均安全的高熵字符；运行配置中的 PostgreSQL URL 必须使用同一个密码。`SMARTSCAN_CORS_ORIGINS` 是 JSON 数组，OPS-001 只允许其中唯一的 staging HTTPS 域名。不得把 `docker compose config` 的完整输出上传到工单，因为展开后的内容含 Secret。

## 服务器准备与校验

以下命令只允许在确认是可重建的隔离 staging 主机后执行：

```bash
sudo install -d -m 0750 /etc/smartscan/staging
sudo install -d -m 0750 \
  /srv/smartscan/staging/postgres \
  /srv/smartscan/staging/data \
  /srv/smartscan/staging/models/ocr
sudo install -m 0600 deploy/compose/staging.env.example \
  /etc/smartscan/staging/deploy.env
sudo install -m 0600 deploy/compose/staging.runtime.env.example \
  /etc/smartscan/staging/runtime.env
```

随后替换全部模板值，并按固定镜像内实际 UID/GID 设置目录所有权；不得猜测 PostgreSQL 或应用用户 UID。OCR 模型目录必须放置已校验的固定模型包。

先执行无网络副作用的严格检查：

```bash
python tools/validate_staging_config.py \
  --deploy-env /etc/smartscan/staging/deploy.env \
  --runtime-env /etc/smartscan/staging/runtime.env \
  --require-host-paths
```

校验器会拒绝生产式项目名、保留域名、80/443、目录重叠/越界、仓库内 Secret、可变镜像、弱占位值、自动迁移、开发验证码、Mock 外部服务、外部 AI 启用、CORS 错配和数据库密码错配。输出摘要不包含密码或 Keyring。

## 启动顺序

人工确认严格校验、镜像来源、目录权限和备份点后，才可执行：

```bash
docker compose \
  --env-file /etc/smartscan/staging/deploy.env \
  -f deploy/compose/docker-compose.staging.yml config --quiet

docker compose \
  --env-file /etc/smartscan/staging/deploy.env \
  -f deploy/compose/docker-compose.staging.yml pull

docker compose \
  --env-file /etc/smartscan/staging/deploy.env \
  -f deploy/compose/docker-compose.staging.yml up -d postgres

docker compose \
  --env-file /etc/smartscan/staging/deploy.env \
  -f deploy/compose/docker-compose.staging.yml run --rm migrate

docker compose \
  --env-file /etc/smartscan/staging/deploy.env \
  -f deploy/compose/docker-compose.staging.yml up -d api worker-cpu-1 worker-cpu-2 nginx
```

不要使用 `down -v`，也不要递归删除 `/srv/smartscan`。首次启动后从主机本地检查 `http://127.0.0.1:<独立端口>/api/health`，再核对 Compose 项目、容器标签、网络、挂载源和数据库名称均属于 staging。

## 回滚与验收

回滚使用上一份已审核的 digest 配置和对应迁移说明。应用镜像可以回退，不代表数据库可以无损降级；破坏性迁移必须遵循 expand/migrate/contract，并在备份副本上演练。停止 staging 时保留数据库和文件目录，除非有单独、明确、可恢复的数据销毁批准。

真实服务器验收至少包括：

- 独立域名、回环端口、Compose 项目、网络和三个主机目录均未复用生产资源。
- 固定镜像 digest、OCR 模型摘要和提交记录一致。
- 空库迁移、旧 staging 备份迁移、健康检查、登录、上传、处理、预览和导出通过。
- 外部 AI 关闭时核心流程完成；日志不包含密码、手机号、Token 或扫描内容。
- 重启后任务和上传可恢复，目录权限、磁盘空间和临时文件回收正常。

TLS、`X-Accel-Redirect` 真实链路、Range/大文件、BBR 和公网对照属于 OPS-002；监控、告警和磁盘保护属于 OPS-003；备份恢复演练属于 OPS-004；30 分钟 16 用户容量属于 OPS-005。它们未通过前不得发布生产。
