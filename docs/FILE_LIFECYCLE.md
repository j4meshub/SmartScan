# 文件下载、上传取消与项目清理

## 接口

- `GET /v1/export-artifacts/{artifact_id}/content`：鉴权下载导出制品；
- `DELETE /v1/uploads/{upload_id}`：幂等取消未完成上传；
- `DELETE /v1/projects/{project_id}`：受理项目删除并立即尝试文件清理；
- `GET /v1/project-deletions/{deletion_id}`：查询项目文件清理状态。

所有接口先按所有者或既有管理员只读策略鉴权。跨用户创建、下载、取消或删除统一返回 `404`；可识别的拒绝动作和管理员读取写入追加式审计。

## 下载与 Range

开发环境直接使用 Starlette `FileResponse`，支持标准单区间 `Range`，有效请求返回 `206` 和 `Content-Range`。响应固定使用附件下载、私有重新验证缓存策略，并在有数据库哈希时返回强格式 ETag。

Compose 生产基线由 API 完成鉴权后返回 `X-Accel-Redirect`。Nginx 的 `/_smartscan_files/` 位置标记为 `internal`，并只读挂载同一 `scan-data` 卷，外部请求无法绕过 API 直接访问文件。URI 路径和 UTF-8 文件名均百分号编码；真实 TLS、缓存、Range 和大文件吞吐仍需在 staging 验收。

## 上传取消与临时目录回收

迁移 `20261020_0017` 把旧 PostgreSQL `uploadstatus` 原生枚举转换为有长度限制的字符串，并新增 `canceled`。只有 `pending` 或 `expired` 上传可取消；已完成上传返回 `409`，重复取消返回 `204`。

取消先提交状态和审计，再删除临时分片。删除失败时保留分片记录，Worker 会继续处理 `canceled` 或 `expired` 上传；到期的 `pending` 上传也由同一队列标记为 `expired` 并回收。降级时 `canceled` 映射为旧客户端可理解的 `expired`。

## 项目删除与可重试清理

项目删除在一个数据库事务中保存 `project_deletions` 清单，并显式删除页面、结果、作业、上传、分片、导出和制品记录。文件清单只接受 `users/{owner_user_id}/...` 下的规范相对路径，拒绝绝对路径、父目录跳转和跨用户路径。

事务提交后立即逐文件清理。全部成功时状态为 `completed`；任何文件系统错误都保持 `cleanup_pending` 和稳定错误码，Worker 后续重试。账号合并在任一账号存在待清理项目时拒绝执行，避免文件所有权迁移与删除竞态；账号删除会覆盖整个用户目录并移除对应项目清理记录。

## 回滚

降级 `0017` 会删除项目清理状态表，并把已取消上传映射为 `expired`，不会恢复已经删除的项目、数据库记录或文件。生产回滚前必须等待 `cleanup_pending` 清零并备份审计证据。禁止通过递归删除整个存储根目录代替状态化清理。
