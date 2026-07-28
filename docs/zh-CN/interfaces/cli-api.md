---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/interfaces/cli-api.md
last-verified: 2026-07-28
---

# CLI 与异步 API

v0.1 产品入口是 CLI/API。当前已经实现本地 CAS、SQLite WAL 作业索引、loopback API，以及下表中的命令入口。OBJ Doctor、结构化机器人接入、MuJoCo/Three.js 参考编译器、隔离生成适配器和 H1 训练门控适配器已实现。创建生成/训练 Job 或通过门控测试仍不等于真实 GPU 已执行；L2/L3 认证仍需对应运行证据。

| 命令 | 输入 | 主要输出 | 当前状态 |
|---|---|---|---|
| `ingest` | 本地源、RightsSpec | CAS SourceBundle、AssetDraft | Mesh/URDF/MJCF 已实现；CAD/USD 隔离检查骨架 |
| `generate` | 源资产与 GenerationProfile | 可恢复 JobSpec | Queue + TRELLIS.2/Nerfstudio Worker 已实现；GPU 未验收 |
| `train` | 原生加载 Conformance 与 LocomotionTrainingProfile | 可恢复 JobSpec | 容量语义修订后的 Digest 锁定镜像、A800 one-step、8,192 环境规模预检和研究级 PPO smoke 已通过；规范训练、Checkpoint 与行为验收未执行 |
| `validate` | JSON 与 Schema 名称 | 结构与语义诊断 | Implemented |
| `compile` | WorldDefinition、TargetProfile 与 BuildIntent | 本地参考 Bundle | MuJoCo/Three.js 参考切片已实现 |
| `certify` | L2 证据；L3 另加 Task/Control/Predicate/InitialState/RuntimeRecord/TaskRunReport | Digest 绑定的 signed/unsigned Certificate | L2 与 L3 证据核验已实现；H1 5/5 未执行 |
| `inspect` | JSON、可选 Schema | Canonical SHA-256 与诊断 | Implemented |
| `resolve` | CAS Digest | 原始不可变 Blob | Implemented |
| `doctor diagnose` | JSON/AssetDraft 或 OBJ | Validator/OBJ 诊断 | 已实现 |
| `doctor repair` | OBJ | 新 OBJ、CAS Blob 与 Derivation | 退化面修复已实现 |
| `bundle` | Build 输入与 Profile | 可恢复 JobSpec | Queue Implemented；Assembler Future |
| `job get/cancel/wait` | Job ID | 作业状态 | Implemented |

所有改变状态的操作返回 Job ID。Job 使用 `queued/running/succeeded/failed/cancelled/timed_out`；结果只通过不可变产物引用返回。URI 形式 ID 在 HTTP 路径中必须做 URL 编码。

API 不接受隐藏默认降级。TargetProfile、BuildIntent 和生成 Backend Profile 必须显式或由可追溯默认 Profile 解析。

API 契约见 [OpenAPI v1](../../../openapi/worldspec-v1.yaml)。当前 CLI 用法、诊断码与边界见 [Validator 实现](../implementation/validator.md)。
