---
status: Accepted
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0035-h1-formal-100m-training-result.md
last-verified: 2026-07-30
---

# ADR-0035：H1 正式 100M 训练结果与站立回归失败

## 背景

ADR-0034 的长时域校准已经选择一个通过中期门的内部 Checkpoint。正式阶段
按冻结 Profile 在最终 H1 + 右手 Robotiq 负载模型上执行一亿步 PPO Warm
Start，并要求五次行走—停稳和五次零命令站立回归全部通过。

第一次正式作业 `worldspec-h1-midterm-dc4g6` 已训练到
`100,270,080` 步，但评估器在训练后同时加载全部候选 Checkpoint，触发
Warp CUDA OOM。作业使用临时卷且没有在评估前封装 Checkpoint，因此该次运行
只能证明训练主循环完成，不能提供可恢复策略，也不能进入质量判断。

实现随后改为：

1. 正式 Profile 只评估终端 Checkpoint；
2. 在行为评估前先封装全部训练 Checkpoint 和恢复清单；
3. 禁止 JAX 预占绝大部分 GPU 显存；
4. 无论质量通过与否都先交接报告、终端 Checkpoint、Trace 和日志。

修正后的提交为 `81df2ed0dc81c2f866a5c2ed2ce4fa897bd85a15`，运行镜像为
`sha256:fda98c9a9623fdd6be96bfdb551b53257d10e3950c85cff1094052546b4381d1`。

## 执行结果

第二次作业 `worldspec-h1-midterm-cdbm5` 在 Drobodata 单张
NVIDIA A800-SXM4-80GB 上完成：

- 最大训练步数：`100,270,080`；
- 末期平均 Episode 长度：`996.4844/1000`，通过 `900/1000` 门；
- 五次行走—停稳：`5/5` 通过；
- 五次零命令站立回归：`0/5` 通过；
- NaN、关节越限、接触容量溢出和异常接触诊断：均为零。

行走—停稳前进距离为 `1.0536–1.0843 m`，速度跟踪 RMSE 为
`0.2200–0.2227 m/s`，最后 `0.2 s` 的线速度和角速度均在门槛内。

零命令站立的平面漂移为 `0.3140–0.3239 m`，超过冻结上限
`0.20 m`。其余高度、直立、末端速度和数值稳定性指标通过，因此本轮根因明确
为站立位置保持失败，而不是跌倒、数值异常或产物交接失败。

终端 Checkpoint、Trace、报告和日志均已回传并校验 SHA-256。脱敏摘要见
[`locomotion-task-load-formal.a800.failed-summary.json`](../../../examples/h1-kitchen/locomotion-task-load-formal.a800.failed-summary.json)。

## 决策

1. 正式训练门固定为 `failed`，策略固定为
   `non_publishable / internal_only`。
2. 不放宽 `0.20 m` 站立漂移门，不把 `5/5` 行走结果升级为完整策略候选。
3. 本轮确认“100M 训练执行完成”和“Checkpoint 可恢复”，但不确认
   Controller Candidate、完整厨房任务、5/5 端到端或 L3。
4. Schema 同时接受历史 `deterministic_gate_rank_v1` 和正式
   `terminal_gate_v1` 报告；该兼容修复不改变任何历史质量结论。
5. 按冻结计划，质量失败后禁止自动调参和自动重试。下一次 GPU 运行必须由新
   ADR 明确选择控制结构或训练目标。

## 待决策

后续只能选择一种新路线，不能沿用本轮 Profile 盲目重跑：

- 将终端 100M Checkpoint 仅作为运动策略，接入已验证的
  Motion → Capture → Stand Supervisor；
- 继续单策略 PPO，但增加显式零命令位移保持状态/奖励与新的小规模门控校准；
- 停止 H1 L3 路线，先完成 WorldSpec 其他 v0.1 闭环。

以上任一路线都不得追溯性地把本轮失败策略标记为可发布。
