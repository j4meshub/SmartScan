# 共享宿主机 UAT 部署

## 状态与用途

本文件是 `OPS-001` 的仓库侧交付，定义按需启停的 `smartscan-uat` 验收栈。`OPS-000` 已完成主机事实采集和资源决策，但不授权部署。部署当天必须重新只读采集网络、路由、VPN、端口和资源状态，由服务器共同使用人确认精确 CIDR、变更、验证和回滚；任何现场冲突立即停止。

旧 `docker-compose.staging.yml`、`/srv/smartscan/staging` 及其监控/备份叠加文件仅保留历史证据，不得与本 UAT 栈混用。UAT 可以使用人工资源检查且不要求备份；生产监控和数据风险由 `OPS-003`、`OPS-004` 继续处理。

## 固定边界

- Compose项目名固定为`smartscan-uat`，数据根固定为`/mnt/data/smartscan/uat`，Secret和确认文件位于`/etc/smartscan/uat`。
- UAT使用完整预分配、非稀疏的50 GiB loop后备文件，格式化为reserved block为0的ext4，并由依赖`/mnt/data`的systemd mount单元挂载到`/mnt/data/smartscan/uat`；不使用project quota、`/etc/fstab`或共享数据盘重挂载。
- 50 GiB分配为数据库/WAL 12 GiB、业务文件32 GiB、OCR模型4 GiB、ext4元数据与运行余量2 GiB。前3项数据预算为48 GiB；创建后实际可用不足48 GiB时必须降低业务预算，不能扩大后备文件。70%提示、85%告警并执行受控清理、95%停止新增写入。
- PostgreSQL是SmartScan专用容器；只有Web发布`127.0.0.1:18082`，PostgreSQL、API、Worker和AI Gateway均不发布宿主机端口。
- `data`、`edge`、`egress`三张网络使用部署当天现场无冲突结果确定的固定CIDR和网关；Compose不允许自动分配。
- 现有共享Nginx 8077使用独立include，将`/smartscan/`去前缀转发到18082；不占用80/443，不覆盖其他location。
- HTTP只验收登录、项目、上传、处理、预览、导出和Range。实时相机、企业微信及正式移动验收继续等待HTTPS。
- 基础栈合计5.5 vCPU/8.75 GiB，启用AI后7.5 vCPU/11.75 GiB；整栈不得超过8 vCPU/16 GiB。八个服务根文件系统只读，所有tmpfs都有明确上限；每个服务设置CPU、内存、PID和`10m×3`日志轮转，全部`restart: "no"`。Docker日志位于loop之外，八容器理论上限约240 MiB。
- 服务器不保存源码、不现场构建、不使用可变tag。`0961cc3`只保留为历史制品证据并拒绝部署；`f38dd4f`五镜像虽已通过来源、平台、SBOM、漏洞和Web基路径核验，但Ops缺少本次loop契约，仍未获部署接受。PostgreSQL候选已接受，SmartScan新镜像必须在本次合并后重新生成、核验并由用户接受。
- AI Worker 和 AI Gateway 位于显式 `ai` Profile，默认不启动；运行配置默认关闭真实 Provider。
- 保留应用健康和带令牌的应用指标，不申请19081。可以复用现有Prometheus/Grafana或记录人工检查能力缺口；不部署Alertmanager、Node Exporter，不挂载宿主机`/`、`/proc`或`/sys`。
- UAT数据允许丢弃和重建，不要求备份，也不启用没有异机目标的WAL归档。

## 仓库文件

| 文件 | 用途 |
|---|---|
| `deploy/compose/docker-compose.uat.yml` | 按需 UAT 服务、固定网络、资源和日志边界 |
| `deploy/compose/uat.env.example` | 无密钥部署模板与当前五个 SmartScan digest |
| `deploy/compose/uat.runtime.env.example` | 生产安全模式的应用运行模板，外部服务默认关闭 |
| `deploy/compose/shared-host-allocation.example.json` | 服务器共同使用人资源确认模板 |
| `deploy/compose/uat-loop-storage-evidence.example.json` | 创建后loop事实的失败关闭占位模板 |
| `deploy/systemd/mnt-data-smartscan-uat.mount.template` | 仅供评审的持久loop mount单元 |
| `deploy/ops/smartscan-uat-loop-storage` | 固定四子命令、固定对象的loop root执行器 |
| `deploy/sudoers/smartscan-uat-loop-storage` | 只允许四组精确命令参数的sudoers模板 |
| `docs/OPS001_LOOP_SUDO_EXECUTOR.md` | 用户人工审核、安装、验证和回滚说明 |
| `deploy/nginx/shared-8077-smartscan-location.conf.template` | 只含 `/smartscan/` 的8077增量location模板 |
| `tools/shared_host_preflight.py` | 现场只读采集与离线冲突校验 |
| `tools/validate_uat_config.py` | 部署参数、审批、运行配置和 Compose 契约校验 |
| `tools/validate_uat_loop_storage.py` | 50 GiB、非稀疏、ext4、autoclear与systemd证据校验 |
| `docs/OPS001_UAT_CHANGE_PLAN.md` | 未执行的精确变更对象、顺序、验收、授权和回滚方案 |

