# WorldSpec（工作名）

WorldSpec 是面向具身资产的规范语义模型、证据模型与跨仿真器编译中间层。目标是把现有资产或图像/视频生成结果整理为可追溯、可验证、损失透明的 SimReady 资产。

> 当前仓库状态：包含 v0.1 文档、JSON Schema、示例、Rust Core 语义验证器和最小 `worldspec validate` CLI。MuJoCo/Three.js 编译器、资产生成器和 L2/L3 认证运行时尚未实现；文档中的产品 v0.1 仍是未来验收目标。

## 快速入口

- [中文文档（规范真源）](docs/zh-CN/index.md)
- [English documentation (official translation)](docs/en/index.md)
- [产品需求 v0.1](docs/zh-CN/product/prd-v0.1.md)
- [架构总览](docs/zh-CN/architecture/overview.md)
- [决策登记](docs/zh-CN/decision-register.md)
- [Validator 实现边界](docs/zh-CN/implementation/validator.md)
- [JSON Schema 0.1](schemas/0.1/)
- [最小示例](examples/)

## 基线范围

```text
SourceBundle -> AssetDraft -> WorldDefinition
WorldDefinition + TargetProfile + BuildIntent
    -> ArtifactBundle + LossReport + BuildManifest
    -> ConformanceReport + Certificate
```

v0.1 计划认证 MuJoCo 与 Three.js。OpenUSD 仅作为输入和原生载荷保留 Profile，不代表 Isaac Sim 已获运行认证。

## 验证

```bash
python3 scripts/validate_baseline.py
git diff --check
```

验证工具检查 JSON/Schema、`$ref`、正负例、双语镜像、文档元数据和本地链接。它不是产品运行时 Validator。

Rust Validator：

```bash
cargo run --quiet -p worldspec-cli -- \
  validate examples/minimal-cube/world.json --output json

cargo test --workspace
```

`worldspec validate` 当前执行 Draft 2020-12 Schema 校验，以及已登记的 WorldDefinition/LossReport 跨对象不变量。

## 许可状态

已接受的产品策略是 `AGPL-3.0 + 商业许可 + CLA`。正式商业许可、CLA 及完整法律文件仍待法务确认；当前仓库中的说明不能替代法律意见。参见 [许可治理](docs/zh-CN/governance/licensing.md)。
