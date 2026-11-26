# OPS-001I 统一受限控制器与通用离线镜像交付

## 目的与边界

目标服务器到 GHCR Blob/CDN 的直接传输已多次出现低速和连接重置，`OPS-001H` 的顺序 `docker pull` 路线停止。`OPS-001I` 保留用户已经接受的六个源 digest，以经审核发布清单、独立 Docker image archive 和本地不可变 Tag 完成等强度内容映射，并用一次性安装的 `smartscan-uatctl` 收口后续 UAT 操作。

本工作包只交付仓库代码、测试、GitHub Actions 和文档，不连接或修改服务器，不导入镜像、不启动容器、不运行迁移，也不修改 Nginx。已有 loop、部署准备、OCR 暂存和 OCR 安装执行器继续保留，统一控制器只验证或复用其结果。

## 固定发布清单

`deploy/releases/uat-2026-11-24.json` 是当前 UAT 候选的唯一机器可读事实源，固定：

- 六个 `ghcr.io/j4meshub/smartscan-*` 源引用及完整 digest；
- `linux/amd64` 平台；
- 每个服务的本地不可变 Tag 和独立归档名；
- SmartScan 应用镜像的来源提交；
- 固定 SSH 别名和服务器上传目录。

后续自动构建不得修改已接受清单。新版本必须新增或明确更新审核清单，重新生成证据并由用户接受；未变化的镜像可以继续引用原归档。

## 通用离线工具

统一入口为：

```powershell
python tools/smartscan_offline_images.py plan
python tools/smartscan_offline_images.py download
python tools/smartscan_offline_images.py verify
python tools/smartscan_offline_images.py upload
python tools/smartscan_offline_images.py status
```

工具不接受 URL、Tag、digest、仓库、平台、服务器或路径参数。`download` 只从成功的按需 GitHub Actions 运行取得固定 Artifact，复用本机 Git 凭据但不打印或保存令牌；`.part` 支持断点续传。`upload` 只连接 `smartscan-server`，上传到固定目录，使用 `.part`、远端摘要复核和原子改名；不读取 SSH 私钥或口令。

本机归档位于 `.smartscan-offline-transfer/images/<release-id>/`，该根目录已被 `.gitignore` 排除。每个服务独立归档，任何一个中断不要求重传其他归档。

## 内容完整性映射

普通 `docker save/load` 不保证保留 Registry 的 `RepoDigest`。本方案不伪造该字段，而是固定以下链路：

```text
用户接受的源 digest
→ 源 index/manifest 原始字节及 SHA-256
→ linux/amd64 manifest
→ config 与全部 layer digest/长度/媒体类型
→ 独立 Docker image archive SHA-256
→ 导入后的 image ID（等于 config digest）
→ SmartScan 本地不可变 Tag
```

归档内保留源 index/manifest 原始对象、config 和原始压缩 layer，并提供传统 Docker daemon 所需的 `manifest.json`；不重新压缩或改写 layer。离线 `verify` 会重新计算每个对象的 SHA-256，核对源 index 到 `linux/amd64` descriptor、平台 manifest 到 config/layer、config 到 diff ID 以及 Docker 清单到本地 Tag 的绑定，并拒绝缺层、额外成员、特殊文件、路径穿越、错误平台、错误长度或摘要。服务器导入后每次启动前必须验证本地 Tag 仍指向发布映射中的 image ID。

UAT Compose 只使用服务器生成的 `local-images.env`，所有服务固定 `pull_policy: never`。`deploy.env` 中的六个 GHCR digest继续作为来源证据，不直接作为离线运行引用。

## GitHub Actions

`.github/workflows/uat-offline-images.yml` 执行：

