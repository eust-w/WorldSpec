---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0017-h1-dual-policy-supervisor.md
last-verified: 2026-07-29
---

# ADR-0017：H1 行走与站立双策略 Supervisor

## 背景

ADR-0015 的过渡策略改善了部分制动指标，但丢失了独立站立能力；ADR-0016 的 A1
通过站立回放和教师动作蒸馏恢复了 5/5 站立，却再次恶化行走后停稳。两次真实 A800
结果说明，在当前预算和网络结构下继续要求单一策略同时承担运动、制动和静止保持，
已经产生明显的能力干扰。

## 决策

选择 A2，把运动策略与零速度/站立策略保持为两个不可变策略，并增加显式 Supervisor：

- 运动阶段使用 ADR-0015 的失败过渡 Checkpoint；选择它是因为它是现有证据中制动
  表现最好的运动候选，不代表该策略本身已通过；
- 零速度与站立阶段使用通过的 `stand-v2.1` Checkpoint；
- 行走测试前 150 个控制步使用运动策略；
- 第 150 步收到零速度命令后，在 5 个控制步（0.1 秒）内将动作从运动策略线性混合到
  站立策略；混合期间两个策略都读取零命令观察；
- 第 155 步起只使用站立策略；
- 站立回归从第 0 步起只使用站立策略；
- 本轮是零训练、单候选探针，不修改任何 Checkpoint，不自动调参或重试；
- 保持 CCD=50 和原十项行为门槛不变；
- 报告、控制器 Manifest 和 Trace 均为 `research_only / internal_only`；
- 即使探针通过，也只获得内部复合控制器候选，不自动启动 100M 训练，也不构成厨房
  L3 证据。

## 证据边界

Profile、Schema、Supervisor 和作业链路在真实 A800 执行前属于实现基线。只有绑定两份
Checkpoint Digest、目标 Bundle、OCI Digest、包锁和代码提交的真实报告，才能证明：

- 两个网络 ABI 均与最终 H1 + 右手 Robotiq 环境兼容；
- 规定的动作混合确实在 MJX 运行；
- 五次行走—停稳和五次站立回归是否全部通过；
- 无 NaN、关节越限、容量溢出或异常接触。

失败必须保存报告和 Trace，并停止后续训练。

## 后果

- H1 运行时从单一 policy 变为 policy set + deterministic supervisor；
- Controller Artifact 必须绑定两份 Checkpoint 的 Digest 和选中步；
- Trace 必须记录 `activePolicy`、`blendAlpha` 与 `actionJumpNorm`；
- A1 不被删除或重写，作为“统一策略发生能力干扰”的失败证据保留；
- 若 A2 失败，下一步必须基于报告重新决策，不能静默放宽门槛。
