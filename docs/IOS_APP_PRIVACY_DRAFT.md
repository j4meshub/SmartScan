# iOS App 隐私披露草稿

## 用途与边界

本文把当前代码的数据流映射为 App Store Connect 隐私问卷和 `PrivacyInfo.xcprivacy` 的工程草稿。它不是法律意见，也不能替代隐私负责人、法务和后端运维对生产日志、供应商与保留期限的确认。

Apple 要求 iOS 应用提供隐私政策 URL，并披露应用及所集成第三方合作方的数据实践；回答需要持续保持准确。详见[管理 App 隐私](https://developer.apple.com/help/app-store-connect/manage-app-information/manage-app-privacy/)和[隐私清单数据声明](https://developer.apple.com/documentation/bundleresources/describing-data-use-in-privacy-manifests)。

## 当前数据映射

| 数据 | Apple 类别草稿 | 与身份关联 | 跟踪 | 目的与处理 |
|---|---|---:|---:|---|
| 已验证手机号 | Contact Info / Phone Number | 是 | 否 | 注册、短信验证、账号合并与删除；服务端加密保存并使用 HMAC 索引 |
| 用户 ID、用户名 | Identifiers / User ID | 是 | 否 | 账号、授权、项目所有权与审计 |
| 稳定安装设备 ID | Identifiers / Device ID | 是 | 否 | 设备会话与刷新令牌族；不用于广告 |
| 扫描照片 | User Content / Photos or Videos | 是 | 否 | 扫描、处理、预览、导出；保留原图 |
| OCR、项目名和导出内容 | User Content / Other User Content | 是 | 否 | 页面检索、智能命名和用户请求的导出 |
| 服务端安全与运行日志 | Diagnostics 或 Other Data，待生产核定 | 可能 | 否 | 故障定位、风控、审计；需确认字段、保留期与访问权限 |

当前版本不包含广告 SDK，不跨应用或网站跟踪用户，`NSPrivacyTracking=false` 且跟踪域名为空。若以后加入分析、崩溃报告或第三方 SDK，必须在合并前重新生成 Xcode Privacy Report，更新清单、App Store Connect 问卷和隐私政策。

## 可选 AI

外部视觉 AI 默认关闭，基础扫描与导出不依赖它。任何 Provider 启用前都必须单独披露传输的数据类型、供应商、处理地点、保留和删除方式，并取得产品/隐私负责人批准。用户扫描内容不能因为存在 Provider 代码骨架就被声明为已传输，也不能在真正启用后继续宣称完全本地处理。

## 发布确认清单

- 生产 API、Nginx、监控、备份、短信、企业微信和未来第三方 SDK 的实际字段已盘点。
- 隐私政策说明收集目的、法律依据、保存期限、接收方、跨境情况、用户权利、删除与联系方式。
- App Store Connect 数据类型与当前上架版本完全一致；隐私负责人完成书面确认。
- Xcode Archive 的 Privacy Report 与仓库清单一致，Required Reason API 没有遗漏。
- 应用内“管理账户”能访问隐私政策与支持页，且账号删除入口无需跳转网站寻找。
- 外部 AI 关闭状态下重新完成端到端测试。