1. Windows 和 Ubuntu 单元测试；
2. 对六个固定源 digest 解析 `linux/amd64` 对象并生成独立 Docker image archive；
3. 离线复核完整对象图；
4. 在没有外部接口的独立 Docker daemon 中导入归档，核对本地 Tag 与 image ID；
5. 使用无网络、只读根文件系统、零 capability 和资源限制执行 UID/GID 探测；
6. 验证 Compose 只使用本地不可变 Tag 且 `pull_policy: never`；
7. 仅在按需运行时上传六个独立归档及中文发布映射。

工作流不发布新镜像、不改变 Package 可见性、不连接目标服务器。归档 Artifact 只在用户已经接受清单后按需生成，不是每次主线提交的常规产物。

PR #106 的Linux实证候选如下。六个归档均在没有外部接口、关闭bridge/iptables/转发的独立Docker daemon中完成`docker load`、image ID核对和受限身份探测；这些摘要在用户明确接受发布映射前不得上传或导入UAT服务器。

| 服务 | 归档大小 | SHA-256 |
|---|---:|---|
| PostgreSQL | 119,900,160字节（114.35 MiB） | `9c70db621d3f56ac7ec509f903447e1455d2b92e4a93ab1d20c511d18da70242` |
| API | 90,163,200字节（85.99 MiB） | `8ae4194b3f28ddd7a9655ac39cf1eb01e0c6b740c953fc440ece309b7dda1fb4` |
| Worker | 499,025,920字节（475.91 MiB） | `4f71e50cd25b0d40cc201b87cef6859c746fe9c7f490832859c553c7dd7b99db` |
| AI Gateway | 90,132,480字节（85.96 MiB） | `cd1a5870af42ee936f6987a6c0b91c4527c0d0308be566e8cca59472fbf6394b` |
| Web | 27,504,640字节（26.23 MiB） | `dc7b601a6737d227ed1a5fac7f573bf192dfcb412f8ee05dd20ee3d487427807` |
| Ops | 90,357,760字节（86.17 MiB） | `035c17b916f6a7be3eccaf3787dd0b6b4ba950df7ea4f677555e37bdd0cf7ad4` |
| 合计 | 917,084,160字节（874.60 MiB） | 每个归档独立校验 |

本机最终文件占用为874.60 MiB。下载器逐个下载、解包并删除Artifact ZIP；最大Worker归档处理期间的理论瞬时占用约1.13 GiB，执行前要求至少2 GiB可用空间，以保留文件系统和ZIP开销余量。

## 统一控制器

安装路径固定为：

```text
/usr/local/libexec/smartscan/smartscan-uatctl
/usr/local/libexec/smartscan/smartscan_uatctl.py
/usr/local/libexec/smartscan/docker-compose.uat.yml
/usr/local/libexec/smartscan/shared-8077-smartscan-location.conf
/etc/sudoers.d/smartscan-uatctl
```

控制器只接受 sudoers 中逐条列出的固定无参数命令：状态、预检、存储/模型/配置验证、发布接受、镜像导入和验证、身份探测、所有权、数据库、迁移、核心服务、Nginx 分阶段操作、基础 UAT、精确停止和镜像回滚。它不接受路径、URL、digest、Tag、服务名或任意命令，不提供 shell、`prune`、`down -v`、通配符删除或数据清理。

OPS-001K取代OPS-001J的正常部署调用链：`verify-storage`、`verify-models`和`verify-config`直接调用`smartscan_uat_validators.py`中的只读结构化函数，不再启动旧执行器、双层sudo或解析stdout。旧loop、OCR和部署准备执行器及其sudoers保持原样，只供低频初始化、修复或维护；统一控制器不新增格式化、重建、模型安装、Secret轮换或删除能力。

内聚验证返回`passed`、`reason_code`、`evidence_summary`和`next_state`。严格JSON解析拒绝重复键、尾随内容、非UTF-8、超大输入和错误类型，但允许合法空白、缩进和字段顺序变化。所有输出均脱敏，配置验证只报告Secret字段存在、权限及长度/格式，不打印管理员密码或其他Secret。

