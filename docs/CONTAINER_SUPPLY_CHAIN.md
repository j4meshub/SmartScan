# GitHub Actions 与公开 GHCR 镜像供应链

## 范围

`OPS-REG-002` 使用 GitHub Actions 构建 SmartScan 的 API、Worker、AI Gateway、Web 和运维工具五类 OCI 镜像。GitHub 是唯一代码与版本事实来源，GHCR 只保存构建产物；本流程不连接公司服务器，也不执行 SSH、Compose 更新或自动部署。

镜像命名固定为：

| 服务 | GHCR 镜像 |
|---|---|
| API | `ghcr.io/j4meshub/smartscan-api` |
| CPU/AI Worker | `ghcr.io/j4meshub/smartscan-worker` |
| AI Gateway | `ghcr.io/j4meshub/smartscan-ai-gateway` |
| H5/管理后台/Nginx | `ghcr.io/j4meshub/smartscan-web` |
| 迁移与配置校验工具 | `ghcr.io/j4meshub/smartscan-ops` |

## 触发和权限

- Pull Request 只执行五类镜像的本地构建、SPDX JSON SBOM 和漏洞扫描，不登录 Registry、不推送镜像。
- 只有合并到 `main` 的 `push` 事件在前置验证全部通过后，才使用 GitHub 自动生成的 `GITHUB_TOKEN` 写入 GHCR。
- 发布作业只申请 `contents: read`、`packages: write`、`id-token: write` 和 `attestations: write`；验证作业只有 `contents: read`。
- 所有第三方 Actions 固定到完整提交 SHA，不使用浮动 Tag。
- 工作流不读取个人 PAT、公司令牌、服务器 SSH 密钥或 Provider Key。

## 证据与失败关闭

验证阶段对每个镜像执行：

1. 使用仓库 Dockerfile 构建本地镜像。
2. 生成 SPDX JSON SBOM，并保存为 `container-evidence-<服务>` Artifact。
3. 使用 Trivy 以`ignore-unfixed=false`检查全部Critical，任何Critical都失败；再以`ignore-unfixed=true`检查可修复High/Critical，存在可用修复版本的High或Critical同样失败；另存全部High JSON报告，确保不可修复High能在发布前逐项风险复核。

`main` 发布阶段重新使用相同缓存构建并推送：

- `sha-<完整提交 SHA>`：用于追溯；
- `main`：只用于识别最新主线，不得部署；
- OCI 来源、提交和版本标签；
- BuildKit 最大级别来源证明与 SBOM；
- GitHub build provenance attestation。

发布完成后生成中文 JSON 与 Markdown 清单，列出每个服务的完整 `image@sha256:digest`、源提交和 SBOM Artifact。清单本身不包含令牌、内部地址或服务器参数。

## 首次公开人工门禁

GHCR 首次创建的个人 Package 默认可能是私有。首次主线发布后必须逐个执行：

1. 在 GitHub Package 设置中检查来源仓库为 SmartScan。
2. 查看镜像配置、历史、SBOM 和来源证明，确认没有 Secret、内部域名、令牌或用户数据。
3. 确认五个 Package 名称与本文件完全一致。
4. 由用户在 Package Settings 中将可见性改为 Public。公开操作不可逆，不由工作流自动执行。
5. 在未登录 GHCR 的环境执行按 digest 拉取，保存成功证据。

上述初始门禁已于2026-11-12完成。主线提交`0961cc3`随后重新生成五个镜像；用户于2026-11-17确认接受，目标服务器同日通过匿名manifest查询逐一核对digest。OPS-001后续复核确认该组Web/运维镜像不兼容当前`/smartscan/`和资源确认1.2契约，因此只保留为历史制品证据，禁止直接部署。`f38dd4f`五镜像又通过来源、`linux/amd64`、SBOM、漏洞和Web基路径核验，但Ops早于2026-11-19新增的loop证据和只读/tmpfs契约，因此同样未获部署接受。`2adbf4f`五镜像已经完成服务器匿名digest、来源、平台、SPDX、SLSA、可修复High/Critical及完整部署契约核验，当前等待用户明确接受。镜像验收不授权部署、拉取或修改可见性；后续新digest仍须重复内容和人工门禁，不能自动替换。

当前已接受但不可部署的历史基线：

| 服务 | 已确认不可变引用 |
|---|---|
| API | `ghcr.io/j4meshub/smartscan-api@sha256:b4f97968a81777c9b46bcae272be5153df796cfd4b2f9221008facc53358300a` |
| Worker | `ghcr.io/j4meshub/smartscan-worker@sha256:0dc0fe0de3e4518985bd906a08815b70419d86d5530e300a216d25a221ad07f7` |
| AI Gateway | `ghcr.io/j4meshub/smartscan-ai-gateway@sha256:8e7af7bf3d23687c19ecdd10b85044eee8321a019f831bb7744ce2575fc0518c` |
| Web | `ghcr.io/j4meshub/smartscan-web@sha256:44a0faf547140844eb065a65034d442b66dd9f971ae5521b8a97400bd50df915` |
| Ops | `ghcr.io/j4meshub/smartscan-ops@sha256:ef4dd40c7b8a494e92540dc5bb476ab144903402142a0bbb0fdc4fd688138a5b` |

## 人工部署与回滚

运维从 `smartscan-container-release-<提交 SHA>` Artifact 取得中文发布清单，将精确不可变引用写入服务器仓库外的部署环境文件，再人工执行：

```text
docker pull ghcr.io/j4meshub/smartscan-api@sha256:<digest>
docker compose --env-file <批准的环境文件> -f <批准的Compose文件> config
docker compose --env-file <批准的环境文件> -f <批准的Compose文件> up -d
```

实际命令中的环境文件、Compose 路径、网络和资源参数必须来自 OPS-000/OPS-001 审批，不得照抄占位符。生产服务器不检出源码、不运行 `docker build`，也不允许工作流自动连接。

回滚时使用上一份已验收清单中的完整 digest，先拉取并校验，再由人工执行同一 Compose 流程。不得把 `main` 或其他可变标签作为回滚依据。

## 本地验证

```text
python -m pytest tests/test_container_supply_chain.py -q
python -m ruff check tools/generate_container_manifest.py tests/test_container_supply_chain.py
python -m ruff format --check tools/generate_container_manifest.py tests/test_container_supply_chain.py
docker build -f deploy/ops/Dockerfile -t smartscan-ops:local .
```

Windows 本机没有 Docker 时，前三项必须本地通过，五类真实构建、SBOM 和扫描由 GitHub Actions 补证。

## PostgreSQL固定上游制品

目标服务器无法访问Docker Hub认证端点，因此PostgreSQL不走服务器直连上游。`OPS-REG-003`使用独立工作流把Docker Official Image固定digest完整复制到GHCR，并保存官方元数据、可变`17`标签关系、完整平台、PG 17配置、SBOM、双漏洞扫描和自定义in-toto来源映射。它不使用Dockerfile重建，也不声称SmartScan或Docker官方构建了GHCR复制品。详见[PostgreSQL固定digest GHCR供应链](POSTGRES_GHCR_SUPPLY_CHAIN.md)。
