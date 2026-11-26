# OPS-001N 修复版 Worker 与增量 UAT 发布

## 固定候选

本工作包只把候选提交给服务器共同使用人接受，不自动改变当前 UAT。

| 证据 | 固定值 |
|---|---|
| 来源提交 | `cb6599bf75da44f5f9b1a0e4e48f866b8db501b1` |
| GHCR 源引用 | `ghcr.io/j4meshub/smartscan-worker@sha256:9957b27924b0eb7ba6819c917a7b32ee2869a8b0bd560f2199f03e3232f3a742` |
| `linux/amd64` manifest | `sha256:4ff5d0ffbfc3b4b0728b673043a511035ea682bd70e149ad023470620305b1d3` |
| Config | `sha256:59616bcf09ea5d7b7538c521471ad393847a320781e1d18892bf92bf0ba8130f` |
| OCI revision | `cb6599bf75da44f5f9b1a0e4e48f866b8db501b1` |
| 本地不可变 Tag | `smartscan-uat-worker:sha256-9957b27924b0` |
| Worker 离线归档 | `smartscan-worker-9957b27924b0-linux-amd64.docker.tar` |
| Worker 归档大小 | `573480960` 字节 |
| Worker 归档 SHA-256 | `33bc7ed9ba28811f8abe12ff4edad7f4634834df8a452a8b56bd9325c0d8b2e7` |
| 候选发布清单 | `deploy/releases/uat-2026-11-26-worker-fix.json` |
| 候选清单 LF 原始字节 SHA-256 | `8debb3d83867d05e6eb6d885a9153a5b5dd20a244411e3ec2fbe6f77038f6003` |

Config 绑定十二个压缩 Layer 及十二个 RootFS diff ID；完整列表由中文离线发布映射保存并由归档、控制器和 Docker 29/containerd CI 逐项复算，不依赖 Tag。主线容器供应链运行 `45750089308` 已生成 SPDX SBOM 和 GitHub SLSA 来源证明（attestation `72482193`），并通过“全部 Critical，包含不可修复项”和“可修复 High/Critical”两类门禁；本工作包还会对最终离线归档重复执行同一门禁。

## 用户接受记录

2026-11-26，服务器共同使用人明确接受上表Worker固定源digest、离线归档大小和SHA-256、候选清单SHA-256以及只替换Worker的六镜像映射。该接受使OPS-001N产品制品门禁完成，但不授权下载Artifact、本机落盘、服务器上传、统一控制器升级、Docker导入、原子激活、核心服务启动或Nginx变更；所有状态改变仍须单独授权。

## 单服务增量范围

新六镜像集合固定为：

- PostgreSQL、API、AI Gateway、Web、Ops：与 `smartscan-uat-2026-11-24` 完全相同；
- Worker：替换为上表候选。

清单的 `base_release_manifest_sha256`、`changed_services=["worker"]` 和五项 `unchanged_archives` 构成机器校验边界。工具拒绝非 Worker 变化、旧归档大小或摘要漂移、复用旧 Worker Tag、可变 Tag、非 `linux/amd64` 平台或非 SmartScan GHCR 仓库。

按需 Actions 只上传新 Worker 归档和新发布映射。CI 为证明升级路径会额外重建已接受的旧 Worker 归档，但该旧制品不会作为新 Artifact 重复交付。新 Worker 归档的精确大小和 SHA-256 已由成功工作流固定在上表；用户接受前不得在本机下载或上传服务器。

## 控制器状态机

现场必须同时满足：

- `migrations_completed` 已完成；
- `core_started` 尚未完成；
- 活动发布仍是已接受旧发布；
- 候选目录只含固定清单、映射和新 Worker 归档；
- data 目录仍为 `10001:10001 0750`。

`accept-release` 在该断点只把候选记录为 `pending_release_update=accepted`，不会替换活动发布。下一次 `resume-basic-uat` 固定执行：

