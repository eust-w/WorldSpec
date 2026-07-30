---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0030-h1-task-load-aware-locomotion.md
last-verified: 2026-07-30
---

# ADR-0030：H1 任务载荷感知下肢策略

## 背景

A5-CK 已证明，将基座恢复命令限制到 Motion Policy 的训练域仍不足以稳定
H1。右臂保持任务姿态和偏置力前馈后，冻结策略在 `+0.5 m/s` 前向命令下仍
持续后滑并触发 `fall_height`。继续修改 PD 增益或放宽高度门不能回答下肢策略
是否学会了加载姿态下的全身平衡。

## 决策

新增 `loaded_track_settle_task_load` 研究校准阶段：

1. 从冻结的 transition-v2 Checkpoint Warm Start，恢复 normalizer、policy
   与 value，优化器重新初始化。
2. 在最终 H1 + 右手 Robotiq 动力学上，将 A5-CK 的九维 held-joint 姿态和
   偏置力前馈作为只读任务载荷；每个 Episode 在 `0.5–1.0` 比例内采样。
3. 初始基座纵向速度在 `[-0.1, 0.1] m/s` 内采样，用于覆盖小幅后滑扰动。
4. 不扩展观察 ABI，不改变命令分布、transition curriculum、奖励、终止条件
   或十项质量门；本阶段检验策略能否通过动力学反馈隐式适应载荷。
5. 使用 16,777,216 步、4,096 环境和八次评估做一次 A800 校准；结果无论
   通过与否都回传 Checkpoint、Report、Trace 与环境锁并验证 Digest。
6. 只有 `formalTrainingGate=passed` 才允许把该 Checkpoint 接入一次有界
   全身控制 Spike；失败时停止并基于证据决定是否增加显式载荷观察或重新设计
   控制接口。

## 边界

- 任务载荷校准通过只产生内部研究策略，不自动成为公开策略或厨房 L3。
- 本阶段不启动完整 A5、5/5 或 100M 训练。
- 固定右臂姿态与力前馈是 A5-CK 的证据重放，不代表所有操作姿态或负载分布。
- 若无显式载荷观察仍不能通过，下一次设计必须单独审查观察 ABI 变化，不允许
  静默替换现有 Checkpoint 兼容性。
