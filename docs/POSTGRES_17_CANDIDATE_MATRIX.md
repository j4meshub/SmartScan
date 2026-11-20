# PostgreSQL 17 固定候选比较报告

报告日期：2026-11-20

工作包：`OPS-REG-003A`

证据：PR #84的GitHub Actions初始比较运行`44656028361`及运行工具失败关闭复核运行`44657713836`。原始SBOM、上游核验JSON、运行契约和Trivy JSON由GitHub保存90天，不提交公开仓库；本报告只保存必要结论。候选发现时间为`2026-11-20T09:37:32.7775099+08:00`，可变标签仅用于发现，所有检查均绑定下列固定digest。

## 结论

没有任何候选通过硬门禁，因此没有可推荐或可写入最终供应链的PostgreSQL digest。PR #84必须保持未合并，`smartscan-postgres`不得发布：

- 四个候选都因`/usr/local/bin/gosu`内Go标准库`v1.24.6`的`CVE-2025-68121`存在可修复Critical而失败；修复版本为Go `1.24.13`、`1.25.7`或`1.26.0-rc.3`。
- 四个候选都还有26项以上可修复High，违反“可修复High必须为0”。
- Debian候选另有不可修复Critical；Alpine虽然没有不可修复High，也不能覆盖可修复Critical/High硬门禁。
- 不采用忽略、改级、排除`gosu`、关闭扫描或仅因Alpine漏洞数较少而选择的方式绕过。

## 候选矩阵

| 发现标签 | 固定digest | PostgreSQL / 基础系统 | UID/GID | 全部Critical | 可修复Critical / High | 不可修复High发现数 | 结论 |
|---|---|---|---:|---:|---:|---:|---|
| `17-bookworm` | `sha256:837bed18782820fe967067cb5328b02b0d9992c1be9a37ee0c9c492cfc03af3b` | `17.12-1.pgdg12+1` / Debian 12 | `999/999` | 4 | 1 / 26 | 114（36个唯一CVE） | 拒绝 |
| `17-trixie` | `sha256:b60e90042aa6b8dbecd58e224b3e36114dbf8ad754465264c2476ad58a86e45c` | `17.12-1.pgdg13+1` / Debian 13 | `999/999` | 2 | 1 / 27 | 122（33个唯一CVE） | 拒绝 |
| 当前`17` | `sha256:b60e90042aa6b8dbecd58e224b3e36114dbf8ad754465264c2476ad58a86e45c` | 与`17-trixie`为同一制品 | `999/999` | 2 | 1 / 27 | 122（33个唯一CVE） | 拒绝 |
| `17-alpine` | `sha256:526f86d93c6ea08fd3f1fe5605650cacc781b2c6013169a0ad8f42c7d3d84f32` | `17.12` / Alpine 3.24.4 | `70/70` | 1 | 1 / 26 | 0 | 拒绝 |

表中“发现数”按Trivy目标和软件包计数，同一CVE影响多个包时会出现多条；完整JSON保留在Actions Artifact。`17-trixie`与当前`17`解析为同一digest，分别保留是为了证明标签关系，不代表存在两个不同制品。

### Critical明细

- Bookworm：`CVE-2023-45853`（`zlib1g`，无修复）、`CVE-2025-7458`（`libsqlite3-0`，无修复）、`CVE-2026-6653`（`libxml2`，无修复）、`CVE-2025-68121`（`gosu`内Go标准库，可修复）。
- Trixie和当前`17`：`CVE-2026-6653`（`libxml2`，无修复）、`CVE-2025-68121`（`gosu`内Go标准库，可修复）。
- Alpine：`CVE-2025-68121`（`gosu`内Go标准库，可修复）。

## 来源、平台与运行契约

四个候选均为OCI image index，Docker Official Images元数据指向`https://github.com/docker-library/postgres.git`的提交`ac9627dcf544a8454f212a12ddeebfcdc0803d3e`；目录分别为`17/bookworm`、`17/trixie`和`17/alpine3.24`。所有候选均包含唯一`linux/amd64`运行manifest并生成SPDX JSON SBOM。

- Bookworm运行平台：`linux/amd64`、`linux/arm/v7`、`linux/arm64/v8`、`linux/386`、`linux/ppc64le`，另含5个上游证明descriptor。
- Trixie和当前`17`运行平台：`linux/amd64`、`linux/arm/v5`、`linux/arm/v7`、`linux/arm64/v8`、`linux/386`、`linux/ppc64le`、`linux/riscv64`、`linux/s390x`，另含8个上游证明descriptor。
- Alpine运行平台：`linux/amd64`、`linux/arm/v6`、`linux/arm/v7`、`linux/arm64/v8`、`linux/386`、`linux/ppc64le`、`linux/riscv64`、`linux/s390x`，另含8个上游证明descriptor。

固定运行契约核验结果：

- 四个候选均提供`docker-entrypoint.sh`、`pg_isready`、`initdb`、`pg_dump`、`pg_restore`、`pg_basebackup`和`pg_verifybackup`，并包含`/docker-entrypoint-initdb.d`。
- 四个候选的`PGDATA`均为`/var/lib/postgresql/data`，与当前UAT Compose绑定目录一致；当前Compose没有覆盖数据库容器`user`，入口可按官方逻辑降权。
- Debian候选提供`C`、`C.utf8`、`en_US.utf8`和`POSIX` locale，UID/GID均为`999/999`，与当前Debian运行假设一致；迁移通过数据库网络执行，不依赖镜像内Python。
- Alpine提供相同入口、健康检查、初始化和备份恢复命令，且UTC时区文件存在，但UID/GID变为`70/70`、locale列表为空。它需要重新确认宿主目录所有权和中文排序/locale行为，不能视为Debian的无差异替换。
- UAT本身不要求备份，但仓库保留的备份/恢复工具依赖`pg_basebackup`、`pg_verifybackup`、`pg_dump`和`pg_restore`；工作流对这些命令逐一核验。

## 处置与后续路线

默认建议等待Docker Official Image更新`gosu`及基础系统包后，重新发现并冻结新digest，再重跑同一矩阵。这条路线保持“完整复制官方固定制品”的简单来源模型。

如果等待时间不可接受，可由用户另行授权独立工作包，评估建设可审计的最小PostgreSQL 17镜像。该方案必须从受信任的固定基础制品和固定PostgreSQL包/源码构建，生成自己的SBOM、SLSA/in-toto来源、更新责任、回归/初始化/升级/备份恢复测试和持续漏洞响应；它不再是Docker Official Image的原样复制，不能在本工作包内静默切换。

旧候选`sha256:0d938e...`和本报告四个候选的拒绝证据都继续保留。任何后续候选不得自动替换，也不得在用户接受及独立部署授权前拉取到目标服务器。
