---
status: Accepted
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0047-h1-hard-negative-replay-result.md
last-verified: 2026-07-30
---

# ADR-0047：操作平衡困难状态重放结果

## 状态

Accepted。

## 背景

`hard-negative-replay-frozen-bank-checkpoint-portfolio-v14` 已由 Job
`worldspec-h1-midterm-2pn45` 在真实 Drobodata A800 上执行。运行使用已锁定
镜像 `sha256:7d445d05…2a73d`，完成 16,777,216 步训练、保存七个
Checkpoint，并在彼此隔离的 CUDA 进程中完成 14/14 份正式套件评测。

训练重置严格采用：

- 50% 静态起步；
- 25% 固定困难状态库索引 `565`；
- 25% 均匀冻结状态库。

正式评测仍使用 v13 的五个固定种子、原均匀状态映射和不变质量门。

## 结果

运行链路和四份主要产物交接全部完成，Report、Checkpoint、Trace 和状态库均
通过本地 SHA-256 校验。七个候选全部得到相同分类结果：

```text
post_walk_capture: 4/5
from_rest:         5/5
overall:           9/10
```

按冻结的候选选择规则，Step `7,372,800` 因平均 Episode 长度 `99.5/100`
被选中，但其正式操作平衡门仍为 `failed`。固定第 2 条步行后测试完成全部
100 步、没有提前终止或非有限值，但仍出现：

```text
minimum base height:          0.7160
minimum upright cosine:       0.7536
maximum base translation:     0.8543 m
maximum lateral drift:        0.5396 m
maximum terminal linear speed: 2.8208 m/s
maximum terminal angular speed: 2.1256 rad/s
```

相较 v13 选中候选，上述六项指标均有改善，但没有改变正式门结果。该证据只
证明“以 25% 概率高频重放单一状态”不足以满足现有门槛；它不能单独证明该
状态不可恢复，也不能确定失败来自可行域、观察别名、控制能力或奖励设计。

## 决策

- v14 策略保持 `non_publishable`；
- 不启动完整厨房单次；
- 不启动独立厨房 `5/5`；
- 不启动 100M 训练；
- 不放宽任何质量门；
- 不自动调参或自动重试；
- 下一轮必须新建控制设计 ADR，并显式选择新的实验变量和可证伪假设。

可接受的下一轮研究方向至少包括：

1. 先做可行域/可恢复性诊断，判断状态 `565` 在现有动作范围和控制器下是否
   存在成功 Witness；
2. 引入显式恢复 Supervisor 或恢复阶段，而不是要求单一操作策略直接吸收
   该动态状态；
3. 修改观察或状态表示前，先证明现有观察是否存在别名。

本 ADR 不选择上述路线中的任何一个，避免把失败证据误写成根因结论。

## 证据

- Report：`sha256:1757154e…381ac`
- Checkpoint：`sha256:b40d6287…b7fae`
- Trace：`sha256:2b29a5be…782b0`
- 状态库：`sha256:d4090fe9…8cec0`
- 脱敏摘要：
  `examples/h1-kitchen/locomotion-manipulation-hard-negative-replay.a800.quality-failed-summary.json`
