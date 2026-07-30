---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0046-h1-manipulation-hard-negative-replay.md
last-verified: 2026-07-30
---

# ADR-0046：操作平衡固定困难状态重放

## 状态

Accepted Design。

## 背景

修正后的 v13 Job `worldspec-h1-midterm-vgtfz` 在真实 Drobodata A800 上完成
16,777,216 步训练、七个 Checkpoint 和 14/14 隔离套件评测。所有候选均通过
静态起步 `5/5`，但步行后均为 `4/5`；Step 4,915,200 仍是选中候选。

失败始终发生在 `post_walk_capture` 第 2 次固定评测。该轨迹完成 100 步，
没有提前终止或非有限值，但超过平移、横向漂移、姿态、高度和终端速度门。
按冻结的 JAX 重置算法重新计算后，该评测对应 4096 状态库中的索引 `565`。

v13 训练使用 50% 静态起步和 50% 均匀状态库。单个索引每轮被采样的期望环境
数只有 `4096 × 0.5 / 4096 = 0.5`。七个候选都在同一状态失败，说明当前主要
问题是已知困难状态暴露不足，而不是继续增加同分布训练或放宽质量门。

## 决策

新增 `hard-negative-replay-frozen-bank-checkpoint-portfolio-v14`：

- 从 v13 Step 4,915,200 Checkpoint Warm Start，继续恢复 normalizer、policy
  和 value，优化器重新初始化；
- 训练重置分布固定为 50% 静态、25% 索引 `565`、25% 均匀冻结状态库；
- 冻结状态库 Blob、动态右臂轨迹、无界恢复成本、训练步数、候选数量、随机
  种子、动作范围和全部质量门不变；
- Profile 必须绑定 v13 Report、Trace、Checkpoint 和困难状态推导证据；
- Report 必须显式记录 `snapshotCurriculum`，不得只依赖有效 Profile Digest；
- `post_walk_capture` 正式评测强制将困难状态概率设为 0、均匀状态库概率设为
  1，保持原五个固定种子和状态映射；
- `from_rest` 正式评测继续不加载状态库。

这是一项训练分布修正，不是质量门修正。困难状态的高频重放只影响优化期间的
采样，不能改变正式评测试题。

## 门控

- v14 仍必须通过步行后 `5/5`、静态 `5/5` 和冻结 Episode 长度门；
- 任一门失败，策略保持 `non_publishable`，停止并归档；
- v14 通过后只解锁一次完整厨房单次运行；
- 完整厨房单次通过后才解锁独立厨房 `5/5`；
- 本决策不授权 100M 训练、自动重试、门槛放宽或 L3 声明。
