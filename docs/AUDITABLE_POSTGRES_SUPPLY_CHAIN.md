# 可审计 PostgreSQL 17 运行镜像供应链

## 目标与边界

`OPS-REG-003B`解决目标服务器不能访问Docker Hub，以及官方PostgreSQL 17镜像中的通用系统包扫描结果无法直接代表SmartScan真实运行风险的问题。它不修改服务器、不部署UAT，也不自动接受任何镜像digest。

构建起点固定为：

```text
docker.io/library/postgres@sha256:526f86d93c6ea08fd3f1fe5605650cacc781b2c6013169a0ad8f42c7d3d84f32
```

该制品属于Docker Official Image的PostgreSQL 17 Alpine谱系。SmartScan在此基础上升级可修复Alpine系统包、删除仅供root降权的`gosu`，并固定以官方Alpine PostgreSQL用户`70:70`运行。最终产物是SmartScan构建的衍生运行镜像，不得描述为Docker官方在GHCR发布的原样镜像。

## 组合安全门禁

门禁不是按扫描器数字建立通配符忽略，而是同时要求：

1. 镜像内`gosu 1.20`与上游固定发布制品SHA-256和字节完全一致；
2. 对该二进制独立执行`govulncheck -mode=binary`，并保存Go构建版本、模块、受影响`crypto/tls`符号和`go tool nm`证据；
3. 最终SBOM不得包含`gosu`，最终文件系统不得存在`/usr/local/bin/gosu`；
4. Trivy以`ignore-unfixed=false`扫描全部High/Critical；任何可修复High/Critical和任何仍存在的Critical均失败关闭；
5. VEX只允许绑定`CVE-2025-68121`、`GO-2026-4337`、精确组件、精确最终镜像digest、源提交、复核日期和90天失效期；理由只能是最终组件不存在；
6. 基础镜像、最终digest、SBOM、gosu摘要、漏洞库结论、容器用户或入口路径任一变化，VEX立即失效并重跑全部门禁。

二进制模式只能判断受影响符号是否存在，不能恢复调用栈。因此即使审计显示符号不可达，SmartScan也不依赖该结论发布，而是从最终运行镜像删除组件。若删除失败、SBOM仍发现组件或证据不足，构建保持阻塞。

## 运行兼容性

PR验证必须在临时Docker环境中完成：

- `USER 70:70`、数据目录所有权和无`gosu`运行；
- `initdb`、`UTF8`编码和中文数据读写；
- SmartScan当前数据库迁移；
- `pg_isready`健康检查；
- 停止/重启后的持久化；
- `pg_dump`/`pg_restore`；
- `pg_basebackup`/`pg_verifybackup`；
- 只读根文件系统、64 MiB `/tmp`和16 MiB PostgreSQL socket tmpfs；
- 当前UAT Compose固定用户、数据目录和初始化参数契约。

测试脚本只在GitHub托管Runner上使用预装的无交互`sudo`为唯一临时目录设置`70:70`所有权并在结束时清理该目录；路径由`mktemp`创建并再次匹配固定前缀。该权限不安装到共享服务器，也不授予或调用SmartScan服务器sudo执行器。

## 发布与人工门禁

PR只构建、扫描和上传审计证据，不发布镜像。只有CI全部通过并合并`main`后，工作流才把同一份已验证镜像发布到`ghcr.io/j4meshub/smartscan-postgres`，生成SPDX SBOM、GitHub SLSA构建来源证明、Trivy报告、精确OpenVEX和中文来源映射。

首次Package默认可见性不得由工作流修改；若发布后仍为私有，只能由用户人工决定是否公开。无论当前是否已公开，都还需在目标服务器只做匿名manifest/digest/`linux/amd64`核验，并明确接受固定digest，才可写入真实UAT配置。发布、公开、服务器核验和用户接受均不构成拉取、迁移或启动授权。

## 首次发布结果

- PR #85已以中文squash提交`264520cc451f144166e2e77e8dee79eef8b142d5`合并。
- 主线运行`44673210889`完成复核并发布固定引用`ghcr.io/j4meshub/smartscan-postgres@sha256:94758173bbe1975014751a2e2855a22e0e554e8df996e4d6303bcf386cdae6d0`。
- 发布证据确认最终SBOM不含gosu、High/Critical为0、精确VEX与自定义in-toto映射均绑定上述digest，且GitHub保存了1条SLSA来源证明。
- 匿名token和manifest HEAD返回HTTP 200且响应digest一致，说明Package当前可公开读取；本工作包未调用可见性修改接口。
- 该digest仍须在目标服务器只读核验`linux/amd64`并由用户明确接受，才能进入仓库外UAT候选配置；不得因本节记录而自动部署。