root 拥有的 `/etc/smartscan/uat/uatctl-state.json` 只记录脱敏状态和证据。每一步验证前置状态；已完成步骤只复核，失败立即停止并保留现场。`resume-basic-uat` 可从断点继续到 PostgreSQL 健康，但在不可逆迁移前返回 `waiting_confirmation`；迁移获得单独授权并完成后，可继续启动并验证18082核心服务。Nginx `activate-nginx` 仍需固定 root 确认文件和单独授权。

静态 `Config.User` 只有同时给出数字 UID:GID 时才直接采用；否则控制器对单个固定本地镜像执行 `--network none`、只读根、无挂载/端口/Secret、`cap-drop ALL`、`no-new-privileges` 和 CPU/内存/PID 限制的固定 `id -u/-g` 探测，并生成 root 拥有的 `image-identities.json`。

Nginx激活不接受命令行路径。共同使用人必须在固定配置根预先安装root拥有的`nginx-activation.json`和`nginx-8077-server.updated.conf`：确认文件记录已审核的现有8077配置绝对路径、变更前SHA-256和更新后SHA-256，更新文件必须只包含一次固定SmartScan include。控制器先保存固定root备份，再安装固定location和已审核配置；`nginx -t`或reload任一步失败会恢复精确备份、移除本次唯一snippet并重新测试/reload。完整配置正文和内部路径不进入Git或脱敏输出。

## 一次性人工安装

用户必须在自己的 SSH 终端中先核对仓库提交和本文件列出的最终 SHA-256，再输入自己的 sudo 密码执行。AI 不请求、读取、传递或保存密码。

| 人工安装资产 | SHA-256 |
|---|---|
| `deploy/ops/smartscan-uatctl` | `d0b5bcdc95b2b2e81119b71eb00f082fc3dbebdb608c5bd0b993472235402153` |
| `deploy/ops/smartscan_uatctl.py` | `85c6adbb1c3e91a65326b75047025e01a9dd9f29b19578ce3d00f480c1ce3b89` |
| `deploy/ops/smartscan_uat_validators.py` | `27916a63ea05c9fb149255b5ee63edc1bd43b1f4e26ec347266eef6026e0467b` |
| `deploy/sudoers/smartscan-uatctl` | `081caf34e05798cc556e495728b6b88ce3b2318a3990ca4351d347a2ffcefef3` |
| `deploy/compose/docker-compose.uat.yml` | `4d1a236a3303bbd70bc3b138265ca4587240b109ca4f6a1cb7b0df3ac28d43bf` |
| `deploy/nginx/shared-8077-smartscan-location.conf.template` | `500aee2ae34f6a14e658823588899647ece628b97fb65554132eef95e741d227` |
| `deploy/releases/uat-2026-11-24.json` | `2caa6eea6c0f6b11f941dc3301069653015fe41c9e5c515569dfb6cc5c099789` |

```bash
sudo install -d -o root -g root -m 0755 /usr/local/libexec/smartscan
sudo install -o root -g root -m 0755 deploy/ops/smartscan-uatctl /usr/local/libexec/smartscan/smartscan-uatctl
sudo install -o root -g root -m 0755 deploy/ops/smartscan_uatctl.py /usr/local/libexec/smartscan/smartscan_uatctl.py
sudo install -o root -g root -m 0644 deploy/ops/smartscan_uat_validators.py /usr/local/libexec/smartscan/smartscan_uat_validators.py
sudo install -o root -g root -m 0644 deploy/compose/docker-compose.uat.yml /usr/local/libexec/smartscan/docker-compose.uat.yml
sudo install -o root -g root -m 0644 deploy/nginx/shared-8077-smartscan-location.conf.template /usr/local/libexec/smartscan/shared-8077-smartscan-location.conf
sudo install -o root -g root -m 0440 deploy/sudoers/smartscan-uatctl /etc/sudoers.d/smartscan-uatctl
sudo visudo -cf /etc/sudoers.d/smartscan-uatctl
sudo visudo -cf /etc/sudoers
sudo -k
sudo -n /usr/local/libexec/smartscan/smartscan-uatctl status
```

