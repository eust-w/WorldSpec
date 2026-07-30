---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0039-h1-manipulation-post-walk-biased-reset.md
last-verified: 2026-07-30
---

# ADR-0039：H1 操作平衡步行后偏置重置

## 背景

mixed-reset-v3 在 Drobodata A800 作业 `worldspec-h1-midterm-hl78d` 中把最终
平均 Episode 长度从 `88.0078125` 提高到 `94.359375`，并把五次静态起步
测试从 `0/5` 提高到 `5/5`。正式门仍失败，因为第五个步行后初态的最大位移
为 `0.3307465 m`、终端线速度为 `0.9128384 m/s`。

训练指标 `eval/episode_state/from_rest_reset=50.0` 证明 50/50 混合确实生效。
审计同时发现，名义上的 `post_walk_capture` 评测环境继承了训练混合概率，
导致五个种子中两个实际从静态状态重置。评测套件因此没有真实覆盖五个步行后
快照，必须先修正，不能用混入的静态通过结果抵扣步行后失败。

## 决策

新增 post-walk-biased-v4 校准：

1. 训练重置改为 75% 步行后快照、25% 静态起步；静态回归仍保留，但训练预算
   偏向当前唯一残余失败分布；
2. `post_walk_capture` 评测强制 `fromRestProbability=0`，五次均必须来自状态库；
3. `from_rest` 评测继续使用无状态库的确定性静态环境；
4. 42 维观察、10 维动作 ABI、右臂轨迹、锚点恢复、训练步数、Episode 长度、
   随机种子和全部质量门保持不变；
5. 仍从已通过来源约束的 Capture Checkpoint 初始化，不把 v3 失败 Checkpoint
   升级成已验证 Warm Start；
6. 只运行一次 A800 校准。门通过后才允许单次完整厨房；单次厨房通过后才允许
   独立 5/5。

## 证据边界

- 75/25 是针对当前失败分布的研究性权重，不是通用步态结论；
- v3 Checkpoint、Trace 和状态库仅作为失败证据绑定，不公开分发；
- 不放宽 `0.20 m` 位移、`0.20 m/s` 终端线速度或任何其他行为门；
- 修正评测分布可能暴露更多失败，这是提高门禁真实性而非回归。
