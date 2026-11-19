# f38dd4f 容器制品核验记录

## 结论

2026-11-19对主线提交`f38dd4f3b6dc43565e70d99e3c0ab93f38d0226c`产生的五个公开GHCR镜像执行了只读Registry manifest、GitHub Actions日志和发布制品核验，没有拉取镜像，也没有连接或修改公司服务器。

五个镜像的来源、`linux/amd64`、SBOM和漏洞门禁均通过；Web支持`/smartscan/api`，Ops支持资源确认1.2。由于该提交早于本次loop ext4证据、只读根文件系统、受限tmpfs和48 GiB数据预算契约，Ops不能验证完整的新部署边界。因此本组是“已核验、未接受、禁止部署”，不得自动写入真实UAT配置。

## 精确digest

| 服务 | 固定镜像 |
|---|---|
| API | `ghcr.io/j4meshub/smartscan-api@sha256:113336df4dbc6db16b35b4bd669a7973fe2901df25900d165ea2f30f4e412086` |
| Worker | `ghcr.io/j4meshub/smartscan-worker@sha256:d164d4582e20b99f5c3a5a4be8676cb877d98a5e1ef3537922b50eb52b95a951` |
| AI Gateway | `ghcr.io/j4meshub/smartscan-ai-gateway@sha256:f22c3487ebad0d98bc958b1665688d643938537b23b34f49b96638aa24a916ab` |
| Web | `ghcr.io/j4meshub/smartscan-web@sha256:1f37e0433840c7318ce9a8cff3e20c0065f1a31744389f578392ad706242cff3` |
| Ops | `ghcr.io/j4meshub/smartscan-ops@sha256:ac68ef8d01ee9b7a4004823d5e6a0ea55b2e552b36924864e7c10f0ad8ca2fbd` |

## 核验证据

- GitHub Actions容器供应链运行`44326436934`成功；五个验证/发布作业及中文镜像清单作业全部成功。
- 中文发布清单记录的源提交为完整`f38dd4f3b6dc43565e70d99e3c0ab93f38d0226c`，并声明不包含Secret。
- GHCR返回的五个OCI index digest与发布清单逐一一致；每个index均包含`linux/amd64`，对应配置也声明`linux/amd64`。
- OCI来源标签为`https://github.com/j4meshub/SmartScan`，revision与完整源提交一致。
- 五个镜像均生成SPDX JSON SBOM；流水线“拦截可修复的High与Critical漏洞”步骤通过。该结论只代表当次流水线门禁，不替代部署窗口重新核验。
- f38dd4f的H5基路径实现和浏览器E2E覆盖`/smartscan/api`。
- f38dd4f的Ops镜像包含资源确认1.2校验，但不包含2026-11-19新增的loop证据schema、systemd mount模板和只读/tmpfs契约，因此不能解除失败关闭。

## 后续门禁

本工作包合并后需要等待新的主线镜像供应链完成，再重复来源、平台、SBOM、漏洞、Web基路径和Ops loop契约核验。只有服务器共同使用人明确接受一整套新固定digest后，才允许把它们写入仓库外真实UAT配置；镜像接受仍不等于部署授权。