安装不会导入镜像、改变网络、启动容器或修改 Nginx。旧执行器不得删除或覆盖。

### OPS-001K仅升级控制器三文件

已安装OPS-001I/OPS-001J的主机不重新安装sudoers、Compose、Nginx模板或旧执行器。共同使用人先核对旧摘要并保存固定备份，再从经过审核的LF暂存目录安装包装器、控制器和内聚验证模块。三者摘要以OPS-001K合并提交和暂存报告为准，验证模块固定安装为`root:root 0644`，其余两文件为`root:root 0755`。

```bash
sudo sha256sum /usr/local/libexec/smartscan/smartscan-uatctl /usr/local/libexec/smartscan/smartscan_uatctl.py
# 预期旧摘要依次为55f65cc6...d66bac和8cd7ac4c...e91a7
sudo test ! -e /usr/local/libexec/smartscan/smartscan_uat_validators.py
sudo install -d -o root -g root -m 0700 /usr/local/libexec/smartscan/.ops001k-backup
sudo install -o root -g root -m 0755 /usr/local/libexec/smartscan/smartscan-uatctl /usr/local/libexec/smartscan/.ops001k-backup/smartscan-uatctl
sudo install -o root -g root -m 0755 /usr/local/libexec/smartscan/smartscan_uatctl.py /usr/local/libexec/smartscan/.ops001k-backup/smartscan_uatctl.py
sudo install -o root -g root -m 0644 <OPS001K_REVIEWED_DIR>/smartscan_uat_validators.py /usr/local/libexec/smartscan/smartscan_uat_validators.py
sudo install -o root -g root -m 0755 <OPS001K_REVIEWED_DIR>/smartscan_uatctl.py /usr/local/libexec/smartscan/smartscan_uatctl.py
sudo install -o root -g root -m 0755 <OPS001K_REVIEWED_DIR>/smartscan-uatctl /usr/local/libexec/smartscan/smartscan-uatctl
sudo sha256sum /usr/local/libexec/smartscan/smartscan-uatctl /usr/local/libexec/smartscan/smartscan_uatctl.py /usr/local/libexec/smartscan/smartscan_uat_validators.py
sudo visudo -cf /etc/sudoers.d/smartscan-uatctl
sudo visudo -cf /etc/sudoers
sudo -k
sudo -n /usr/local/libexec/smartscan/smartscan-uatctl status
```

新摘要必须与上表一致。`deploy/sudoers/smartscan-uatctl`仍为`081caf34...fcefef3`，无需替换。升级不运行`preflight`、旧执行器、镜像导入或状态迁移；`status`必须保留原`completed`列表。

若新文件摘要、wrapper自校验或`status`失败，只回滚本次三文件，先恢复辅助工具和包装器，再移除本次新增验证模块：

```bash
sudo install -o root -g root -m 0755 /usr/local/libexec/smartscan/.ops001k-backup/smartscan_uatctl.py /usr/local/libexec/smartscan/smartscan_uatctl.py
sudo install -o root -g root -m 0755 /usr/local/libexec/smartscan/.ops001k-backup/smartscan-uatctl /usr/local/libexec/smartscan/smartscan-uatctl
sudo rm -- /usr/local/libexec/smartscan/smartscan_uat_validators.py
sudo -k
sudo -n /usr/local/libexec/smartscan/smartscan-uatctl status
```

备份删除不属于升级授权，保留到后续单独清理决定。

### OPS-001L仅升级控制器两文件

OPS-001K三文件已经安装且内聚验证模块未变化。OPS-001L只需要从合并提交Git对象导出的LF包装器和控制器，不替换`smartscan_uat_validators.py`、sudoers、Compose、Nginx模板或旧执行器。人工命令中的暂存目录固定为`/home/szhzx/smartscan-uatctl-upgrade-ops001l`：

