# OPS-001 UAT loop存储受限sudo执行器

## 目的与边界

本工作包只准备UAT loop存储阶段的最小root能力，不安装服务器对象、不创建loop、不部署应用。继续使用本机原生OpenSSH、SSH别名`smartscan-server`、Windows `ssh-agent`和已有可信`known_hosts`；不安装`classfang/ssh-mcp-server`，也不让AI接触sudo密码、SSH私钥、口令或其他凭据。

计划安装的执行器为：

```text
/usr/local/libexec/smartscan/smartscan-uat-loop-storage
```

它只接受`create`、`verify`、`status`、`stop`、`recreate-empty`五个无参数子命令。固定对象为：

- 后备文件：`/mnt/data/smartscan-loop/uat.ext4`；
- 挂载点：`/mnt/data/smartscan/uat`；
- systemd单元：`/etc/systemd/system/mnt-data-smartscan-uat.mount`。

执行器不接受路径、大小、设备名、挂载点、命令片段或额外参数，不包含Docker、Nginx、网络、Secret、数据库、迁移或其他服务操作。除`recreate-empty`在证明固定UAT确为空且后备文件确为稀疏后只删除该唯一固定文件外，其他命令都不会删除后备文件；执行器不提供通用root shell、通用`systemctl`、通用文件删除或loop设备分离权限。

## 固定摘要

安装前必须在已审核提交上复核：

| 文件 | SHA-256 |
|---|---|
| `deploy/ops/smartscan-uat-loop-storage` | `cce1e8040cae9d6ca0a43ed077b878820ae72aeab2a9285c44a129857f85f6a7` |
| `deploy/systemd/mnt-data-smartscan-uat.mount.template` | `e48feb8db96f5fe42b21249846e12a2165b639504afdf99ded882e28eeedd5a3` |
| `deploy/sudoers/smartscan-uat-loop-storage` | `486f13e2aba23e0c4d48a5ba853d824d0afdfb7faf623f5eff79b33fcabde550` |

sudoers模板只列出五条精确命令及参数。目标sudo版本不依赖可选的命令digest扩展；执行器和sudoers摘要由用户在安装前人工核对，安装后文件由root拥有、普通用户不可写。任何执行器或sudoers字节变化都必须重新走代码评审、测试、摘要更新和人工安装流程。

## OPS-001B现场人工升级

已安装提交`ced1970`版本的服务器只需要升级执行器和sudoers；mount单元摘要没有变化，不重新安装。以下步骤只能由服务器共同使用人在自己的SSH终端执行，AI不得获取sudo密码：

```powershell
scp deploy/ops/smartscan-uat-loop-storage smartscan-server:/home/szhzx/smartscan-loop-bootstrap/executor.ops001b
scp deploy/sudoers/smartscan-uat-loop-storage smartscan-server:/home/szhzx/smartscan-loop-bootstrap/sudoers.ops001b
ssh smartscan-server
```

在SSH终端人工核对摘要和内容：

```bash
cd /home/szhzx/smartscan-loop-bootstrap
sha256sum executor.ops001b sudoers.ops001b
sed -n '1,520p' executor.ops001b
sed -n '1,120p' sudoers.ops001b
sudo visudo -cf /home/szhzx/smartscan-loop-bootstrap/sudoers.ops001b
```

摘要必须与上表一致。确认后人工输入sudo密码升级：

```bash
sudo install -o root -g root -m 0755 /home/szhzx/smartscan-loop-bootstrap/executor.ops001b /usr/local/libexec/smartscan/smartscan-uat-loop-storage
sudo install -o root -g root -m 0440 /home/szhzx/smartscan-loop-bootstrap/sudoers.ops001b /etc/sudoers.d/smartscan-uat-loop-storage
sudo visudo -cf /etc/sudoers
sudo stat -c '%U:%G %a %n' /usr/local/libexec/smartscan/smartscan-uat-loop-storage /etc/sudoers.d/smartscan-uat-loop-storage
sudo sha256sum /usr/local/libexec/smartscan/smartscan-uat-loop-storage /etc/sudoers.d/smartscan-uat-loop-storage
sudo -n /usr/local/libexec/smartscan/smartscan-uat-loop-storage status
```

