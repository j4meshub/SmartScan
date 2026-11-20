# OPS-001C UAT应用部署受限执行器与配置准备

> 状态：仓库实现完成，尚未安装或执行。本文只定义后续分阶段授权的固定对象与失败关闭行为；本工作包没有连接或修改共享服务器，没有创建目录、Secret、Docker对象、数据库或Nginx配置。

## 能力边界

本工作包增加两个root资产和一个精确sudoers模板：

- `/usr/local/libexec/smartscan/smartscan-uat-deployment-preparation`：固定Bash执行器；
- `/usr/local/libexec/smartscan/smartscan-uat-config`：固定Python配置工具；
- `/etc/sudoers.d/smartscan-uat-deployment-preparation`：只允许五条完整命令。

执行器固定核验主机名、`SUDO_USER`、安装路径、root所有权、权限和配置工具SHA-256。它不接受路径、镜像、UID/GID、大小或任意命令参数，不调用Docker、Nginx、数据库、迁移、网络管理、`systemctl`、`prune`、shell或通配符删除，也不删除数据。

允许的命令只有：

```text
sudo -n /usr/local/libexec/smartscan/smartscan-uat-deployment-preparation prepare-directories
sudo -n /usr/local/libexec/smartscan/smartscan-uat-deployment-preparation generate-config
sudo -n /usr/local/libexec/smartscan/smartscan-uat-deployment-preparation verify-config
sudo -n /usr/local/libexec/smartscan/smartscan-uat-deployment-preparation apply-ownership
sudo -n /usr/local/libexec/smartscan/smartscan-uat-deployment-preparation status
```

`status`只报告固定对象是缺失、普通文件、目录还是异常对象，不读取或输出Secret。每个改变状态的命令都可以由`status`或`verify-config`独立复核。配置生成出现部分状态时拒绝覆盖；已有完整配置再次生成时只做验证，不轮换Secret。

## 固定目录和配置文件

`prepare-directories`未来只会创建以下固定目录：

| 路径 | 初始所有者/权限 | 用途 |
|---|---|---|
| `/mnt/data/smartscan/uat/postgres` | `root:root 0700` | 镜像身份核验后再改为实际PostgreSQL身份，必须为`70:70` |
| `/mnt/data/smartscan/uat/data` | `root:root 0750` | 镜像身份核验后再改为API与Worker共同的实际身份 |
| `/mnt/data/smartscan/uat/models/ocr` | `root:root 0755` | 真实固定OCR模型包，只读挂载 |
| `/etc/smartscan/uat` | `root:szhzx 0750` | UAT仓库外配置根目录 |

执行器拒绝符号链接、已有异常对象、额外UAT根目录子项和权限漂移。首次准备只创建空目录，不会把空OCR目录解释为模型门禁通过。

固定配置与证据如下：

| 文件 | 所有者/权限 | 产生方式 |
|---|---|---|
| `deployment-input.json` | `root:root 0600` | 共同使用人从仓库外现场记录生成并人工安装；只含内部入口、CIDR、确认记录和监控缺口记录，不含Secret |
| `preflight-summary.json` | `root:root 0600` | 从已通过的最终只读预检生成脱敏摘要并人工安装 |
| `loop-storage-evidence.json` | `root:root 0600` | 从已通过的loop验收生成脱敏摘要并人工安装 |
| `deploy.env` | `szhzx:szhzx 0600` | `generate-config`本机生成；供Compose读取 |
| `runtime.env` | `szhzx:szhzx 0600` | `generate-config`本机生成；供容器读取 |
| `shared-host-allocation.json` | `root:root 0600` | `generate-config`根据固定输入生成 |
| `bootstrap-admin-password` | `szhzx:szhzx 0600` | 本机随机生成的一次性管理员口令交付文件，不打印 |
| `image-identities.json` | `root:root 0600` | 六镜像实际拉取并核验后由共同使用人人工安装；`apply-ownership`只信任此固定文件 |

公开模板只包含占位值。真实内部地址、CIDR、现场快照、凭据和Secret不得进入GitHub、聊天或执行命令参数。禁止把完整`docker compose config`写入日志，因为展开内容可能包含数据库口令和运行Secret。

## 字段分类

可公开部署参数包括：环境为UAT、Compose项目`smartscan-uat`、回环监听`127.0.0.1:18082`、固定目录、50 GiB/8 vCPU/16 GiB资源边界、70/85/95阈值、六个已接受镜像引用和AI Profile默认关闭。

仓库外内部参数包括：共享入口origin、三张现场无冲突CIDR与网关、保留网段摘要、确认人/时间/变更/验证/回滚记录，以及预检和loop证据摘要。

完整字段机器清单位于[`deploy/compose/uat-config-fields.json`](../deploy/compose/uat-config-fields.json)。自动测试要求清单四类字段的并集与生成的`deploy.env`/`runtime.env`逐项相等，防止Settings、Compose或校验器新增字段后静默漏配。

目标主机本地随机生成且不回显的Secret字段为：