```bash
sudo sha256sum /usr/local/libexec/smartscan/smartscan-uatctl /usr/local/libexec/smartscan/smartscan_uatctl.py /usr/local/libexec/smartscan/smartscan_uat_validators.py
# 升级前预期依次为d18bdf2b...9a6c、4ead9ee4...104a、27916a63...467b
sudo install -d -o root -g root -m 0700 /usr/local/libexec/smartscan/.ops001l-backup
sudo install -o root -g root -m 0755 /usr/local/libexec/smartscan/smartscan-uatctl /usr/local/libexec/smartscan/.ops001l-backup/smartscan-uatctl
sudo install -o root -g root -m 0755 /usr/local/libexec/smartscan/smartscan_uatctl.py /usr/local/libexec/smartscan/.ops001l-backup/smartscan_uatctl.py
sudo install -o root -g root -m 0755 /home/szhzx/smartscan-uatctl-upgrade-ops001l/smartscan_uatctl.py /usr/local/libexec/smartscan/smartscan_uatctl.py
sudo install -o root -g root -m 0755 /home/szhzx/smartscan-uatctl-upgrade-ops001l/smartscan-uatctl /usr/local/libexec/smartscan/smartscan-uatctl
sudo sha256sum /usr/local/libexec/smartscan/smartscan-uatctl /usr/local/libexec/smartscan/smartscan_uatctl.py
# 升级后摘要以本节固定资产表和合并提交导出报告为准
sudo visudo -cf /etc/sudoers.d/smartscan-uatctl
sudo visudo -cf /etc/sudoers
sudo -k
sudo -n /usr/local/libexec/smartscan/smartscan-uatctl status
```

`status`必须保留五个已经完成的前置状态并返回`next_required=images_imported`。本步骤不授权`resume-basic-uat`。若包装器自校验、摘要或`status`失败，只回滚本次两文件：

```bash
sudo install -o root -g root -m 0755 /usr/local/libexec/smartscan/.ops001l-backup/smartscan_uatctl.py /usr/local/libexec/smartscan/smartscan_uatctl.py
sudo install -o root -g root -m 0755 /usr/local/libexec/smartscan/.ops001l-backup/smartscan-uatctl /usr/local/libexec/smartscan/smartscan-uatctl
sudo -k
sudo -n /usr/local/libexec/smartscan/smartscan-uatctl status
```

备份和暂存目录的删除不属于升级授权。

### OPS-001M升级控制器与迁移Compose

OPS-001M只替换包装器、控制器和UAT Compose，不修改验证模块、sudoers、Nginx模板或旧执行器。迁移服务继续使用只读根，只在现有32 MiB `/tmp` tmpfs中设置`SMARTSCAN_STORAGE_ROOT=/tmp/smartscan-data`，没有真实data挂载；API和Worker仍使用`/srv/smartscan/data`。迁移失败时Docker不保存原始日志，控制器只把固定错误码、异常类型和退出码写入`/etc/smartscan/uat/migration-failure.json`，不包含原始输出、连接串或Secret。

人工升级目录固定为`/home/szhzx/smartscan-uatctl-upgrade-ops001m`。升级前现场预期包装器、控制器和Compose摘要依次为`08003566…7861e`、`476f5656…c823`和`227af87b…408c`；应以现场人工核验为准。安装顺序固定为辅助工具、Compose、包装器，确保包装器最后才切换摘要门禁：

