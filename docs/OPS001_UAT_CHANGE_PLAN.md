# OPS-001 共享宿主机 UAT 变更方案

> 状态：**待授权、未执行**。本方案不授权服务器写入，不包含真实 CIDR、内部地址、凭据或 Secret。命令均为将来取得逐项授权后的草案。

## 1. 变更对象

| 对象 | 计划值 | 边界 |
|---|---|---|
| Compose项目 | `smartscan-uat` | 不接管现有项目 |
| 配置目录 | `/etc/smartscan/uat` | 目录`0750`，真实文件`0600` |
| 数据根 | `/mnt/data/smartscan/uat` | 整体硬上限50 GiB，UAT数据可丢弃重建 |
| 子目录 | `postgres`、`data`、`models/ocr` | UID/GID按拉取后镜像事实设置，不猜测 |
| 配置文件 | `deploy.env`、`runtime.env`、`shared-host-allocation.json`、`preflight-summary.json` | 仓库外生成，不打印完整内容 |
| Docker网络 | `smartscan-uat_data`、`smartscan-uat_edge`、`smartscan-uat_egress` | 数据、入口、受控出站三种用途，固定CIDR |
| 回环入口 | `127.0.0.1:18082` | 唯一发布的宿主机端口 |
| Nginx增量 | `/etc/nginx/snippets/smartscan-uat-8077.locations.conf` | 只含SmartScan location |

基础容器和上限：PostgreSQL 1 vCPU/2 GiB/256 PID；一次性migrate 0.25/512 MiB/128；API 1.5/2 GiB/512；两个CPU Worker各1.25/2 GiB/256；Web Nginx 0.25/256 MiB/128。AI Worker 1/2 GiB/256和AI Gateway 1/1 GiB/256属于默认关闭的`ai` Profile。基础栈含migrate为5.5 vCPU/8.75 GiB，启用AI后为7.5 vCPU/11.75 GiB，均低于整栈8 vCPU/16 GiB。

预期名称为`smartscan-uat-postgres-1`、`smartscan-uat-migrate-1`、`smartscan-uat-api-1`、`smartscan-uat-worker-cpu-1-1`、`smartscan-uat-worker-cpu-2-1`、`smartscan-uat-nginx-1`，以及默认不启动的两个AI容器。PostgreSQL、API、Worker和AI Gateway不发布宿主机端口。

完全不修改：其他Compose项目、容器、网络、卷和镜像；80/443；8077全局参数及无关`server/location`；Docker daemon、防火墙、路由、VPN、系统服务、GPU、现有数据库和监控。不会新增Alertmanager、Node Exporter、19081、主机代理或源码目录。

## 2. 网络方案

部署窗口先通过唯一批准的SSH别名，以普通用户重新只读采集全部Docker IPAM/端点、主机路由表、策略路由、接口和当前可见VPN路由、8077/18082监听、磁盘、inode、内存、负载及容器状态；不得扫描其他主机或网段。

三张CIDR只从仓库外候选中选择，必须互不重叠、网关属于子网，并且不与Docker IPAM、任何主机/策略/VPN路由或保留网段重叠。精确CIDR、网关、时间、确认人、验证和回滚只进入给用户的仓库外审批报告及真实配置。公开仓库仅保留占位符。任一重叠、采集不完整、18082被占用或8077结构变化，立即停止且不创建网络。

## 3. 存储方案

50 GiB是整个UAT根的硬限制，不是业务文件单项配额：

| 用途 | 预算 |
|---|---:|
| PostgreSQL数据与内置WAL | 12 GiB |
| 业务原图、结果与导出 | 32 GiB |
| OCR模型 | 4 GiB |
| 容器日志预算 | 1 GiB |
| 文件系统与运行余量 | 1 GiB |

应用部署级和单用户配额最多为32 GiB。PostgreSQL不启用无异机目标的WAL归档；每容器继续使用`10m × 3`日志轮转，不能直接操作Docker日志文件。分配后共享盘仍须保留“15%或200 GiB中的较高者”。

- 70%提示并检查增长；85%告警并执行经确认的受控清理，禁止自动删除原图；95%停止新增写入和上传，保留只读访问。
- 首选仅在ext4已启用`project`特性、挂载已有`prjquota`且工具可用时使用project quota。将来经授权的草案是：

  ```bash
  sudo chattr -p <UAT_PROJECT_ID> +P /mnt/data/smartscan/uat
  sudo setquota -P <UAT_PROJECT_ID> 50G 50G 0 0 /mnt/data
  sudo quota -P <UAT_PROJECT_ID> -v /mnt/data
  ```

