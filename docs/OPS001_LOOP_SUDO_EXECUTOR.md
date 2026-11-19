# OPS-001 UAT loop存储受限sudo执行器

## 目的与边界

本工作包只准备UAT loop存储阶段的最小root能力，不安装服务器对象、不创建loop、不部署应用。继续使用本机原生OpenSSH、SSH别名`smartscan-server`、Windows `ssh-agent`和已有可信`known_hosts`；不安装`classfang/ssh-mcp-server`，也不让AI接触sudo密码、SSH私钥、口令或其他凭据。

计划安装的执行器为：

```text
/usr/local/libexec/smartscan/smartscan-uat-loop-storage
```

它只接受`create`、`verify`、`status`、`stop`四个无参数子命令。固定对象为：

- 后备文件：`/mnt/data/smartscan-loop/uat.ext4`；
- 挂载点：`/mnt/data/smartscan/uat`；
- systemd单元：`/etc/systemd/system/mnt-data-smartscan-uat.mount`。

执行器不接受路径、大小、设备名、挂载点、命令片段或额外参数，不包含Docker、Nginx、网络、Secret、数据库、迁移或其他服务操作。它不会删除后备文件，也不提供通用root shell、通用`systemctl`或loop设备分离权限。

## 固定摘要

安装前必须在已审核提交上复核：

| 文件 | SHA-256 |
|---|---|
| `deploy/ops/smartscan-uat-loop-storage` | `e0944c15931480858d2b35b8e3ab3fe2f40f904c62388a486f5752487bf29103` |
| `deploy/systemd/mnt-data-smartscan-uat.mount.template` | `e48feb8db96f5fe42b21249846e12a2165b639504afdf99ded882e28eeedd5a3` |

sudoers模板同时使用上述执行器摘要锁定四条命令。任何执行器字节变化都会使sudo拒绝执行，必须重新走代码评审、测试、摘要更新和人工安装流程。

## 一次性人工引导安装

以下步骤只能由服务器共同使用人在自己的终端中审核并执行。AI不得请求、读取、保存、代输或传递sudo密码。本节不是本轮部署授权。

### 1. 在本机准备暂存目录

从已审核的SmartScan仓库根目录执行：

```powershell
ssh smartscan-server "umask 077; mkdir -p /home/szhzx/smartscan-loop-bootstrap"
scp deploy/ops/smartscan-uat-loop-storage smartscan-server:/home/szhzx/smartscan-loop-bootstrap/executor
scp deploy/systemd/mnt-data-smartscan-uat.mount.template smartscan-server:/home/szhzx/smartscan-loop-bootstrap/mount-unit
scp deploy/sudoers/smartscan-uat-loop-storage smartscan-server:/home/szhzx/smartscan-loop-bootstrap/sudoers
ssh smartscan-server
```

这些命令会写入用户自己的暂存目录，必须在用户另行授权安装时才执行。

### 2. 在SSH终端先复核摘要和内容

```bash
cd /home/szhzx/smartscan-loop-bootstrap
sha256sum executor mount-unit
sed -n '1,420p' executor
sed -n '1,120p' mount-unit
sed -n '1,120p' sudoers
```

前两个摘要必须与“固定摘要”表一致。用户应人工确认脚本只包含固定对象和四个子命令。不要把终端中的密码、sudo票据或环境变量复制给AI。

### 3. 人工输入sudo密码完成一次性安装

```bash
sudo install -d -o root -g root -m 0755 /usr/local/libexec/smartscan
sudo install -o root -g root -m 0755 /home/szhzx/smartscan-loop-bootstrap/executor /usr/local/libexec/smartscan/smartscan-uat-loop-storage
sudo install -o root -g root -m 0644 /home/szhzx/smartscan-loop-bootstrap/mount-unit /etc/systemd/system/mnt-data-smartscan-uat.mount
sudo visudo -cf /home/szhzx/smartscan-loop-bootstrap/sudoers
sudo install -o root -g root -m 0440 /home/szhzx/smartscan-loop-bootstrap/sudoers /etc/sudoers.d/smartscan-uat-loop-storage
sudo visudo -cf /etc/sudoers
```