- `POSTGRES_PASSWORD`；
- `SMARTSCAN_DATABASE_URL`（包含同一数据库口令的派生Secret字段）；
- `SMARTSCAN_SECRET_KEY`；
- `SMARTSCAN_PHONE_HMAC_PEPPERS`中的活动pepper；
- `SMARTSCAN_PHONE_ENCRYPTION_KEYS`中的32字节URL-safe Base64密钥；
- `SMARTSCAN_SUPERADMIN_PASSWORD`；
- `SMARTSCAN_OPS_METRICS_TOKEN`。

生成器只报告字段是否存在、长度或脱敏状态，不输出值。短信、企业微信和真实AI Provider固定关闭；`SMARTSCAN_DEV_SMS_CODE`、企微凭据、AI URL/Key/Token均为空，`SMARTSCAN_AI_MOCK_MODE=false`。AI Worker与AI Gateway只在以后显式启用`ai` Profile时启动，基础UAT禁止启用。

### 宿主机余量与loop内余量

“预分配50 GiB后仍保留宿主机15%或200 GiB中的较高者”由loop存储执行器和部署前现场预检保证。应用看到的是50 GiB loop文件系统，不能把200 GiB写入`SMARTSCAN_STORAGE_MIN_FREE_BYTES`，否则上传会永久返回容量不足。因此UAT运行配置固定为：

- loop内绝对余量2 GiB；
- loop内比例余量15%；
- 业务数据配额32 GiB；
- 70%提示、85%告警与清理、95%停止新增写入。

两层门禁同时生效，前者不替代宿主机安全余量。

## 首个UAT账号

基础UAT不能走正常注册：生产模式下注册必须消费短信挑战，而短信供应商按本次边界关闭。API首次启动时会使用`SMARTSCAN_SUPERADMIN_PASSWORD`创建用户名`admin`的超级管理员，并设置`must_change_password=true`；已有超级管理员时不会重复创建。

随机初始密码只写入`bootstrap-admin-password`和`runtime.env`，不进入Git、聊天、命令行或日志。共同使用人必须在不记录屏幕和Shell输出的人工会话中，将固定文件内容直接导入批准的密码管理器或等价安全输入通道；禁止使用`cat`、`grep`或让AI读取。首次登录立即修改密码。旧引导值此后不再改变已有账号；删除交付文件或轮换运行配置属于新的明确授权，不在本执行器权限内。

## OCR模型是Worker启动门禁

CPU Worker的`main()`在进入心跳和领取任务循环前调用`get_ocr_engine()`。生产配置固定`SMARTSCAN_OCR_ENABLED=true`，模型目录缺少`manifest.json`、版本不符、目录不完整或任一文件SHA-256不符都会使Worker启动失败。

仓库当前只有适配器、清单生成工具和自动化假模型，没有可部署的真实`PP-OCRv6_small_det`/`PP-OCRv6_small_rec`权重包，也没有已接受的来源快照、许可证证据、完整文件清单和SHA-256。因此：

- `prepare-directories`可以创建空模型目录，但`verify-config`必须失败；
- 不得使用空目录、Mock模型或首次启动联网下载通过门禁；
- 在启动两个CPU Worker前，必须另行完成模型制品工作包：固定官方来源和取得时间、许可证文本/版本、内部模型版本`PP-OCRv6-small-v1`、完整文件清单/SHA-256、总大小不超过4 GiB，并以`root:root`、不可组/全局写的方式安装；
- 模型目录只读挂载到`/opt/smartscan/models/ocr`，API、PostgreSQL和Web不读取模型。

模型缺失不阻止仓库工具完成，但阻塞`verify-config`和应用Compose启动阶段。

## 镜像身份和所有权

当前源码意图是：PostgreSQL固定`70:70`；API、Worker、AI Gateway和Ops Dockerfile创建UID 10001的`smartscan`用户；Web Dockerfile没有声明`USER`。这些只能作为预期，不得替代已接受digest的现场证据，尤其不能提前猜测GID或Web运行身份。

| 镜像 | 仓库可见预期 | 实际部署门禁 |
|---|---|---|
| PostgreSQL | 已接受制品固定`70:70` | 拉取后RepoDigest、OCI用户及受控`id -u/-g`仍必须全部为70 |
| API | Dockerfile创建UID 10001并声明`USER smartscan` | 数字GID和接受digest中的实际身份必须现场核验 |
| Worker | Dockerfile创建UID 10001并声明`USER smartscan` | 必须与API数字UID/GID相同，才能共享业务目录 |
| AI Gateway | Dockerfile创建UID 10001并声明`USER smartscan` | AI默认不启动，但身份仍写入六镜像证据 |
| Web | Dockerfile未声明`USER` | 不猜测；拉取后记录OCI用户和受控运行身份，且只读挂载业务目录 |
| Ops | Dockerfile创建UID 10001并声明`USER smartscan` | 只使用有界tmpfs，不创建专用宿主机可写目录 |

未来顺序固定为：

