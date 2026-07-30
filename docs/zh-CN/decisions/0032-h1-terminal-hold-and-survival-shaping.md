---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0032-h1-terminal-hold-and-survival-shaping.md
last-verified: 2026-07-30
---

# ADR-0032：H1 终端静止保持测量与存活塑形

## 背景

`loaded_track_settle_task_load_retention` 已在 Drobodata A800 上真实执行
16,777,216 步，并评估全部七个 Checkpoint。正式门仍失败：

- 被选 Checkpoint 的平均 Episode 长度为 `500.7891 < 900`，末期降至
  `387.9922`；
- 训练终止以 `fall_height` 为主；
- 五次负载站立回归全部通过；
- 五次行走—停稳除 `maximumSettleLinearSpeed` 外全部通过；
- 历史评估把完整一秒减速段都作为“静止保持”窗口，因此命令刚切换为零时仍有
  约 `0.35 m/s` 的正常减速速度也会触发失败；
- 对同一 Trace 的最后 `0.2 s` 重新计算后，线速度为
  `0.048–0.078 m/s`，角速度为 `0.083–0.113 rad/s`，均低于原门槛。

ADR-0018、Capture Profile 与 Supervisor Profile 已将“停稳测量”定义为
一秒减速段末尾的 `0.2 s` 静止保持。Retention 阶段遗漏了该字段，造成同一
行为在不同校准阶段采用不同语义。与此同时，PPO 奖励在终止前被截断为非负，
且没有终止惩罚，无法直接学习避免 `fall_height`。

## 决策

新增 `loaded_track_settle_task_load_survival` 研究阶段：

1. 保留一秒减速阶段和 `0.20 m/s`、`0.40 rad/s` 原门槛，只把权威测量窗口
   明确为最后 `0.2 s`；这不是放宽阈值。
2. 继续从 retention-v3 原始 Checkpoint Warm Start，不从已退化的
   task-load-retention Checkpoint 续训；后者只作为失败血缘证据。
3. 保留完整 A5-CK 任务载荷、Stand/Capture 双教师、观察 ABI、终止条件、
   课程比例和所有正式质量门。
4. 增加 `terminationPenalty=25`，让 `fall_height` 等终止进入可学习回报；
   增加 Stand/Capture 教师动作误差成本各 `1.0`，防止仅靠正奖励掩盖策略漂移。
5. 学习率降至 `2e-5`、熵成本降至 `5e-4`，其余训练规模不变。
6. 继续评估全部 Checkpoint，并要求平均 Episode 长度至少 `900/1000`、
   五次行走—停稳和五次负载站立全部通过。任何失败候选保持
   `non_publishable`。
7. 只允许一次门控 A800 校准；通过后停止在内部步态候选边界，不自动执行
   A5、5/5、100M 或 L3。

## 边界

- 本决策修正评估语义不一致，不更改速度、漂移、姿态或 Episode 门槛。
- 终止惩罚与教师动作成本是研究性奖励塑形，不证明真实机器人稳定性。
- 若 Episode 门仍失败，下一步必须依据终止分布另立控制或观察设计，不自动调参。
- 通过本阶段只证明锁定模型、Profile、Checkpoint 和确定性测试下的负载步态候选。
