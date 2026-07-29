---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0022-h1-a5r-dynamic-control-failure.md
last-verified: 2026-07-30
---

# ADR-0022：H1 A5-R 动态控制失败后的边界选择

## 已确认事实

2026-07-30，A5-R 在一张 NVIDIA A800-SXM4-80GB 上完成真实单次门控。
Profile 提交为 `8a17027`，运行镜像为 `sha256:da616c...def3`，镜像源提交为
`f8e0bdc`。结果为 `formalTaskGate=failed`，其余四次没有执行，也没有启动 100M。

A5-R 已经消除了 A5 首次运行中的三个基准问题：

- 实际站稳状态上的 10/10 IK 目标预检通过，最大残差为 `0.013819 m`，最小关节
  限位余量为 `0.307619 rad`；
- 杯子全程保持在支撑面上，Trace 中最低高度为 `1.193794 m`，最终高度为
  `1.193856 m`；
- `capacityOverflowCount=0`，不再出现 broadphase/CCD 容量溢出。

H1 仍然完成 1.4032 米行走，最低基座高度为 0.9883 米，最低直立余弦为
0.9937；没有提前终止、NaN、关节越限或异常接触。

剩余失败属于动态操作控制：

- `stand_ready` 的 25 步结束时，实际 TCP 目标误差仍为 `0.121290 m`；
- `reach_handle` 的 100 步中，实际误差从 `0.174114 m` 最低降到
  `0.096223 m`，最终回升到 `0.146487 m`；
- 同期 TCP 高度从 `1.043681 m` 降至 `0.946329 m`，而把手目标高度为
  `1.075 m`；
- IK 预检和每步虚拟求解均表明目标运动学可达，但四关节 PD/阻抗执行没有跟踪
  求出的关节目标。因此继续加超时不会解决当前问题。

规范化报告见
[`kitchen-task.a5r.a800.failed.json`](../../../examples/h1-kitchen/kitchen-task.a5r.a800.failed.json)。
完整内部 Trace Digest 为 `sha256:f9680841...e907a`。

## 备选路线

### A5-CG（推荐）：加入模型重力补偿和动态跟踪门

- 仍只控制既有四个右臂关节，不允许底座微调或隐藏抓取；
- 基于 MuJoCo 逆动力学或规范化偏置力加入右臂重力补偿；
- 对控制力矩、误差和关节速度增加 Trace 通道；
- `stand_ready` 不再只按时间放行，必须实际达到目标误差和速度门；
- 先在 CPU 固定基座与 A800 MJX 上做单关节/末端跟踪 Spike，只有 Spike 通过
  才重新运行 A5。

这条路线针对已经证实的动态跟踪缺口，扩展最小，不把腿部和全身控制一起引入。

### A5-C：升级为全身任务空间 MPC/QP

允许站稳后的底座、躯干和右臂共同调整，使用任务空间 MPC/QP 或全身控制完成
操作。这更接近最终全身操作，但会显著扩大控制、碰撞、安全和验证范围。

### A5-S：在这里停止

保留 A5-R 为 `non_publishable` 研究证据，停止 A800 消耗。等有经验证的操作
控制器、真实安装位姿或外部任务策略后再恢复。

## 决策

用户于 2026-07-30 选择 **A5-C**。实施采用分层全身任务空间控制，而不是把
腿部直接交给一个新的未验证控制器：

- 冻结 A4 的 Motion、Capture、Stand 腿部策略和 Supervisor；
- QP 决策变量仅包含底座平面速度、底座偏航速度、躯干和四个右臂关节速度；
- 使用规范 MuJoCo `qfrc_bias` 作为显式、可追踪的逆动力学前馈，PD 仍提供局部
  反馈；禁止隐藏约束、mocap 牵引和运动学瞬移；
- 首个 `whole_body_task_space_control_spike` 仅认证“行走、站稳、跟踪抽屉把手”，
  不认证抓取、完整厨房任务或 L3；
- CPU 固定基座预检和真实 A800 MJX Spike 必须先通过，之后才能重新运行 A5；
- Spike 失败即保存报告并停止，不自动调参，不继续 5/5，不启动 100M。

该选择扩大了控制范围，但证据与声明范围保持收缩：通过 Spike 只能得到
`control_candidate`，不能得到 `integration_candidate` 或 L3。