1. 校验候选清单与旧活动清单的基线摘要；
2. 证明其余五项镜像和映射完全不变；
3. 只导入或复用新 Worker 的新不可变 Tag；
4. 复算源 digest、平台 manifest、Config、全部 Layer、归档 SHA 和 Docker 29/containerd 运行时 Descriptor；
5. 以无网络、只读根、无挂载、零 capability 的探测确认 `10001:10001`；
6. 只验证现有 data 所有权，不再次 `chown`；
7. 保存旧清单、映射、本地 Tag 环境和身份文件；
8. 原子切换活动文件并重新验证；
9. 启动 API、两个 CPU Worker 和内部 Web，AI Profile 保持关闭。

核心已启动时控制器拒绝接受增量发布。任何导入、身份、归档或切换失败都不会记录 `core_started`，不会重置存储、模型、网络、数据库或迁移，也不会删除旧 Worker、新 Worker、归档或缓存。

## 真实运行门禁

Docker 29/containerd 和传统独立 daemon 都使用 exact mixed release：旧 PostgreSQL、API、AI Gateway、Web、Ops，加新 Worker。验证包括：

- 完全离线导入与 `pull_policy: never`，不存在 Registry 访问；
- 数据库已在 `20261022_0024` 时重复迁移只做验证；
- API在基础UAT固定为单进程，避免当前固定API镜像首次创建唯一超级管理员时发生多进程竞态；该限制由后续业务初始化重构和OPS-005容量验收解除；
- Worker 只读根、`cap_drop: ALL`、`no-new-privileges`、1.25 CPU、2 GiB、256 PID；
- 512 MiB `/tmp` 是 PaddleX 唯一缓存位置，OCR 模型只读挂载；
- `libGL.so.1`、`libgthread-2.0.so.0`、`libgomp.so.1` 和 `cv2` 动态加载；
- PaddleOCR/PaddleX 使用固定模型初始化，不联网下载；
- 两个 CPU Worker 同时心跳；
- 通过内部 HTTP 上传固定真实图片，任务最终产生非空 OCR 文本；
- 18082 核心健康，AI Profile 关闭，共享 Nginx 不参与。两种CI daemon均在独立网络边界中禁用iptables，因此同时核对`127.0.0.1:18082`固定端口绑定，并通过同一nginx容器的固定edge地址完成HTTP与真实OCR闭环；生产控制器仍直接验证回环18082。

最终技术验证头为`903a7d9e20651a17becac4f632a24982b9b0306f`，GitHub Actions运行`45759198125`、作业`139704933686`。Docker 29/containerd与传统隔离daemon都返回`migration-and-core-complete`，六归档总大小为`991539200`字节；两条路径均确认数据库保持`20261022_0024`、核心服务数为5、`registry_access=false`、`shared_nginx_touched=false`，严格全Critical和可修复High/Critical门禁通过。

## 用户接受后的自动流程

用户明确接受新 Worker 源 digest、归档大小/SHA-256和候选清单 SHA-256 后，AI 才能按独立授权执行：

```text
按需Actions Artifact → smartscan_offline_images.py download/verify
→ 固定SSH别名断点上传到候选release_id子目录
→ 服务器普通用户摘要复核
→ smartscan-uatctl accept-release
→ smartscan-uatctl resume-basic-uat
```

这一路径不要求用户手工下载或 SCP。控制器和候选清单若有变化，仍由用户一次性人工安装 root 资产；sudoers 命令集合不变。共享 Nginx 激活、删除、清理和生产上线继续保持独立人工门禁。

## 回滚

旧发布证据和旧 Worker Tag 不会被覆盖。新发布激活后如核心验证失败，先执行固定 `stop-core`，再由单独授权的 `rollback-images`验证旧内容链并恢复旧活动文件。回滚不删除任何镜像、数据或网络；由于旧 Worker 存在已知运行库缺陷，回滚只恢复可审计断点并保持核心停止，不能将旧发布标记为健康。