- 若未启用project quota，本工作包不得改`/etc/fstab`、在线重挂载、改变文件系统特性或Docker daemon，部署保持阻塞。更安全的独立方案是经评审的50 GiB LVM逻辑卷；无LVM时才评估只挂载到UAT根的50 GiB loopback ext4。两者都需单独授权和回滚。
- 应用32 GiB配额与70/85/95只是纵深防御，不能替代50 GiB文件系统硬限制。

## 4. 镜像方案

只记录用户已确认的`0961cc3`五个SmartScan digest，不使用可变标签：

```text
ghcr.io/j4meshub/smartscan-api@sha256:b4f97968a81777c9b46bcae272be5153df796cfd4b2f9221008facc53358300a
ghcr.io/j4meshub/smartscan-worker@sha256:0dc0fe0de3e4518985bd906a08815b70419d86d5530e300a216d25a221ad07f7
ghcr.io/j4meshub/smartscan-ai-gateway@sha256:8e7af7bf3d23687c19ecdd10b85044eee8321a019f831bb7744ce2575fc0518c
ghcr.io/j4meshub/smartscan-web@sha256:44a0faf547140844eb065a65034d442b66dd9f971ae5521b8a97400bd50df915
ghcr.io/j4meshub/smartscan-ops@sha256:ef4dd40c7b8a494e92540dc5bb476ab144903402142a0bbb0fdc4fd688138a5b
```

**失败关闭：不得直接部署这组镜像。** 源码复核确认`0961cc3` Web默认请求根路径`/api`，不支持`/smartscan/api`；其Ops校验器也早于50 GiB分项预算契约。禁止用共享根`/api`、Nginx `sub_filter`或浏览器本地覆盖绕过。新主线镜像不得自动替换；只有用户另行确认整套兼容固定digest后才能进入拉取。

PostgreSQL 17候选为`postgres@sha256:0d938e975177bef9f1f61f3f9dbcf2e0aa0a139568f66d3415ed8892eb97f6ac`。2026-11-18只执行官方Registry manifest `HEAD`，没有拉取。部署前须再次核对digest、由用户接受；获准拉取后核对RepoDigest、`linux/amd64`、实际UID/GID和`postgres --version`，不一致立即停止。

## 5. Nginx最小增量

拟安装文件以[`shared-8077-smartscan-location.conf.template`](../deploy/nginx/shared-8077-smartscan-location.conf.template)为唯一来源，核心内容为：

```nginx
location = /smartscan { return 308 /smartscan/; }
location = /smartscan/api/internal/metrics { return 404; }
location ^~ /smartscan/ {
    client_max_body_size 26m;
    client_body_timeout 120s;
    proxy_request_buffering off;
    proxy_buffering off;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header Range $http_range;
    proxy_set_header If-Range $http_if_range;
    proxy_pass http://127.0.0.1:18082/;
}
```

在真实8077 `server`中只增加`include /etc/nginx/snippets/smartscan-uat-8077.locations.conf;`。若现有、仅属于该server的include已覆盖该文件，则不重复增加。真实主配置路径只写仓库外记录。

外层去掉`/smartscan/`后，容器Web处理相对静态资源；`/smartscan/api/v1/...`变为`/api/v1/...`，再由容器规则转为API`/v1/...`。Hash路由无需刷新回退。模板保留26 MiB、上传/下载超时、请求/响应无缓冲和Range/If-Range；验收`Content-Disposition`、`ETag`、`Accept-Ranges`和`Content-Range`。不得覆盖其他location或代理内部指标。

将来先把精确现状备份到记录中的单个路径，再以`sudo install -o root -g root -m 0644`安装增量文件，执行`sudo nginx -t`，通过后才`sudo nginx -s reload`。失败时恢复精确备份或删除本次唯一include行和增量文件，重新测试后reload。禁止通配符操作。本轮不写配置、不reload。

## 6. 将来部署顺序

以下步骤本轮均不执行：

1. 新鲜只读预检；任一身份、网络、端口、资源或8077结构异常即停止。
2. 共同使用人在仓库外记录精确CIDR、硬配额方法、变更、验证、回滚和共租户停止阈值。
3. 再次核对manifest。当前`0961cc3`不兼容，必须在此停止，直到用户接受兼容SmartScan镜像集和PostgreSQL候选。
4. 经授权用精确`sudo install -d`创建配置根和数据子目录，按核验UID/GID设所有权，实施硬配额或另批独立挂载。
5. 仓库外生成真实配置，以`sudo install -m 0600`安装，禁止回显或提交。
6. 创建三张已记录固定网络；运行预检、UAT配置校验和`docker compose ... config --quiet`，不输出展开Secret。
7. 只按最新接受的固定digest拉取并核对；不登录无关Registry，不拉可变标签。
8. 启动专用PostgreSQL并等健康，运行一次性migrate；失败即停，不启动API。
9. 启动API、两个CPU Worker和内层Web，AI关闭；先验证`127.0.0.1:18082`。
10. 最后安装Nginx增量、测试、reload，经8077基础UAT并观察共租户。

