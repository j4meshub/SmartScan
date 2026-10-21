# 监控、容量配额与磁盘保护

`OPS-003` 为单机 staging 建立可观测性和失败关闭基线。它不把仓库夹具或 GitHub Runner 当作真实主机告警验收；真实服务器、通知接收人、值班流程、磁盘挂载点和负载阈值仍需人工确认。

## 保护语义

应用使用四层容量边界：

1. `SMARTSCAN_QUEUE_HIGH_WATER_JOBS` 限制未结束任务总数。上传分片可以完成，但当队列达到高水位时，完成接口返回稳定错误 `queue_capacity_reached`（HTTP `429`），不会创建页面或重复任务。
2. `SMARTSCAN_MAX_ACTIVE_JOBS_PER_USER` 限制同一用户同时占用的 CPU Worker。PostgreSQL 通过用户级事务 advisory lock 与行锁共同裁决，不会让多个 Worker 各自放行；其他用户仍可被公平领取。
3. `SMARTSCAN_USER_STORAGE_QUOTA_BYTES` 使用用户目录实际文件字节数加未接收上传预留计算。新会话超过配额时返回 `user_storage_quota_reached`（HTTP `413`）。值为 `0` 只允许开发环境表示不设用户配额；staging 必须设置正值。
4. 磁盘门禁同时检查固定预留字节、最小可用比例、全部未接收上传预留和当前操作临时副本。空间不足返回 `storage_capacity_reached`（HTTP `507`）。组装整图前额外预留一个完整文件，避免分片与组装副本同时存在时耗尽数据盘。

相同幂等键和已确认分片的查询/重放先返回既有结果，不因后来进入保护状态制造冲突。下载、上传取消、项目删除和账号删除不经过新写入高水位，仍可释放空间。Worker 每轮先执行过期上传、项目和账号清理，再检查磁盘；保护状态下不领取新的 CPU 任务，但已经持有租约的任务继续按租约语义完成或失败重入。

用户目录扫描拒绝符号链接，不跟随越出用户根目录的文件。全局上传预留在 PostgreSQL 中使用事务锁串行化新会话裁决；外部进程直接写盘仍可能改变可用空间，因此每个分片和完整组装前都会重新检查。

## Worker 存活证据

迁移 `20261022_0022` 增加 `worker_heartbeats`。每个 Worker 以主机名和进程 ID 形成临时身份，空闲时按配置间隔更新，处理任务时同时保存随机任务 ID；任务内部续租也刷新 Worker 心跳。表不保存图片、用户 ID、文件路径或 OCR 内容。

Worker 心跳只证明进程最近能访问数据库。处理中的真实性仍以 `processing_jobs` 的随机租约令牌、`heartbeat_at` 和 `lease_until` 为准；告警同时观察活跃 Worker、失联 Worker 和过期任务租约。

## 内部指标端点

`GET /internal/metrics` 不进入公开 OpenAPI，并且仅在 `SMARTSCAN_OPS_METRICS_ENABLED=true` 且 Bearer Token 与 `SMARTSCAN_OPS_METRICS_TOKEN` 定时安全匹配时返回 Prometheus 文本。关闭、缺少或错误令牌统一返回 `404`。公网 Nginx 只代理 `/api/`，不会转发 `/internal/metrics`；Prometheus 只通过 Compose 内部 `data` 网络直连 API。

API 四 Worker 使用 `PROMETHEUS_MULTIPROC_DIR` 合并请求计数和直方图。staging Compose 把该目录放在容器临时文件系统，避免重启后继承陈旧进程文件。指标包括：

- API 路由模板、状态码、成功率与延迟直方图，不使用带 ID 或查询字符串的原始 URL；
- 分片有效落盘字节与内容一致的重放次数；
- 数据库可用性、探测耗时和 PostgreSQL 当前连接数；
- 各任务状态、最老等待时间、活动任务、过期租约、Worker 心跳；
- 上传会话、实际磁盘空间、未接收上传预留和保护状态；
- 最近五分钟按稳定动作码聚合的拒绝审计，不含操作者、目标用户、IP 或对象 ID；
- 待复核页面按稳定原因聚合；
- 最近 24 小时 AI 调用状态、保守费用和熔断器状态，不含媒体、模型原文或凭据。

指标标签必须保持低基数。禁止增加用户 ID、项目/页面/任务 ID、文件名、路径、手机号、IP、User-Agent、Provider URL、媒体令牌或错误原文。

