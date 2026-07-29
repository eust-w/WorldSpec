---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0015-h1-transition-braking-calibration.md
last-verified: 2026-07-29
---

# ADR-0015：H1 过渡制动课程与 CCD 单候选探针

## 背景

`loaded-track-settle-v1` 的真实 A800 运行通过了行走、姿态、站立回归和平均
Episode 长度门槛，但五次测试均未通过原始停稳速度门槛。该结果是失败证据，不能通过
降低阈值改写为通过。日志还出现两条将 `ccd_iterations=35` 提高的建议；它们不是
CCD 容量溢出，但在下一次训练前需要独立验证。

## 决策

选择方案 A：

- 保持 `0.20 m/s` 停稳线速度和 `0.40 rad/s` 停稳角速度等全部原始门槛；
- 新增显式“移动到零命令”课程：75% 周期先移动 150 个控制步，再零命令 50 个
  控制步；
- 仅在该零命令阶段增加线速度、偏航速度停稳奖励，并降低动作变化惩罚权重；
- 从失败的 `loaded-track-settle-v1` 内部 Checkpoint Warm Start，恢复
  normalizer、policy 和 value，重置优化器；
- 在重新训练前只测试一个预先声明的 CCD 候选：`35 → 50`；
- CCD 探针必须在 4,096 个环境、200 步批量轨迹中无迭代建议、CCD 容量溢出和
  其他容量溢出，才允许创建过渡校准 Job；
- 探针或校准失败均立即停止，不自动调参、不自动重试。

## 证据边界

本 ADR 和对应 Profile、Schema、Worker、Job 只是 `Accepted Design` 与实现基线。
在真实 A800 报告生成前，不得声称：

- CCD=50 已解决数值问题；
- 过渡课程已改善停稳；
- 中期策略已通过；
- 正式 100M 训练已获放行。

即使新中期校准通过，也只允许创建正式步态训练，不构成完整厨房任务或 L3 证据。

## 后果

- 原始失败报告和 Checkpoint 成为新实验的不可变输入；
- CCD 数值变化与奖励/课程变化分别出证，避免把两个变量混为一个结论；
- 新产物继续保持 `research_only / internal_only / non_publishable`；
- 正式训练仍由不变的十项行为门控决定。
