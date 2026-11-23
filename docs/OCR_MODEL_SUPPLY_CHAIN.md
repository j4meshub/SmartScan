# OCR-002 离线模型制品供应链

## 固定范围

SmartScan CPU Worker 固定使用 PaddleOCR `3.7.0`、PaddlePaddle `3.3.1`和
`paddle_static` CPU 后端。模型内部版本为`PP-OCRv6-small-v1`：

| 用途 | 官方模型 | 最终目录 | 文件 |
|---|---|---|---|
| 文字检测 | `PP-OCRv6_small_det` | `PP-OCRv6_small_det/` | `inference.json`、`inference.pdiparams`、`inference.yml` |
| 文字识别 | `PP-OCRv6_small_rec` | `PP-OCRv6_small_rec/` | `inference.json`、`inference.pdiparams`、`inference.yml` |

识别字典、预处理和后处理参数均在官方`inference.yml`中。现有Worker显式关闭文档方向、
去弯曲和文字行方向分类，因此本工作包不增加方向分类模型。模型文件保持官方Paddle静态
推理格式；仅把上游`*_infer`目录规范化为运行时固定目录，六个模型文件的字节不变，
没有ONNX或其他格式转换。

来源锁定位于`deploy/ocr-models/source-lock.json`。它固定PaddleOCR `v3.7.0`完整提交、
两个官方BCE下载URL、归档大小与SHA-256、官方PaddlePaddle模型仓库提交以及六个文件的
大小和SHA-256。2026-11-20复核时，两个BCE归档中的六个文件与相应官方模型仓库固定
提交逐字节一致。

## 许可证结论

PaddleOCR `v3.7.0`项目许可证和两个PaddlePaddle官方模型仓库的模型卡均标记
`Apache-2.0`。该许可证允许在保留许可证和归属说明的条件下再分发。上游固定版本没有
独立`NOTICE`文件；制品保留完整`LICENSE`、`THIRD_PARTY_NOTICES.md`和来源锁定文件。
因此现有证据支持公开GHCR再分发。该结论针对上述固定来源和摘要；任一来源、版本、文件
或许可证发生变化都必须重新审核，不能沿用结论。

## 构建与发布

`.github/workflows/ocr-model-supply-chain.yml`执行以下失败关闭流程：

1. PR和main均从固定HTTPS URL下载归档，先校验归档大小和SHA-256，再进行安全解包；
   绝对路径、目录逃逸、链接、异常类型、重复、缺失或额外文件均拒绝。
2. 生成兼容现有Worker的schema v1 `manifest.json`，并扩展记录文件大小、制品类型、
   来源提交、许可证、未转换声明和证据摘要。总安装大小必须小于4 GiB。
3. 以`scratch`构建最小OCI制品。镜像只包含模型、清单和许可证证据，不包含运行包、
   Secret、用户数据或联网下载脚本。
4. 使用三张PaddleOCR官方固定样本执行简体中文、英文和中英混排真实CPU推理，运行时
   禁止网络连接，并以两个进程并发读取同一只读模型包。
5. 生成SPDX组件清单、自定义in-toto固定上游映射、BuildKit/SLSA来源证明并扫描漏洞。
6. PR只验证而不发布；只有main前置门禁通过后才发布
   `ghcr.io/j4meshub/smartscan-ocr-models`。可变Tag只用于识别，部署必须使用用户明确接受的
   `image@sha256:<digest>`。

首次Package可能是私有，工作流不得自动改变可见性。用户须先检查制品不含敏感信息，
再决定是否公开。公开、接受digest和服务器匿名核验是三个独立人工门禁；后续构建不得
替换已接受digest。

工作流使用路径过滤：说明文档、进度记录等与模型内容和运行契约无关的提交不会重新发布
模型制品。只有模型来源/封装、安装器、Worker适配器、固定运行时、真实验收或工作流自身
变化才触发；即使触发并生成新digest，也仍为未接受候选，不能自动替换UAT配置。

## 当前候选证据

main提交`9be7b7c366f568d82a19341e072a3144ddd025a2`的工作流`44722932514`完成全部来源、
真实CPU、双Worker、SPDX、漏洞、in-toto和SLSA门禁，发布未接受候选：

`ghcr.io/j4meshub/smartscan-ocr-models@sha256:0fc7f95eb14f18996c6f22d71b4873b28e79ea0afde8a66ddea6b6c095740c13`