将来需要sudo的精确类别只有：创建/授权目录、配额或独立挂载、安装0600配置、安装/回滚Nginx include、`nginx -t`和受控reload。Docker是否需要sudo以现场权限为准，不修改Docker组或daemon。

经逐项授权后使用的命令形态如下；`<...>`必须来自同一次仓库外确认，不得在Shell中使用未解析变量、通配符或命令替换：

```bash
sudo install -d -o root -g root -m 0750 /etc/smartscan/uat
sudo install -d -o <POSTGRES_UID> -g <POSTGRES_GID> -m 0700 /mnt/data/smartscan/uat/postgres
sudo install -d -o 10001 -g 10001 -m 0750 /mnt/data/smartscan/uat/data
sudo install -d -o 10001 -g 10001 -m 0750 /mnt/data/smartscan/uat/models/ocr
sudo install -o root -g root -m 0600 <PRIVATE_DEPLOY_ENV> /etc/smartscan/uat/deploy.env
sudo install -o root -g root -m 0600 <PRIVATE_RUNTIME_ENV> /etc/smartscan/uat/runtime.env
sudo install -o root -g root -m 0600 <PRIVATE_ALLOCATION> /etc/smartscan/uat/shared-host-allocation.json
sudo install -o root -g root -m 0600 <PRIVATE_PREFLIGHT_SUMMARY> /etc/smartscan/uat/preflight-summary.json
sudo install -o root -g root -m 0644 <REVIEWED_SMARTSCAN_INCLUDE> /etc/nginx/snippets/smartscan-uat-8077.locations.conf
sudo nginx -t
sudo nginx -s reload
```

现有8077配置的单文件备份、增加include行与回滚必须使用仓库外记录的精确`<8077_SERVER_CONFIG>`和`<BACKUP_FILE>`，先逐行审阅再授权；方案刻意不生成可能误改共享配置的通用`sed`命令。网络创建、镜像拉取、Compose迁移和启动命令由最终接受的CIDR及digest生成，在当前制品兼容门禁解除前不得生成可直接执行的部署脚本。

## 7. 验收

- 登录、刷新会话和退出；创建项目并验证跨用户隔离。
- 分片上传、断点续传、重复分片、大小/哈希错误和取消。
- 两个CPU Worker处理，AI关闭时基础流程正常。
- 原图/结果预览、页序和版本绑定；JPG及多页PDF导出。
- 鉴权下载、Range `206`、文件哈希和下载响应头。
- 精确停止/重启项目后数据库和业务文件持久化。
- 验证兼容digest版本回滚；比较其他服务前后状态、错误率、资源和OOM，异常立即撤回。
- 8077的308、静态资源、API和内部指标404全部符合预期。

HTTP IP入口不能通过`getUserMedia`实时相机、企业微信、Android/iOS正式网络安全或完整移动验收；文件选择或系统拍照兜底也不等于实时相机通过。

## 8. 回滚

1. 先移除本次唯一Nginx include行或恢复精确备份，`nginx -t`后reload，退出外部流量。
2. 对精确项目执行`docker compose -p smartscan-uat ... stop`，默认保留对象取证。
3. 仅在确认三张网络没有非SmartScan端点且获得清理授权后执行精确项目`down`，不带`-v`；有未知端点立即停止。
4. 默认保留数据和Secret。清理是另一个破坏性授权，须列出每个绝对路径并核对挂载点、项目ID和所有权。
5. 当前迁移入口不提供自动降级。首次空库失败可经独立授权重建；产生数据后保留并向前修复。UAT无备份，不承诺数据回滚。
6. 只能回到用户已接受且兼容当前数据库和`/smartscan/`契约的上一组digest。`0961cc3`不是可用回滚组，因此首次部署前的回滚只有撤入口并停止整栈。

禁止任何prune、通配符删除、`down -v`、强删未知网络/卷、修改无关服务或把UAT目录转为生产。

## 9. 最终授权点

实际部署必须分别取得：部署窗口只读复查；精确三网/18082/配额/停止阈值确认；兼容五镜像digest接受；PostgreSQL digest接受；sudo目录和硬限制授权；Secret安装授权；Docker网络/拉取授权；PostgreSQL/迁移/应用启动授权；Nginx安装测试reload授权；停止重启、回滚及最终保留或清理授权。

未获相应授权前，不得创建目录、Secret、网络、容器，不得拉取镜像、迁移或修改/reload Nginx。
