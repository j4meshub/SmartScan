# PostgreSQL 固定 digest GHCR 供应链

## 目的与边界

`OPS-REG-003` 解决目标服务器无法连接 `auth.docker.io:443` 的外部条件：GitHub Actions 从 Docker Official Image 的固定 PostgreSQL 17 制品复制完整多平台索引到 `ghcr.io/j4meshub/smartscan-postgres`。这是固定上游制品复制，不是源码重建，也不表示 SmartScan 构建了 PostgreSQL 或 Docker 官方在 GHCR 发布了该镜像。

固定上游为：

```text
docker.io/library/postgres@sha256:0d938e975177bef9f1f61f3f9dbcf2e0aa0a139568f66d3415ed8892eb97f6ac
```

工作流不使用 Dockerfile，不修改镜像层，不发布 `latest` 或 `main`，不自动修改 UAT 配置，也不连接目标服务器。PR 只核验；只有合并到 `main` 后才使用仓库内置 `GITHUB_TOKEN` 写入 GHCR。

## 上游核验

`.github/workflows/postgres-supply-chain.yml` 和 `tools/postgres_supply_chain.py` 失败关闭地核验：

1. Registry 路径必须是 Docker Hub 官方命名空间 `library/postgres`，固定 digest 响应必须完全一致。
2. Docker Official Images 的公开 `library/postgres` 元数据必须把精确标签 `17` 绑定到 `docker-library/postgres` 源码仓库和完整 `GitCommit`。
3. 固定制品必须是 OCI 或 Docker 多平台索引，并保存全部 descriptor；必须且只能存在一个 `linux/amd64` 运行镜像。
4. `linux/amd64` 配置必须同时包含 `PG_MAJOR=17` 和 `PG_VERSION=17.x`。
5. 同时记录查询时可变 `17` 标签的 digest 及其是否仍等于固定候选。标签移动不会改变已选固定 digest，但必须公开记录，不能伪造为相等。

2026-11-20 的本机只读实测中，固定候选仍可访问，媒体类型为 OCI image index，包含 16 个 descriptor；运行平台覆盖 `linux/amd64`、`linux/arm/v5`、`linux/arm/v7`、`linux/arm64/v8`、`linux/386`、`linux/ppc64le`、`linux/riscv64`、`linux/s390x`，另有 8 个 `unknown/unknown` 的上游证明 descriptor。`linux/amd64` 配置给出的版本为 `17.12-1.pgdg13+1`。当前可变 `17` 标签已移动到 `sha256:b60e90042aa6b8dbecd58e224b3e36114dbf8ad754465264c2476ad58a86e45c`，与固定候选不同；这正是部署必须使用 digest、不能使用标签的原因。

## 复制、SBOM 与来源映射

主线发布使用 Docker 官方文档支持的 `docker buildx imagetools create`，以固定上游 `image@digest` 为唯一来源复制完整多平台制品，并使用只含上游 digest 的不可变追溯标签。发布后再次读取 GHCR 索引，要求其结构与上游索引完全相同。

发布 Artifact 包含：

- 上游核验 JSON和完整平台列表；
- `linux/amd64` SPDX JSON SBOM；
- PostgreSQL 两类 Trivy JSON 报告；
- Buildx 目标 digest 元数据和 GHCR 索引；
- 中文 JSON/Markdown 来源映射；
- 自定义 in-toto Statement v1，`predicateType` 为 SmartScan 的 `upstream-copy/v1`，明确 `layersModified=false`、`sourceCodeRebuilt=false`、不声称 Docker 官方 GHCR 发布。

如果上游与 GHCR 顶层 digest 相同，说明顶层 manifest 字节身份保持；如果不同，只能在两边索引结构完全一致时记录为 Registry 序列化差异，并分别按各自 digest 追溯，不能隐瞒差异。

## 漏洞门禁

PostgreSQL 固定制品必须同时通过：

- `severity=CRITICAL`、`ignore-unfixed=false`：所有 Critical（含不可修复）必须为 0；
- `severity=HIGH,CRITICAL`、`ignore-unfixed=true`：有可用修复的 High/Critical 必须为 0。

同一工作流还对主线 `2adbf4f` 的五个固定 SmartScan 候选执行第一类严格 Critical 扫描。现有五镜像构建工作流也增加同样门禁，避免后续发布重新出现未覆盖的不可修复 Critical。

六个镜像还分别生成`ignore-unfixed=false`、`severity=HIGH`、退出码为0的完整High报告。任何 Critical 均不得自动豁免。发现后必须保留候选未接受状态，记录 CVE、组件、可达性、缓解措施和替代基础镜像。不可修复 High 不会被第二类扫描拦截，但必须从完整High报告进入最终风险记录逐项说明。

## 首次公开和服务器只读核验

首次推送创建的 GHCR Package 可能为私有，工作流不会自动改变可见性。主线发布后按以下顺序继续：

1. 检查 Package 内容、SBOM、来源映射和扫描报告不含 Secret、内部地址或用户数据。
2. 由用户在 GitHub Package Settings 中人工把 `smartscan-postgres` 改为 Public；公开操作不由工作流代替。
3. 仅在公开后，通过唯一 SSH 别名 `smartscan-server` 做 DNS、TLS、匿名 HEAD/manifest、digest 和 `linux/amd64` 只读核验。
4. 不执行 `docker login`、`docker pull`，不修改服务器缓存或文件。
5. 用户明确接受 GHCR 固定 digest 后，才能把它写入仓库外 UAT 配置；接受仍不等于授权拉取或部署。

如果匿名访问失败，停止并报告，不配置服务器 Registry 令牌，不使用代理或其他镜像站绕过。

## 当前阻塞

PR #84运行`44652361383`证明指定固定候选没有通过漏洞门禁：`libxml2`存在当前无修复版本的Critical `CVE-2026-6653`，`gosu`内Go标准库存在可修复Critical `CVE-2025-68121`，可修复High/Critical门禁同样失败。因此PR不合并、main复制不执行、GHCR Package未创建。详细风险见[PostgreSQL固定digest漏洞门禁报告](POSTGRES_FIXED_DIGEST_VULNERABILITY_REPORT.md)。

在用户明确授权新的固定候选前，不得把当前可变`17`标签或任何其他digest写入工作流。新候选必须重跑本文件的全部门禁。

## 本地验证

```text
python -m pytest tests/test_postgres_supply_chain.py tests/test_container_supply_chain.py -q
python -m ruff check tools/postgres_supply_chain.py tests/test_postgres_supply_chain.py
python -m ruff format --check tools/postgres_supply_chain.py tests/test_postgres_supply_chain.py
```

完整上游网络核验和镜像扫描由 GitHub Actions 执行；本机测试不替代 Actions 制品证据。
