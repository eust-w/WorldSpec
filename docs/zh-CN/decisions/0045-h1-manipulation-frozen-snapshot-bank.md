---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0045-h1-manipulation-frozen-snapshot-bank.md
last-verified: 2026-07-30
---

# ADR-0045：操作平衡校准复用冻结 v11 状态库

## 状态

Accepted Design。

## 背景

修复 v12 的输入阶段识别后，Job `worldspec-h1-midterm-jnj6z` 进入真实 A800
`manipulation_portfolio_training`。PPO 尚未开始，状态库生成器就报告：

```text
Frozen motion/capture teachers terminated before snapshot capture.
```

原因是 v12 同时把 v11 最佳 Checkpoint 用作训练 Warm Start 和 Capture
教师。该 Checkpoint 是在已有步行后状态上训练的操作平衡策略，不是负责从
运动策略稳定交接并生成 Capture 状态的策略；把这两个角色合并没有证据基础。

v11 已经交付一个完整状态库，包含 4096 个有限值状态、`qpos/qvel/last_action`
三个数组，`terminatedSnapshotCount=0`，并被 v11 七候选训练和十四个正式
评测共同使用。

## 决策

新增 `unbounded-recovery-frozen-bank-checkpoint-portfolio-v13`：

- 训练 Warm Start 仍为 v11 选中的 Step 4,915,200 Checkpoint；
- 无界恢复成本、50/50 训练混合、控制范围、候选数量、种子和质量门均不变；
- 不再让操作平衡 Checkpoint 冒充 Capture 教师；
- 将 v11 状态库作为第五个只读输入分块上传；
- 启动前校验来源 Job、Report Digest、Blob Digest、大小、数组集合、形状、
  有限值和 `terminatedSnapshotCount=0`；
- 将输入 Blob 原字节写入本次 Artifact，训练进程和十四个隔离评测使用同一
  Digest。

这使 v13 的步行后训练分布与 v11 完全相同，并把唯一实验变量限制在 ADR-0044
定义的无界恢复成本。

## 门控

- v13 仍必须通过步行后 `5/5`、静态 `5/5` 和冻结 Episode 门。
- v13 通过后只解锁一次完整厨房单次运行。
- 单次完整厨房通过后才解锁独立厨房 `5/5`。
- 该修复不授权新 100M 训练、自动重试、门槛放宽或 L3 声明。