匿名请求返回200且Registry摘要完全一致。OCI index包含`linux/amd64`运行manifest
`sha256:7c5dccfc9b5cb3175718344b913d0993b13ad489835fbdbc4204e11f658a15f7`和独立证明
manifest；运行配置的来源仓库与提交标签均与上述main提交一致。Package已可匿名读取，
不需要修改可见性。用户已于2026-11-23明确接受该digest为UAT唯一模型候选；该接受仅
允许记录候选和服务器只读核验，不授权拉取、暂存、提取、安装或Worker启动。服务器匿名
核验确认Registry摘要一致、`linux/amd64`配置可读、来源提交一致，单个压缩层为
`26,534,130`字节，远低于4 GiB。此前`77d67e…3441`候选明确不接受，只保留为历史证据；
后续自动构建产生的新digest也不得替换当前接受值。

2026-11-23目标服务器在可信身份、Docker可读、空间充足、精确digest未缓存且无运行容器的
前提下，执行唯一授权的完整digest拉取；Docker daemon返回`failed to resolve reference ...
not found`。操作立即停止，没有重试、登录、Tag、替代digest、容器、提取、删除或`prune`。
这与此前匿名Registry manifest成功的证据并存，必须作为独立兼容性/Registry路径问题调查；
不得把manifest成功改写为实际拉取成功，也不得自动选择新制品。

### OCR-002A 媒体协商诊断

后续只读诊断确认发布对象树完整：顶层OCI index包含一个大小482字节的`linux/amd64`
运行manifest和一个`unknown/unknown`证明descriptor；运行manifest引用1877字节OCI config及
26,534,130字节OCI gzip layer。子manifest、config和layer的HEAD均为200且摘要一致。

差异发生在Accept协商：顶层仅对OCI index媒体类型返回200，平台子manifest仅对OCI
manifest媒体类型返回200；Docker manifest list/schema2媒体类型的单独HEAD/GET返回404。
目标Docker 29.0.2使用containerd image store，Registry mirror数量为0，当前用户Docker配置
文件不存在，因此没有发现mirror或客户端认证配置导致的路径差异。诊断归类为C，而不是
对象缺失的B或认证配置存在的D。

推荐把`sha256:7c5dccfc9b5cb3175718344b913d0993b13ad489835fbdbc4204e11f658a15f7`
作为待人工接受的`linux/amd64`平台运行候选，顶层`0fc7f9…40c13`继续作为供应链index和
证明关联证据。用户接受及一次精确子digest拉取必须分别授权；本次诊断不构成接受或拉取。
若子digest仍无法拉取，再发布显式Docker schema2兼容的新候选，不使用Tag临时绕过。

### OCR-002B 平台子manifest接受与拉取前停止

用户已精确接受`linux/amd64`运行manifest
`sha256:7c5dccfc9b5cb3175718344b913d0993b13ad489835fbdbc4204e11f658a15f7`；
其上级index、config、layer和来源提交继续构成不可替换的关联证据。接受不扩展到Tag、历史
候选、后续构建或其他平台。

目标服务器拉取前确认子digest未缓存、无关联容器且空间充足，但受限模型执行器的精确
NOPASSWD `status`命令返回需要密码。由于无法重新确认目标目录仍为空，流程在`docker pull`
前失败关闭；没有产生Docker写入。共同使用人恢复并人工验证该精确sudoers授权后，仍须
重新单独授权一次子digest拉取，不能沿用已经停止的授权。

共同使用人随后恢复并验证精确NOPASSWD规则，新一轮拉取前`status`已实时返回`empty`。
新的独立授权只调用一次已接受的子digest；Docker能够解析平台manifest并开始下载唯一layer，
说明顶层OCI index协商问题已被平台引用绕开。但该操作没有返回完成或明确错误，数分钟内本地
精确引用仍不存在。当前状态记为layer传输未完成，不自动重试，也不把部分缓存当成可安装制品。

### OCR-002C Layer传输诊断

目标服务器已确认原始pull客户端进程不存在，精确镜像未落盘、无关联容器，模型目标仍为空。
固定layer HEAD在2.049秒内返回200，长度26,534,130字节且摘要一致；1 MiB Range GET
正确返回206并只读取1,048,576字节，但耗时54.900秒、平均19,099.9 B/s。请求正文丢弃，
令牌、重定向签名参数和完整远端地址均未输出或落盘。

