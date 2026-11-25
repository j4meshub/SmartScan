# 共享宿主机 UAT 部署

## 状态与用途

本文件是 `OPS-001` 的仓库侧交付，定义按需启停的 `smartscan-uat` 验收栈。`OPS-000` 已完成主机事实采集和资源决策；OPS-001B的固定空UAT已完成单次`recreate-empty`和两次独立`verify`，50 GiB完整预分配loop存储门禁正式通过。OPS-001G已创建三张固定Docker网络且端点数均为0；应用尚未部署，镜像、所有权、数据库、Compose和Nginx仍需独立授权。

旧 `docker-compose.staging.yml`、`/srv/smartscan/staging` 及其监控/备份叠加文件仅保留历史证据，不得与本 UAT 栈混用。UAT 可以使用人工资源检查且不要求备份；生产监控和数据风险由 `OPS-003`、`OPS-004` 继续处理。

## 固定边界

- Compose项目名固定为`smartscan-uat`，数据根固定为`/mnt/data/smartscan/uat`，Secret和确认文件位于`/etc/smartscan/uat`。
- UAT使用完整预分配、非稀疏的50 GiB loop后备文件，以`nodiscard,lazy_itable_init=0,lazy_journal_init=0`格式化为reserved block为0的ext4，并由依赖`/mnt/data`的systemd mount单元挂载到`/mnt/data/smartscan/uat`；不使用project quota、`/etc/fstab`或共享数据盘重挂载。
- 50 GiB分配为数据库/WAL 12 GiB、业务文件32 GiB、OCR模型4 GiB、ext4元数据与运行余量2 GiB。前3项数据预算为48 GiB；创建后实际可用不足48 GiB时必须降低业务预算，不能扩大后备文件。70%提示、85%告警并执行受控清理、95%停止新增写入。
- 宿主机“预分配后仍保留15%或200 GiB中的较高者”由loop执行器和现场预检保证；应用容器看到的是50 GiB loop，因此运行配置使用2 GiB绝对余量和15%比例余量。不得把宿主机200 GiB门禁写入容器配置，否则会永久阻止上传。
- PostgreSQL是SmartScan专用容器；只有Web发布`127.0.0.1:18082`，PostgreSQL、API、Worker和AI Gateway均不发布宿主机端口。
- `data`、`edge`、`egress`三张网络使用部署当天现场无冲突结果确定的固定CIDR和网关；Compose不允许自动分配。
- 现有共享Nginx 8077使用独立include，将`/smartscan/`去前缀转发到18082；不占用80/443，不覆盖其他location。
- HTTP只验收登录、项目、上传、处理、预览、导出和Range。实时相机、企业微信及正式移动验收继续等待HTTPS。
- 基础栈合计5.5 vCPU/8.75 GiB，启用AI后7.5 vCPU/11.75 GiB；整栈不得超过8 vCPU/16 GiB。八个服务根文件系统只读，所有tmpfs都有明确上限；常驻服务设置CPU、内存、PID和`10m×3`日志轮转，全部`restart: "no"`。迁移服务不持久化原始容器日志，由控制器保存脱敏失败证据。Docker日志位于loop之外，八容器理论上限不超过240 MiB。
- 服务器不保存源码、不现场构建、不使用可变tag。用户已接受`2adbf4f`五个应用镜像及`OPS-REG-003B`可审计PostgreSQL镜像为固定UAT源候选。因GHCR Blob链路连接重置，服务器直接pull路线停止；OPS-001I使用同一六个源digest生成兼容传统Docker load的独立归档和内容映射，归档仍保存原始manifest/config/压缩layer证据，后续自动构建不得替换候选。
- AI Worker 和 AI Gateway 位于显式 `ai` Profile，默认不启动；运行配置默认关闭真实 Provider。
- 保留应用健康和带令牌的应用指标，不申请19081。可以复用现有Prometheus/Grafana或记录人工检查能力缺口；不部署Alertmanager、Node Exporter，不挂载宿主机`/`、`/proc`或`/sys`。
- UAT数据允许丢弃和重建，不要求备份，也不启用没有异机目标的WAL归档。

