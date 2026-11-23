# OPS-001E UAT仓库外部署输入与证据

## 目标与边界

本工作包补齐`deployment-input.json`、`preflight-summary.json`和`loop-storage-evidence.json`的安全生成路径。三份文件只在目标服务器的固定用户暂存目录产生，不提交Git，不安装到`/etc/smartscan/uat`，也不生成Secret。

生成过程仅通过SSH别名`smartscan-server`运行。原始Docker IPAM、路由、接口地址、内部入口和真实loop设备只存在于目标进程内存或仓库外0600文件中；标准输出只报告固定暂存根、生成器SHA-256及各文件名、字节数和SHA-256。

本工作包不授权Docker网络、镜像拉取、容器、数据库、迁移、Nginx变更、`generate-config`、`verify-config`或应用启动。

## 固定输出

暂存根固定为：

```text
/home/szhzx/smartscan-uat-config-bootstrap
```

生成器只允许创建以下对象：

| 文件 | 暂存所有者/权限 | 内容边界 |
|---|---|---|
| `deployment-input.json` | `szhzx:szhzx 0600` | 内部HTTP origin、三张仓库外CIDR及派生首个可用网关、确认记录、保留网段和监控缺口记录；不含Secret |
| `preflight-summary.json` | `szhzx:szhzx 0600` | 新鲜只读快照的脱敏通过摘要和哈希；不保存原始路由、IPAM或容器明细 |
| `loop-storage-evidence.json` | `szhzx:szhzx 0600` | 50 GiB、ext4、挂载、autoclear和systemd事实；真实loop设备只留在此仓库外文件 |

暂存根必须为普通目录、非符号链接、所有者`szhzx`、权限0700且生成前为空。生成器拒绝覆盖；三份文件先写入同目录0600临时文件，再以硬链接一次性发布，失败时不留下部分结果。最终文件必须是普通文件、非符号链接且硬链接数为1。

## 输入与运行方式

仓库公开代码不保存真实CIDR。调用方通过标准输入提供唯一允许的私有对象：

```json
{
  "schema_version": "1.0",
  "networks": {
    "data": "<仓库外已确认/28>",
    "edge": "<仓库外已确认/28>",
    "egress": "<仓库外已确认/28>"
  }
}
```

工具拒绝其他字段，因此内部入口、确认文字、网关或Secret都不能由命令行注入。共享入口从当前SSH连接的服务器端私有IPv4地址取得，并与主机接口证据交叉验证；网关固定派生为每个已确认`/28`的首个可用地址。

Windows调用器固定使用`smartscan-server`，把生成器源码和上述私有JSON封装到同一个标准输入流，在服务器内存中执行，不上传脚本文件，也不把CIDR放进进程参数：

```powershell
$privateNetworkSpec | python tools/run_uat_bootstrap_over_ssh.py prepare
```

`$privateNetworkSpec`必须只存在于当前PowerShell内存变量，不写入Git工作区、命令历史、聊天或日志。生成器摘要必须与本工作包合并后的受信任提交一致。

## 现场门禁

生成前重新验证：

- 主机名、登录用户和UID为可信基线；
- loop受限执行器`verify`通过，50 GiB完整预分配、ext4、至少48 GiB可用、挂载和systemd正常；
- OCR受限执行器`verify/status`通过，版本为`PP-OCRv6-small-v1`且`installed=true`；
- 三张候选网络彼此不重叠，并与Docker IPAM、全部主机/策略/VPN可见路由无冲突；
- `127.0.0.1:18082`空闲；
- 8077共享Nginx入口存在，且没有`/smartscan/`或18082既有引用；
- 共享盘、inode、CPU、内存和15分钟负载满足既有停止阈值；
- UAT继续采用人工监控缺口记录，不新增Node Exporter、Alertmanager或19081；UAT数据可重建且不要求备份。

原始现场快照不落盘。`preflight-summary.json`只保存脱敏检查名、采集/验证时间及内存快照和1.2资源确认的SHA-256。

## 校验与人工安装

生成器在发布输出前复用`shared_host_preflight.validate_preflight`，测试同时要求生成的部署输入与`smartscan_uat_config._validate_input/_allocation`逐字段一致，并由`validate_uat_loop_storage`验证loop证据。任何schema漂移、路径、权限、符号链接、已有文件、网络重叠、端口占用、Nginx冲突、资源不足、loop或OCR异常都会失败关闭。

共同使用人审核文件摘要后，后续独立授权的root安装命令固定为：

```bash
sudo install -o root -g root -m 0600 \
  /home/szhzx/smartscan-uat-config-bootstrap/deployment-input.json \
  /etc/smartscan/uat/deployment-input.json
sudo install -o root -g root -m 0600 \
  /home/szhzx/smartscan-uat-config-bootstrap/preflight-summary.json \
  /etc/smartscan/uat/preflight-summary.json
sudo install -o root -g root -m 0600 \
  /home/szhzx/smartscan-uat-config-bootstrap/loop-storage-evidence.json \
  /etc/smartscan/uat/loop-storage-evidence.json
sudo stat -c '%F %U:%G %a %h %n' \
  /etc/smartscan/uat/deployment-input.json \
  /etc/smartscan/uat/preflight-summary.json \
  /etc/smartscan/uat/loop-storage-evidence.json
sudo sha256sum \
  /etc/smartscan/uat/deployment-input.json \
  /etc/smartscan/uat/preflight-summary.json \
  /etc/smartscan/uat/loop-storage-evidence.json
```

这些命令需要共同使用人在自己的SSH终端审核并输入sudo密码；AI不得请求、读取或传递密码。安装前必须逐项比对本轮报告的三个SHA-256。安装失败时不执行`generate-config`，不自动覆盖、删除或清理文件。

## 下一授权边界

三份文件安装并核对后，下一阶段最多单独授权：

```bash
sudo -n /usr/local/libexec/smartscan/smartscan-uat-deployment-preparation generate-config
sudo -n /usr/local/libexec/smartscan/smartscan-uat-deployment-preparation verify-config
```

`generate-config`会在服务器本地生成Secret、一次性管理员密码和运行配置；输出不得显示Secret值。`verify-config`通过仍不授权网络、镜像、所有权、数据库、迁移、容器或Nginx。任何删除、重建或Secret轮换都需要新的单独授权。
