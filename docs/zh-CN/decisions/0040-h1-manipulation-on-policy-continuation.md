---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0040-h1-manipulation-on-policy-continuation.md
last-verified: 2026-07-30
---

# ADR-0040：H1 操作平衡同策略状态库续训

## 背景

post-walk-biased-v4 已在 Drobodata A800 作业
`worldspec-h1-midterm-rf9zh` 中按修正后的纯分布完成评测。静态起步保持
`5/5`，但步行后初态只有 `3/5` 通过；最差初态的最大基座位移为
`0.9506179 m`、终端线速度为 `3.5268508 m/s`。最终平均 Episode 长度也从
mixed-reset-v3 的 `94.359375` 降到 `91.828125`。75% 步行后重置没有修复
残余失败，反而扩大了最差初态的失稳。

失败初态的 held 关节速度没有形成异常值，因此“状态库速度不一致”没有证据
支持。另一个更直接的分布差异是：v3/v4 都从早期 Capture Policy 生成步行后
状态库，再用新的操作平衡策略学习；状态库的收敛段并不是由待续训策略自身
产生。

## 决策

新增 on-policy-continuation-v5 校准：

1. 从 mixed-reset-v3 的内部失败 Checkpoint Warm Start，恢复 normalizer、
   policy 和 value，优化器重新初始化；
2. Motion 段仍使用冻结的正式 100M 任务载荷 Motion Policy；
3. Capture/停稳段改用同一个 v3 操作平衡策略生成 4096 个状态，形成与续训
   初始策略一致的状态库；
4. 训练重置恢复到 v3 的 50% 步行后状态、50% 静态起步，不延续已回归的
   75/25 偏置；
5. 步行后评测继续强制 `fromRestProbability=0`，静态评测继续使用无状态库
   环境；
6. 42 维观察、10 维动作、右臂轨迹、锚点恢复、训练步数、Episode 长度、
   随机种子和全部质量门保持不变；
7. 只运行一次 A800 校准。十项门全部通过后才允许集成独立 Manipulation
   Policy 并运行一次完整厨房；单次完整厨房通过后才允许独立 5/5。

## 证据边界

- v3 Checkpoint 是 `non_publishable / internal_only` 的失败证据，用作 Warm
  Start 不会升级其证据或授权等级；
- “on-policy”仅指状态库 Capture 段与续训初始策略相同，不代表 PPO 训练期间
  状态库持续在线刷新；
- v4 Checkpoint、Trace 和状态库继续保留为失败证据，不作为 v5 初始化；
- 不放宽任何位移、速度、姿态、Episode 或厨房行为门；
- v5 通过只产生操作平衡候选，不等于完整厨房或 L3。
