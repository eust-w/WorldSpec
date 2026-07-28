---
status: Normative
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/architecture/evidence-and-uncertainty.md
last-verified: 2026-07-28
---

# 证据与不确定性

EvidenceGraph 由 Claim、EvidenceSource 与 Derivation 构成。所有影响质量、惯量、碰撞、关节、尺度和认证的高影响属性必须能追溯到 Claim 或显式 Default Policy。

## Claim

Claim 声明目标字段、名义值、单位、区间/分布、证据状态和适用域。状态固定为：

`measured / manufacturer_declared / imported / reconstructed / derived / estimated / generated / default / unknown`

后续流程不得把 `generated`、`estimated` 或 `default` 静默升级为 `measured`。

## EvidenceSource 与 Derivation

EvidenceSource 记录源 Digest、权利状态、采集方法和时间。Derivation 记录算法、版本、输入 Claim、输出 Claim 与假设。EvidenceGraph 必须是 DAG。

## 不确定性传播

- 从区间/分布压缩为名义值必须声明 `nominal / conservative / optimistic / sampled / measured-only` 选择策略。
- 推导结果必须保存输入、假设和方法版本。
- 无法传播时标记 `unpropagated`，不得删除不确定性。
- 自动生成资产通过 L2/L3 不改变其证据状态。

证据等级说明“我们为什么相信这个值”；认证等级说明“在指定目标和测试下通过了什么”。两者必须分开。
