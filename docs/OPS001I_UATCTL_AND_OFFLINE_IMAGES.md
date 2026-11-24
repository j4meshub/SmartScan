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

root 拥有的 `/etc/smartscan/uat/uatctl-state.json` 只记录脱敏状态和证据。每一步验证前置状态；已完成步骤只复核，失败立即停止并保留现场。`resume-basic-uat` 可从断点继续到 PostgreSQL 健康，但在不可逆迁移前返回 `waiting_confirmation`；迁移获得单独授权并完成后，可继续启动并验证18082核心服务。Nginx `activate-nginx` 仍需固定 root 确认文件和单独授权。

静态 `Config.User` 只有同时给出数字 UID:GID 时才直接采用；否则控制器对单个固定本地镜像执行 `--network none`、只读根、无挂载/端口/Secret、`cap-drop ALL`、`no-new-privileges` 和 CPU/内存/PID 限制的固定 `id -u/-g` 探测，并生成 root 拥有的 `image-identities.json`。

Nginx激活不接受命令行路径。共同使用人必须在固定配置根预先安装root拥有的`nginx-activation.json`和`nginx-8077-server.updated.conf`：确认文件记录已审核的现有8077配置绝对路径、变更前SHA-256和更新后SHA-256，更新文件必须只包含一次固定SmartScan include。控制器先保存固定root备份，再安装固定location和已审核配置；`nginx -t`或reload任一步失败会恢复精确备份、移除本次唯一snippet并重新测试/reload。完整配置正文和内部路径不进入Git或脱敏输出。

## 一次性人工安装

用户必须在自己的 SSH 终端中先核对仓库提交和本文件列出的最终 SHA-256，再输入自己的 sudo 密码执行。AI 不请求、读取、传递或保存密码。

| 人工安装资产 | SHA-256 |
|---|---|
| `deploy/ops/smartscan-uatctl` | `4b32eaf02872066d538e69bce8123e0582ea604d33960b1882395829e25d9448` |
| `deploy/ops/smartscan_uatctl.py` | `90a5e4be565e6efaafd08e2ea86f03f462dfcc41c4b32d884262dd47229cb6ac` |
| `deploy/sudoers/smartscan-uatctl` | `081caf34e05798cc556e495728b6b88ce3b2318a3990ca4351d347a2ffcefef3` |
| `deploy/compose/docker-compose.uat.yml` | `227af87ba75638c729254d8e78af819b9ab7e88f73c632e79c4c2a8eedc2408c` |
| `deploy/nginx/shared-8077-smartscan-location.conf.template` | `500aee2ae34f6a14e658823588899647ece628b97fb65554132eef95e741d227` |
| `deploy/releases/uat-2026-11-24.json` | `2caa6eea6c0f6b11f941dc3301069653015fe41c9e5c515569dfb6cc5c099789` |

```bash
sudo install -d -o root -g root -m 0755 /usr/local/libexec/smartscan
sudo install -o root -g root -m 0755 deploy/ops/smartscan-uatctl /usr/local/libexec/smartscan/smartscan-uatctl
sudo install -o root -g root -m 0755 deploy/ops/smartscan_uatctl.py /usr/local/libexec/smartscan/smartscan_uatctl.py
sudo install -o root -g root -m 0644 deploy/compose/docker-compose.uat.yml /usr/local/libexec/smartscan/docker-compose.uat.yml
sudo install -o root -g root -m 0644 deploy/nginx/shared-8077-smartscan-location.conf.template /usr/local/libexec/smartscan/shared-8077-smartscan-location.conf
sudo install -o root -g root -m 0440 deploy/sudoers/smartscan-uatctl /etc/sudoers.d/smartscan-uatctl
sudo visudo -cf /etc/sudoers.d/smartscan-uatctl
sudo visudo -cf /etc/sudoers
sudo -k
sudo -n /usr/local/libexec/smartscan/smartscan-uatctl status
```

安装不会导入镜像、改变网络、启动容器或修改 Nginx。旧执行器不得删除或覆盖。

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

## 回滚

- 下载或上传失败：保留 `.part`，下次从固定偏移续传；不改用Tag或其他digest。
- 导入失败：停止后续步骤，保留已导入镜像和证据；不执行清理或`prune`。
- 身份或所有权失败：不启动数据库；异常目录保持现场。
- 数据库启动失败：仅停止固定SmartScan数据库需另行授权，数据保留。
- 迁移失败：不自动降级、不删除数据库，转为人工评估。
- 核心服务失败：不进入Nginx阶段。
- Nginx失败：只处理本次固定增量对象并重新验证，不影响其他location。
- 所有删除、替换、数据清理和现有网络移除仍需新的精确授权。

## 当前状态

截至本工作包仓库交付，服务器上的loop、OCR模型、配置和三张固定网络事实保持不变；六个应用/数据库镜像尚未通过离线归档导入，`image-identities.json`、所有权、数据库、迁移、核心服务和Nginx均未执行。
