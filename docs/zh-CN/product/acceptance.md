---
status: Normative
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/product/acceptance.md
last-verified: 2026-07-28
---

# 验收与认证等级

## 资产等级

| 等级 | 名称 | 最低证据 |
|---|---|---|
| L0 | Parsed | 输入可解析，来源与原生载荷已登记 |
| L1 | Canonical Valid | WorldDefinition 通过 Schema 与核心不变量 |
| L2 | Target Loadable | 目标 Bundle 由目标运行时原生加载，LossReport 完整 |
| L3 | Task Validated | 绑定 Task Profile 后通过规定行为与谓词测试 |

等级绑定资产 Digest、TargetProfile、BuildIntent、编译器版本和运行环境。任何依赖变化都需重新认证。

## 证据等级

`measured`、`manufacturer_declared`、`imported`、`reconstructed`、`derived`、`estimated`、`generated`、`default`、`unknown` 是来源/权威状态，不是 L0–L3 的替代物。生成资产即使达到 L3，质量或摩擦仍可保持 `estimated`。

## v0.1 整体验收

- 三条产品闭环均产生符合 Schema 的可追溯产物。
- MuJoCo 与 Three.js 参考编译器达到 L2；选定刚体任务达到 L3。
- 每个非精确 Lowering 都出现于 LossReport，状态只可为 `exact / converted / approximated / baked / emulated / dropped / unsupported`。
- Conformance Corpus 覆盖自制合成资产和一个授权状态明确的真实厨房案例。
- 双语文档、Schema、示例、报告格式和版本策略通过仓库基线检查。
- 性能、显存、成本、加载率和行为偏差用真实结果报告，不设未经测量的通过数字。

当前仓库已完成文档/Schema 基线、Rust Validator、平台骨架、OBJ Doctor、参考编译切片，以及当前 macOS arm64 本地 Profile 的 MuJoCo/Three.js L2。Linux x86_64 参考 Profile、真实 GPU 生成、全格式原生运行和 H1 厨房 L3 尚未完成，因此仍不满足产品 v0.1 整体验收。
