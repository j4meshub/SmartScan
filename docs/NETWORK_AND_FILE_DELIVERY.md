# TLS、内部文件发送与 BBR 基线

## 状态与边界

OPS-002 的仓库侧交付包括主机 TLS 入口模板、证书与私钥离线校验、Nginx `internal` 文件发送容器集成测试、BBR 只读快照/对照/回滚工具和人工验收清单。它不会连接公司服务器、申请真实证书、开放防火墙、修改内核参数或执行公网压测。

CI 使用自签名测试证书、隔离容器和小型固定文件，只证明配置语法、入口约束、内部重定向、Range 和失败关闭行为可重复；不能代替真实域名、可信证书、手机网络、大文件吞吐或 BBR 前后对照。因此 OPS-002 在仓库侧合并后仍保持“等待人工验收”。

## 两层 Nginx 边界

```text
公网客户端
  │ HTTPS 443 / HTTP/2
  ▼
主机 Nginx（TLS、真实客户端限频、安全日志）
  │ 127.0.0.1:<staging 独立端口>
  ▼
staging Web Nginx（H5、后台、API 代理、internal 文件发送）
  │                                  │ 只读文件目录
  └──────── API 鉴权与审计 ──────────┘
```

- 主机 Nginx 只代理到 OPS-001 已绑定回环地址的 Web 入口；PostgreSQL 和 API 不发布主机端口。公网边界丢弃调用方伪造的 `X-Forwarded-For`，以实际远端地址重新建立代理链。
- 主机入口覆盖 HTTP 到 HTTPS 的 `308` 跳转、TLS 1.2/1.3、HTTP/2、短期 HSTS、连接上限、认证接口限频和不含查询字符串的访问日志。
- 两层代理都关闭请求缓冲，避免把分片上传完整落到代理临时文件；文件响应关闭外层代理缓冲，以便 Range 和断点下载及时返回。
- JPEG、PDF 等已压缩文件不在 gzip 类型中；JSON、JavaScript、CSS、XML、SVG 和纯文本可以压缩。
- 内层 Nginx 的 `/_smartscan_files/` 始终为 `internal`，只读挂载业务文件目录并拒绝符号链接；外部直访返回 `404`。
- API 先执行所有者鉴权、`404` 隐藏和审计，再返回百分号编码的 `X-Accel-Redirect`。该内部头由 Nginx 消费，不返回给客户端；internal location 关闭基于时间/大小的自动 ETag，并显式保留 API 基于文件 SHA-256 生成的强 ETag。

认证接口限频改用 `$uri` 映射空键：只有 `/api/v1/auth/login` 和 `/api/v1/auth/register` 进入限频区，普通 API 不计数；请求仍通过带尾斜杠的 `proxy_pass http://api/` 去掉外部 `/api/` 前缀。这样避免正则 location 把错误的 `/api/v1/...` 路径传给 FastAPI。

## TLS 材料与配置

真实证书和私钥只能位于仓库外，例如：

```text
/etc/smartscan/staging/tls/fullchain.pem
/etc/smartscan/staging/tls/privkey.pem
```

将 ACME 客户端产物复制或原子安装到上述目录；校验器在真实模式下拒绝符号链接，避免续期目录切换绕过已审核路径。私钥权限必须为 `0600` 或更严格，证书禁止组/其他用户写入。仓库不管理 ACME 账号、DNS 凭据或私钥。

先离线检查证书：

```bash
python tools/validate_tls_material.py \
  --host staging.smartscan.company \
  --certificate /etc/smartscan/staging/tls/fullchain.pem \
  --certificate-key /etc/smartscan/staging/tls/privkey.pem
```

校验内容包括精确 SAN、证书/私钥匹配、RSA 至少 2048 位或椭圆曲线至少 256 位、当前有效、至少 14 天剩余有效期、非 SHA-1/MD5 签名摘要和 POSIX 权限。真实私钥还必须由 root 持有。输出摘要不包含私钥、公钥或证书正文。

渲染新的主机 Nginx 片段时使用一个不存在的候选文件：

```bash
python tools/render_staging_edge.py \
  --host staging.smartscan.company \
  --upstream-port 18080 \
  --certificate /etc/smartscan/staging/tls/fullchain.pem \
  --certificate-key /etc/smartscan/staging/tls/privkey.pem \
  --output /tmp/smartscan-staging.conf.candidate
```

渲染器拒绝占位域名、非 staging 域名、常用/特权上游端口、TLS 目录外路径、危险字符和覆盖已有文件。人工检查候选差异后，在专用 staging 主机执行 `nginx -t`，再原子安装到 `/etc/nginx/conf.d/smartscan-staging.conf` 并使用 `nginx -s reload`。任何语法或证书检查失败都不得 reload。

