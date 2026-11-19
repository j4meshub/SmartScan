# OPS-001 共享宿主机 UAT 变更方案

> 状态：**待授权、未执行**。本方案不授权服务器写入，不包含真实 CIDR、内部地址、凭据或 Secret。命令均为将来取得逐项授权后的草案。

## 1. 变更对象

| 对象 | 计划值 | 边界 |
|---|---|---|
| Compose项目 | `smartscan-uat` | 不接管现有项目 |
| 配置目录 | `/etc/smartscan/uat` | 目录`0750`，真实文件`0600` |
| loop后备文件 | `/mnt/data/smartscan-loop/uat.ext4` | 完整预分配50 GiB、`0600`、禁止稀疏 |
| 数据根 | `/mnt/data/smartscan/uat` | loop ext4挂载点，UAT数据可丢弃重建 |
| systemd单元 | `/etc/systemd/system/mnt-data-smartscan-uat.mount` | `0644`，依赖`/mnt/data`，不使用`/etc/fstab` |
| 子目录 | `postgres`、`data`、`models/ocr` | UID/GID按拉取后镜像事实设置，不猜测 |
| 配置文件 | `deploy.env`、`runtime.env`、资源确认、预检和loop证据 | 仓库外生成，不打印完整内容 |
| Docker网络 | `smartscan-uat_data`、`smartscan-uat_edge`、`smartscan-uat_egress` | 数据、入口、受控出站三种用途，固定CIDR |
| 回环入口 | `127.0.0.1:18082` | 唯一发布的宿主机端口 |
| Nginx增量 | `/etc/nginx/snippets/smartscan-uat-8077.locations.conf` | 只含SmartScan location |

基础容器和上限：PostgreSQL 1 vCPU/2 GiB/256 PID；一次性migrate 0.25/512 MiB/128；API 1.5/2 GiB/512；两个CPU Worker各1.25/2 GiB/256；Web Nginx 0.25/256 MiB/128。AI Worker 1/2 GiB/256和AI Gateway 1/1 GiB/256属于默认关闭的`ai` Profile。基础栈含migrate为5.5 vCPU/8.75 GiB，启用AI后为7.5 vCPU/11.75 GiB，均低于整栈8 vCPU/16 GiB。

预期名称为`smartscan-uat-postgres-1`、`smartscan-uat-migrate-1`、`smartscan-uat-api-1`、`smartscan-uat-worker-cpu-1-1`、`smartscan-uat-worker-cpu-2-1`、`smartscan-uat-nginx-1`，以及默认不启动的两个AI容器。PostgreSQL、API、Worker和AI Gateway不发布宿主机端口。八个服务的容器根文件系统全部只读；PostgreSQL socket使用16 MiB tmpfs，不使用named volume。

完全不修改：`/mnt/data`原挂载参数、现有100/400 GiB loop挂载及其后备文件；其他Compose项目、容器、网络、卷和镜像；80/443；8077全局参数及无关`server/location`；Docker daemon、防火墙、路由、VPN、GPU、现有数据库和监控。不会新增Alertmanager、Node Exporter、19081、主机代理或源码目录。

## 2. 网络方案

部署窗口先通过唯一批准的SSH别名，以普通用户重新只读采集全部Docker IPAM/端点、主机路由表、策略路由、接口和当前可见VPN路由、8077/18082监听、磁盘、inode、内存、负载及容器状态；不得扫描其他主机或网段。

三张CIDR只从仓库外候选中选择，必须互不重叠、网关属于子网，并且不与Docker IPAM、任何主机/策略/VPN路由或保留网段重叠。精确CIDR、网关、时间、确认人、验证和回滚只进入给用户的仓库外审批报告及真实配置。公开仓库仅保留占位符。任一重叠、采集不完整、18082被占用或8077结构变化，立即停止且不创建网络。

## 3. loop ext4存储方案

50 GiB是整个UAT根的硬限制，不是业务文件单项配额：

| 用途 | 预算 |
|---|---:|
| PostgreSQL数据与内置WAL | 12 GiB |
| 业务原图、结果与导出 | 32 GiB |
| OCR模型 | 4 GiB |
| ext4元数据与运行余量 | 2 GiB |

前3项是48 GiB持久化数据预算。创建文件系统后实际可用空间不足48 GiB时，只能下调业务文件预算并增加运行余量，不得扩大后备文件突破50 GiB。应用部署级和单用户配额最多为当次确认的业务文件预算。PostgreSQL不启用无异机目标的WAL归档。固定digest镜像不计入loop；Docker `json-file`日志位于共享Docker根目录，每容器固定`10m × 3`，AI Profile启用时八个容器理论上限约240 MiB。

