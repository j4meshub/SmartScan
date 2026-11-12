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
3. 使用 Trivy 检查操作系统与语言依赖；存在有修复版本的 High 或 Critical 漏洞时失败。暂时没有修复版本的漏洞仍出现在报告中，发布前必须完成风险复核。

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

上述门禁已于 2026-11-12 完成：五个 Package 的来源、配置和构建历史已检查，匿名按固定 digest 访问成功，用户明确确认接受当前公开状态。`OPS-REG-002` 因此完成；后续新提交产生的新 digest 仍须经过相同门禁，公司服务器也只能在变更审批后人工拉取。

当前确认基线：

| 服务 | 已确认不可变引用 |
|---|---|
| API | `ghcr.io/j4meshub/smartscan-api@sha256:56b607f8d283215e8084db00404225ee1af9d6cdd0943e5cc935aed51f3e2713` |
| Worker | `ghcr.io/j4meshub/smartscan-worker@sha256:887688516a5b137d1a2e7ee8071977e93ce4ac46150b5ab6219401faa650703e` |
| AI Gateway | `ghcr.io/j4meshub/smartscan-ai-gateway@sha256:dc866a5aa70a30976a8798acc3e38cb8c5d98aa9e001d708315d8b82c8c33b8f` |
| Web | `ghcr.io/j4meshub/smartscan-web@sha256:af5480ebdf4b3269698e9c617c66e9f6062bda81570e255995baac8682f4ec55` |
| Ops | `ghcr.io/j4meshub/smartscan-ops@sha256:b1a9e195be17bdb72b785ec325ad08f48e66fe3d5c0c93e95fe30421e9c379fc` |

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
