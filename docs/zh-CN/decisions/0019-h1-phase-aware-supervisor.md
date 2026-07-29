---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0019-h1-phase-aware-supervisor.md
last-verified: 2026-07-29
---

# ADR-0019：H1 相位感知三策略 Supervisor

## 背景

ADR-0018 的 A800 校准已得到通过门控的 Capture Policy。五次真实轨迹在零命令后的
第 174–181 个控制步形成 `线速度 ≤ 0.12 m/s`、`角速度 ≤ 0.20 rad/s` 的连续稳定
窗口，并在最后 0.2 秒保持静止。

该结果不能直接证明静态 Stand Policy 可以接管。A2 已证明，按固定时间从运动策略
直接混合到 Stand 会失败。因此下一步必须单独验证：

```text
Motion Policy → Capture Policy → Stand Policy
```

## 决策

新增 `phase_aware_supervisor_probe` 研究阶段，不进行 PPO 更新：

- 运动命令存在时只使用冻结的 transition-v2 Motion Policy；
- 零命令到来后进入冻结的 A3 Capture Policy；
- Capture 至少运行 20 个控制步，最多允许 40 个控制步；
- 只有线速度不超过 `0.12 m/s` 且角速度不超过 `0.20 rad/s` 连续满足 5 步，
  才允许进入交接；
- Capture 与 `stand-v2.1` 通过 5 个控制步线性动作混合；
- 混合结束后只使用 Stand Policy，最终必须有至少 10 个纯 Stand 控制步；
- 五次行走—停稳与五次 Stand 回归全部通过，且运行日志干净，才标记
  `supervisor_candidate`；
- 超过 Capture 上限、Stand 未激活、Stand 驻留不足或任一历史质量门失败，都
  fail closed；
- Controller、三份 Checkpoint、Trace、目标 Bundle、OCI、包锁和代码提交全部
  绑定 Digest，产物保持 `research_only / internal_only`。

## 边界

该探针只证明三份冻结策略在固定目标模型和固定 4 秒评测中的监督切换行为。它：

- 不启动或授权 100M 正式训练；
- 不证明行走—开抽屉—抓杯—放置—关抽屉任务；
- 不证明随机初始状态鲁棒性；
- 不构成厨房 L3、可公开发布策略或真机安全证据。

只有 A4 真实 A800 报告通过后，才允许讨论是否将 Supervisor 接入更长时序任务。