- 70%提示并检查增长；85%告警并执行经确认的受控清理，禁止自动删除原图；95%停止新增写入和上传，保留只读访问。
- 使用专用后备文件`/mnt/data/smartscan-loop/uat.ext4`，必须以`fallocate`完整预分配50 GiB并证明不是稀疏文件，权限`0600`。
- 格式化为ext4，reserved block比例为0；挂载到`/mnt/data/smartscan/uat`，参数固定为`loop,nodev,nosuid,noatime`。
- 通过[`mnt-data-smartscan-uat.mount.template`](../deploy/systemd/mnt-data-smartscan-uat.mount.template)持久挂载，单元权限`0644`、明确依赖`/mnt/data`；loop设备必须为autoclear。
- 不使用ext4 project quota、`/etc/fstab`或共享数据盘重挂载，不触碰现有loop挂载。应用配额和70/85/95只是纵深防御，不能替代50 GiB文件系统硬限制。
- 全部服务根文件系统只读。tmpfs上限：PostgreSQL 64+16 MiB；migrate 32 MiB；API 128+32 MiB；两个CPU Worker各512 MiB；AI Worker 128 MiB；AI Gateway 16 MiB；Web 64+32+4 MiB。PostgreSQL只有数据目录允许持久写入loop。

## 4. 镜像方案

`0961cc3`五个SmartScan digest只保留历史制品证据，不使用可变标签：

```text
ghcr.io/j4meshub/smartscan-api@sha256:b4f97968a81777c9b46bcae272be5153df796cfd4b2f9221008facc53358300a
ghcr.io/j4meshub/smartscan-worker@sha256:0dc0fe0de3e4518985bd906a08815b70419d86d5530e300a216d25a221ad07f7
ghcr.io/j4meshub/smartscan-ai-gateway@sha256:8e7af7bf3d23687c19ecdd10b85044eee8321a019f831bb7744ce2575fc0518c
ghcr.io/j4meshub/smartscan-web@sha256:44a0faf547140844eb065a65034d442b66dd9f971ae5521b8a97400bd50df915
ghcr.io/j4meshub/smartscan-ops@sha256:ef4dd40c7b8a494e92540dc5bb476ab144903402142a0bbb0fdc4fd688138a5b
```

**失败关闭：不得直接部署这组镜像。** 源码复核确认`0961cc3` Web默认请求根路径`/api`，不支持`/smartscan/api`；其Ops校验器也早于资源确认1.2。禁止用共享根`/api`、Nginx `sub_filter`或浏览器本地覆盖绕过。

主线`f38dd4f3b6dc43565e70d99e3c0ab93f38d0226c`五个镜像已经核对来源提交、`linux/amd64`、SBOM和漏洞门禁。Web支持`/smartscan/api`，Ops支持资源确认1.2；但Ops早于本次loop证据、只读根文件系统和48 GiB数据预算契约，整套仍未获部署接受。精确digest和证据见[`F38DD4F_CONTAINER_VERIFICATION.md`](F38DD4F_CONTAINER_VERIFICATION.md)，不得自动写入真实UAT配置或拉取。

新主线镜像不得自动替换任何已记录候选；只有用户明确接受整套兼容固定digest后，才允许写入仓库外真实配置。

PostgreSQL 17候选为`postgres@sha256:0d938e975177bef9f1f61f3f9dbcf2e0aa0a139568f66d3415ed8892eb97f6ac`，已由用户于2026-11-19接受为拟部署候选，但本轮未拉取。获准实际拉取后仍须核对RepoDigest、`linux/amd64`、实际UID/GID和`postgres --version`为17，不一致立即停止。SmartScan五镜像需要本工作包合并后的新制品核验和用户另行接受，不能自动替换。

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
2. 共同使用人在仓库外记录精确CIDR、loop参数、变更、验证、回滚和共租户停止阈值。
3. 取得独立授权后创建并验证50 GiB非稀疏后备文件、ext4和systemd mount，生成脱敏loop证据；实际可用不足48 GiB则下调业务预算后重新确认。
4. 再次核对manifest；只有用户接受兼容当前loop契约的SmartScan五镜像后才允许拉取。PostgreSQL候选虽已接受，仍须在拉取后核对平台、版本和UID/GID。
5. 在已挂载loop内按核验UID/GID创建数据子目录；仓库外生成并以`0600`安装真实配置，禁止回显或提交。
6. 创建三张已记录固定网络；运行预检、loop证据校验、UAT配置校验和`docker compose ... config --quiet`，不输出展开Secret。
7. 只按最新接受的固定digest拉取并核对；不登录无关Registry，不拉可变标签。
8. 启动专用PostgreSQL并等健康，运行一次性migrate；失败即停，不启动API。
9. 启动API、两个CPU Worker和内层Web，AI关闭；先验证`127.0.0.1:18082`。
10. 最后安装Nginx增量、测试、reload，经8077基础UAT并观察共租户。