升级只建立受限能力，不授权执行`recreate-empty`。若安装或`visudo`失败，不得运行重建；将两个固定文件恢复为升级前人工备份属于另行人工回滚操作。

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
sha256sum executor mount-unit sudoers
sed -n '1,420p' executor
sed -n '1,120p' mount-unit
sed -n '1,120p' sudoers
```

三个摘要必须与“固定摘要”表一致。用户应人工确认脚本只包含固定对象和五个子命令。不要把终端中的密码、sudo票据或环境变量复制给AI。

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
sudo sha256sum /usr/local/libexec/smartscan/smartscan-uat-loop-storage /etc/systemd/system/mnt-data-smartscan-uat.mount /etc/sudoers.d/smartscan-uat-loop-storage
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
sudo -n /usr/local/libexec/smartscan/smartscan-uat-loop-storage recreate-empty
```

sudoers不会允许第六个子命令、额外参数、不同路径、`sudo bash`、`sudo sh`或通用`systemctl`。脚本还会核对主机名、`SUDO_USER`、`SUDO_COMMAND`、自身安装路径和root所有权；安装摘要由用户另行核对。

## 子命令行为

### `create`

- 重新确认`/mnt/data`是独立挂载并满足“预分配50 GiB后仍保留15%或200 GiB中的较高者”。
- 拒绝符号链接、错误类型、错误权限、错误模板摘要和不完整既有对象。
- 全新状态下使用`fallocate`完整预分配50 GiB，使用`nodiscard,lazy_itable_init=0,lazy_journal_init=0`格式化为reserved block为0、label为`smartscan-uat`的ext4。
- 通过固定systemd单元启用并挂载，随后执行完整验证。
- 已完整挂载时幂等返回`already_ready`；由`stop`保留的有效文件系统可安全重新挂载，不重新格式化。

### `verify`

验证后备文件精确大小、非稀疏、root/0600、ext4、label、reserved block、至少48 GiB可用空间、`nodev,nosuid,noatime`、唯一loop来源、autoclear及单元启用/激活状态。输出不包含真实loop设备名或其他项目信息。

### `status`

只报告后备文件、挂载、单元摘要、启用和激活状态，不读取业务数据，不改变服务器。

### `stop`

只停止并禁用固定mount单元，确认挂载消失和autoclear释放；默认保留后备文件、文件系统和数据。它不删除单元、后备文件或目录，也不强制`losetup -d`。

### `recreate-empty`

该命令只处理OPS-001首次创建后出现lazy初始化空洞、且从未部署应用的固定空UAT：

- 后备文件必须是固定路径、普通文件、root/0600、逻辑大小精确50 GiB并已被严格判定为稀疏；非稀疏状态拒绝。
- 当前挂载必须来自该后备文件的唯一autoclear loop，ext4、label、reserved block、挂载参数、systemd和至少48 GiB可用空间全部正确。
- UAT根目录只能包含真实且为空的`lost+found`；存在任何其他文件、目录、符号链接或`lost+found`内容都在卸载和删除前拒绝。
- 当前共享盘必须仍满足完整预分配50 GiB后的15%或200 GiB安全余量。
- 条件全部满足后，停止并在重建窗口禁用固定mount，确认挂载消失及loop释放后只`unlink`固定后备文件；重新完整预分配并用禁用lazy初始化的参数格式化，重新启用固定mount并执行完整验证及第二次非稀疏确认。
- 中途任何异常立即停止；不清理部分状态、不触碰其他loop、目录、挂载或服务。

## 失败与回滚

- 参数、身份、主机、摘要、路径类型、空间、文件系统或挂载事实不符时立即失败关闭。
- 新建过程中断后可能保留部分SmartScan专用对象；后续`create`不会覆盖或重新格式化异常对象，必须人工只读调查。
- `stop`失败时不会强制分离loop或删除数据；保留现场供调查。
- 除严格受限的`recreate-empty`只删除已证明为空且稀疏的固定UAT后备文件外，删除后备文件、mount单元、sudoers或执行器属于独立人工回滚授权。
- 安装层回滚由用户人工删除精确sudoers文件、执行器和未启用的mount单元，并运行`visudo -cf /etc/sudoers`；不得使用通配符或影响其他服务。

## 未解除的部署阻塞

该执行器只解决loop存储阶段的最小root操作，不授权Docker网络、镜像拉取、PostgreSQL、迁移、Compose、Secret或Nginx。服务器访问`auth.docker.io`超时导致PostgreSQL Registry manifest尚未核验，完整应用部署继续独立阻塞。
