---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0034-h1-long-horizon-survival-credit.md
last-verified: 2026-07-30
---

# ADR-0034：H1 负载步态长时生存信用与 PPO 漂移约束

## 背景

`loaded_track_settle_task_load_deployment_eval` 已在 Drobodata A800 上完成真实
确定性评估。Warm Start 的平均 Episode 长度为 `771.7578/1000`；首个训练
Checkpoint 提升到 `801.8203/1000`，并通过五次行走—停稳与五次负载站立测试，
但仍低于不可放宽的 `900/1000` 门槛。随后 Checkpoint 退化，末期
`training/kl_mean=0.0401`，主要终止通道仍是 `fall_height`。

原训练使用 `discounting=0.97` 和 Brax 默认 `gae_lambda=0.95`。其信用时域明显
短于 200 步的行走—停稳周期，`terminationPenalty=25` 也只在跌倒时单点进入
回报。确定性评估口径已经正确，继续只改评估不能解决真实长时跌倒。

## 决策

新增 `loaded_track_settle_task_load_horizon` 研究阶段：

1. Warm Start 锁定为 deployment-eval-v4 失败报告选出的内部 Checkpoint；
   恢复 normalizer、policy 和 value，优化器重置。
2. 使用 `discounting=0.995`、`gaeLambda=0.99`，让终止信用覆盖完整
   行走—停稳周期。
3. `terminationPenalty` 从 `25` 增加到 `100`，但不改变任何终止条件。
4. PPO 使用 `clippingEpsilon=0.2` 和目标 `desiredKl=0.01` 的
   `ADAPTIVE_KL` 学习率；初始/最大值为 `1e-5`，最小值为 `2.5e-6`。
5. 把 `entropyCost` 降到 `0.0002`，并以 `normalizeUntilCount=1` 冻结已经
   恢复的观测归一化统计，降低 Warm Start 后的策略漂移。
6. 完整 A5-CK 载荷、Stand/Capture 教师、命令分布、随机种子、训练预算、
   十项确定性行为测试和 `900/1000` 门槛保持不变。
7. Warm Start 与所有保存 Checkpoint 继续进入同一正式门排序；失败时保存最佳
   证据，但保持 `non_publishable`。
8. 本阶段最多形成内部负载步态候选，不自动启动 A5、5/5、100M 或厨房 L3。

## 边界

- 这是长时信用和优化稳定性修正，不证明随机初始化或真机鲁棒性。
- 归一化冻结只适用于观察 ABI 与当前任务分布不变的本阶段。
- 若仍失败，下一轮必须依据新报告选择任务分布专化或控制结构调整，不得通过
  降低 `900/1000` 门槛过关。