短期 HSTS 起步为 300 秒且不含 `includeSubDomains`；只有真实域名和回滚链路稳定后才能单独评审延长。TLS 私钥轮换、ACME 自动续期及续期后校验必须在真实主机验收，不能由 CI 自签名证书替代。

## 内部文件发送验证

仓库内 `deploy/compose/docker-compose.nginx-test.yml` 使用隔离的假 API 返回 `X-Accel-Redirect`，再由实际 Web 镜像只读发送固定文件。CI 验证：

- 直接访问 `/_smartscan_files/...` 返回 `404`；
- 通过 `/api/v1/file` 的内部重定向返回完整文件，但不泄露 `X-Accel-Redirect`；
- `ETag`、私有缓存策略和附件下载头保留；
- `Range: bytes=10-15` 返回 `206`、正确字节与 `Content-Range`；
- Nginx 配置启用 `sendfile`、公平分块和符号链接阻断。

这条容器链路使用合成授权结果，只验证代理契约。真实 staging 仍需用普通用户、管理员和跨用户账号检查下载、导出、审计与 IDOR，并以至少一个大 PDF/JPG 验证暂停/恢复、并发公平性和内存占用。

## BBR 基线、启用与回滚

`tools/bbr_baseline.py` 只读取 Linux procfs 和写入新的证据文件，不执行 `modprobe`、`sysctl`、删除或覆盖。建议把证据保存在被 Git 忽略的 `.ops-evidence/` 或受控运维目录。

变更前记录快照，并立即生成精确回滚配置：

```bash
python tools/bbr_baseline.py capture \
  --output .ops-evidence/bbr-before.json
python tools/bbr_baseline.py render-rollback \
  --snapshot .ops-evidence/bbr-before.json \
  --output .ops-evidence/60-smartscan-bbr.rollback.conf
```

快照固定记录经过 SHA-256 单向处理的主机指纹、内核版本、可用/当前拥塞控制、默认 qdisc 和 `tcp_bbr` 模块补充状态，不写入原始 machine-id。回滚配置使用实际原值，不假设原来一定是 `cubic` 或 `fq_codel`。

人工确认主机是隔离 staging、`bbr` 已出现在可用列表、回滚文件可读且备份点完成后，才能安装仓库配置：

```bash
sudo modprobe tcp_bbr
sudo install -o root -g root -m 0644 \
  deploy/sysctl/60-smartscan-bbr.conf \
  /etc/sysctl.d/60-smartscan-bbr.conf
sudo sysctl --system
python tools/bbr_baseline.py capture \
  --output .ops-evidence/bbr-after.json
python tools/bbr_baseline.py evaluate \
  --before .ops-evidence/bbr-before.json \
  --after .ops-evidence/bbr-after.json \
  --output .ops-evidence/bbr-transition.json
```

对照器只有在主机和内核未变化、变更后快照时间更晚、`bbr` 可用且已生效、qdisc 为 `fq` 时才允许进入真实网络对照，并始终把核心网络验收保持为未完成。`lsmod` 仅是补充证据，因为 BBR 可能内建于内核。

出现异常或无收益时，人工用已生成的原值配置替换 `/etc/sysctl.d/60-smartscan-bbr.conf`，运行 `sudo sysctl --system`，再次 capture 并核对当前值等于变更前快照。禁止下载一键脚本、替换为第三方内核或盲目调大 TCP 缓冲区。

## 真实验收清单

- DNS 只指向隔离 staging，证书链受目标 Android/iOS/企业微信浏览器信任，SAN 和续期时间正确。
- 远程只开放 80/443；staging 上游端口仅在主机 `127.0.0.1` 监听，数据库/API 没有公网端口。
- HTTP 跳转 HTTPS，TLS 1.0/1.1 拒绝，TLS 1.2/1.3 和 HTTP/2 可用；安全日志不记录查询字符串、Token、手机号或文件内容。
- 外部 AI 关闭时，登录、上传、处理、预览、JPG/PDF 下载和 Range 恢复完成；跨用户下载仍统一 `404` 并有拒绝审计。
- 在同一提交、文件、并发、客户端位置、带宽上限和网络条件下分别运行 BBR 前后测试，记录下载吞吐、P95、重传和公平性。
- 局域网、4G/5G、家庭宽带和跨地区链路分别验证。上传关注分片成功率、重试字节和恢复时间，不把服务端下载改善误报为上传改善。
- 无收益、延迟/公平性恶化或异常时执行精确回滚并复测。

上述真实证据齐全前，OPS-002 和生产发布门禁保持红色。
