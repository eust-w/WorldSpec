---
status: Pending Decision
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0023-h1-a5c-control-spike-failure.md
last-verified: 2026-07-30
---

# ADR-0023：H1 A5-C A800 控制 Spike 失败后的证据边界

## 已确认事实

2026-07-30，A5-C 在 Drobodata 的一张 NVIDIA A800-SXM4-80GB 上执行。
作业 `worldspec-h1-midterm-d5z6c` 正常完成，Pod 为 `Succeeded`，运行镜像为
`sha256:684daf...9f94c`，输入 Profile Digest 为
`sha256:84175b...787fd`。控制器和 Trace 均已回传并通过 SHA-256 校验。

结果为 `formalControlGate=failed` 和 `controllerStatus=non_publishable`：

- H1 已完成冻结的 150 步行走与 50 步 Motion→Capture→Stand 交接；
- 全身控制进入 `whole_body_settle`，执行 19 步后 `done=true`；
- TCP 误差从 `0.167584 m` 降至最低 `0.010992 m`，终止时为
  `0.026351 m`，说明 QP 能把末端带进位置容差；
- 终止时 TCP 速度仍为 `0.253163 m/s`，没有形成要求的 20 步稳定保持；
- 底座只平移 `0.033109 m`、横向漂移 `0.010167 m`，最低高度
  `0.988330 m`，最低直立余弦 `0.991174`；
- QP 最大投影梯度为 `4.08e-8`，无 NaN、容量溢出、CCD 溢出或异常接触日志。

本次 Trace 只记录了 `done=true`，没有记录环境的 `joint_limit`、
`fall_height`、`fall_upright` 和 `nonfinite` 终止子通道。因此报告中的
`logDiagnostics.clean=true` 只能说明日志扫描项为空，不能证明没有关节限位终止。
精确终止原因必须标记为 `unknown`。规范化摘要见
[`whole-body-control.a800.failed-summary.json`](../../../examples/h1-kitchen/whole-body-control.a800.failed-summary.json)。

## 边界

- CPU 固定基座预检通过不等于 A800 全身控制通过；
- 位置误差短暂进入容差不等于稳定控制通过；
- 本次没有执行把手抓取、抽屉操作、完整厨房 5/5 或 100M 训练；
- 不允许把失败 Controller 标记为候选、集成资产或 L3；
- 在选择下一条路线前，不自动改门槛、调参或消耗新的 A800 作业。

## 需要选择

### A5-CI（推荐）：仅补齐终止诊断并做一次等价重放

- 控制器矩阵、权重、门槛和输入策略保持不变；
- Trace 增加四个终止子通道、关节位置/速度、力矩饱和和活动策略；
- 构建新镜像后只重放一次控制 Spike；
- 若再次失败，按精确终止原因进入新的控制设计，不继续自动重试。

这条路线不会把未知原因误当成增益问题，是最小的信息增益步骤。

### A5-CR：直接重做全身控制契约

重新设计速度上限、目标地平线、阻尼、关节限位保护和基座/手臂优先级。该选择
会改变控制器 Profile，不能与当前失败作业做等价比较，必须重新做 CPU 门控。

### A5-S：停止 H1 厨房路线

保留 CPU 通过与 A800 失败证据，不再投入 A800；等待成熟全身操作策略、真实安装
标定或外部控制器后再恢复。
