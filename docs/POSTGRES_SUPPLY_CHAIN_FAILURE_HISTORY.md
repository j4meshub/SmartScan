# PostgreSQL供应链失败证据

## OPS-REG-003与003A

PR #84保留了官方PostgreSQL固定digest原样复制方案及候选更新矩阵。该PR不得合并，只有`OPS-REG-003B`验证成功后才关闭。

- 原候选`sha256:0d938e975177bef9f1f61f3f9dbcf2e0aa0a139568f66d3415ed8892eb97f6ac`在严格Critical扫描中失败。
- `postgres:17-bookworm`固定候选为`sha256:837bed...`，除gosu所带Go标准库发现外还存在Debian系统包问题。
- `postgres:17-trixie`与当时`postgres:17`解析到`sha256:b60e900...`，仍未通过严格门禁。
- `postgres:17-alpine`固定候选为`sha256:526f86d93c6ea08fd3f1fe5605650cacc781b2c6013169a0ad8f42c7d3d84f32`，运行契约最接近可控目标，但官方原样镜像仍因`gosu`使用受影响Go标准库而不能直接接受。

以上省略号摘要仅用于说明候选关系，不能作为部署引用；完整证据保存在PR #84的GitHub Actions产物和日志中。失败记录不会被改写为通过，也不会通过忽略、改级、排除组件或关闭扫描消除。

## 替代关系

`OPS-REG-003B`不是放宽原门禁，而是把“镜像包含通用组件”与“SmartScan运行时真实可达风险”拆开审计：验证上游gosu、升级系统包、删除最终运行不需要的gosu、固定非root用户，再以SBOM、扫描、可达性证据和精确VEX组合判定。若该方案仍有真实Critical、可修复High或关键运行兼容性失败，工作包保持阻塞，不自动选择其他镜像。
