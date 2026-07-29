---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0018-h1-motion-state-capture-policy.md
last-verified: 2026-07-29
---

# ADR-0018：H1 运动状态 Capture Policy

## 背景

ADR-0017 的真实 A800 结果证明，静态站立策略不能通过五步动作插值直接接管运动中的
步态状态。失败发生在状态分布和步态相位，而不是 Checkpoint ABI、模型绑定或运行时
容量。

同时，旧评测把零命令后的整个一秒都称为“停稳窗口”，并从第一控制步开始取最大速度。
该定义把制动前的运动速度也计入静止保持指标，无法区分“能否在一秒内停下”和“停下后
能否保持”。A2 在最后一步仍超限，因此历史失败结论不受这个定义问题影响。

## 决策

新增独立的 `loaded_track_settle_capture` 研究阶段：

- 冻结 ADR-0017 使用的 motion policy，只作为只读运动教师；
- 由 motion policy 在最终 H1 + 右手 Robotiq 模型中真实 rollout，生成 4096 个交接
  状态；
- 交接步从 140–159 均匀采样，命令范围为 `vx 0.4–0.6 m/s`、
  `vy -0.05–0.05 m/s`、`yaw -0.1–0.1 rad/s`；
- capture policy 从通过的 `stand-v2.1` 恢复 normalizer、policy 和 value，优化器
  重新初始化；
- 每个训练 Episode 从交接状态开始，只接收零速度命令，训练 100 个控制步；
- 使用 8,388,608 PPO 步、4096 环境，不启用 Domain Randomization；
- 快照库、Checkpoint 和 Trace 均为 `research_only / internal_only`；
- 训练失败时仍回传全部证据，不自动调参、不创建 100M Job。

## 评测语义修正

保持行走三秒、零命令一秒和原阈值不变，但将时间语义拆开：

- `settleWindowSeconds=1.0`：允许 capture policy 完成制动的总时间；
- `settleMeasurementWindowSeconds=0.2`：最后 0.2 秒的静止保持测量段；
- 测量段内最大线速度必须不超过 `0.20 m/s`；
- 测量段内最大角速度必须不超过 `0.40 rad/s`。

这不是放宽速度阈值，而是避免把制动初始状态错误地当作已停稳状态。A1、A2 报告保持
原样，不回写或重新解释。

## 放行边界

正式 Capture Candidate 必须同时满足：

- 五次 motion → capture 测试全部通过；
- 五次 capture-from-rest 站立回归全部通过；
- 平均训练 Episode 长度至少为 90/100；
- 无 NaN、关节越限、CCD/容量溢出或异常接触；
- Snapshot Bank、两份源 Checkpoint、目标 Bundle、OCI、包锁和代码提交全部绑定
  Digest。

即使通过，也只证明 motion-to-zero capture policy 候选。之后仍需单独验证
motion → capture → stand 的相位感知 Supervisor；不构成厨房 L3，也不自动触发
100M 正式训练。

## 真实执行记录

首次 A800 作业 `worldspec-h1-midterm-n7ck6` 在 PPO 前生成快照时失败。实现错误把
MJX State 内按容量分配的 65,536 行数组与 4,096 个环境的选择掩码共同做
`tree_map`，触发广播维度错误。该结果固定为
`implementation_failure_before_training`，不包含策略质量证据。修复只选择每环境
的 `qpos`、`qvel` 与 `last_action`，没有修改训练超参数或质量门槛。

纠正后的作业 `worldspec-h1-midterm-rmnnr` 在单张
NVIDIA A800-SXM4-80GB 上完成。它生成并校验了 4,096 个真实运动交接快照，在
8,601,600 个报告步后达到 100/100 的最终平均 Episode 长度，并通过五次
motion-to-capture 与五次 capture-from-rest 测试。五次行走测试的前进距离为
1.3686–1.3729 米，移动阶段速度 RMSE 为 0.1516–0.1519 m/s；最后 0.2 秒的最大
线速度为 0.0535–0.0637 m/s，最大角速度为 0.0623–0.0736 rad/s。运行中没有
NaN、关节越限、CCD/容量溢出或异常接触。

规范报告见
[`locomotion-capture.a800.passed.json`](../../../examples/h1-kitchen/locomotion-capture.a800.passed.json)。
Checkpoint、Snapshot Bank 与 Trace 分别绑定
`sha256:7f8c45e7…5cfbe`、`sha256:11a93ac2…9870` 和
`sha256:7ad8ca4d…4734`，并保持 `research_only / internal_only`。本次结果只将
策略标记为 `capture_candidate`；没有启动 100M 正式训练，也没有形成厨房 L3
证据。
