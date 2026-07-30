---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0036-h1-task-load-supervisor-gate.md
last-verified: 2026-07-30
---

# ADR-0036：H1 任务载荷三策略 Supervisor 门控

## 背景

ADR-0035 的正式 100M 训练已经证明任务载荷运动策略能完成五次行走—停稳，
但该单策略在零命令站立回归中产生 `0.314–0.324 m` 漂移，不能成为独立
Policy Candidate。此前 ADR-0019 的 Motion → Capture → Stand 三策略
Supervisor 已在无任务载荷探针中通过十项确定性测试。

不能仅凭这两份分离证据推断它们组合后仍然成立。完整 A5 和厨房 5/5 会同时
引入手臂控制、接触与任务状态机，无法把失败归因到下肢策略组合，因此需要一个
只增加任务载荷的中间门。

## 决策

新增 `task_load_phase_aware_supervisor_probe`（A6-S）研究阶段：

1. 100M 终端 Checkpoint 只作为 Motion Policy 使用；
2. Capture 与 Stand Policy、速度连续稳定门、40 步 Capture 上限、5 步
   Blend 和至少 10 步 Stand Dwell 保持不变；
3. reset 注入 A5-CK 冻结右臂姿态与力前馈，载荷缩放固定为 `1.0`，不注入
   随机基座扰动；
4. 不运行 PPO，不修改任何质量门；
5. 在一张 Drobodata A800 上执行一次包含五次行走—停稳和五次站立回归的
   确定性探针；
6. 只有 `formalTaskLoadSupervisorGate=passed` 时，才允许创建一个新的
   单次完整 A5 集成 Profile；A5 单次通过后才允许厨房固定场景 5/5；
7. A6-S 失败时回传 Controller、Trace 和 Report 后停止，不自动调参、
   重试、启动 A5 或声明 L3。

A6-S 使用独立 Profile、Report Schema、结果 Marker 和 Controller 文件名，
不修改历史 A4 Profile 与 Report。

## 证据边界

- 100M 策略仍为 `non_publishable / internal_only`；
- A6-S 通过只产生 `task_load_supervisor_candidate`，不产生完整 Controller
  Candidate；
- 本 ADR 的代码与 Schema 完成不等于 A800 探针通过；
- 单次 A5 与厨房 5/5 需要新的运行证据，不能由 A6-S 结果替代。

## 后续门控

```text
A6-S task-load supervisor 10/10
  → one full A5 integration run
    → fixed-kitchen 5/5
      → L3 evidence review
```

任何阶段失败都停止在该阶段并保留准确结论。
