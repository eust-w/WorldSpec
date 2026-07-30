---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0041-h1-manipulation-checkpoint-portfolio.md
last-verified: 2026-07-30
---

# ADR-0041：H1 操作平衡 Checkpoint 组合门控

## 背景

on-policy-continuation-v5 已在 Drobodata A800 作业
`worldspec-h1-midterm-hftjt` 中完成。最终平均 Episode 长度为
`97.453125/100`，静态起步为 `5/5`，但步行后初态只有 `3/5`，所以正式门
失败，Checkpoint 继续保持 `non_publishable / internal_only`。

该作业回传的 Checkpoint 归档实际包含七个训练阶段：

```text
2,457,600
4,915,200
7,372,800
9,830,400
12,288,000
14,745,600
17,203,200
```

现有实现只对终端 `17,203,200` 阶段执行十项确定性行为门。训练期间可能存在
早期阶段满足全部门、终端阶段发生退化的情况；仅评估终端阶段不足以完成已经
保存的候选证据审计。

## 决策

新增 checkpoint-portfolio-v6：

1. 保持 v5 的 Warm Start、Motion/Capture 策略、状态库生成、50/50 重置、
   PPO 超参数、随机种子、观察/动作 ABI 和全部质量门不变；
2. 对同一次训练保存的七个数字 Checkpoint，使用同一个 4096 状态库、同一
   纯步行后评测环境和同一静态评测环境分别运行十项确定性门；
3. 候选排序首先要求正式门通过，再比较通过测试数、平均 Episode 长度，最后
   选择更早的训练步数；没有候选通过时不得升级证据；
4. 导出的 `midterm-checkpoint.zip` 只包含被选中的数字阶段，Report 同时保存
   七个候选的门控摘要；
5. 当前归档不能在既有双 Checkpoint 输入协议下独立重放而不新增未冻结输入，
   因此用一次集成评估的 A800 重跑生成同运行、同状态库的完整候选证据；
6. 只有选中候选十项全过且平均 Episode 门通过，才允许把它作为独立
   Manipulation Policy 集成到一次完整厨房任务；单次通过后才允许独立 5/5。

## 证据边界

- 本决策不是降低门槛，也不改变训练分布或超参数；
- 候选排序不能把 `9/10` 或平均 Episode 未达标的阶段标记为通过；
- v5 的 Report、Checkpoint、Trace 和状态库继续作为失败证据保存；
- v6 通过只产生内部操作平衡候选，不等于完整厨房、5/5 或 L3；
- 若七个阶段均失败，本路线停止在校准阶段，不自动调参或启动厨房任务。