```bash
sudo sha256sum /usr/local/libexec/smartscan/smartscan-uatctl /usr/local/libexec/smartscan/smartscan_uatctl.py /usr/local/libexec/smartscan/docker-compose.uat.yml
sudo install -d -o root -g root -m 0700 /usr/local/libexec/smartscan/.ops001m-backup
sudo install -o root -g root -m 0755 /usr/local/libexec/smartscan/smartscan-uatctl /usr/local/libexec/smartscan/.ops001m-backup/smartscan-uatctl
sudo install -o root -g root -m 0755 /usr/local/libexec/smartscan/smartscan_uatctl.py /usr/local/libexec/smartscan/.ops001m-backup/smartscan_uatctl.py
sudo install -o root -g root -m 0644 /usr/local/libexec/smartscan/docker-compose.uat.yml /usr/local/libexec/smartscan/.ops001m-backup/docker-compose.uat.yml
sudo install -o root -g root -m 0755 /home/szhzx/smartscan-uatctl-upgrade-ops001m/smartscan_uatctl.py /usr/local/libexec/smartscan/smartscan_uatctl.py
sudo install -o root -g root -m 0644 /home/szhzx/smartscan-uatctl-upgrade-ops001m/docker-compose.uat.yml /usr/local/libexec/smartscan/docker-compose.uat.yml
sudo install -o root -g root -m 0755 /home/szhzx/smartscan-uatctl-upgrade-ops001m/smartscan-uatctl /usr/local/libexec/smartscan/smartscan-uatctl
sudo sha256sum /usr/local/libexec/smartscan/smartscan-uatctl /usr/local/libexec/smartscan/smartscan_uatctl.py /usr/local/libexec/smartscan/docker-compose.uat.yml
sudo visudo -cf /etc/sudoers.d/smartscan-uatctl
sudo visudo -cf /etc/sudoers
sudo -k
sudo -n /usr/local/libexec/smartscan/smartscan-uatctl status
```

升级后第一条控制器命令只能是`status`，必须保留现场已完成状态并继续显示`next_required=migrations_completed`；本步骤不授权再次运行迁移。若摘要、包装器自检或`status`失败，按辅助工具、Compose、包装器顺序恢复备份：

```bash
sudo install -o root -g root -m 0755 /usr/local/libexec/smartscan/.ops001m-backup/smartscan_uatctl.py /usr/local/libexec/smartscan/smartscan_uatctl.py
sudo install -o root -g root -m 0644 /usr/local/libexec/smartscan/.ops001m-backup/docker-compose.uat.yml /usr/local/libexec/smartscan/docker-compose.uat.yml
sudo install -o root -g root -m 0755 /usr/local/libexec/smartscan/.ops001m-backup/smartscan-uatctl /usr/local/libexec/smartscan/smartscan-uatctl
sudo -k
sudo -n /usr/local/libexec/smartscan/smartscan-uatctl status
```

备份与暂存目录的删除仍不属于升级授权；sudoers摘要保持`081caf34…fcefef3`，无需替换。

## 授权与恢复顺序

在用户接受发布映射、归档已校验并上传且控制器安装通过后，可以单独授权：

```bash
sudo -n /usr/local/libexec/smartscan/smartscan-uatctl resume-basic-uat
```

该命令只执行可安全续接的固定步骤，并在迁移前停止。其后仍需分别授权：

1. `run-migrations`：不可逆数据库迁移；
2. 再次 `resume-basic-uat`：启动并验证核心服务；
3. `stage-nginx`：只在 SmartScan 配置根暂存固定片段；
4. `activate-nginx`：共享 Nginx 增量和 reload；
5. 生产上线、删除、数据清理或网络清理：不属于普通控制器授权。

`stop-core` 只停止固定核心服务并保留数据库、网络、镜像和数据。`rollback-images` 只允许切换到预先安装并验证的上一发布映射；它不删除当前镜像或数据。任何异常对象、Tag/image ID漂移、部分状态或摘要不一致都会失败关闭。

## OPS-001L Docker 29 containerd身份兼容

