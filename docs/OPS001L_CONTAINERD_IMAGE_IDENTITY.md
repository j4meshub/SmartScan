# OPS-001L Docker 29 containerd离线镜像身份兼容

## 现场断点与诊断结论

统一控制器已经完成`preflight`、存储、模型、配置和发布接受。首次`resume-basic-uat`只导入PostgreSQL归档，随后以`imported_image_id_mismatch:postgres`失败关闭；后五镜像、身份探测、所有权、数据库、迁移、应用和Nginx均未执行。

只读诊断确认目标Docker Engine为29.0.2/API 1.52，镜像存储由containerd snapshotter提供。固定PostgreSQL对象的以下证据全部一致：

- 已接受源digest与`linux/amd64`平台manifest；
- 离线归档大小和SHA-256；
- Config文件名、字节摘要、平台、用户和revision；
- 十个压缩Layer的digest、大小及RootFS diff IDs；
- 唯一本地不可变Tag及其实际平台和文件系统层。

传统Docker image store把Config digest作为Image ID。Docker 29 containerd image store在`docker load`时为同一Config和Layer生成Docker schema2 manifest，并把该manifest digest作为本地Image ID/Descriptor digest。固定PostgreSQL归档重算后的schema2文档为1883字节，摘要与现场实际Descriptor逐字一致。因此根因归类为B：内容完全一致，运行时身份字段不同。

Docker官方说明Docker Engine 29的新安装默认使用containerd image store，并可通过`DriverStatus`中的`io.containerd.snapshotter.v1`确认：[containerd image store](https://docs.docker.com/engine/storage/containerd/)。

## 联合身份契约

控制器不再把单一`.Id`当成唯一证据，也没有删除Image ID门禁。每个镜像必须同时满足：

1. 发布清单只包含已接受的`ghcr.io/j4meshub/smartscan-*`固定digest和`linux/amd64`；
2. 归档SHA-256、Config digest/大小、全部压缩Layer digest/大小与内嵌Registry证据一致；
3. RootFS diff IDs与固定Config逐项一致；
4. 实际镜像为`linux/amd64`，`Config.User`、revision和version与发布映射一致；
5. 该镜像只具有预期的SmartScan本地不可变Tag；
6. 传统image store的Image ID等于Config digest；
7. containerd image store的Image ID、Descriptor digest和控制器重算的Docker schema2 digest三者相等，Descriptor媒体类型和大小也一致。

本地RepoDigest可能由Docker根据本地Tag和运行时Descriptor生成，仅作为运行时证据保存，不能代替用户接受的GHCR源digest。`image-identities.json`使用1.1契约同时保存源内容身份、归档身份、实际运行时身份和UID/GID；应用所有权前重新验证。

## 状态机续接

升级不修改或迁移`uatctl-state.json`。现场PostgreSQL本地Tag已经存在时，`import-images`先执行完整联合身份验证：

- 全部通过：不重复`docker load`，继续导入后五个固定归档；
- 任一差异：以明确原因失败关闭，不改Tag、不清理、不重试。

六镜像全部完成后，状态机仍按`images_verified`、`identities_verified`、`ownership_applied`、`database_started`和`database_verified`推进，并在`run-migrations`前返回`waiting_confirmation`。

## CI门禁

离线工作流执行两条Linux路径：

- 传统独立daemon：继续验证Config digest形式的Image ID；
- 固定Docker 29.0.2：启用containerd image store和`overlayfs` snapshotter，使用与containerd相同主机命名空间的真实daemon执行相同完整状态机。该daemon的HTTP/HTTPS代理固定指向不可用的本机端口，所有容器探测仍使用`--network none`；任何Registry请求都会失败关闭。

两条路径都必须完成六个归档连续导入、Tag/身份验证、无网络UID/GID探测、`image-identities.json`、所有权、PostgreSQL健康和迁移前等待确认。传统daemon使用独立containerd namespace，防止两条CI路径共享镜像元数据而误跳过导入。Docker 29由官方`docker/setup-docker-action`固定到不可变提交和版本，启用方式遵循其官方`daemon-config`说明：[setup-docker-action](https://github.com/docker/setup-docker-action)。

首次Docker 29 CI的镜像导入和身份验证均成功，但因dockerd与docker调用位于不同网络命名空间，containerd在启动第一个UID/GID探测容器时失败。这是CI运行时编排问题，不是镜像内容或服务器故障；修复不改变生产控制器的安全探测参数。

## 服务器升级边界

OPS-001L只改变统一控制器包装器和Python实现时，不替换sudoers、Compose、Nginx模板、内聚验证模块或旧执行器。合并后必须从合并提交的Git对象导出LF字节，上传到固定普通用户暂存目录，核对SHA-256后由共同使用人人工安装。

人工升级前需备份现有包装器和控制器；安装后只运行`status`，结果必须仍包含五个已完成前置状态且`next_required=images_imported`。升级授权不包含`resume-basic-uat`、镜像导入、容器、迁移或Nginx。
