---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0025-h1-task-policy-handoff-fix.md
last-verified: 2026-07-30
---

# ADR-0025：H1 任务阶段腿部策略安全交接

## 背景

A5-CI Attempt-05 的正式诊断门通过，但控制门因 `right_hip_yaw`
关节限位失败。225 条 Trace 显示，这不是缓慢漂移：在
`whole_body_settle` 中，QP 底座命令范数从阈值 `0.01` 上方下降到下方，
腿部控制在一个控制周期内从 Motion Policy 直接切换到 Stand Policy。
`right_hip_yaw` 控制量由约 `+4 Nm` 跳到 `-20 Nm`，随后速度达到约
`+10/-15 rad/s` 并在数次振荡后越过原始 `[-0.43, 0.43] rad` 范围。

四次 A800 诊断重放均在同一阶段、同一策略切换后终止于同一关节。旧 A5-C
和 A5-CI 证据保持不可变；本 ADR 只决定新的 A5-CF 控制变体。

## 决策

1. 保留 A5-C 的 QP、场景、三份策略、种子、MJX 容量、关节范围、终止条件和
   质量门，不通过放宽门槛、修改关节范围或隐藏约束来消除失败。
2. 在任务阶段增加独立的腿部策略 Supervisor：
   - 初始状态为 Stand；
   - 命令范数达到 `0.05` 才从 Stand 进入 Motion；
   - Motion 中命令降至 `0.02` 才进入 Capture；
   - Capture 复用 A4 已验证的连续速度稳定门，最多 40 步；
   - Capture 到 Stand 复用 5 步线性动作混合；
   - Capture/Blend 期间命令重新达到 `0.05` 时允许回到 Motion。
3. 采用迟滞区间，避免 QP 的微小底座修正让腿部策略在一个阈值附近抖动。
   Capture、Blend、Stand 的策略观察命令固定为零；原 QP 请求仍完整记录。
4. 新 Profile 必须绑定 A5-CI Attempt-05 的 Profile、Report、Trace 和摘要
   Digest；缺少交接契约或诊断血缘时 fail closed。
5. 先通过 Schema、状态机、历史 A5-C 回归和本地 CPU/MJX 预检；之后只允许
   一次单 GPU A5-CF Spike。失败即回传 Report、Controller 和 Trace 后停止，
   不自动调参。

## 放行边界

- A5-CF 通过只产生 `control_candidate`，不证明完整抽屉任务、5/5 或 L3；
- 本阶段不启动 100M PPO；
- 历史 A5-C/A5-CI 重放不自动启用新 Supervisor；
- 若 A800 仍失败，下一步必须基于新的终止证据另立决策，不能静默扩大修复。
