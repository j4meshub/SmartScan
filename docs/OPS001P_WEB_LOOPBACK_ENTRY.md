# OPS-001P Web资源与回环入口兼容修复

## 最终拓扑

```text
共享Nginx :8077（尚未接入）
        │ /smartscan/
        ▼
127.0.0.1:18082
        │
loopback-proxy（Web同镜像、101:101、无数据、无Secret）
        │ edge + publish
        ▼
主Web（仅internal edge、无宿主机端口、data只读）
        │
        ▼
API（internal edge + data）
```

`loopback-proxy`只承担回环发布和固定反向代理。PostgreSQL、API、Worker、AI和主Web均不连接publish网络。publish是第四张SmartScan专用bridge网络，非internal；精确`/28`和网关只进入仓库外`publish-network.json`，创建前必须重新检查Docker IPAM、全部路由、策略路由、接口和VPN可见网段。

## 安全与资源契约

- 主Web固定`worker_processes 1`，只连接edge，无默认网关和端口发布；业务data继续只读挂载。
- 代理复用Web固定镜像，不增加第七种镜像；以`101:101`运行，根文件系统只读，`cap_drop: ALL`、`no-new-privileges`，没有业务挂载和Secret字段。
- 代理仅有32 MiB `/tmp`，上限0.10 CPU、64 MiB、32 PID；主Web上限0.25 CPU、128 MiB、64 PID。两者均使用`json-file`的10 MiB×3轮转。
- 基础UAT共7个运行容器，继续落在既有“最多8个容器、约240 MiB Docker日志”确认内；AI Profile保持关闭。以后若同时启用两个AI容器，必须先重新确认第9个容器的日志与资源预算，不能沿用本次门禁。
- publish网络使代理具有理论出站路径。代理不含用户数据和凭据以限制影响，但这不等于网络层绝对无出站。当前UAT明确接受该有限风险。
- 只有代理发布`127.0.0.1:18082:8080`；`0.0.0.0`、宿主机内网IP、80/443和19081均被拒绝。

## Docker 29验收

必须在containerd image store真实验证：

1. 六镜像exact mixed release只替换Web，其他五项内容链和本地不可变Tag不变；
2. `docker port`为`127.0.0.1:18082`，回环HTTP成功，非回环地址访问失败；
3. 主Web只有internal edge且无默认路由；代理只有edge和publish，没有data、egress或AI访问；
4. 代理无挂载和敏感环境字段，主Web单Worker的PID与内存有明确余量且无`sendmsg() failed`；
5. PostgreSQL、API、两个CPU Worker、主Web和代理健康，真实OCR结果非空，AI Profile关闭；
6. Compose全部`pull_policy: never`，离线导入后不访问Registry；共享Nginx不参与。

## 固定候选与验证证据

| 项目 | 固定值 |
|---|---|
| Web来源提交 | `58c9b9976c7eb14d32de1ef3efba4e0727a95c35` |
| Web源digest | `sha256:0dbcea47325a8c87362a3a180004e7d4ff384efddf6de08d710d7e14c6226db0` |
| `linux/amd64` manifest | `sha256:736a773974a866d13d33dd8d1336d5f657641ac013d3d5034361da2c3bf4120e` |
| Config | `sha256:5ac426b2ca563678de923900d4e8a623466f11966afbb42f2f9802a5ac2a831e` |
| Web离线归档 | `smartscan-web-0dbcea47325a-linux-amd64.docker.tar`，`27,863,040`字节 |
| Web归档SHA-256 | `d8a81f1b6bdb34a461417997fe58b9b55109f4ae691f421f218768a52e32dda3` |
| 六镜像候选清单SHA-256 | `d8b364800e899c884a6eabe2a540cc7e251b31a53b9fe9acf8219dad5fa5c797` |
| 六归档总大小 | `991,897,600`字节；只有Web归档变化 |

