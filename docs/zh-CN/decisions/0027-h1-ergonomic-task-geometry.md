---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0027-h1-ergonomic-task-geometry.md
last-verified: 2026-07-30
---

# ADR-0027：H1 任务几何工作空间校准

## 背景

A5-CG Job `worldspec-h1-midterm-9zmdg` 在真实 Drobodata A800 上执行了
301 条 Trace，并因 `fall_height` 失败。诊断通道完整，终止时无关节越限、
非有限值、策略交接失败或容量异常。

Trace 显示 TCP 在约 `[1.8351, -0.1891, 1.1411] m` 已达到低速稳定状态；
旧自制抽屉把手却位于 `[1.87, -0.21, 1.075] m`。为继续下降约 6.6 cm，
四关节右臂 QP 持续屈肘并进入近奇异区域，基座随后向后滑移并跌落。

## 决策

采用 A5-CH 最小修正：

1. 保留三份策略、种子、Controller、终止条件和全部质量门，不放宽阈值。
2. 保留 A5-CG 的固定底座命令、固定躯干、四关节右臂 QP 和显式
   `qfrc_bias` 前馈。
3. 将自制抽屉、杯子和支撑面整体平移 `[-0.03, 0, +0.065] m`，形成
   `primitive-drawer-cup-v3-ergonomic`。
4. 把手目标随物理几何一起移动至 `[1.84, -0.21, 1.14] m`；不得只修改
   Predicate 或控制目标而不修改真实碰撞几何。
5. 新 Profile 必须绑定 A5-CG Report、Controller 和 Trace Digest，并保存
   作为生成式任务几何的 Derivation 证据。
6. 固定底座 CPU 预检通过后，只运行一次单 GPU A800 Spike；失败时继续保留
   `non_publishable`，通过时最多成为内部 `control_candidate`。

## 执行结果

A5-CH Job `worldspec-h1-midterm-ddkxh` 在真实 Drobodata A800 上执行了
287 条 Trace。校准后的物理几何、四关节动态臂和 Stand Policy 均按 Profile
启用，且无关节越限、非有限值或交接失败；但机器人仍触发 `fall_height`。

Trace 显示右臂开始追踪把手后，基座从任务原点持续向后滑移。由于把手目标固定
在世界坐标，而控制器继续伸臂追逐目标，基座后滑与手臂伸展形成正反馈。最终
基座平面位移为 `0.6912 m`，最低高度为 `0.7796 m`。因此 A5-CH 证明，把手
高度不是唯一根因；任务阶段缺少抵抗手臂扰动的基座位置恢复。

## 边界

- 这是自制生成场景的机器人工作空间校准，不是对真实厨房测量结果的修改。
- 不证明物理抓取、抽屉开合、杯子放置、5/5、L3 或 100M 训练。
- A5-CG 失败证据保持不可变；A5-CH 不能追溯性改变其结论。
