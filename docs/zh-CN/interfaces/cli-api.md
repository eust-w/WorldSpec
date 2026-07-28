---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/interfaces/cli-api.md
last-verified: 2026-07-28
---

# CLI 与异步 API

v0.1 产品入口是 CLI/API。当前已经实现本地 CAS、SQLite WAL 作业索引、loopback API，以及下表中的命令入口。创建 Job 不等于执行后端：GPU 生成、Doctor 网格修复、MuJoCo/Three.js 编译和 L2/L3 认证仍需对应 Worker/Backend。

| 命令 | 输入 | 主要输出 | 当前状态 |
|---|---|---|---|
| `ingest` | 本地源、RightsSpec | CAS SourceBundle、AssetDraft | Implemented Envelope |
| `generate` | 源资产与 GenerationProfile | 可恢复 JobSpec | Queue Implemented；Worker Future |
| `validate` | JSON 与 Schema 名称 | 结构与语义诊断 | Implemented |
| `compile` | WorldDefinition 与 TargetProfile | 可恢复 JobSpec | Queue Implemented；Backend Future |
| `certify` | Certificate、可选 Ed25519 Seed | 校验后的 signed/unsigned Certificate | Implemented Envelope |
| `inspect` | JSON、可选 Schema | Canonical SHA-256 与诊断 | Implemented |
| `resolve` | CAS Digest | 原始不可变 Blob | Implemented |
| `doctor diagnose` | JSON/AssetDraft | Validator 诊断 | Implemented Baseline |
| `doctor repair` | AssetDraft 与 Profile | 可恢复 JobSpec | Queue Implemented；Worker Future |
| `bundle` | Build 输入与 Profile | 可恢复 JobSpec | Queue Implemented；Assembler Future |
| `job get/cancel/wait` | Job ID | 作业状态 | Implemented |

所有改变状态的操作返回 Job ID。Job 使用 `queued/running/succeeded/failed/cancelled/timed_out`；结果只通过不可变产物引用返回。URI 形式 ID 在 HTTP 路径中必须做 URL 编码。

API 不接受隐藏默认降级。TargetProfile、BuildIntent 和生成 Backend Profile 必须显式或由可追溯默认 Profile 解析。

API 契约见 [OpenAPI v1](../../../openapi/worldspec-v1.yaml)。当前 CLI 用法、诊断码与边界见 [Validator 实现](../implementation/validator.md)。
