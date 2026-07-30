---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0029-h1-forward-only-base-recovery.md
last-verified: 2026-07-30
---

# ADR-0029：H1 纵向前进域内基座恢复

## 背景

A5-CJ 的真实 A800 Trace 表明，任务阶段的 PD 速度阻尼会产生负向 `vx`，
但冻结 Motion Policy 的训练命令范围是 `vx ∈ [0, 0.6] m/s`。这使恢复器
把策略驱动到训练域外；当右臂扰动引起后滑时，负向命令没有形成稳定制动，
最终触发 `fall_height`。

## 决策

采用一次 A5-CK 门控运行：

1. 保留 A5-CJ 的场景、种子、三份冻结策略、Controller、手臂冻结逻辑、
   终止条件和所有质量门。
2. 纵向恢复命令严格限制为 `[0, 0.5] m/s`；负向位置误差或速度阻尼结果
   裁剪为零，不向 Motion Policy 发送训练域外的负向命令。
3. 横向命令仍限制在 `[-0.1, 0.1] m/s`，偏航保持为零。
4. A5-CK Profile 必须绑定 A5-CJ 的 Report、Controller 和 Trace Digest。
5. 本地 Schema、契约测试和固定底座 CPU 预检通过后，只执行一次 A800
   Spike。失败时完整归档证据，不自动重试、调参或启动后续训练。

## 边界

- 固定底座预检不能验证动态基座制动。
- A5-CK 通过最多产生内部 `control_candidate`。
- 不自动执行完整 A5、5/5、100M 训练或 L3 认证。
- 若 A5-CK 仍无法在域内命令下制动，下一步应评估任务载荷感知的下肢策略或
  重新训练，而不是继续放宽质量门。
