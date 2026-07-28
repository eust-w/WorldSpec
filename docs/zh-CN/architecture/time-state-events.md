---
status: Normative
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/architecture/time-state-events.md
last-verified: 2026-07-28
---

# 时间、状态与事件

## 永久分离

- **Parameter**：WorldDefinition Revision 内不可变的质量、惯量、限位、内参和材料参数。
- **InitialState**：Episode 起点，不是永久资产参数。
- **StateChannelDescriptor**：状态的 Subject、Property、单位、ClockDomain 与插值语义。
- **StateStream**：RuntimeRecord 中的时间采样值。
- **EventLog**：离散事件及其因果引用。

## 时间模型

必须区分 simulation、control、sensor、render 和 wall-clock 域。每个 StateStream/Event 必须声明 ClockDomain；跨域对齐必须声明同步、插值与延迟策略。

时间戳在同一 Stream/Epoch 内单调不减。Reset 开始新 Epoch。Snapshot 必须绑定 WorldDefinition Digest，且不能承诺目标后端无法序列化的接触内部状态可比特恢复。

## 权威来源

由 Frame Graph 可计算的 world pose 不能作为第二份权威状态。每个被驱动 Frame 在一个 Build 中只能有一个权威驱动源。Runtime 写入不得修改静态 Parameter；参数变化通过 override 或新 revision 表达。
