# 共享宿主机 UAT 部署

## 状态与用途

本文件是 `OPS-001` 的仓库侧交付，定义按需启停的 `smartscan-uat` 验收栈。它不会连接或修改公司服务器，也不表示 OPS-000 已通过。目标主机的固定 CIDR、网关、端口、内部 HTTPS、存储硬限制和计算配额必须由运维在部署当天以 24 小时内的只读证据批准；任何缺项都失败关闭。

旧 `docker-compose.staging.yml`、`/srv/smartscan/staging` 及其监控/备份叠加文件仅保留历史证据，不得与本 UAT 栈混用。监控接入和异机备份分别由 `OPS-003`、`OPS-004` 继续改造。

## 固定边界

- Compose 项目名固定为 `smartscan-uat`，数据根固定为 `/mnt/data/smartscan/uat`，Secret 与审批文件位于 `/etc/smartscan/uat`。
- PostgreSQL 是 SmartScan 专用容器，不复用宿主机或其他项目数据库；PostgreSQL、API 不发布主机端口。
- `data`、`edge`、`egress` 三个网络必须显式使用 OPS-000 批准的固定 CIDR 和网关；Compose 不允许自动分配。
- Web 只绑定批准的非 80/443 地址和端口，供后续内部 HTTPS 入口转发。普通 HTTP 不能作为 H5 相机正式验收入口。
- 每个服务都有 CPU、内存、PID 和 `json-file` 日志轮转限制；全部服务 `restart: "no"`，UAT 不随宿主机自动恢复。
- 服务器不保存源码、不现场构建、不使用可变 tag；五个 SmartScan 镜像来自公开 GHCR，并固定到用户于 2026-11-12 确认接受的 digest。PostgreSQL 镜像 digest 仍需单独审批。
- AI Worker 和 AI Gateway 位于显式 `ai` Profile，默认不启动；运行配置默认关闭真实 Provider。
- 不部署 Node Exporter，不挂载宿主机 `/`、`/proc` 或 `/sys`，不修改共享 Nginx、Docker daemon、防火墙或其他容器。

## 仓库文件

| 文件 | 用途 |
|---|---|
| `deploy/compose/docker-compose.uat.yml` | 按需 UAT 服务、固定网络、资源和日志边界 |
| `deploy/compose/uat.env.example` | 无密钥部署模板与当前五个 SmartScan digest |
| `deploy/compose/uat.runtime.env.example` | 生产安全模式的应用运行模板，外部服务默认关闭 |
| `deploy/compose/shared-host-allocation.example.json` | OPS-000 资源审批模板 |
| `tools/shared_host_preflight.py` | 现场只读采集与离线冲突校验 |
| `tools/validate_uat_config.py` | 部署参数、审批、运行配置和 Compose 契约校验 |

真实文件不得提交仓库，建议路径为：

```text
/etc/smartscan/uat/deploy.env
/etc/smartscan/uat/runtime.env
/etc/smartscan/uat/shared-host-allocation.json
/etc/smartscan/uat/preflight-summary.json
```

文件权限必须为 `0600`。`deploy.env` 中的 `SMARTSCAN_UAT_PREFLIGHT_EVIDENCE_SHA256` 必须填写当次脱敏预检摘要的 SHA-256；参数变化后必须重新采集、审批和校验。

## 失败关闭校验

运维先在仓库外保存真实文件。仓库评审阶段从受控工作站的对应提交执行校验；本工作包合并后，包含该校验器的新 Ops 镜像还必须重复 OPS-REG-002 的扫描、内容检查、公开和人工确认，才允许在目标主机以固定 digest 执行。当前已确认的 Ops digest 可用于迁移，但不包含本次尚未合并的 UAT 校验器，不得伪造为已完成容器化现场校验。以下命令仅展示校验接口；不得把展开后的 Compose 或 Secret 输出上传到工单：

```bash
python tools/validate_uat_config.py \
  --deploy-env /etc/smartscan/uat/deploy.env \
  --runtime-env /etc/smartscan/uat/runtime.env \
  --allocation /etc/smartscan/uat/shared-host-allocation.json

docker compose \
  --env-file /etc/smartscan/uat/deploy.env \
  -f deploy/compose/docker-compose.uat.yml \
  config --quiet
```

校验器会拒绝：

- 自动网段、审批不一致或互相重叠的 UAT 网段；OPS-000 仍负责与全部现有 Docker IPAM、主机/VPN/策略路由和保留网段比较。
- 80/443、全接口监听、未批准端口、`/srv` 数据目录或生产目录复用。
- 可变镜像、错误 GHCR 仓库、现场 `build`、自动重启、缺少 CPU/内存/PID/日志限制或总资源超过审批。
- 重复 Node Exporter、宿主机根目录/`procfs`/`sysfs` 挂载，以及默认启用的短信、企微或外部 AI。
- 未确认的 100 GiB UAT 硬限制、非内部 HTTPS 入口或公网入口。

CI 使用合成审批夹具，只证明规则可运行；夹具网段、端口、摘要和简单 digest 不能作为服务器审批证据。

## 人工发布顺序

取得变更单与 OPS-000 脱敏通过摘要后，运维按精确对象执行：

1. 核对目标主机、现有负载、磁盘高水位和审批有效期，不符合即停止。
2. 创建 `/etc/smartscan/uat` 与 `/mnt/data/smartscan/uat` 的批准子目录，设置最小权限、配额和正确容器 UID/GID；不得猜测权限或复用生产目录。
3. 匿名按 digest 拉取经人工确认的 SmartScan 镜像及批准的 PostgreSQL 镜像，核对拉取后的 RepoDigest。若使用本工作包新增的容器化校验器，必须先确认包含它的新 Ops digest；不得用可变 `main` 标签替代。
4. 先运行配置校验和 `docker compose config --quiet`，再由一次性 `migrate` 服务执行空库或旧库迁移并记录版本头。
5. 启动 PostgreSQL、API、CPU Worker 与 Web；AI Profile 只有在 Provider、隐私说明和真实测试变更单另行批准后才启用。
6. 通过 OPS-002A 的内部 HTTPS 完成上传、处理、预览、导出、停止/重启持久化和回滚检查。
7. 验收结束后停止 `smartscan-uat`。保留数据还是按审批清理必须在变更单中明确；禁止使用通配符或把 UAT 目录改名为生产目录。

生产仍使用独立的 `smartscan-prod`、数据库、网络、目录、Secret 和审批，不得从本文件直接推导生产部署。

## 当前外部门禁

截至 2026-11-12，仓库尚未取得目标主机的 24 小时内快照、固定网络/端口、内部 HTTPS、100 GiB 硬限制、8 vCPU/16 GiB 配额和运维账户审批。因此本工作包完成仓库实现后只能进入“等待人工验收”，不得创建真实网络、目录或容器。
