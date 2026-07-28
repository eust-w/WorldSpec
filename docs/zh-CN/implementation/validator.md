---
status: Normative
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/implementation/validator.md
last-verified: 2026-07-28
---

# Rust Validator 实现边界

## 已实现

`worldspec-core` 加载本地 `schemas/0.1`，建立无网络 Schema Registry，并使用 Draft 2020-12 与格式校验验证 JSON。

对 schema-valid `WorldDefinition`，当前额外检查：

- 全局对象 ID 重复；
- World Root、Entity Ownership 及所有权环；
- Entity/Frame 所有权和 root frame；
- Frame Placement 缺失、多驱动、自连接、未知引用和环；
- 四元数归一化；
- Component/Representation/Model/Relation 跨引用；
- Claim、EvidenceSource、Derivation 引用和证据环；
- ClockDomain、StateChannel 和 InitialState 引用。

对 schema-valid `LossReport`，检查 entries 数量、complete coverage 和可选 TargetProfile 中非 exact capability 的报告覆盖。

## CLI

```bash
cargo run --quiet -p worldspec-cli -- \
  validate examples/minimal-cube/world.json \
  --schema world-definition.schema.json \
  --schema-dir schemas/0.1 \
  --output json
```

LossReport 可附加：

```bash
--target-profile examples/minimal-cube/target-profile.json
```

退出码：

- `0`：结构与已实现语义规则均通过；
- `1`：文档无效，已输出诊断；
- `2`：文件、JSON、Schema Catalog 或 Validator 无法运行。

## 尚未实现

- 全部 WS-INV-001 至 WS-INV-042；
- Schema migration、Profile Registry 和扩展命名空间治理；
- Parameter/State 值类型及单位量纲求解；
- 权威证据等级传播证明；
- BuildIntent 与 LossReport 的完整 Lowering 覆盖；
- MuJoCo/Three.js 编译、原生加载和 L2/L3 认证。

通过当前 Validator 只证明 `Canonical Valid` 的一个子集，不自动授予正式 L1 证书。
