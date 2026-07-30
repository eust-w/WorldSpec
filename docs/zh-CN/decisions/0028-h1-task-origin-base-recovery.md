---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0028-h1-task-origin-base-recovery.md
last-verified: 2026-07-30
---

# ADR-0028：H1 任务原点基座恢复

## 背景

A5-CH Job `worldspec-h1-midterm-ddkxh` 在真实 Drobodata A800 上以
`fall_height` 结束。校准后的把手已位于观测到的稳定工作空间内，但基座在右臂
开始追踪后持续向后滑移。固定世界目标令手臂继续伸展，从而放大基座偏移。

现有 Motion Policy 已通过短距行走阶段，Capture 与 Stand Policy 也已有独立
证据。当前最小改动不是新增隐藏约束或放宽门槛，而是让任务阶段复用现有腿部
策略恢复任务开始时的基座平面位置。

## 决策

采用 A5-CJ 单次门控：

1. 任务阶段首次进入时记录基座平面原点。
2. 以位置误差和局部速度构成确定性 PD 命令，分别限制前进、后退和横向速度；
   偏航命令保持为零。
3. 恢复命令范数达到 `0.05` 时进入 Motion Policy；降至 `0.02` 后复用既有
   Capture 稳定门和五步 Blend 返回 Stand。
4. 基座恢复期间冻结最近一次稳定的右臂目标和偏置力前馈，禁止继续追逐固定
   世界目标；返回 Stand 后才恢复当前任务空间解。
5. 保留 A5-CH 的场景、三份策略、种子、Controller、终止条件和全部质量门，
   不增加 mocap、weld、运动学瞬移或隐藏抓取约束。
6. 新 Profile 必须绑定 A5-CH Report、Controller 和 Trace Digest，并记录
   恢复命令、活动步数和手臂目标来源。
7. 本地契约与固定底座预检通过后，只执行一次单 GPU A800 Spike；通过最多
   产生内部 `control_candidate`，失败则先归档真实终止证据。

## 边界

- 固定底座 CPU 预检只能证明右臂跟踪，不证明基座恢复行为。
- 单次 A5-CJ 不证明物理抓取、抽屉开合、杯子放置、5/5、L3 或 100M 训练。
- A5-CH 失败证据保持不可变；A5-CJ 不能追溯性改变其结论。

## 执行结果

A5-CJ Job `worldspec-h1-midterm-dlrnk` 已在 Drobodata A800 上真实执行。
Report、Controller 和 368 行 Trace 已完整回传并通过 SHA-256 校验，但
`formalControlGate=failed`，终止原因为 `fall_height`，Controller 保持
`non_publishable`。

Trace 显示任务阶段开始时基座仍有正向残余速度；PD 速度阻尼立即产生负向
`vx`，而冻结 Motion Policy 的训练命令域为非负纵向速度。随后策略在域外
命令和手臂扰动下振荡，并在已形成明显后向速度后无法恢复。该结论只解释
本次 A5-CJ 运行，不追溯修改历史失败结论。
