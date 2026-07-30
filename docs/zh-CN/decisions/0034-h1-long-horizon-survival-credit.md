---
status: Accepted
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

## 执行结果

2026-07-30，本阶段使用锁定提交
`7a2081e62c41a8e31dae796d658be2a68349a537` 和 OCI
`sha256:c5b801f45d9cfa6de2a210cb25a38ddf242639ed3aa63acb6490a274467dbf69`
在 Drobodata 单张 A800 上真实执行。报告步数为 `17,203,200`，共评估八个
候选；从 `4,915,200` 步起连续六个保存候选通过正式门。确定性排序最终选择
`12,288,000` 步 Checkpoint，其平均 Episode 长度为 `996.0078/1000`；末期
Checkpoint 仍为 `991.3672/1000`，没有复现上一轮的后期崩溃。

所选 Checkpoint 的五次行走—停稳和五次负载站立回归全部通过，行走前进
`1.1849–1.2122 m`、速度跟踪 RMSE `0.1863–0.1872 m/s`，最终测量窗口线速度
不高于 `0.0911 m/s`、角速度不高于 `0.0940 rad/s`。最低基座高度高于
`0.9882 m`，最低直立余弦高于 `0.9946`；没有 NaN、关节越限、容量溢出或
异常接触。

正式训练门因此为 `passed`，但策略仍固定为
`non_publishable / internal_only`。Checkpoint 摘要为
`sha256:d5ddb461d27366e6959c22dac928d81ab0039b55030427c80e9ab6ffb09b1943`，
Trace 摘要为
`sha256:611d6af92c827491b057cfb217705bfeed9b128aba96acddb23c88bcbfc6f87c`。
本结果只关闭任务载荷步态中期校准门，没有自动启动 100M、A5、5/5 或厨房 L3。
规范化报告见
[`locomotion-task-load-horizon.a800.passed.json`](../../../examples/h1-kitchen/locomotion-task-load-horizon.a800.passed.json)。