将来需要sudo的精确类别只有：创建专用目录和50 GiB后备文件、格式化专用文件、安装及启停SmartScan mount单元、创建/授权loop内目录、安装0600配置、安装/回滚Nginx include、`nginx -t`和受控reload。Docker是否需要sudo以现场权限为准，不修改Docker组或daemon。

经逐项授权后使用的命令形态如下；`<...>`必须来自同一次仓库外确认，不得在Shell中使用未解析变量、通配符或命令替换：

```bash
sudo install -d -o root -g root -m 0750 /etc/smartscan/uat
sudo install -d -o root -g root -m 0700 /mnt/data/smartscan-loop
sudo install -d -o root -g root -m 0755 /mnt/data/smartscan/uat
sudo sh -c 'umask 077; set -C; : > /mnt/data/smartscan-loop/uat.ext4'
sudo fallocate -l 50GiB /mnt/data/smartscan-loop/uat.ext4
sudo chmod 0600 /mnt/data/smartscan-loop/uat.ext4
sudo mkfs.ext4 -F -m 0 -E nodiscard -L smartscan-uat /mnt/data/smartscan-loop/uat.ext4
sudo install -o root -g root -m 0644 <REVIEWED_MOUNT_UNIT> /etc/systemd/system/mnt-data-smartscan-uat.mount
sudo systemctl daemon-reload
sudo systemctl enable --now mnt-data-smartscan-uat.mount
sudo install -d -o <POSTGRES_UID> -g <POSTGRES_GID> -m 0700 /mnt/data/smartscan/uat/postgres
sudo install -d -o 10001 -g 10001 -m 0750 /mnt/data/smartscan/uat/data
sudo install -d -o 10001 -g 10001 -m 0750 /mnt/data/smartscan/uat/models/ocr
sudo install -o root -g root -m 0600 <PRIVATE_DEPLOY_ENV> /etc/smartscan/uat/deploy.env
sudo install -o root -g root -m 0600 <PRIVATE_RUNTIME_ENV> /etc/smartscan/uat/runtime.env
sudo install -o root -g root -m 0600 <PRIVATE_ALLOCATION> /etc/smartscan/uat/shared-host-allocation.json
sudo install -o root -g root -m 0600 <PRIVATE_PREFLIGHT_SUMMARY> /etc/smartscan/uat/preflight-summary.json
sudo install -o root -g root -m 0600 <PRIVATE_LOOP_EVIDENCE> /etc/smartscan/uat/loop-storage-evidence.json
sudo install -o root -g root -m 0644 <REVIEWED_SMARTSCAN_INCLUDE> /etc/nginx/snippets/smartscan-uat-8077.locations.conf
sudo nginx -t
sudo nginx -s reload
```

创建前必须证明后备文件和挂载点未被使用。`fallocate`后及`mkfs.ext4`后均核对`stat`的逻辑大小与已分配块，拒绝稀疏文件。创建后用`dumpe2fs -h`核对ext4、label和reserved block，用`findmnt`核对挂载点、类型和参数，用`df -B1`核对实际可用空间，用`losetup --list --output NAME,BACK-FILE,AUTOCLEAR`核对autoclear，再将脱敏事实交给`tools/validate_uat_loop_storage.py`。以上命令本轮均未执行。

任何`sudo`写入前先运行创建前计划校验，不传`--evidence`：

```bash
python tools/validate_uat_loop_storage.py \
  --allocation <PRIVATE_ALLOCATION> \
  --mount-unit <REVIEWED_MOUNT_UNIT>
```

占位确认、未确认硬限制、错误预算、错误路径/参数或缺少回滚说明都会失败关闭。创建完成后再增加`--evidence <PRIVATE_LOOP_EVIDENCE>`验证实际事实。

创建后的只读验证命令草案为：

