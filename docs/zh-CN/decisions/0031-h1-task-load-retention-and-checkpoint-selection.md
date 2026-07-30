---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0031-h1-task-load-retention-and-checkpoint-selection.md
last-verified: 2026-07-30
---

# ADR-0031：H1 任务载荷保持与 Checkpoint 选择

## 背景

`loaded_track_settle_task_load` 已在 Drobodata A800 上真实执行
16,777,216 步。训练无 NaN、容量溢出或异常接触，但正式门失败：

- 最终平均 Episode 长度为 `774.3047 < 900`；
- 五次行走—停稳的最终线速度为 `0.48–0.56 m/s`，均高于
  `0.20 m/s` 门槛；
- 五次负载站立的最大平面漂移为 `0.287–0.315 m`，均高于
  `0.20 m` 门槛；
- 训练早期平均 Episode 长度为 `922.2813`，末期退化为 `774.3047`。

这说明仅靠隐式动力学反馈学习任务载荷会破坏原有站立保持，而且只封装训练末期
Checkpoint 会丢失“中间策略可能更好”的证据。

## 决策

新增 `loaded_track_settle_task_load_retention` 研究阶段：

1. 从已完成站立保持校准的 retention-v3 Checkpoint Warm Start；恢复
   normalizer、policy 和 value，优化器重新初始化。
2. 将 stand-v2.1 作为 `stand_replay_only` 教师，将已通过 A3 的 Capture
   Policy 作为 `transition_settle_only` 教师。
3. 使用 `75%` 行走—停稳和 `25%` 站立回放；完整使用 A5-CK 右臂 held
   姿态和偏置力前馈，不采样部分载荷，不注入额外初始速度。
4. 学习率降为 `5e-5`，熵成本降为 `0.001`；加强停稳奖励，但十项正式质量门
   和终止条件保持不变。
5. 保存的每个 PPO Checkpoint 都运行同一组五次行走—停稳和五次站立回归。
   选择顺序固定为：正式门、通过测试数、Episode 门、归一化违规量、Episode
   长度、较早步数。
6. 仅封装被选中的 Checkpoint，并在 Report 中保存全部候选的步骤、门结果和
   归一化违规分数。选择机制不能把失败候选标为通过。
7. 只运行一次真实 A800 校准；失败时完整交接证据后继续设计，不自动启动
   A5、5/5、100M 或 L3。

## 边界

- 本阶段未改变观察 ABI；若双教师与完整负载仍失败，显式负载观察必须另立 ADR。
- Capture 教师只约束停稳窗口，不能替代任务阶段 Supervisor。
- 中间 Checkpoint 选择解决的是策略退化证据保存，不是提前停止或门槛放宽。
- 通过本阶段只产生内部步态候选，仍不证明完整厨房任务。
