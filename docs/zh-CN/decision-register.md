---
status: Normative
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../en/decision-register.md
last-verified: 2026-07-28
---

# 决策登记

| ID | 决策 | 状态 | ADR |
|---|---|---|---|
| D-001 | 产品是具身资产平台；v0.1 同时验收三条闭环 | Accepted | [ADR-0001](decisions/0001-product-scope-and-name.md) |
| D-002 | WorldSpec 为工作名，公开品牌后定；不采用 SimForge | Accepted | [ADR-0001](decisions/0001-product-scope-and-name.md) |
| D-003 | 仓库为真源；中文规范、英文官方译本 | Accepted | [ADR-0002](decisions/0002-document-and-schema-binding.md) |
| D-004 | JSON + Draft 2020-12 JSON Schema 为规范绑定 | Accepted | [ADR-0002](decisions/0002-document-and-schema-binding.md) |
| D-005 | Rust Core + Python/TypeScript/WASM 绑定 | Accepted Design | [ADR-0003](decisions/0003-implementation-and-runtime.md) |
| D-006 | Linux + NVIDIA 80GB A800/H100 为参考生成环境 | Accepted Design | [ADR-0003](decisions/0003-implementation-and-runtime.md) |
| D-007 | 支持 Mesh、机器人、CAD、USD、图像和视频输入 | Accepted Design | [ADR-0004](decisions/0004-inputs-and-native-payload.md) |
| D-008 | CAD/USD Profile 完备 + Native Payload 保留 | Accepted | [ADR-0004](decisions/0004-inputs-and-native-payload.md) |
| D-009 | v0.1 认证 MuJoCo/Three.js；OpenUSD 不代表 Isaac 认证 | Accepted | [ADR-0005](decisions/0005-targets-and-certification.md) |
| D-010 | 生成资产默认最高 L2；行为验证后可 L3，证据不升级 | Accepted | [ADR-0005](decisions/0005-targets-and-certification.md) |
| D-011 | 生成后端可插拔；TRELLIS.2/Nerfstudio 类参考适配器 | Accepted Design | [ADR-0006](decisions/0006-generation-and-corpus.md) |
| D-012 | Corpus 为合成基准 + 一个授权明确的真实厨房案例 | Accepted Design | [ADR-0006](decisions/0006-generation-and-corpus.md) |
| D-013 | v0.1 入口 CLI/API；Three.js 仅预览调试 | Accepted | [ADR-0007](decisions/0007-product-surface-and-distribution.md) |
| D-014 | 本地 CAS Manifest/Lock/证书；OCI/Marketplace 后移 | Accepted | [ADR-0007](decisions/0007-product-surface-and-distribution.md) |
| D-015 | AGPL-3.0 + 商业许可 + CLA；法律文本待法务 | Accepted Design | [ADR-0008](decisions/0008-licensing-and-contributions.md) |
| D-016 | 现实世界“最大完备表达” | Superseded | 由 Profile Complete + Loss Transparency 取代 |
| D-017 | 单一 Scene Tree 或字段并集 | Superseded | 由对象库、多图与 Profile 取代 |
| D-018 | 跨后端逐帧物理一致 | Superseded | 改为任务/行为容差内一致 |
| D-019 | World/Task/Benchmark Generation、Registry、Marketplace | Future | [路线图](roadmap.md) |
| D-020 | 物理推断、碰撞参数和生成成本阈值 | Research | [开放问题](research/open-questions.md) |

新增或改变 Accepted 决策必须通过 ADR，不允许只改实施文档。
