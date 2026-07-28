---
status: Accepted
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0007-product-surface-and-distribution.md
last-verified: 2026-07-28
---

# ADR-0007：产品入口与分发

## 决策

v0.1 入口为 CLI 与异步 API，不建设正式 Web 工作台。Three.js Bundle 提供预览与调试。

分发使用本地内容寻址 Manifest、Lockfile、证书和报告。OCI Registry 与 Marketplace 后移。

## 后果

接口优先稳定 Job、Artifact 和 Report 契约。浏览器 UI 不成为 v0.1 验收依赖；本地 Bundle 必须可离线检查和复现。
