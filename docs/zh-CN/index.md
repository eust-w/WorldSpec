---
status: Normative
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../en/index.md
last-verified: 2026-07-28
---

# WorldSpec v0.1 文档索引

中文是规范真源；英文是官方译本。冲突时以中文和已接受 ADR 为准。

## 文档成熟度

- **Normative**：v0.1 必须实现或验收。
- **Accepted Design**：架构决策已接受，但当前仓库不证明已实现。
- **Research**：需要实验或基准验证的候选方案。
- **Future**：不进入 v0.1 代码验收。
- **Superseded**：保留追溯，但不再采用。

## 导航

- 产品：[愿景](product/vision.md)、[PRD v0.1](product/prd-v0.1.md)、[验收](product/acceptance.md)
- 架构：[总览](architecture/overview.md)、[对象模型](architecture/object-model.md)、[证据与不确定性](architecture/evidence-and-uncertainty.md)、[时间/状态/事件](architecture/time-state-events.md)、[安全与原生载荷](architecture/security-and-native-payload.md)
- 流水线：[接入](pipelines/ingestion.md)、[生成](pipelines/generation.md)、[物理与碰撞](pipelines/physics-collision.md)、[SimReady 认证](pipelines/simready-certification.md)
- 编译与接口：[编译器模型](compiler/compiler-model.md)、[MuJoCo](compiler/mujoco.md)、[Three.js](compiler/threejs.md)、[CLI/API](interfaces/cli-api.md)、[报告](interfaces/reports.md)
- 当前实现：[Rust Validator](implementation/validator.md)
- 治理：[决策登记](decision-register.md)、[版本](governance/versioning.md)、[许可](governance/licensing.md)
- 研究与后续：[开放问题](research/open-questions.md)、[路线图](roadmap.md)
- ADR：[决策目录](decisions/README.md)

## 规范绑定

机器可读规范位于 `schemas/0.1/`，采用 JSON Schema Draft 2020-12。JSON 是 v0.1 规范绑定；YAML 只可作为未来作者格式，不是规范真值。