真实文件不得提交仓库，建议路径为：

```text
/etc/smartscan/uat/deploy.env
/etc/smartscan/uat/runtime.env
/etc/smartscan/uat/shared-host-allocation.json
/etc/smartscan/uat/preflight-summary.json
/etc/smartscan/uat/loop-storage-evidence.json
```

文件权限必须为`0600`。`deploy.env`中的`SMARTSCAN_UAT_PREFLIGHT_EVIDENCE_SHA256`填写部署当天脱敏预检摘要；参数变化后重新采集、确认和校验。

## 失败关闭校验

服务器共同使用人在仓库外保存真实文件，并从受控工作站的对应提交执行校验。以下命令只展示接口；不得公开展开后的Compose或Secret：

```bash
python tools/validate_uat_config.py \
  --deploy-env /etc/smartscan/uat/deploy.env \
  --runtime-env /etc/smartscan/uat/runtime.env \
  --allocation /etc/smartscan/uat/shared-host-allocation.json \
  --loop-evidence /etc/smartscan/uat/loop-storage-evidence.json \
  --mount-unit <REVIEWED_MOUNT_UNIT>

docker compose \
  --env-file /etc/smartscan/uat/deploy.env \
  -f deploy/compose/docker-compose.uat.yml \
  config --quiet
```

校验器会拒绝：

- 自动、互相重叠或与现场Docker IPAM、主机路由、策略路由、VPN、保留网段冲突的网络。
- 18082以外的宿主机端口、非回环监听、80/443、`/srv`目录或生产目录复用。
- 后备文件不是精确50 GiB、稀疏文件、非ext4、reserved block不为0、挂载点/参数错误、缺少autoclear或systemd `/mnt/data`依赖和回滚说明。
- 持久化数据预算超过48 GiB、创建后实际可用空间不足数据预算、非70/85/95阈值或整栈超过8 vCPU/16 GiB。
- 可变镜像、错误GHCR仓库、现场`build`、自动重启、缺少服务资源/PID/`10m×3`日志限制、应只读的根文件系统可写或tmpfs无界。
- Alertmanager、Node Exporter、宿主机敏感挂载，以及默认启用的短信、企微或外部AI。
- 把HTTP基础UAT声明为实时相机、企微或正式移动验收。

CI使用合成确认夹具，只证明规则可运行；夹具网段、摘要和简单digest不能作为服务器现场证据。

## 人工发布顺序

取得单独部署授权后，服务器共同使用人按精确对象执行：

1. 重新采集现场网络、路由、VPN、端口、负载和磁盘，确认8077结构未变、18082空闲，任何冲突立即停止。
2. 形成仓库外精确CIDR、loop参数、变更、验证、回滚和共租户停止阈值记录。
3. 经单独sudo授权创建50 GiB非稀疏后备文件、ext4和systemd mount；核对实际可用空间与autoclear并生成脱敏证据。不得影响现有loop挂载。
4. 先通过兼容性门禁；用户接受本工作包合并后产生的新SmartScan五镜像，才可与已接受的PostgreSQL候选一起拉取并核对RepoDigest、平台、版本和UID/GID；不得用`main`或`latest`。
5. 在loop内创建数据子目录，安装配置，创建三张网络，校验配置和Compose，执行一次性迁移，再启动PostgreSQL、API、CPU Worker与Web；AI Profile另行授权。
6. 通过8077 `/smartscan/` 完成基础UAT、Compose及mount停止/重启持久化和digest回滚；实时相机及企微保持未通过。
7. 验收结束后停止UAT。默认保留后备文件取证；卸载后必须确认autoclear释放loop。任何清理都需独立授权，禁止通配符或把UAT目录转为生产。

生产仍使用独立的`smartscan-prod`、100 GiB硬上限、数据库、网络、目录和Secret，不得从本文件直接推导生产部署。

## 当前外部门禁

截至2026-11-19，OPS-000事实采集和资源决策已完成，loop方案和PostgreSQL候选已定版，但OPS-001仍等待人工验收。实际部署前仍缺部署当天现场复查、精确CIDR、loop创建证据、本次合并后兼容新镜像的核验与接受、服务器Secret和逐项sudo/Docker/Nginx授权。详见[OPS-001共享宿主机UAT变更方案](OPS001_UAT_CHANGE_PLAN.md)；本文件不授权创建真实资源。