现场Docker 29.0.2启用了containerd image store。首个PostgreSQL归档导入后，归档、Config和全部Layer均与发布映射一致，但本地Image ID不再等于Config digest，而是Docker为导入内容生成的schema2 manifest digest。该差异归类为运行时身份字段变化，不是镜像内容变化。

统一控制器现在同时验证两层身份：

1. 源内容层：接受的GHCR源digest、`linux/amd64`平台manifest、Config digest、全部压缩Layer digest/大小、RootFS diff IDs和归档SHA-256；
2. 运行时层：用已验证Config和Layer重算Docker schema2 manifest，核对`Descriptor.digest/size`、实际Image ID、平台、用户、revision/version及唯一本地不可变Tag。

传统daemon仍要求Image ID等于Config digest；containerd模式必须满足“实际Image ID = Descriptor digest = 重算schema2 digest”。因此没有删除Image ID比较，也没有把containerd生成的本地RepoDigest伪装成源Registry RepoDigest。`image-identities.json`使用1.1契约同时记录源内容字段和实际运行时身份，所有权应用前再次验证。

CI保留传统daemon完全断网路径，并使用固定Docker 29.0.2和containerd image store再执行一次六镜像连续导入、UID/GID探测、身份文件、所有权及PostgreSQL健康。OPS-001M已把两条路径扩展到空库迁移`20261022_0024`；首次完整核心续接发现接受的Worker候选缺少`libGL.so.1`，API与内层Web健康但两个CPU Worker失败关闭。仓库已修复Worker运行库并增加无网络只读启动检查；新固定digest和发布映射经用户接受前，CI明确停在迁移完成门禁，不把当前候选写成核心健康。Compose仍固定`pull_policy: never`。

## 回滚

- 下载或上传失败：保留 `.part`，下次从固定偏移续传；不改用Tag或其他digest。
- 导入失败：停止后续步骤，保留已导入镜像和证据；不执行清理或`prune`。
- 身份或所有权失败：不启动数据库；异常目录保持现场。
- 数据库启动失败：仅停止固定SmartScan数据库需另行授权，数据保留。
- 迁移失败：不自动降级、不删除数据库，转为人工评估。
- 核心服务失败：不进入Nginx阶段。
- Nginx失败：只处理本次固定增量对象并重新验证，不影响其他location。
- 所有删除、替换、数据清理和现有网络移除仍需新的精确授权。

## OPS-001N 单Worker增量发布

现场迁移已达到`20261022_0024`，状态停在`core_started`前。旧Worker缺少视觉运行库而禁止启动；候选发布`smartscan-uat-2026-11-26-worker-fix`只替换Worker，并将其余五项源digest、归档证据和本地不可变Tag锁定为旧发布值。

统一控制器新增的增量路径不重置既有`completed`：`accept-release`只登记等待候选，后续`resume-basic-uat`才验证并导入新Worker、确认`10001:10001`和data所有权、保存旧活动文件并切换发布。新Tag不覆盖旧Tag；任何失败恢复旧活动文件并保持核心停止。旧Worker已知不可启动，因此`rollback-images`恢复旧证据后不会自动重启核心。

本次需人工安装的资产为包装器、控制器、UAT Compose和候选清单；`smartscan_uat_validators.py`、Nginx模板及sudoers未改变。精确摘要在OPS-001N合并提交确定后更新到本节，安装顺序必须为控制器、Compose、候选清单、包装器，确保包装器最后切换摘要门禁。详见[OPS-001N修复版Worker与增量UAT发布](OPS001N_WORKER_INCREMENTAL_RELEASE.md)。

仓库LF规范字节摘要如下；合并后必须从合并提交Git对象导出，不能直接使用可能被Windows换行转换的工作树文件：

