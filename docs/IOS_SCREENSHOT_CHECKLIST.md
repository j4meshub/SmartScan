# iOS App Store 截图清单

## 尺寸策略

应用当前支持 iPhone 与 iPad（`TARGETED_DEVICE_FAMILY=1,2`），因此两个设备族都必须准备截图。按照 2026-10-21 查阅的 Apple [截图规格](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/)，每种设备与本地化可上传 1 至 10 张 JPEG/JPG/PNG，且不能带透明通道。本项目统一使用竖屏：

- iPhone 6.9 英寸：首选 `1320 × 2868`；校验器也接受 Apple 当前列出的 `1290 × 2796` 与 `1260 × 2736`。
- iPad 13 英寸：首选 `2064 × 2752`；校验器也接受 `2048 × 2732`。

Apple 规格会随设备更新，正式生成前必须复核官网并同步 `apps/ios/release/screenshots.yml`，不能为通过脚本而缩放到失真尺寸。

## 每种语言的场景顺序

1. 登录与安全会话：不出现真实手机号、验证码或内部地址。
2. 文档拍摄：展示矩形与质量提示，画面使用授权的非敏感样张。
3. 页面编辑：展示页序、旋转、四角与滤镜，但不暗示可以恢复被遮挡文字。
4. 导出与分享：展示 PDF/JPG、质量档和 OCR 文本层选项。
5. 账户与隐私：展示隐私政策、支持页和应用内账号删除入口。

英文和简体中文分别在对应系统语言下重新拍摄，不把中文文本覆盖到英文截图上。状态栏不得出现个人账户、内网 Wi-Fi 名称、通知、位置或调试标记。

## 生成与登记

截图文件不使用真实用户数据。将最终文件放在受控发布资产目录，并在 `apps/ios/release/screenshots.yml` 中登记相对 `apps/ios/release/` 的路径；顺序即 App Store 展示顺序。执行：

```bash
python tools/validate_ios_release.py --release
```

校验器会检查数量、格式、尺寸和透明通道。构图、文案真实性、授权和视觉质量仍由人工复核。上传后按[上传截图](https://developer.apple.com/help/app-store-connect/manage-app-information/upload-app-previews-and-screenshots/)在两种语言中逐一预览，确认缩放没有裁掉功能或免责声明。
