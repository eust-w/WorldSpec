---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0048-h1-fixed-state-viability-diagnostic.md
last-verified: 2026-07-31
---

# ADR-0048：H1 固定困难状态可恢复性诊断

## 状态

Accepted Design。真实 A800 结果尚未产生。

## 背景

ADR-0047 记录的 v14 训练在固定步行后困难状态索引 `565` 上仍未通过正式
操作平衡门。训练失败不能证明该状态在冻结的控制器、观察 ABI 和动作范围内
不可恢复。继续修改奖励或重训也无法区分“状态不可恢复”和“策略没有找到
恢复动作”。

用户选择路线 A：先搜索一个满足原质量门的构造性动作 Witness。

## 决策

新增 `loaded_track_settle_manipulation_viability` 诊断：

- 精确绑定 v14 Step `7,372,800` Checkpoint、状态库、索引 `565`、评测
  Seed `2`、目标模型和包锁；
- 先以零残差重放冻结策略，所有归档指标必须在 `0.001` 绝对容差内复现；
- 在相同 10 维腿部动作 ABI 与 `[-1, 1]` 动作范围内，搜索冻结策略之上的
  有界残差；
- 使用 10 个时间结点、100 步时域、4,096 个候选、128 个精英和 12 轮
  CEM；残差限制为 `[-0.5, 0.5]`；
- 质量门、模型、初态、随机种子、控制器、观察和动作维度均不得改变；
- 仅运行一次单 GPU A800 诊断，不训练、不自动重试。

结果语义固定为：

```text
找到通过原质量门的轨迹
→ constructive_witness
→ 只证明状态在冻结契约内可恢复

搜索未找到轨迹
→ unknown
→ 不构成不可恢复证明
```

`formalViabilityDiagnosticGate` 只判断血缘、基线复现、搜索完成和诊断
完整性；`formalWitnessGate` 独立表示是否找到构造性 Witness。无论结果如何，
Controller 都保持 `non_publishable`，且不得解锁完整厨房单次、5/5 或
100M。

## 后果

- Witness 可以为下一轮显式恢复 Supervisor 提供动作和状态证据，但本身不是
  可发布策略；
- 搜索未命中时，需要另行决定扩大可行性求解器、检查观察别名，或设计恢复
  Supervisor；
- 运行时或实现缺陷可以修复后以新证据重跑；一次正常完成但未命中的搜索不得
  自动扩大预算或重复。

## 证据状态

本 ADR 目前只绑定 Profile、Schema、实现和本地测试。真实 A800 Report、
Witness、Search Progress 和 Trace 必须在运行完成后另行归档。
