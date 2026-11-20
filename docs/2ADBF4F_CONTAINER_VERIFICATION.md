# 2adbf4f 容器制品核验记录

## 结论

2026-11-19对主线提交`2adbf4f3a000a0fc57aa76b1bff0faa5b99b2697`产生的五个公开GHCR镜像执行了只读Registry manifest、OCI配置标签、GitHub Actions日志、SPDX SBOM和SLSA来源证明核验。目标服务器仅通过唯一SSH别名执行DNS、TLS、匿名token及manifest查询；没有执行`docker pull`、`docker login`、sudo或服务器写入。

五个镜像的Registry digest、`linux/amd64`、完整源提交、SPDX 2.3 SBOM、SLSA provenance及可修复High/Critical漏洞门禁均通过。Web支持`/smartscan/`和`/smartscan/api`，Ops来源提交包含最新loop、只读根文件系统、有界tmpfs、整栈资源和部署校验契约。因此本组可以提交服务器共同使用人接受，但在用户明确接受前仍不得写入真实UAT配置或拉取部署。

## 精确digest

| 服务 | 固定镜像 |
|---|---|
| API | `ghcr.io/j4meshub/smartscan-api@sha256:80aea0a272791ea44d76895dbd825d091620e0f43ad76c32f32fb6ba97c646d0` |
| Worker | `ghcr.io/j4meshub/smartscan-worker@sha256:f1cb15e434e99fdced69885667e8646346c75bc293e8ecf9f6b0fa24951768a6` |
| AI Gateway | `ghcr.io/j4meshub/smartscan-ai-gateway@sha256:1813ada8bda225530d71e5afa9e1c3fd640d5e23d05000d370fdccad0e5e8b00` |
| Web | `ghcr.io/j4meshub/smartscan-web@sha256:3d701a4bcaf24c03ead231f10abd316ba83ab89a6984894dfe31af404d3c930c` |
| Ops | `ghcr.io/j4meshub/smartscan-ops@sha256:be6c50fbdbc9404a9d9589a53799dbc6084470a63f2306ec6bee5736adf94cae` |

## 核验证据

- GitHub Actions容器供应链运行`44488695512`成功；五个验证、五个发布及中文镜像清单作业全部成功。常规主线CI运行`44488695528`的API、Web、Android、iOS和容器作业全部成功。
- 中文发布清单和五个OCI配置标签均绑定完整源提交`2adbf4f3a000a0fc57aa76b1bff0faa5b99b2697`，来源仓库为GitHub SmartScan，清单声明不包含Secret。
- 目标服务器对五个OCI index的匿名`HEAD`和manifest查询返回HTTP 200；Registry digest逐一匹配，五个index均包含`linux/amd64`。未记录真实loop设备、内部地址或原始响应。
- 五份SBOM均为SPDX 2.3；五个固定digest均有`application/vnd.in-toto+json`的SLSA provenance，证明主体digest逐一匹配，`resolvedDependencies`绑定完整源提交。
- 原工作流以Trivy扫描`os,library`，设置`ignore-unfixed: true`、`severity: HIGH,CRITICAL`及失败退出码；五项日志均显示被扫描目标为Clean。因此“可修复High/Critical为0”门禁通过。`OPS-REG-003`已增加五个固定digest的`ignore-unfixed=false`、`severity=CRITICAL`严格补扫；在对应Actions结果通过前，本记录仍不宣称不可修复Critical为0。
- H5部署路径单元测试和Chromium E2E覆盖`/smartscan/`及`/smartscan/api`；主线Web作业成功。
- Ops镜像从同一提交复制`tools/`，包含loop计划/证据、UAT Compose、只读根文件系统、有界tmpfs、50 GiB/48 GiB预算及8 vCPU/16 GiB整栈限制的校验逻辑；主线API与容器作业已执行相应测试和Compose解析。

## PostgreSQL阻塞

目标服务器对`auth.docker.io`的DNS解析同时获得IPv4和IPv6结果，但IPv4连接443端口超时，IPv6立即无法连接；TLS握手、匿名Registry token和`library/postgres` manifest查询均未发生。因此候选`postgres@sha256:0d938e975177bef9f1f61f3f9dbcf2e0aa0a139568f66d3415ed8892eb97f6ac`尚未完成服务器侧核验，不能进入实际部署。

`OPS-REG-003`已进入仓库实现：GitHub Actions从Docker Official Image的固定digest复制完整多平台manifest到GHCR，不重建或改写上游层；同时保存上游仓库、固定digest、当前`17` tag关系、平台清单、SBOM、两类漏洞结果和自定义in-toto来源映射。2026-11-20只读核验确认可变`17`标签已移动，固定候选仍由`PG_MAJOR=17`和`PG_VERSION=17.12-1.pgdg13+1`证明为PostgreSQL 17。发布后仍须人工确认公开可见性、目标服务器匿名manifest核验和用户明确接受，不能把镜像复制误记为Docker官方签名或SmartScan自行构建的来源证明。

## 当前边界

- 本记录只证明候选制品可供人工接受，不构成接受、拉取或部署授权。
- `main`、`latest`及以后自动产生的新digest不得替代本组候选。
- PostgreSQL GHCR供应链、真实部署配置、Secret、Docker网络、迁移、容器和Nginx仍需独立工作包和单独授权。