容器供应链为新Web生成SBOM和SLSA来源证明；严格全Critical与可修复High/Critical均为0。PR #122技术头`b499b629786214c9b1cca461a141ebb9e55b4e1d`的CI、离线发布、容器供应链和PostgreSQL审计全部通过。Docker 29/containerd与传统隔离daemon均验证：

- 主Web为一个Nginx master加一个Worker，进程数明显低于64 PID上限，运行内存低于128 MiB上限的80%，最近日志无`sendmsg() failed`；
- `docker port`仅为`127.0.0.1:18082`，回环HTTP为200，非回环地址不可达；
- 主Web没有默认路由；loopback-proxy具有已披露的理论出站路径，但无Secret、数据挂载、data/egress/AI网络；
- PostgreSQL、API、主Web和代理Docker Health通过；两个CPU Worker运行且各有120秒内的新鲜心跳，真实OCR结果非空；
- AI Profile关闭、共享Nginx未修改、离线运行没有Registry访问，状态机停在`stage-nginx`确认前。

这些结果只构成候选验收材料；用户未明确接受前，不得下载、上传、导入或部署该Web候选。

## 发布接口冻结

OPS-001P后，普通代码发布只交付用户明确接受的候选清单、固定digest、单服务离线归档和仓库外publish网络确认。固定候选入口为`/home/szhzx/smartscan-uat-offline-images/candidate-release.json`，部署用户所有、0600、普通文件、单硬链接；控制器不再把单次文件名或摘要编译进包装器。

`accept-release`只登记候选；`resume-basic-uat`可连续完成网络现场复核、离线导入、身份验证、必要服务重建和健康检查。数据库迁移、共享Nginx、生产发布、删除和清理仍是独立人工门禁。不提供通用root自更新器；普通发布不升级控制器，也不新增受限执行器。

## `stop-core`评估

`stop-core`可安全停止代理、主Web、两个CPU Worker和API，并移除`core_started/core_verified`完成标记。它保留PostgreSQL及健康状态、`20261022_0024`迁移、活动发布和身份、三张既有网络、publish网络（若已创建）、数据、OCR模型、离线归档和回滚文件。共享Nginx已激活时命令失败关闭。

因此等待修复候选期间建议停止当前已达到PID/内存上限且无法提供18082的旧核心，但执行仍需用户单独授权；OPS-001P仓库阶段不连接或修改服务器。

## 首次冻结升级资产

OPS-001P需要最后一次人工升级控制器、Compose和包装器，以安装固定四网拓扑和稳定候选上传接口；validators、sudoers和共享Nginx模板不变。下列摘要按仓库LF规范字节计算，最终安装仍须从合并提交Git对象导出：

| 资产 | SHA-256 |
|---|---|
| `deploy/ops/smartscan-uatctl` | `6183595007fcdf9b7271977841ab2d50ff616a68f1c8560586033646a4aa39c9` |
| `deploy/ops/smartscan_uatctl.py` | `463502d828851f7dbf967555e893537653dca2d9ad15dd13617fc4af01b95c4e` |
| `deploy/compose/docker-compose.uat.yml` | `01b5970c309074a19e5722c8ce2ae2a1a646b69cea6777b29140121cb1d76b37` |
| `deploy/ops/smartscan_uat_validators.py`（不变） | `27916a63ea05c9fb149255b5ee63edc1bd43b1f4e26ec347266eef6026e0467b` |
| `deploy/sudoers/smartscan-uatctl`（不变） | `081caf34e05798cc556e495728b6b88ce3b2318a3990ca4351d347a2ffcefef3` |
| `deploy/nginx/shared-8077-smartscan-location.conf.template`（不变） | `500aee2ae34f6a14e658823588899647ece628b97fb65554132eef95e741d227` |

普通发布不再安装上述控制器资产。用户接受候选摘要后，AI只使用固定工具上传`candidate-release.json`、候选目录中的`release-map.json`、单服务归档及仓库外`publish-network.json`，再按既有状态机继续。