## staging 监控 Profile

`deploy/compose/docker-compose.monitoring.yml` 只在显式 `monitoring` Profile 启动：

- Prometheus：只在内部数据网络抓取 API、Node Exporter 和自身；15 天本地保留。
- Alertmanager：读取仓库外渲染配置，不发布主机端口。
- Node Exporter：只读挂载 `/proc`、`/sys` 和主机根，用于 CPU、内存、磁盘及只读文件系统指标；无 capabilities 且禁止提权。

三项镜像必须固定 digest。Prometheus 与 Alertmanager 数据目录位于独立 staging 根；监控数据不是业务备份。所有容器根文件系统只读、不暴露端口，并仅连接内部 `data` 网络。启动前必须从固定 digest 镜像确认 Prometheus、Alertmanager 的实际运行 UID/GID，并让各自数据目录、渲染后的配置文件和指标 Token 归对应运行 UID/GID 所有；不得通过放宽到全局可读来规避权限问题。

仓库规则覆盖 API 不可用、P95、5xx 比例、数据库、队列高水位/等待、过期租约、Worker 数、磁盘保护/低空间、审计拒绝突增、AI 熔断以及主机 CPU/内存/文件系统。阈值是 staging 起步值，必须结合 `OPS-005` 的同机 30 分钟负载调整，不能直接宣称适合生产。

## 安全渲染与启动

先生成独立高熵 Token，并把完全相同的值写入：

- `/etc/smartscan/staging/runtime.env` 的 `SMARTSCAN_OPS_METRICS_TOKEN`；
- `/etc/smartscan/staging/monitoring/ops-metrics.token`，权限 `0600`。

告警 Webhook 只允许标准端口 HTTPS，配置会写入仓库外目录，因此 URL 中若含接收端 Secret，同样按 Secret 管理。渲染器拒绝符号链接、弱 Token、不匹配 Token、不安全 URL、仓库内真实目标和覆盖现有配置：

```bash
python tools/render_monitoring_config.py \
  --runtime-env /etc/smartscan/staging/runtime.env \
  --metrics-token-file /etc/smartscan/staging/monitoring/ops-metrics.token \
  --alert-webhook-url https://alerts.company.example/hooks/smartscan-staging \
  --target-dir /etc/smartscan/staging/monitoring
```

渲染完成后保持文件权限 `0600`，再把 `prometheus.yml`、`rules.yml` 和 `ops-metrics.token` 的所有者设置为 Prometheus 镜像的实际运行 UID/GID，把 `alertmanager.yml` 的所有者设置为 Alertmanager 镜像的实际运行 UID/GID；两项数据目录也分别使用对应所有者。所有 UID/GID 都必须从已固定 digest 的镜像读取并复核，不能直接复制示例数字。

人工检查安全摘要、`promtool check config`、`promtool check rules` 和 `amtool check-config` 后，才可启动：

```bash
docker compose \
  --env-file /etc/smartscan/staging/deploy.env \
  -f deploy/compose/docker-compose.staging.yml \
  -f deploy/compose/docker-compose.monitoring.yml \
  --profile monitoring up -d prometheus alertmanager node-exporter
```

不要把展开后的 Compose、Alertmanager 配置或 Token 上传到工单。Prometheus/Alertmanager 不通过主机端口开放；需要排障时使用受控 SSH 端口转发，并保留访问审计。

## 人工验收与回滚

真实 staging 至少验证：

- 停止一个 Worker 后两分钟内收到告警，恢复后收到 resolved；空闲与忙碌心跳、过期租约判断准确；
- 受控降低磁盘空间后停止新上传/组装和新任务领取，下载与删除仍可用，释放空间后自动恢复；
- 队列达到高水位不创建重复页面，两个 Worker 不同时处理同一用户超过配置上限；
- API 5xx、延迟、数据库断开、Node Exporter 断开、AI 熔断和审计突增各进行一次无生产数据的故障注入；
- 通知只到批准的 staging 接收端，正文不含 Secret、用户数据、扫描内容或原始 URL；
- 监控进程的 CPU、内存、磁盘增长和 15 天保留符合目标主机容量。

回滚时先停用 `monitoring` Profile，再恢复上一份仓库外配置和固定镜像 digest。容量阈值回滚只修改运行配置并重启相应 API/Worker；不得关闭磁盘保护来强行接收任务。`worker_heartbeats` 是新增独立表，降级到 `0021` 会删除心跳证据，不影响既有任务租约。
