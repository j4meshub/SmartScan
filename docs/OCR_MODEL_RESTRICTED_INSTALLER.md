# OCR-002 受限模型安装器人工安装说明

> 本说明只准备固定模型安装能力，不授权拉取、提取或安装模型。AI不得请求、读取、保存或
> 传递sudo密码。

## 固定文件与摘要

| 仓库文件 | 安装位置 | 所有者/权限 | SHA-256 |
|---|---|---|---|
| `deploy/ops/smartscan-uat-ocr-model` | `/usr/local/libexec/smartscan/smartscan-uat-ocr-model` | `root:root 0755` | `8d425b4679b394e1c4e6b0e7a86a811292293a98f48ffce902150dddcee86865` |
| `deploy/ops/smartscan_uat_ocr_model.py` | `/usr/local/libexec/smartscan/smartscan_uat_ocr_model.py` | `root:root 0644` | `f4c4cc8bb6023901845a880ec2eaa82ade3da5eba25bb20caea2a790ae63761b` |
| `deploy/ops/smartscan-uat-ocr-model.sudoers` | `/etc/sudoers.d/smartscan-uat-ocr-model` | `root:root 0440` | `d3bd45297e2b65f75139738ffbfe9a8988cd2c74dc56c374baa7cda127ddce2b` |

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
