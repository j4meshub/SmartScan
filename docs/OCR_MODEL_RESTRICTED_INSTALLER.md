# OCR-002 受限模型安装器人工安装说明

> 本说明只准备固定模型安装能力，不授权拉取、提取或安装模型。AI不得请求、读取、保存或
> 传递sudo密码。

## 固定文件与摘要

| 仓库文件 | 安装位置 | 所有者/权限 | SHA-256 |
|---|---|---|---|
| `deploy/ops/smartscan-uat-ocr-model` | `/usr/local/libexec/smartscan/smartscan-uat-ocr-model` | `root:root 0755` | `8623dfe1bdee24f143e1cc7ee2eee5b12ed17ee16873c374c887a4e2d3e914e2` |
| `deploy/ops/smartscan_uat_ocr_model.py` | `/usr/local/libexec/smartscan/smartscan_uat_ocr_model.py` | `root:root 0644` | `654dd06634c64ef15f95523ba227cbb7ec866c6eae162db3b33911afc82cadac` |
| `deploy/ops/smartscan-uat-ocr-model.sudoers` | `/etc/sudoers.d/smartscan-uat-ocr-model` | `root:root 0440` | `e9604f687f6eb5fc336e369036ad010e2fa28a2a5f7d906bc6d52d2c70e3d282` |

共同使用人应在自己的SSH终端中，从已审核提交检出文件，先在本机核对上述摘要，再用
`sudo install`逐一安装，并执行`sudo visudo -cf /etc/sudoers`。密码只能由共同使用人在
自己的终端交互输入，不能写入命令、文件、聊天或日志。安装后再次核对root所有权、权限
和摘要。

## 精确sudo范围

sudoers只允许：

```text
sudo -n /usr/local/libexec/smartscan/smartscan-uat-ocr-model install
sudo -n /usr/local/libexec/smartscan/smartscan-uat-ocr-model verify
sudo -n /usr/local/libexec/smartscan/smartscan-uat-ocr-model status
```

执行器拒绝额外参数、自定义路径、错误主机、错误`SUDO_USER`、自身或辅助工具摘要/权限
变化。它不提供shell、curl、wget、Docker、网络、数据库、Secret、Nginx、删除、替换、
`prune`或通用systemctl权限。

`install`只接受固定暂存目录中的`PP-OCRv6-small-v1`，并要求最终模型目录为空。它拒绝
符号链接、异常文件、缺失/多余/重复文件、摘要/大小/许可证/schema偏差和超过4 GiB。
成功后所有文件为root只读。中途失败不会把部分状态记为成功，也不会自动清理；必须先
报告，再由用户决定独立清理授权。`verify`重新计算完整清单；`status`只返回脱敏状态。

## OCR-002D 固定Layer暂存执行器

GHCR Blob/CDN链路不稳定后，新增一组独立安装资产。它只把已上传的原始固定Layer安全解包到
既有安装器要求的暂存树，不修改已经人工安装的模型安装器：

| 仓库文件 | 安装位置 | 所有者/权限 | LF规范化SHA-256 |
|---|---|---|---|
| `deploy/ops/smartscan-uat-ocr-stage` | `/usr/local/libexec/smartscan/smartscan-uat-ocr-stage` | `root:root 0755` | `14aef2c9fd31b5e7e31fafb076ec9388faa30fd8d397b1718fb4fa3354505ede` |
| `deploy/ops/smartscan_uat_ocr_stage.py` | `/usr/local/libexec/smartscan/smartscan_uat_ocr_stage.py` | `root:root 0644` | `34ff9a749737c38ec64b1dedd274a58e8d04612327fc3a80acc783ce84f146a1` |
| `deploy/ops/smartscan_ocr_layer_contract.py` | `/usr/local/libexec/smartscan/smartscan_ocr_layer_contract.py` | `root:root 0644` | `90b52b43f6bd5f0792d193e1405b28c9f4737813fe78a56eb011dfc4bc8b0997` |
| `deploy/ops/smartscan-uat-ocr-stage.sudoers` | `/etc/sudoers.d/smartscan-uat-ocr-stage` | `root:root 0440` | `f813940d1957ad6c115da68db018aabbda43f9cb929323d9b46c44a4fd08d0df` |

共同使用人只能在PR合并并审核固定提交后，在自己的SSH终端用交互式`sudo install`安装，随后
执行`sudo visudo -cf /etc/sudoers`并逐个核对所有权、权限和SHA-256。AI不得请求、读取、保存
或传递sudo密码。sudoers只允许以下三条无额外参数命令：

```text
sudo -n /usr/local/libexec/smartscan/smartscan-uat-ocr-stage stage
sudo -n /usr/local/libexec/smartscan/smartscan-uat-ocr-stage verify
sudo -n /usr/local/libexec/smartscan/smartscan-uat-ocr-stage status
```

上传文件固定为
`/home/szhzx/smartscan-ocr-offline-transfer/smartscan-ocr-layer-fdae8d61585e.tar.gz`，必须是
`szhzx`拥有的0600普通单链接文件，大小26,534,130字节且SHA-256为
`fdae8d61585eef7d6a5c810e10847cd10039f3a8b69645d480c6d4127c1aebfb`。暂存执行器拒绝绝对路径、
`..`、链接、设备、FIFO、重复/额外成员、大小异常和超过4 GiB；固定暂存树已有任何完整或部分
状态时也拒绝覆盖。中途失败保留`.partial`证据，执行器没有清理或替换命令。

完整顺序为：本机固定下载与离线`verify` → 单独授权创建固定用户上传目录和SCP → 重新核对
0600/所有者/大小/摘要 → 单独授权暂存`stage`和`verify` → 单独授权既有模型`install`和
`verify`。每一步授权互不延续，最终模型目录验证通过前CPU Worker继续失败关闭。
