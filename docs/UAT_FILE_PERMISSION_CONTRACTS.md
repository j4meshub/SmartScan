# UAT 固定文件权限契约

## 目标

本表是 `smartscan-uatctl`、包装器、安装说明和测试共享的权限事实来源。OPS-001O历史候选曾作为root安装的0644资产；OPS-001P冻结普通发布接口后，当前候选改由固定普通用户0600上传入口交付。部署证据、身份、活动发布状态和Secret仍是内部文件，接口冻结不得放宽任何内部文件。

所有表内普通文件均必须满足：固定绝对路径、普通文件、非符号链接、硬链接数为 1、所有者与精确模式一致。包含固定摘要的资产还必须逐字匹配审核摘要；目录、设备、FIFO、链接、额外路径或组/其他用户可写均失败关闭。

## 安装资产

| 对象 | 所有者与模式 | 敏感性 | 校验策略 |
|---|---|---|---|
| `/usr/local/libexec/smartscan/smartscan-uatctl` | `root:root 0755` | 非敏感 | 包装器自检、固定摘要、单硬链接 |
| `/usr/local/libexec/smartscan/smartscan_uatctl.py` | `root:root 0755` | 非敏感 | 包装器自检、固定摘要、单硬链接 |
| `/usr/local/libexec/smartscan/smartscan_uat_validators.py` | `root:root 0644` | 非敏感 | `PUBLIC_ROOT_ASSET_0644`、固定摘要、单硬链接 |
| `/usr/local/libexec/smartscan/docker-compose.uat.yml` | `root:root 0644` | 非敏感 | `PUBLIC_ROOT_ASSET_0644`、固定摘要、单硬链接 |
| `/usr/local/libexec/smartscan/shared-8077-smartscan-location.conf` | `root:root 0644` | 非敏感 | `PUBLIC_ROOT_ASSET_0644`、固定摘要、单硬链接 |
| `/etc/sudoers.d/smartscan-uatctl` | `root:root 0440` | 授权策略 | `visudo`、固定命令集合、固定摘要；本工作包不修改 |

包装器只固定控制器、validators和不可变运行资产摘要，不再固定单次候选文件名或摘要。普通候选必须通过下表固定上传入口和既有`accept-release`状态机，不能成为通用root代码更新通道。

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
| `/home/szhzx/smartscan-uat-offline-images/candidate-release.json` | `szhzx:szhzx 0600` | 冻结后的固定候选入口；普通文件、非符号链接、单硬链接，摘要须与候选目录清单一致 |
| `/etc/smartscan/uat/publish-network-evidence.json` | `root:root 0600` | publish网络仓库外CIDR、风险接受、现场冲突检查和回滚证据 |

以上敏感JSON使用`INTERNAL_STATE_ROOT_0600`或`UPLOADED_RELEASE_DEPLOY_0600`。任何内部JSON变为`0644`都必须拒绝；历史root候选的0644策略不再参与普通发布路径。

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

- Ubuntu单元作业使用真实root文件和真实sudo调用包装器；固定上传候选只接受部署用户0600，0640、0644、0664、0777、错误所有者、符号链接、硬链接和异常类型均拒绝。
- Python加载器以同一`UPLOADED_RELEASE_DEPLOY_0600`策略验证固定候选入口；内部root JSON仍只接受0600。
- Docker 29/containerd完整断点测试从`core_started`接受单Web候选，导入和验证新Web、创建经确认的publish网络、原子激活主Web与代理，并验证回环可达/非回环不可达、真实OCR、AI关闭和共享Nginx未接触。