| 资产 | SHA-256 |
|---|---|
| `deploy/ops/smartscan-uatctl` | `0e06377cc467798a8ae75654eb33e258c55f58f35adfbbe42bc162792b050636` |
| `deploy/ops/smartscan_uatctl.py` | `30ffb74e2f2baf209f8a0dbb69a8e6bc9aea6aa2b2ed67bb05efe81d66444638` |
| `deploy/compose/docker-compose.uat.yml` | `b8bc7d1208bb58dd353f0934e1fb9e19b0b251aaaeac023fc19edd5aa7075d31` |
| `deploy/releases/uat-2026-11-26-worker-fix.json` | `8debb3d83867d05e6eb6d885a9153a5b5dd20a244411e3ec2fbe6f77038f6003` |
| `deploy/ops/smartscan_uat_validators.py`（不变） | `27916a63ea05c9fb149255b5ee63edc1bd43b1f4e26ec347266eef6026e0467b` |
| `deploy/sudoers/smartscan-uatctl`（不变） | `081caf34e05798cc556e495728b6b88ce3b2318a3990ca4351d347a2ffcefef3` |
| `deploy/nginx/shared-8077-smartscan-location.conf.template`（不变） | `500aee2ae34f6a14e658823588899647ece628b97fb65554132eef95e741d227` |
| `deploy/releases/uat-2026-11-24.json`（不变） | `2caa6eea6c0f6b11f941dc3301069653015fe41c9e5c515569dfb6cc5c099789` |

本工作包不修改sudoers。用户接受候选并完成普通用户资产暂存后，人工升级仍须先备份现有包装器、控制器和Compose，再按“控制器→Compose→候选清单→包装器”安装，运行`visudo -cf /etc/sudoers.d/smartscan-uatctl`，最后只执行`status`。新摘要获最终合并提交确认前不得用于服务器安装。

```bash
sudo install -d -o root -g root -m 0700 /usr/local/libexec/smartscan/.ops001n-backup
sudo install -o root -g root -m 0755 /usr/local/libexec/smartscan/smartscan-uatctl /usr/local/libexec/smartscan/.ops001n-backup/smartscan-uatctl
sudo install -o root -g root -m 0755 /usr/local/libexec/smartscan/smartscan_uatctl.py /usr/local/libexec/smartscan/.ops001n-backup/smartscan_uatctl.py
sudo install -o root -g root -m 0644 /usr/local/libexec/smartscan/docker-compose.uat.yml /usr/local/libexec/smartscan/.ops001n-backup/docker-compose.uat.yml
sudo install -o root -g root -m 0755 /home/szhzx/smartscan-uatctl-upgrade-ops001n/smartscan_uatctl.py /usr/local/libexec/smartscan/smartscan_uatctl.py
sudo install -o root -g root -m 0644 /home/szhzx/smartscan-uatctl-upgrade-ops001n/docker-compose.uat.yml /usr/local/libexec/smartscan/docker-compose.uat.yml
sudo install -o root -g root -m 0644 /home/szhzx/smartscan-uatctl-upgrade-ops001n/uat-2026-11-26-worker-fix.json /usr/local/libexec/smartscan/uat-2026-11-26-worker-fix.json
sudo install -o root -g root -m 0755 /home/szhzx/smartscan-uatctl-upgrade-ops001n/smartscan-uatctl /usr/local/libexec/smartscan/smartscan-uatctl
sudo visudo -cf /etc/sudoers.d/smartscan-uatctl
sudo -k
sudo -n /usr/local/libexec/smartscan/smartscan-uatctl status
```

升级前若任一摘要、对象类型或权限不一致即停止。回滚只替换上述三项既有资产并删除尚未被活动控制器引用的候选清单需要新的人工授权；不得修改`uatctl-state.json`。候选清单一旦已被接受，不得只回滚控制器而保留不兼容状态。

## 当前状态

截至OPS-001N开始，六镜像旧发布、身份文件、所有权、PostgreSQL健康及迁移`20261022_0024`均已完成；API、Worker、Web、AI和共享Nginx未启动。新Worker和新发布映射经用户明确接受前，不下载、不上传、不导入，也不修改服务器活动发布。