该结果证明Registry权限、对象完整性和Range语义正常，但Blob/CDN传输对UAT部署不具备可接受
速度，归类为B类。当前不再尝试Docker pull；下一步需单独设计公司网络路径改善或可审计
离线固定制品传输，仍须保持已接受digest、哈希、来源和安装门禁。

### OCR-002D 可审计离线Layer传输

共同使用人随后人工执行精确平台子digest拉取，唯一Layer在约376.8 KB处因TCP连接被对端重置
而失败。服务器Docker pull路线至此停止；可能存在的部分缓存不删除、不`prune`，也不作为可安装
制品。离线路线仍绑定以下同一组已接受对象：

| 对象 | 固定值 |
|---|---|
| 供应链index | `sha256:0fc7f95eb14f18996c6f22d71b4873b28e79ea0afde8a66ddea6b6c095740c13` |
| `linux/amd64` manifest | `sha256:7c5dccfc9b5cb3175718344b913d0993b13ad489835fbdbc4204e11f658a15f7` |
| config | `sha256:c6344931bf46a076ebc180117988d7240e5f0e7320db647a6a98d365a74e480d`，1877字节 |
| gzip Layer | `sha256:fdae8d61585eef7d6a5c810e10847cd10039f3a8b69645d480c6d4127c1aebfb`，26,534,130字节 |
| 来源提交 | `9be7b7c366f568d82a19341e072a3144ddd025a2` |

`tools/ocr_offline_layer.py`不接受URL、仓库、Tag或digest参数，只提供`download`和离线
`verify`。下载令牌不落盘，HTTPS重定向只允许GHCR批准的Blob/CDN域名；固定`.part`支持
Range续传，完成前不覆盖最终文件。原子改名以前必须重新验证index/platform/config/来源、
Layer媒体类型、精确大小、SHA-256、gzip/tar结构和完整预期成员。固定输出目录
`.smartscan-offline-transfer/`已被Git忽略，真实模型和临时文件不得提交。

仓库下载工具的LF规范化SHA-256为
`ef7cfe1b7aca043cca7293488744640fbe793e039215442f72e69c16940e1c75`。只有PR合并且取得本机下载
授权后，才在仓库根目录运行：

```powershell
python tools/ocr_offline_layer.py download
python tools/ocr_offline_layer.py verify
```

固定输出为
`.smartscan-offline-transfer/ocr/smartscan-ocr-layer-fdae8d61585e.tar.gz`，精确大小26,534,130
字节，SHA-256为`fdae8d61585eef7d6a5c810e10847cd10039f3a8b69645d480c6d4127c1aebfb`。
PR合并后仍须另行授权创建服务器固定用户目录和上传；未来SCP命令固定为：

```powershell
scp .smartscan-offline-transfer/ocr/smartscan-ocr-layer-fdae8d61585e.tar.gz smartscan-server:/home/szhzx/smartscan-ocr-offline-transfer/smartscan-ocr-layer-fdae8d61585e.tar.gz
```

上传前必须已由`szhzx`创建固定目录并设为0700；上传后必须独立核对普通文件、所有者、0600、
精确大小和摘要。以上命令不包含自动建目录、改权限、暂存或安装，不能在没有对应授权时执行。

离线传输的是上述原始Layer字节，不是新模型版本。任何重打包都会改变Layer摘要，必须被拒绝，
不能以“内容相同”为由冒用现有digest。PR的Ubuntu真实Layer作业只在临时工作区下载、复核并于
结束时清理；PR和main均不发布或替换模型制品。

## 服务器离线提取边界

服务器Docker提取路线已经停止。未来只允许把固定Layer上传到固定用户路径，再由独立受限
暂存执行器安全解包到`/mnt/data/smartscan/uat/models/.ocr-staging/PP-OCRv6-small-v1`。
不得直接把上传文件或tar内容复制进最终目录。受限root安装器完成完整清单复核后，才把文件复制到
`/mnt/data/smartscan/uat/models/ocr`，设置`root:root`、目录`0755`、文件`0444`。
Worker只读挂载最终目录，运行时禁止联网下载。

模型安装失败会保留部分状态和原因，不自动删除。暂存目录、部分安装、已安装模型的删除
或替换均需新的单独授权；禁止`prune`和通配符删除。
