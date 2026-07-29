---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0016-h1-stand-retention-distillation.md
last-verified: 2026-07-29
---

# ADR-0016：H1 站立回放与教师动作蒸馏

## 背景

ADR-0015 的 A800 过渡校准改善了行走后的部分制动指标，但五次零命令站立回归由
5/5 退化为 0/5，说明原训练分布只有极少独立站立样本，并发生了明显的站立能力遗忘。
该失败不能通过放宽原行为门槛解决。

## 决策

选择 A1，继续使用一个统一策略，但把站立保持作为显式训练分布和只读教师约束：

- 从 ADR-0015 的失败内部 Checkpoint Warm Start，恢复 normalizer、policy 和
  value，重置优化器；
- 每个 200 控制步周期固定为 60% 行走 150 步再零命令 50 步，40% 全程零命令
  站立回放；
- 使用通过的 `stand-v2.1` Checkpoint 作为确定性只读教师；
- 教师只在站立回放阶段参与，将学生动作与教师动作的均方误差转换为蒸馏奖励；
- 该方法是教师动作蒸馏，不宣称为严格的策略分布 KL；
- 小规模校准为 8,388,608 个目标步、4,096 环境、6 次评估，学习率
  `1e-4`、熵系数 `0.003`；
- 保持 CCD=50、原始十项行为门槛和 `research_only / internal_only` 不变；
- 校准失败即停止，不自动调参、不自动重试，也不启动 100M 训练。

## 证据边界

Profile、Schema、环境奖励、教师载入与 A800 作业链路在真实运行前仅属于
`Accepted Design` 和实现基线。真实 A800 报告用于证明：

- 教师 Checkpoint 已成功载入且网络 ABI 一致；
- 站立回放和蒸馏奖励在真实 JAX/MJX 训练中执行；
- 十项行为门槛是否通过。

即使本校准通过，也只产生内部步态候选，不构成完整厨房任务或 L3 证据。

## 执行结果

2026-07-29，A1 在单张 NVIDIA A800-SXM4-80GB 上完成。运行从过渡失败
Checkpoint 恢复学生 normalizer、policy 和 value，并从 `stand-v2.1` 恢复只读教师；
两者优化器均未恢复。训练达到 8,601,600 个报告步，耗时约 584 秒。

A1 达到了保站目标：五次零命令站立回归从上一轮 0/5 恢复为 5/5，最大平面漂移为
0.1327–0.1727 米，最大线速度为 0.0698–0.0801 m/s，且无提前终止。
但五次行走—停稳测试仍全部失败：停稳窗口最大线速度为 0.5120–0.5488 m/s，
高于 0.20 m/s 门槛。最终平均 Episode 长度为 836.15625，也低于 900 门槛。
运行中没有 NaN、关节越限、容量溢出或异常接触诊断。

因此 A1 的正式门控为 `failed`，策略为 `non_publishable`；Checkpoint 只按
`research_only / internal_only` 保存，没有启动 100M 训练，也没有自动调参或重跑。
规范化失败证据见
[`locomotion-retention.a800.failed.json`](../../../examples/h1-kitchen/locomotion-retention.a800.failed.json)。

## 后果

- 失败过渡策略和通过站立策略分别作为学生初始化与教师证据保存；
- 报告必须同时绑定两套 Checkpoint 的 Digest、大小和选中步；
- 训练报告增加站立教师动作误差诊断，但正式放行仍只看原物理行为门槛；
- 是否进行更大预算训练由本次校准结果和后续用户决策共同决定。