## 仓库文件

| 文件 | 用途 |
|---|---|
| `deploy/compose/docker-compose.uat.yml` | 按需 UAT 服务、固定网络、资源和日志边界 |
| `deploy/compose/uat.env.example` | 无密钥部署模板与当前五个 SmartScan digest |
| `deploy/compose/uat.runtime.env.example` | 生产安全模式的应用运行模板，外部服务默认关闭 |
| `deploy/compose/uat.local-images.env.example` | 离线导入后由控制器生成的本地不可变Tag示例；不得人工安装代替验证 |
| `deploy/compose/shared-host-allocation.example.json` | 服务器共同使用人资源确认模板 |
| `deploy/compose/uat-loop-storage-evidence.example.json` | 创建后loop事实的失败关闭占位模板 |
| `deploy/systemd/mnt-data-smartscan-uat.mount.template` | 仅供评审的持久loop mount单元 |
| `deploy/ops/smartscan-uat-loop-storage` | 固定五子命令、固定对象的loop root执行器；`recreate-empty`只处理稀疏且空的固定UAT |
| `deploy/sudoers/smartscan-uat-loop-storage` | 只允许五组精确命令参数的sudoers模板 |
| `docs/OPS001_LOOP_SUDO_EXECUTOR.md` | 用户人工审核、安装、验证和回滚说明 |
| `deploy/nginx/shared-8077-smartscan-location.conf.template` | 只含 `/smartscan/` 的8077增量location模板 |
| `tools/shared_host_preflight.py` | 现场只读采集、离线冲突校验及OPS-001E固定三证据生成 |
| `tools/run_uat_bootstrap_over_ssh.py` | Windows通过固定SSH别名以内存载荷运行生成器，CIDR不进入参数或Git |
| `docs/OPS001E_UAT_BOOTSTRAP_EVIDENCE.md` | 仓库外暂存、摘要审核、root安装及下一授权边界 |
| `tools/validate_uat_config.py` | 部署参数、审批、运行配置和 Compose 契约校验 |
| `tools/validate_uat_loop_storage.py` | 50 GiB、非稀疏、ext4、autoclear与systemd证据校验 |
| `docs/OPS001_UAT_CHANGE_PLAN.md` | 未执行的精确变更对象、顺序、验收、授权和回滚方案 |
| `deploy/releases/uat-2026-11-24.json` | 六个已接受源digest、平台、本地不可变Tag和独立归档名 |
| `tools/smartscan_offline_images.py` | 审核清单驱动的按需下载、离线校验、断点上传和状态工具 |
| `deploy/ops/smartscan-uatctl` | 一次性安装、固定命令和固定摘要的统一root入口 |
| `deploy/ops/smartscan_uatctl.py` | 镜像导入、身份、所有权、数据库、核心服务及Nginx阶段状态机 |
| `docs/OPS001I_UATCTL_AND_OFFLINE_IMAGES.md` | 离线内容映射、人工安装、授权收敛和回滚边界 |

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
  --env-file /etc/smartscan/uat/local-images.env \
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
3. 复核已验收的50 GiB非稀疏loop、ext4、systemd mount、实际可用空间与autoclear仍正常；不得重新格式化、扩大或影响现有loop挂载。
4. 五个`2adbf4f` SmartScan固定digest与可审计PostgreSQL固定digest均已获接受并完成服务器匿名manifest核验。服务器直接pull路线已经停止；按OPS-001I从按需GitHub Actions取得六个独立归档，核对源对象、平台manifest、config/layer、归档SHA、image ID及本地不可变Tag，不使用`main`、`latest`或替代digest。
5. OPS-001C受限执行器、固定配置工具和sudoers已人工安装，`prepare-directories`已成功。OPS-001E三份仓库外证据已由共同使用人核对SHA-256并独立安装为root拥有；OPS-001F已一次执行`generate-config`并由独立`verify-config`确认配置、Secret长度、固定镜像和OCR契约通过，所有Secret均未回显。
6. 固定真实OCR模型已按来源、许可、版本和完整SHA-256清单完成受限安装，模型状态为`installed=true,status=passed`；三张固定网络、统一控制器和发布映射也已安装/接受。现场五项前置状态均已通过。首次导入PostgreSQL归档后，Docker 29 containerd以schema2 Descriptor digest作为Image ID，旧的Config digest单字段判断失败关闭；OPS-001L改用源内容链、归档摘要、可重算Descriptor和唯一本地Tag联合校验。
7. `resume-basic-uat`校验既有门禁并启动PostgreSQL至健康后，在不可逆迁移前停止。`run-migrations`只允许固定`migrate`服务使用32 MiB `/tmp`内的`/tmp/smartscan-data`，不挂载真实业务目录；成功核对`20261022_0024`后才能再次续接API、两个CPU Worker与Web。AI Profile另行授权。
8. 通过8077 `/smartscan/` 完成基础UAT、Compose及mount停止/重启持久化和digest回滚；实时相机及企微保持未通过。
9. 验收结束后停止UAT。默认保留后备文件取证；卸载后必须确认autoclear释放loop。任何清理都需独立授权，禁止通配符或把UAT目录转为生产。

