---
status: Accepted
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0010-generation-model-bundles.md
last-verified: 2026-07-28
---

# ADR-0010：生成模型包内容寻址

## 决策

v0.1 生成 Worker 从外部只读缓存加载模型，不在仓库、Job Manifest 或报告中保存权重和凭证。每个模型包使用规范 Manifest 标识；包 Digest 为 `formatVersion`、`backend` 和按路径排序的文件记录之 Canonical JSON SHA-256。

Worker 必须验证：

- Profile、目录和 Manifest 的包 Digest 一致；
- 所有声明文件的路径、SHA-256 与大小；
- 包内没有未声明文件；
- 不接受符号链接和路径穿越；
- Profile 对每个参考后端选择唯一模型包。

## 后果

目录名或 Manifest 自声明不再被视为内容证据。模型包可以由 OCI、对象存储或离线介质分发，但进入 Worker 只读缓存前必须物化为同一套可验证 Manifest。签名、透明日志和远程证明属于后续安全 Profile。
