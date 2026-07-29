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

## 执行证据

2026-07-29，A4 在单张 NVIDIA A800-SXM4-80GB 上完成两次真实评测。第一次计算
门控通过，但 Kubernetes 流在复制 Trace 时发生 `unexpected EOF`，原编排器随后
清理 Pod，因而该次只能算“计算通过、证据包不完整”。这暴露了证据生命周期缺陷，
不是策略质量失败。

编排器随后改为 128 KiB 输出分块、每块最多 12 次重试，并在
`artifact_copied` 前发生传输错误时保留 Job、Pod 和 ConfigMap。修复通过全仓测试
后，以相同 OCI、三份冻结 Checkpoint、Profile 和固定种子重放评测。重放 Job
`worldspec-h1-midterm-bg88v` 成功完成，全部五次行走—停稳和五次 Stand 回归通过：

- 前进距离为 1.3714–1.3770 米；
- 速度跟踪 RMSE 为 0.1518–0.1521 m/s；
- Capture 使用 30–33 个控制步，随后纯 Stand 驻留 12–15 步；
- 最终线速度为 0.0626–0.0669 m/s，最终角速度为
  0.0478–0.0531 rad/s；
- 无 NaN、关节越限、CCD/容量溢出或异常接触。

Controller Digest 为
`sha256:0949f073c6f70f945638b485850e0560af4f658cacac69116bb2eba07e6d9e4a`，
完整 Trace Digest 为
`sha256:6503609c7231996f238b6dc0c97b25e8568fd3b1ae31e8141dc43ea3c24ed602`。
规范报告见
[`locomotion-supervisor.a800.passed.json`](../../../examples/h1-kitchen/locomotion-supervisor.a800.passed.json)。

两次运行的 Controller Digest 相同且两次门控均通过，但 GPU 动力学指标与 Trace
Digest 有小幅差异。因此这里证明的是固定 Profile 下的重复行为通过，不宣称跨运行
逐字节或逐帧确定性。

## 边界

该探针只证明三份冻结策略在固定目标模型和固定 4 秒评测中的监督切换行为。它：

- 不启动或授权 100M 正式训练；
- 不证明行走—开抽屉—抓杯—放置—关抽屉任务；
- 不证明随机初始状态鲁棒性；
- 不构成厨房 L3、可公开发布策略或真机安全证据。

只有 A4 真实 A800 报告通过后，才允许讨论是否将 Supervisor 接入更长时序任务。
