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

## 服务器离线提取边界

后续Docker阶段只负责拉取已接受的固定digest，并把`/models/ocr`复制到固定暂存目录
`/mnt/data/smartscan/uat/models/.ocr-staging/PP-OCRv6-small-v1`。不得直接把容器内容复制
进最终目录。受限root安装器完成完整清单复核后，才把文件复制到
`/mnt/data/smartscan/uat/models/ocr`，设置`root:root`、目录`0755`、文件`0444`。
Worker只读挂载最终目录，运行时禁止联网下载。

模型安装失败会保留部分状态和原因，不自动删除。暂存目录、部分安装、已安装模型的删除
或替换均需新的单独授权；禁止`prune`和通配符删除。