```bash
stat --format='%n %s %b %B %a' /mnt/data/smartscan-loop/uat.ext4
sudo dumpe2fs -h /mnt/data/smartscan-loop/uat.ext4
findmnt -no SOURCE,FSTYPE,OPTIONS,TARGET /mnt/data/smartscan/uat
df -B1 --output=size,avail,target /mnt/data/smartscan/uat
sudo losetup --list --output NAME,BACK-FILE,AUTOCLEAR
systemctl is-enabled mnt-data-smartscan-uat.mount
systemctl is-active mnt-data-smartscan-uat.mount
```

`stat`中的逻辑字节必须精确为50 GiB，`blocks × block-size`不得小于逻辑字节；证据文件只保存脱敏后的计算结果，不保存其他项目路径或完整主机快照。

现有8077配置的单文件备份、增加include行与回滚必须使用仓库外记录的精确`<8077_SERVER_CONFIG>`和`<BACKUP_FILE>`，先逐行审阅再授权；方案刻意不生成可能误改共享配置的通用`sed`命令。网络创建、镜像拉取、Compose迁移和启动命令由最终接受的CIDR及digest生成，在当前制品兼容门禁解除前不得生成可直接执行的部署脚本。

将来停止和解除loop挂载的命令草案如下；必须先确认SmartScan容器全部停止，且不得对其他项目执行：

```bash
docker compose -p smartscan-uat --env-file <PRIVATE_DEPLOY_ENV> -f <REVIEWED_COMPOSE> stop
sudo systemctl stop mnt-data-smartscan-uat.mount
findmnt --target /mnt/data/smartscan/uat
sudo losetup --list --output NAME,BACK-FILE,AUTOCLEAR
sudo systemctl disable mnt-data-smartscan-uat.mount
```

`findmnt`应证明挂载已解除，`losetup`应证明对应loop映射因autoclear消失。否则停止回滚并调查，不得强制detach仍在使用的设备。

## 7. 验收

- 登录、刷新会话和退出；创建项目并验证跨用户隔离。
- 分片上传、断点续传、重复分片、大小/哈希错误和取消。
- 两个CPU Worker处理，AI关闭时基础流程正常。
- 原图/结果预览、页序和版本绑定；JPG及多页PDF导出。
- 鉴权下载、Range `206`、文件哈希和下载响应头。
- 精确停止/重启Compose及systemd mount后数据库和业务文件持久化；验证loop autoclear后能重新挂载。
- 验证兼容digest版本回滚；比较其他服务前后状态、错误率、资源和OOM，异常立即撤回。
- 8077的308、静态资源、API和内部指标404全部符合预期。

HTTP IP入口不能通过`getUserMedia`实时相机、企业微信、Android/iOS正式网络安全或完整移动验收；文件选择或系统拍照兜底也不等于实时相机通过。

## 8. 回滚

1. 先移除本次唯一Nginx include行或恢复精确备份，`nginx -t`后reload，退出外部流量。
2. 对精确项目执行`docker compose -p smartscan-uat ... stop`，默认保留对象取证。
3. 仅在确认三张网络没有非SmartScan端点且获得清理授权后执行精确项目`down`，不带`-v`；有未知端点立即停止。
4. 停止`mnt-data-smartscan-uat.mount`，确认挂载解除且autoclear已释放loop设备，再禁用该单元。默认保留后备文件、配置和网络取证。
5. 删除systemd单元、后备文件、数据目录或网络是另一个破坏性授权，须列出每个绝对路径并核对挂载、端点、项目和所有权。
6. 当前迁移入口不提供自动降级。首次空库失败可经独立授权重建；产生数据后保留并向前修复。UAT无备份，不承诺数据回滚。
7. 只能回到用户已接受且兼容当前数据库、`/smartscan/`和loop契约的上一组digest。没有上一组时只能撤入口并停止整栈。

禁止任何prune、通配符删除、`down -v`、强删未知网络/卷、修改无关服务或把UAT目录转为生产。

## 9. 最终授权点

实际部署必须分别取得：部署窗口只读复查；精确三网/18082/停止阈值确认；sudo创建专用目录、后备文件、ext4和mount单元授权；mount启停授权；兼容五镜像digest接受；PostgreSQL候选拉取及核验授权；loop内目录和Secret安装授权；Docker网络/拉取授权；PostgreSQL/迁移/应用启动授权；Nginx安装测试reload授权；停止重启、回滚及最终保留或清理授权。

未获相应授权前，不得创建目录、后备文件、文件系统、挂载、Secret、网络或容器，不得拉取镜像、迁移或修改/reload Nginx。
