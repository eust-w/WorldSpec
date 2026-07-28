---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/interfaces/cli-api.md
last-verified: 2026-07-28
---

# CLI 与异步 API

v0.1 产品入口是 CLI/API。当前只实现 `validate` 的本地 Rust CLI；其他命令和异步 Job API 仍是规划接口。

| 命令 | 输入 | 主要输出 | 当前状态 |
|---|---|---|---|
| `ingest` | 本地源或 SourceBundle | AssetDraft、诊断 | Future |
| `generate` | 图片/视频与 Backend Profile | AssetDraft、生成证据 | Future |
| `validate` | JSON 与 Schema 名称 | 结构与部分语义诊断 | Implemented Baseline |
| `compile` | WorldDefinition、TargetProfile、BuildIntent | Bundle、LossReport、Manifest | Future |
| `certify` | Build 与测试 Profile | ConformanceReport、Certificate | Future |
| `inspect` | ID/Digest/报告 | 人机可读视图 | Future |
| `bundle` | 已验证 Build | 内容寻址交付包与 Lockfile | Future |

所有改变状态的操作返回 Job ID。Job 使用 `queued/running/succeeded/failed/cancelled`；结果只通过不可变产物引用返回。失败响应包含 stage、code、message、diagnostics 和可重试性。

API 不接受隐藏默认降级。TargetProfile、BuildIntent 和生成 Backend Profile 必须显式或由可追溯默认 Profile 解析。

当前 CLI 用法、诊断码与边界见 [Validator 实现](../implementation/validator.md)。
