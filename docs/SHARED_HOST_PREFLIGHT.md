# 共享宿主机只读预检与资源审批

## 目的与状态

`OPS-000` 在创建任何 SmartScan 网络、目录、容器、入口或定时任务前，重新采集共享生产宿主机的只读状态，并将其与公司运维批准的资源分配离线比较。

仓库提供的工具不能授权生产变更，也不能证明 2026-10-12 交接快照至今仍然有效。只有 24 小时内采集的现场快照、完整审批文件和通过的脱敏摘要才能让 `OPS-001` 进入真实资源创建；缺少任一输入都保持失败关闭。

## 安全边界

- 现场采集只允许在 Linux 运行固定的只读命令：Docker版本/容器列表/网络 IPAM、Compose 版本、磁盘容量与 inode、主机负载、`ip address`、`ip route`、`ip rule` 和 `ss`。
- 不执行 `docker inspect` 容器，不读取环境变量、挂载内容、Compose 配置、Nginx 配置、数据库、日志、用户文件或 Secret。
- Docker 访问通常等同高权限操作。运行账户、时间窗口和输出目录必须先经运维批准，不能因为命令只读就绕过审计。
- 原始快照和资源分配包含内部网络、端口与主机信息，必须保存在仓库外 `0600` 目录，不上传 GitHub、不附加 PR、不粘贴到聊天。
- 工具拒绝覆盖已有证据。每次采集使用新的文件名，避免把旧现场状态伪装成新快照。
- 仓库只允许保存校验器生成的脱敏摘要；摘要只含输入 SHA-256、时间、环境、项目名和检查项，不含 CIDR、域名、端口或 Secret。

## 现场采集

生产机不检出 SmartScan 源码。运维从已审核提交或发布制品中单独取得 `tools/shared_host_preflight.py`，核对 SHA-256 后放入临时受控目录。预先创建仅运行账户可读写的证据目录，然后执行：

```bash
python3 shared_host_preflight.py collect \
  --output /var/lib/smartscan-preflight/snapshot-20261110T120000Z.json
```

采集器要求输出路径为绝对路径、父目录已存在且目标文件不存在；成功文件权限为 `0600`。采集结束后按运维流程删除临时脚本，保留原始快照至变更单关闭。

原始快照必须在 24 小时内用于校验。现场发生 Docker 网络、路由、VPN、端口、磁盘或大型服务变更后，即使未超过 24 小时也必须重新采集。

## 资源分配文件

复制 `deploy/compose/shared-host-allocation.example.json` 到仓库外目录，由公司运维填写。示例中的 `REPLACE_*`、端口 `0` 和 `hard_limit_confirmed=false` 均会被校验器拒绝，不能作为默认值。

资源审批至少包含：

- 精确目标主机、批准人、带时区批准时间和变更单号。
- `data`、`edge`、`egress` 三个互不重叠的私有 IPv4 CIDR 与网关。
- 公司/VPN保留网段清单；不能只检查 Docker 默认地址池。
- UAT Web 与内部指标的绑定地址、端口及用途；地址必须真实属于目标宿主机，禁止 80/443、所有接口、公网地址和已占用端口。
- `/mnt/data/smartscan/uat` 至少 100 GiB 硬限制，分配后仍保留数据盘 15% 或 200 GiB 中较高者。
- UAT 至少 8 vCPU/16 GiB 上限，分配后宿主机仍保留至少 16 个逻辑 CPU 和 32 GiB当前可用内存。
- 内部 HTTPS 域名且 `public_access=false`。
- 现有监控接入工单，明确不重复部署 Node Exporter。
- 异机或对象存储备份工单；同一 `/mnt/data` 不能填写为异机端点。

批准文件不得包含密码、Token、私钥、完整备份凭据或 Provider Key。端点字段只填写内部工单/Secret引用，不填写凭据 URL。

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
2. 批准人、时间和变更单均为实际值。
3. 三个固定网段彼此不重叠，且不与现有 Docker IPAM、所有非默认主机路由或公司保留网段重叠。
4. 主机端口未被 `ss` 监听或 Docker发布占用，绑定地址属于目标主机，且不使用 80/443、所有接口或公网地址。
5. 存储根、100 GiB 硬限制、容量与 inode 安全余量满足要求。
6. CPU、内存上限、15 分钟主机负载及共享宿主机安全余量满足要求。
7. 第一阶段仅内部 HTTPS，不允许公网入口。
8. 现场同时存在 Prometheus、Grafana 和 Alertmanager，复用现有监控且不部署 Node Exporter。
9. 备份目标明确位于异机或对象存储。

退出码 `0` 表示校验通过，退出码 `2` 表示失败。失败输出只有稳定错误代码和不含实际内部地址的中文原因。

## 人工复核与解锁

自动校验通过后，运维仍需人工确认：

- Docker 网络分配已经进入公司 IPAM，且路由/VPN负责人认可。
- 内部 HTTPS 入口的实际转发方式不会覆盖共享 Nginx，也不会占用现有 80/443。
- 存储硬限制的实现方式与文件系统匹配，而不是只填写应用软配额。
- 监控系统能到达带令牌的指标目标，且现有 Node Exporter 已覆盖主机指标。
- Restic 端点、保留锁、限速和恢复账户属于异机或对象存储。
- 执行窗口、回滚负责人和共租户停止阈值已写入变更单。

上述人工项完成后，`OPS-000` 才能从“等待人工验收”转为“完成”，并允许 `OPS-001` 在同一已批准参数下创建 UAT 资源。任何参数变化都必须重新生成分配文件并重跑校验。
