# OPS-001应用部署前最终只读预检（2026-11-20）

## 结论

`OPS-001D`全部只读门禁通过，SmartScan具备进入应用部署准备与分阶段授权的条件，但本报告不授权创建目录、Secret、Docker网络或容器，不授权镜像拉取、数据库迁移、Nginx修改或启动UAT。

本次只使用批准的SSH别名，主机名、登录用户和普通用户UID与可信基线一致。仓库不保存内部地址、精确候选CIDR、原始Docker IPAM/路由、真实loop设备、原始服务器快照、凭据或业务数据。

## 制品证据

- 用户接受可审计PostgreSQL固定候选`sha256:94758173bbe1975014751a2e2855a22e0e554e8df996e4d6303bcf386cdae6d0`；明确拒绝后续文档提交产生的`sha256:e54319a0ae69c22731599fb942500e942e5ba03d34c32406a3d747bffcefd04b`，后者不得自动替换。
- PostgreSQL及五个已接受SmartScan固定digest均通过目标服务器匿名manifest请求，HTTP状态成功且`Docker-Content-Digest`逐字一致。五个应用digest沿用[`2ADBF4F_CONTAINER_VERIFICATION.md`](2ADBF4F_CONTAINER_VERIFICATION.md)的固定清单，不重新选择。
- PostgreSQL媒体类型为OCI image manifest；子manifest/配置元数据只读核验为`linux/amd64`、`USER 70:70`、PostgreSQL 17.12，配置摘要一致。
- GHCR DNS和TLS 1.3成功。服务器没有执行`docker login`、`docker pull`，没有下载镜像层或改变Docker缓存。

## 存储、入口与网络证据

- 受限执行器只运行`status`与`verify`且均通过；50 GiB后备文件完整物理预分配，ext4、label、约48.9 GiB文件系统可用空间、autoclear及systemd enabled/active保持正常。
- 共享数据盘在50 GiB已经分配后仍约有693 GiB可用，高于约528 GiB安全余量；inode余量通过。
- 共享Nginx仍监听8077，可读结构中未发现`/smartscan/`或指向18082的既有代理；18082空闲。19081未被使用，也不纳入部署申请。
- 三张仓库外固定`/28`候选网络彼此不重叠，并与27个Docker网络、全部Docker IPAM、主机路由、策略路由、当前VPN可见路由及接口前缀无冲突。精确CIDR和网关只保存在仓库外审批记录。

## 资源证据

- 主机为128逻辑CPU，15分钟负载约8.3，低于80%门禁。
- 当前可用内存约406 GiB；扣除UAT整栈16 GiB后仍高于32 GiB保留门禁。Swap仍有可用余量。
- 现场共有88个容器，其中57个运行；未发现`unhealthy`或`restarting`容器，Docker未发布18082或19081。
- 本次未读取容器环境变量、Secret、业务数据或完整inspect，未连接数据库，未修改服务器、Docker、Nginx、网络、文件或仓库外配置。

## 下一阶段边界

进入`OPS-001`应用部署前，仍须由用户分别授权：

1. 在已验收loop内创建固定应用数据子目录，并安装仓库外`0600`配置与Secret。
2. 按仓库外已确认参数创建三张固定Docker网络。
3. 拉取六个已接受固定digest，并现场复核RepoDigest、平台、PostgreSQL版本及UID/GID。
4. 启动PostgreSQL、等待健康、执行一次性迁移，再启动API、CPU Worker和Web；AI Profile继续关闭。
5. 安装唯一SmartScan Nginx include，执行`nginx -t`并reload，再进行HTTP基础UAT。

任何阶段失败都应立即停止，不得替换digest、调整网络或扩大权限来绕过门禁。应用部署、入口变更和回滚授权继续相互独立。
