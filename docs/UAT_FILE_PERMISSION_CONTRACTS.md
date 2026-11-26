# UAT 固定文件权限契约

## 目标

本表是 `smartscan-uatctl`、包装器、安装说明和测试共享的权限事实来源。候选发布清单属于公开、非敏感、root 安装的不可变资产；部署证据、身份、活动发布状态和 Secret 仍是内部文件。修复候选清单权限冲突不得放宽任何内部文件。

所有表内普通文件均必须满足：固定绝对路径、普通文件、非符号链接、硬链接数为 1、所有者与精确模式一致。包含固定摘要的资产还必须逐字匹配审核摘要；目录、设备、FIFO、链接、额外路径或组/其他用户可写均失败关闭。

## 安装资产

| 对象 | 所有者与模式 | 敏感性 | 校验策略 |
|---|---|---|---|
| `/usr/local/libexec/smartscan/smartscan-uatctl` | `root:root 0755` | 非敏感 | 包装器自检、固定摘要、单硬链接 |
| `/usr/local/libexec/smartscan/smartscan_uatctl.py` | `root:root 0755` | 非敏感 | 包装器自检、固定摘要、单硬链接 |
| `/usr/local/libexec/smartscan/smartscan_uat_validators.py` | `root:root 0644` | 非敏感 | `PUBLIC_ROOT_ASSET_0644`、固定摘要、单硬链接 |
| `/usr/local/libexec/smartscan/docker-compose.uat.yml` | `root:root 0644` | 非敏感 | `PUBLIC_ROOT_ASSET_0644`、固定摘要、单硬链接 |
| `/usr/local/libexec/smartscan/shared-8077-smartscan-location.conf` | `root:root 0644` | 非敏感 | `PUBLIC_ROOT_ASSET_0644`、固定摘要、单硬链接 |
| `/usr/local/libexec/smartscan/uat-2026-11-26-worker-fix.json` | `root:root 0644` | 公开候选元数据 | `CANDIDATE_RELEASE_PUBLIC_ROOT_0644`、固定摘要、单硬链接；`0600`、`0640`、`0664`和`0777`均拒绝 |
| `/etc/sudoers.d/smartscan-uatctl` | `root:root 0440` | 授权策略 | `visudo`、固定命令集合、固定摘要；本工作包不修改 |

包装器中的 `CANDIDATE_RELEASE_MODE=644` 与 Python 的 `CANDIDATE_RELEASE_PUBLIC_ROOT_0644` 由源码一致性测试和真实 Linux sudo 测试共同约束，不能分别演化。

## 内部状态、部署证据与 Secret

| 对象 | 所有者与模式 | 策略或用途 |
|---|---|---|
| `deployment-input.json`、`preflight-summary.json`、`loop-storage-evidence.json` | `root:root 0600` | 仓库外部署输入与现场证据 |
| `shared-host-allocation.json` | `root:root 0600` | 内部地址、CIDR、端口和资源分配 |
| `release-manifest.json`、`release-map.json` | `root:root 0600` | 当前活动发布；`INTERNAL_STATE_ROOT_0600` |
| `previous-release-manifest.json`、`previous-release-map.json` | `root:root 0600` | 增量发布回滚证据；`INTERNAL_STATE_ROOT_0600` |
| `image-identities.json`、`previous-image-identities.json` | `root:root 0600` | 镜像运行身份和内容链证据；`INTERNAL_STATE_ROOT_0600` |
| `uatctl-state.json`、`migration-failure.json` | `root:root 0600` | 控制器状态和脱敏迁移失败证据；不得手工编辑 |
| `local-images.env`、`previous-local-images.env` | `root:root 0600` | 本地不可变 Tag 映射，不含 Registry 凭据 |
| `nginx-activation.json`、暂存/准备/备份的 Nginx 文件 | `root:root 0600` | 内部路径、摘要、确认和精确回滚证据；正式启用的 snippet 才为 `0644` |
| `deploy.env`、`runtime.env` | `szhzx:szhzx 0600` | Compose 与容器运行参数，包含 Secret |
| `bootstrap-admin-password` | `szhzx:szhzx 0600` | 一次性管理员密码；AI 不读取、不输出 |
| 上传根中的基础/候选 `release-manifest.json`、`release-map.json`与归档 | `szhzx:szhzx 0600` | 部署用户上传证据；`UPLOADED_RELEASE_DEPLOY_0600` |

以上敏感 JSON 使用 `INTERNAL_STATE_ROOT_0600` 或 `UPLOADED_RELEASE_DEPLOY_0600`。候选清单的 `0644` 例外不会被传播到这些文件；任何内部 JSON 变为 `0644` 都必须拒绝。

## 模型与数据目录

| 对象 | 所有者与模式 | 说明 |
|---|---|---|
| `/mnt/data/smartscan/uat/postgres` | `70:70 0700` | PostgreSQL 专用数据目录 |
| `/mnt/data/smartscan/uat/data` | `10001:10001 0750` | API 与两个 CPU Worker 共用业务目录 |
| `/mnt/data/smartscan/uat/models/ocr`及其子目录 | `root:root 0755` | Worker 只读挂载 |
| OCR 模型普通文件 | `root:root 0444` | 固定清单、逐文件摘要、无符号/硬链接 |
| `/etc/smartscan/uat` | `root:szhzx 0750` | 固定配置根；文件仍分别执行上表契约 |
| 离线上传根与候选版本子目录 | `szhzx:szhzx 0700` | 仅存已接受归档和元数据，不允许异常同名对象 |

## 自动化证据

- Ubuntu 单元作业使用真实 root 文件和真实 `sudo -u szhzx sudo -n` 调用包装器，验证候选 `0644`通过，`0600`、`0640`、`0664`、`0777`、非 root 所有者、符号链接、硬链接、目录和摘要漂移均拒绝。
- Python 加载器使用相同命名策略验证候选 `0644`和内部 JSON `0600`；内部 JSON `0644`拒绝。
- Docker 29/containerd 与传统 daemon 的完整断点测试以 root 安装的 `0644`候选清单，从`migrations_completed`执行增量接受、单 Worker 导入、身份核验、原子激活、API/双 CPU Worker/Web 健康和 18082 内部闭环，并在共享 Nginx 门禁前停止；AI Profile 保持关闭。