若任一`visudo`检查失败，禁止继续，不得手工放宽sudoers。

### 4. 安装后核验

```bash
sudo stat -c '%U:%G %a %n' /usr/local/libexec/smartscan/smartscan-uat-loop-storage /etc/systemd/system/mnt-data-smartscan-uat.mount /etc/sudoers.d/smartscan-uat-loop-storage
sudo sha256sum /usr/local/libexec/smartscan/smartscan-uat-loop-storage /etc/systemd/system/mnt-data-smartscan-uat.mount
sudo -n /usr/local/libexec/smartscan/smartscan-uat-loop-storage status
```

期望权限分别为`root:root 755`、`root:root 644`、`root:root 440`。`status`只报告固定对象状态，不创建文件或挂载。

暂存目录默认保留到安装和`status`验证完成。清理暂存目录是用户自己的独立操作，不属于AI受限执行器能力。

## 安装后的AI可执行命令

只有用户另行授权相应阶段后，AI才能通过原生OpenSSH运行：

```bash
sudo -n /usr/local/libexec/smartscan/smartscan-uat-loop-storage status
sudo -n /usr/local/libexec/smartscan/smartscan-uat-loop-storage create
sudo -n /usr/local/libexec/smartscan/smartscan-uat-loop-storage verify
sudo -n /usr/local/libexec/smartscan/smartscan-uat-loop-storage stop
```

sudoers不会允许第五个子命令、额外参数、不同路径、不同摘要、`sudo bash`、`sudo sh`或通用`systemctl`。脚本还会核对主机名、`SUDO_USER`、`SUDO_COMMAND`、自身安装路径和root所有权。

## 子命令行为

### `create`

- 重新确认`/mnt/data`是独立挂载并满足“预分配50 GiB后仍保留15%或200 GiB中的较高者”。
- 拒绝符号链接、错误类型、错误权限、错误模板摘要和不完整既有对象。
- 全新状态下使用`fallocate`完整预分配50 GiB，格式化为reserved block为0、label为`smartscan-uat`的ext4。
- 通过固定systemd单元启用并挂载，随后执行完整验证。
- 已完整挂载时幂等返回`already_ready`；由`stop`保留的有效文件系统可安全重新挂载，不重新格式化。

### `verify`

验证后备文件精确大小、非稀疏、root/0600、ext4、label、reserved block、至少48 GiB可用空间、`nodev,nosuid,noatime`、唯一loop来源、autoclear及单元启用/激活状态。输出不包含真实loop设备名或其他项目信息。

### `status`

只报告后备文件、挂载、单元摘要、启用和激活状态，不读取业务数据，不改变服务器。

### `stop`

只停止并禁用固定mount单元，确认挂载消失和autoclear释放；默认保留后备文件、文件系统和数据。它不删除单元、后备文件或目录，也不强制`losetup -d`。

## 失败与回滚

- 参数、身份、主机、摘要、路径类型、空间、文件系统或挂载事实不符时立即失败关闭。
- 新建过程中断后可能保留部分SmartScan专用对象；后续`create`不会覆盖或重新格式化异常对象，必须人工只读调查。
- `stop`失败时不会强制分离loop或删除数据；保留现场供调查。
- 删除后备文件、mount单元、sudoers或执行器属于独立人工回滚授权，不包含在四个子命令中。
- 安装层回滚由用户人工删除精确sudoers文件、执行器和未启用的mount单元，并运行`visudo -cf /etc/sudoers`；不得使用通配符或影响其他服务。

## 未解除的部署阻塞

该执行器只解决loop存储阶段的最小root操作，不授权Docker网络、镜像拉取、PostgreSQL、迁移、Compose、Secret或Nginx。服务器访问`auth.docker.io`超时导致PostgreSQL Registry manifest尚未核验，完整应用部署继续独立阻塞。
