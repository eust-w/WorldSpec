---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/architecture/overview.md
last-verified: 2026-07-28
---

# 架构总览

```text
Sources
  -> Forge (ingest/generate/repair/infer)
  -> AssetDraft
  -> Doctor (validate/diagnose/evidence)
  -> WorldDefinition
  -> Compiler (select/lower/package)
  -> Target Bundle
  -> Conformance + Certificate
```

## 模块边界

- **Core**：Entity、Frame、Component、Relation、Model、Representation、Evidence、Time/State 的规范对象和不变量。
- **Forge**：把 Mesh、机器人描述、CAD/USD 或图像/视频转成 AssetDraft；结果是候选，不是真值。
- **Doctor**：执行结构、几何、物理、证据和目标兼容性诊断；修复必须生成新资源和 Derivation。
- **Compiler**：根据 TargetProfile、BuildIntent 和 Model Selection 生成 LoweringPlan 与目标 Bundle。
- **Manifest**：用内容 Digest、工具版本、Profile、选择和产物建立可复现记录。

## 不做大字段并集

WorldSpec Core 不等于 MJCF、USD、glTF 等字段的并集。目标专有数据走版本化 Native Payload；从规范语义到目标能力的差异由 LoweringPlan 和 LossReport 显式承担。

## 实现方向

Rust Core 的确定性 Validator、CLI、CAS/API、OBJ Doctor、结构化机器人接入、MuJoCo/Three.js 参考编译和本地 L2 认证，以及 TRELLIS.2/Nerfstudio 隔离 Worker 已实现。真实 GPU 生成、Linux x86_64 参考 Profile L2、TypeScript/WASM 绑定、完整 Compiler/Doctor 和 H1 L3 仍未完成。语言选择不进入 Schema 语义。