1. 创建空目录；
2. 单独授权创建三张网络和拉取六个固定digest；
3. 核对每个RepoDigest、`linux/amd64`、OCI `Config.User`和受控运行时`id -u`/`id -g`；
4. 将脱敏结果写入固定`image-identities.json`并由root以0600安装；
5. 单独授权`apply-ownership`。

`apply-ownership`要求六个引用逐字匹配已接受digest、平台为`linux/amd64`、全部RepoDigest已核验、PostgreSQL为`70:70`、API与Worker的数字UID/GID相同。它只改变三个固定目录：PostgreSQL目录使用70:70和0700，业务数据目录使用现场核验的API/Worker共同身份和0750，模型目录保持root:root 0755。PostgreSQL目录非空时拒绝执行。Web只读挂载业务目录，Ops仅使用tmpfs，不为它们猜测或创建可写宿主机目录。

## 一次性人工安装

共同使用人必须在自己的SSH终端中审核仓库提交、核对以下摘要并人工输入sudo密码。AI不得请求、读取、保存或转发密码。

| 仓库文件 | 安装路径 | SHA-256 |
|---|---|---|
| `deploy/ops/smartscan-uat-deployment-preparation` | `/usr/local/libexec/smartscan/smartscan-uat-deployment-preparation` | `b6ad682e35fecad0d5c5958f6cb43a2b38dd9f13be5c5c36880003ac8079c0a8` |
| `deploy/ops/smartscan_uat_config.py` | `/usr/local/libexec/smartscan/smartscan-uat-config` | `0fcfd58fa5d7f76fa953e69885b26de567f039e13c856ae101397e930610e729` |
| `deploy/sudoers/smartscan-uat-deployment-preparation` | `/etc/sudoers.d/smartscan-uat-deployment-preparation` | `3f2ef203358b12990d00bd4f0d53e769635536b0f8ca7f23db52d174a2f28aa6` |

人工安装的等价命令如下；`<审核后的临时文件>`必须是共同使用人亲自上传或在受信任终端准备的固定仓库资产，不得由AI替换内容：

```bash
sudo install -d -o root -g root -m 0755 /usr/local/libexec/smartscan
sudo install -o root -g root -m 0755 <执行器临时文件> /usr/local/libexec/smartscan/smartscan-uat-deployment-preparation
sudo install -o root -g root -m 0755 <配置工具临时文件> /usr/local/libexec/smartscan/smartscan-uat-config
sudo install -o root -g root -m 0440 <sudoers临时文件> /etc/sudoers.d/smartscan-uat-deployment-preparation
sudo visudo -cf /etc/sudoers
sha256sum /usr/local/libexec/smartscan/smartscan-uat-deployment-preparation \
  /usr/local/libexec/smartscan/smartscan-uat-config \
  /etc/sudoers.d/smartscan-uat-deployment-preparation
sudo -n /usr/local/libexec/smartscan/smartscan-uat-deployment-preparation status
```

安装资产不包含Secret。`deployment-input.json`、两份脱敏证据和以后产生的`image-identities.json`必须分别审核后以`root:root 0600`安装；它们不属于sudoers授权，也不得通过命令参数传值。

安装完成后，第一项可以单独授权的服务器写操作是且仅是`prepare-directories`。它不生成Secret、不调用Docker、不安装Nginx，也不改变现有loop挂载。目录复核通过后，再分别授权仓库外输入/证据安装和`generate-config`，不得一次授权扩展到网络或应用部署。

## 分阶段回滚

- 目录准备失败：保留现场证据，禁止创建Docker对象；已有精确空目录不自动删除，删除需新授权。
- 配置生成失败：部分状态拒绝覆盖；不打印Secret、不创建Docker对象，由共同使用人审核固定文件后决定修复或删除，删除需新授权。
- 镜像身份或所有权失败：不启动容器；PostgreSQL目录非空时拒绝改变所有权。
- 网络创建失败：以后只允许删除无端点的三个SmartScan精确网络，禁止`prune`。
- 镜像拉取失败：不执行`prune`，不删除无关镜像。
- PostgreSQL启动失败：只停止SmartScan PostgreSQL并保留数据。
- 迁移失败：不自动降级或删除数据库。
- 应用启动失败：不安装共享Nginx include。
- Nginx失败：恢复新增include的上一版本，`nginx -t`通过后才reload。
- 数据、目录、Secret、镜像和网络清理均需独立授权。

## 后续独立授权点

仓库工具完成不等于部署授权。后续仍需依次明确授权：

1. 人工安装三个root资产；
2. `prepare-directories`；
3. 安装仓库外输入和两份脱敏证据；
4. `generate-config`与`verify-config`；
5. 固定OCR模型包选型、安装和验证；
6. 创建三张固定网络；
7. 拉取六个固定digest并产生镜像身份记录；
8. `apply-ownership`；
9. 启动PostgreSQL、执行迁移、启动API/两个CPU Worker/Web；
10. 单独评审共享Nginx include、`nginx -t`和reload。

AI Profile、数据删除、清理、Nginx写入和reload均不在本执行器中。
