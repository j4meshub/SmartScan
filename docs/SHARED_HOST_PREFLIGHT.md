# 共享宿主机只读预检与资源确认

## 目的与状态

`OPS-000` 已完成共享主机事实采集、8077入口核对和资源策略确认。公司没有专职运维，资源参数由服务器共同使用人确认；这不取消部署当天由`OPS-001`执行的新鲜只读采集、冲突检查、验证和回滚。

仓库工具不能授权服务器变更。只有部署前24小时内的新鲜现场快照、完整确认文件、通过的脱敏摘要和用户单独部署授权，才允许`OPS-001`创建资源；参数或现场状态变化后必须重跑。

## 安全边界

- 现场采集只允许在 Linux 运行固定的只读命令：Docker版本/容器列表/网络 IPAM、Compose 版本、磁盘容量与 inode、主机负载、`ip address`、`ip route`、`ip rule` 和 `ss`。
- 不执行 `docker inspect` 容器，不读取环境变量、挂载内容、Compose 配置、Nginx 配置、数据库、日志、用户文件或 Secret。
- Docker访问通常等同高权限操作。只使用用户明确授权的账户、SSH别名、时间窗口和只读命令；AI不得读取SSH私钥、sudo密码或其他凭据。
- 原始快照和资源分配包含内部网络、端口与主机信息，必须保存在仓库外 `0600` 目录，不上传 GitHub、不附加 PR、不粘贴到聊天。
- 工具拒绝覆盖已有证据。每次采集使用新的文件名，避免把旧现场状态伪装成新快照。
- 仓库只允许保存校验器生成的脱敏摘要；摘要只含输入 SHA-256、时间、环境、项目名和检查项，不含 CIDR、域名、端口或 Secret。

## 现场采集

生产机不检出SmartScan源码。服务器共同使用人从已审核提交或发布制品中取得预检工具并核对SHA-256；脚本可以通过SSH标准输入执行而不在服务器落盘。若需落盘，必须另行授权精确路径和清理步骤。

```bash
python3 shared_host_preflight.py collect \
  --output /var/lib/smartscan-preflight/snapshot-20261110T120000Z.json
```

采集器要求输出路径为绝对路径、父目录已存在且目标文件不存在；成功文件权限为 `0600`。采集结束后按运维流程删除临时脚本，保留原始快照至变更单关闭。

原始快照必须在 24 小时内用于校验。现场发生 Docker 网络、路由、VPN、端口、磁盘或大型服务变更后，即使未超过 24 小时也必须重新采集。

## 资源确认文件

复制`deploy/compose/shared-host-allocation.example.json`到仓库外目录，由服务器共同使用人填写。示例中的`REPLACE_*`和`hard_limit_confirmed=false`会被校验器拒绝。

资源确认至少包含：

- 精确目标主机、确认人、带时区确认时间、变更记录、验证记录和回滚记录。
- `data`、`edge`、`egress` 三个互不重叠的私有 IPv4 CIDR 与网关。
- 当前VPN可见路由和保留网段清单；不能只检查Docker默认地址池，任何冲突立即停止。
- 唯一宿主机端口`127.0.0.1:18082`，供现有8077 Nginx转发；不申请19081。
- `/mnt/data/smartscan/uat`为完整预分配、非稀疏的50 GiB loop ext4挂载，reserved block为0，systemd单元依赖`/mnt/data`且loop为autoclear；数据预算不超过48 GiB，70/85/95阈值生效，分配后仍保留数据盘15%或200 GiB中的较高者。
- 整个UAT Compose栈8 vCPU/16 GiB上限，分配后宿主机仍保留至少16个逻辑CPU和32 GiB当前可用内存。
- `http_basic_uat`入口模式、8077、`/smartscan/`和`127.0.0.1:18082`，并确认基础UAT后仍需HTTPS。
- 监控选择`manual`或`existing`；两种模式都保留应用指标，禁止新增Alertmanager和Node Exporter。
- UAT备份`required=false`、数据可丢弃、单机风险已知；不要求异机端点。

确认文件不得包含密码、Token、私钥、完整地址快照、备份凭据或Provider Key。

## 离线校验

在受控工作站或临时运维环境执行：

```text
python tools/shared_host_preflight.py validate \
  --snapshot D:\secure\smartscan\snapshot.json \
  --allocation D:\secure\smartscan\allocation.json \
  --evidence D:\secure\smartscan\preflight-summary.json
```

Linux 使用对应绝对路径。校验器执行以下失败关闭检查：

1. 快照版本、只读标记、目标主机和 24 小时有效期。
2. 确认人、时间、变更、验证和回滚记录均为实际值。
3. 三个固定网段彼此不重叠，且不与现有 Docker IPAM、所有非默认主机路由或公司保留网段重叠。
4. `127.0.0.1:18082`未被`ss`或Docker占用，不存在第二个SmartScan宿主机端口；8077共享入口结构由人工复核。
5. 存储根、50 GiB非稀疏loop ext4计划、48 GiB数据预算、70/85/95阈值、容量与inode安全余量满足要求；创建后的文件系统事实由OPS-001专用证据校验器复核。
6. CPU、内存上限、15 分钟主机负载及共享宿主机安全余量满足要求。
7. 第一阶段为非公网HTTP基础UAT，且明确保留后续HTTPS门禁。
8. `existing`模式验证Prometheus/Grafana存在；`manual`模式验证共同使用人接受能力缺口。两种模式均禁止新增Alertmanager、Node Exporter和宿主机敏感挂载。
9. UAT无备份且数据可重建，不能将同盘副本标记为灾备。

退出码 `0` 表示校验通过，退出码 `2` 表示失败。失败输出只有稳定错误代码和不含实际内部地址的中文原因。

## 人工复核与解锁

自动校验通过后，服务器共同使用人仍需人工确认：

- 三张网络与部署当时全部Docker IPAM、主机路由、策略路由、VPN和保留网段无冲突。
- 8077现有include结构未变，`/smartscan/`未被占用，增量location只转发到18082且可精确回滚。
- 后备文件精确50 GiB且完整分配，ext4 reserved block为0，mount参数、autoclear、systemd父挂载依赖和回滚记录全部匹配；实际可用空间不足数据预算时只下调业务预算。
- 应用指标和健康检查可用；如不接入现有监控，人工检查步骤和能力缺口已写入记录。
- UAT数据可丢弃且不存在重要生产数据唯一副本；不把同盘副本记为灾备。
- 执行窗口、回滚负责人和OOM/共租户影响停止阈值已写入变更记录。

`OPS-000`已经完成。上述部署当天人工项属于`OPS-001`前置条件；通过后仍需用户单独授权，不能因预检通过自动创建目录、网络、容器或Nginx配置。任何参数变化都必须重新生成确认文件并重跑校验。
