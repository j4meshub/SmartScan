# SmartScan 共享生产服务器部署边界

## 文档目的

本文记录SmartScan适配共享生产宿主机后的目标边界，供`OPS-000～OPS-006`续接。公司没有专职运维，服务器共同使用人负责确认SmartScan参数、变更、验证和回滚；本文和仓库自动化均不授权实际服务器变更。

现有证据来自 `8.150-生产运维交接-20261012` 中 2026-10-12 的只读快照。快照显示目标主机同时承载大量容器、Docker 网络、数据库、入口、监控和 GPU 推理服务；其数值只能用于识别风险，不能作为部署当天的永久事实。任何创建网络、目录、容器、定时任务或入口配置前，必须重新完成只读预检。

SSH访问仅使用用户配置的`smartscan-server`别名和ssh-agent。AI不得读取私钥、口令、平台访问令牌、Provider Key或签名材料，这些内容不得进入仓库、证据或聊天。

## 目标拓扑

第一阶段仅建设内网/VPN可达的按需验收环境：

```text
公司内网/VPN用户
       |
共享 Nginx 8077：/smartscan/（基础 UAT 为 HTTP）
       |
smartscan-uat Web ── API ── 专用 PostgreSQL
                         ├── CPU Worker
                         ├── AI Worker（默认关闭）
                         └── AI Gateway ── HTTPS 出站 ── 公司 AI
```

- UAT Compose项目固定为`smartscan-uat`；数据根`/mnt/data/smartscan/uat`是50 GiB专用loop ext4挂载，不是共享盘普通目录或project quota。
- 生产 Compose 项目固定为 `smartscan-prod`，数据根为 `/mnt/data/smartscan/production`。
- 两个环境使用不同数据库、网络、目录、Secret、端口和镜像锁文件，禁止复制 UAT 数据目录充当生产数据。
- Secret 位于 `/etc/smartscan/{uat,production}`，文件权限为 `0600`，不写入镜像、Compose、日志或证据。
- SmartScan 不使用目标主机 GPU，不复用宿主机 PostgreSQL、MySQL、Redis、RabbitMQ 或其他项目容器。
- UAT验收结束后停止服务，不设置自动重启；UAT数据允许清理和重建，不能保存重要生产数据的唯一副本。

## OPS-000 只读预检

仓库侧采集器、离线校验器、失败关闭规则和人工解锁流程见[共享宿主机只读预检与资源确认](SHARED_HOST_PREFLIGHT.md)。

OPS-000已完成历史现场事实和资源策略确认。部署当天由OPS-001重新采集并保存脱敏证据：

1. 主机标识、系统、内核、Docker 与 Compose 版本、CPU、内存、15 分钟负载、接口地址和挂载点。
2. `docker ps`、现有 Compose 项目、全部已创建网络及其 IPAM。
3. 全部主机路由表、策略路由、VPN 路由和公司保留网段。
4. 已监听端口、共享 Nginx include 结构、内部 DNS/TLS 入口及现有监控接入方式。
5. `/` 与 `/mnt/data` 的容量、inode、文件系统类型、配额能力和代表性共租户负载。
6. 服务器到公开GHCR的DNS、TLS和匿名manifest能力；镜像拉取只在部署授权后执行。

预检只读输出不得包含环境变量、容器 Secret、私钥、令牌、数据库内容或用户扫描件。发现资料与现场不一致时，以现场只读证据为准，先更新决策再继续。

## 已确认的资源边界

以下边界由服务器共同使用人确认。精确CIDR只写入仓库外记录，并在部署当天按现场无冲突结果选择：

| 资源 | 初始申请 | 约束 |
|---|---:|---|
| UAT 存储 | 50 GiB | 非稀疏loop ext4硬限制；12/32/4/2 GiB预算；70/85/95保护 |
| 生产存储 | 100 GiB | 初期硬限制；不得从UAT目录转换 |
| UAT 计算 | 8 vCPU / 16 GiB | 整个Compose栈总上限，不是每个容器分别分配 |
| 生产计算 | 8 vCPU / 16 GiB | 初期整栈上限，以16用户真实容量结果复核 |
| Docker 网络 | `data`、`edge`、`egress` 的固定 CIDR/网关 | 不提供仓库默认值，不得自动分配 |
| 用户入口 | 8077 `/smartscan/`→`127.0.0.1:18082` | HTTP仅基础UAT；不占用80/443 |
| 监控 | 应用健康与应用指标 | 复用现有Prometheus/Grafana或人工检查；不申请19081 |
| 备份 | UAT不要求 | 数据可丢弃；同盘副本不算灾备 |

当 `/mnt/data` 可用空间低于总量的 15% 或 200 GiB 中较高者时，SmartScan 停止接纳新增写入，但继续允许下载、取消和清理。

## 网络与入口硬边界