生产仍使用独立的`smartscan-prod`、100 GiB硬上限、数据库、网络、目录和Secret，不得从本文件直接推导生产部署。

## 当前外部门禁

截至2026-11-25，loop、OCR模型、配置、三张网络、六镜像离线导入、身份文件、所有权及PostgreSQL健康均已完成。首次`run-migrations`在连接数据库前因只读根目录创建失败；OPS-001M的Docker 29真实CI已证明有界临时目录可让空库完整达到`20261022_0024`。同一CI随后确认当前已接受Worker候选缺少`libGL.so.1`，因此核心启动仍失败关闭；实际部署还缺新Worker固定digest和发布映射接受、OPS-001M人工升级、重新授权迁移、核心服务、Nginx增量和HTTP基础UAT。

### 迁移只读根边界

`migrate`继承生产运行配置，但只在该服务内覆盖`SMARTSCAN_STORAGE_ROOT=/tmp/smartscan-data`。根文件系统保持只读，唯一可写目录是现有32 MiB `/tmp` tmpfs；服务没有真实data挂载，迁移结束后临时内容随容器销毁。API与Worker的storage root和业务挂载不变。失败时`migrations_completed`不写入，控制器只保存0600脱敏错误证据，不保存原始日志或Secret。

当前接受的Worker离线归档只可用于保留历史和迁移前内容链验证，不可继续启动两个CPU Worker。仓库已为新构建显式加入`libgl1`并增加无网络、只读根运行时导入测试；主线新digest未经用户接受前不得替换现有发布映射，也不得在服务器通过挂载宿主机库或联网安装绕过。

### Docker 29 containerd离线身份

离线归档继续以用户接受的源digest、平台manifest、Config、原始压缩Layer和归档SHA-256为事实来源。导入后控制器按运行时区分但不降低强度：

- 传统image store：本地Image ID必须等于Config digest；
- Docker 29 containerd image store：用Config digest/大小和全部Layer digest/大小重算Docker schema2 manifest，本地Image ID、`Descriptor.digest`与重算摘要必须相等；
- 两种模式都必须再次核对`linux/amd64`、`Config.User`、revision/version、RootFS diff IDs和唯一SmartScan本地Tag；
- 本地合成RepoDigest只作为运行时证据，不冒充接受的GHCR RepoDigest；Compose继续使用不可变本地Tag和`pull_policy: never`。

升级不重置`uatctl-state.json`。当现场已有PostgreSQL Tag且上述全部证据通过时，`import-images`只验证并继续后五镜像，不重复导入；任何差异立即失败关闭。