- Compose必须为每个网络声明服务器共同使用人依据现场无冲突结果确认的固定CIDR和网关。
- 网络创建前必须与全部 Docker IPAM、所有主机路由表、策略路由、VPN 和公司保留网段逐项比较；任一重叠立即停止。
- 禁止执行 `docker network prune`、重启 Docker daemon、批量启动停止无关容器或修改无关网络。
- 第一阶段复用已只读确认的8077，SmartScan只申请`127.0.0.1:18082`；部署前再次检查两者状态。
- H5静态资源和Hash路由支持`/smartscan/`，API外部路径为`/smartscan/api/v1/...`。外层去除`/smartscan/`后由内层Nginx继续去除`/api/`。
- HTTP可以验收文件选择或系统拍照兜底，但不得记录为`getUserMedia`实时相机通过；实时相机、企微和正式移动端网络安全必须等待可信HTTPS。
- 公网或零信任入口属于 `OPS-002B`，不得通过临时开放主机端口绕过。
- BBR、Docker daemon、宿主机防火墙、系统升级和全局 Nginx 调优是平台级变更，不属于 SmartScan 默认部署步骤。

## AI 出站边界

- 公司 AI 是默认首选 Provider；外部供应商必须单独启用、单独告知数据去向，且不得作为自动故障降级目标。
- `AI-013` 完成后，AI Gateway 通过内部鉴权读取单页媒体，核对 MIME、字节数和 SHA-256，再使用 `inline_data_url`、`multipart` 或 `files_api` 主动上传。
- Provider 配置、地址、密钥和传输方式只存在于部署 Secret；业务 API 与客户端不返回这些字段。
- 所有出站请求禁止重定向，只允许批准的 HTTPS 目标，并限制连接、请求、响应、超时和并发。
- `files_api` 必须记录供应商临时文件标识和过期/删除结果，但不得把标识返回客户端。
- 现有 `signed_url` 只作为明确审批的兼容兜底，第一阶段不对公网路由 AI 媒体下载路径。

## 镜像、监控与备份

- GitHub 是唯一代码仓库、PR、评审、合并、Tag 和版本事实来源；GitHub Actions 构建并发布公开 GHCR 镜像。
- API、Web、CPU Worker、AI Worker、AI Gateway 和运维工具均发布固定 digest，同时生成漏洞扫描、SBOM 和版本锁文件。
- 主线`0961cc3`和`f38dd4f`五镜像只保留历史证据并拒绝部署。提交`2adbf4f`产生的五个兼容digest已通过目标服务器匿名manifest、来源、平台、SBOM、SLSA、可修复High/Critical、全部Critical、Web子路径和Ops契约核验，并获用户明确接受为UAT候选；接受不自动回填公开模板，也不授权拉取或部署。服务器Docker Hub仍不可达；原PostgreSQL固定候选因不可修复Critical被拒绝，完整应用部署继续阻塞。
- loop阶段使用[`OPS001_LOOP_SUDO_EXECUTOR.md`](OPS001_LOOP_SUDO_EXECUTOR.md)中的固定执行器。OPS-001B执行器已人工升级，固定空UAT经单次`recreate-empty`和两次独立`verify`通过；50 GiB完整物理预分配、ext4和挂载门禁已获用户接受。该完成事实不扩大AI的Docker、网络、Secret、迁移、Compose或Nginx权限。
- `OPS-REG-003`已实现GitHub Actions的官方来源、完整多平台、SBOM、双漏洞扫描和自定义in-toto复制契约，但指定PostgreSQL固定候选未通过门禁，PR不合并且GHCR包未创建。用户授权新固定候选并通过全部门禁前不得进入复制或UAT配置。
- UAT使用专用完整预分配50 GiB后备文件、reserved block为0的ext4和依赖`/mnt/data`的systemd mount；不修改共享盘挂载或`/etc/fstab`。八个服务根文件系统只读，所有tmpfs有界；Docker日志在loop外按每容器`10m×3`轮转。
- 服务器不检出源码、不安装项目虚拟环境、不现场构建，也不接受GitHub自动SSH部署；每次变更由服务器共同使用人确认后人工执行。
- UAT不新增Alertmanager、Node Exporter或主机代理，也不挂载宿主机`/`、`/proc`、`/sys`；现有Prometheus/Grafana接入不是基础UAT前置条件。
- UAT不启用没有异机目标的WAL归档或备份。生产备份能力保留，但必须有真实异机恢复证据；否则明确记录单机数据丢失风险接受。

镜像构建、SBOM、漏洞扫描、首次公开和人工按 digest 部署的详细流程见[GitHub Actions 与公开 GHCR 镜像供应链](CONTAINER_SUPPLY_CHAIN.md)。

## 上线门禁

只有以下条件全部满足，才能从 UAT 进入生产：

1. 固定网络、入口、存储和整栈资源已由服务器共同使用人确认，并通过部署当天现场复查。
2. GitHub Actions 可构建、测试、扫描并发布公开 GHCR 固定 digest，部署机可匿名拉取且能回滚到上一锁文件。
3. HTTP基础UAT完成登录、项目、上传、处理、预览、导出、Range、停止/重启持久化和迁移验证；HTTPS完成实时相机、企微和正式移动端验收。
4. 公司 AI 完成至少一条主动上传的“项目授权→页面任务→候选→用户接受→导出”真实闭环。
5. 应用健康、任务、Worker、数据库和70/85/95存储状态已通过现有监控或人工检查记录验证。
6. 生产已完成异机恢复演练，或明确接受单机数据丢失风险；风险接受不得标记为灾备完成。
7. 30 分钟 16 用户测试在代表性共租户负载下通过，且未提高其他服务错误率或触发平台资源阈值。

生产部署仍需服务器共同使用人单独确认、显式迁移、观察期和回滚记录。真实企业微信外网回调、非VPN移动使用和公网发布继续保持阻塞。
