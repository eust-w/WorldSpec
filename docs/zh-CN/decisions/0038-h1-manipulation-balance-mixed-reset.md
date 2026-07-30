---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0038-h1-manipulation-balance-mixed-reset.md
last-verified: 2026-07-30
---

# ADR-0038：H1 操作平衡混合重置校准

## 背景

A6-K1 单次完整厨房仍在 `reach_handle` 阶段失败，因此不能直接启动完整
厨房重跑或 5/5。首轮操作平衡校准 `worldspec-h1-midterm-w2f8x` 的十项
确定性测试全部失败；加入锚点恢复命令后的
`worldspec-h1-midterm-dxbgm` 将步行后测试提高到 4/5，但五次静态起步测试
仍全部失败，最终平均 Episode 长度为 `88.0078125/100`。

dxbgm 的五次静态起步结果高度一致：最大位移约 `0.1942 m`，已进入
`0.20 m` 位移门，但终端线速度约 `0.5424 m/s`，超过 `0.20 m/s`。代码和
Profile 审计确认，训练环境在存在状态库时 100% 从步行后 Capture Snapshot
重置；正式确定性门却有 5/10 从静态起步重置。这是可观测的训练/验收分布
缺口，而不是质量门过严。

## 决策

新增 mixed-reset-v3 校准：

1. 训练重置固定为 50% 步行后 Capture Snapshot、50% 静态起步，与十项门的
   两类测试等权；
2. 保持 42 维观察、10 维下肢动作 ABI、右臂轨迹、锚点恢复命令、训练步数、
   Episode 长度、随机种子和全部质量门不变；
3. `state/from_rest_reset` 进入训练指标，用真实进度报告证明混合采样生效；
4. Profile 必须绑定 dxbgm 的 Report、Checkpoint、Trace 和状态库摘要；
5. 只运行一次 Drobodata A800 校准。失败时产物先回传并保持
   `non_publishable`；通过时才允许启动 ADR-0037 的单次完整厨房；
6. 单次完整厨房通过后才允许独立 5/5。mixed-reset 通过本身不等于厨房 L3。

## 证据边界

- 50/50 是与当前确定性测试结构对齐的研究分布，不是通用步态结论；
- 本次不放宽位移、速度、姿态、基座高度或 Episode 长度门；
- v2 的失败 Checkpoint 仅作为证据归档，不作为 v3 Warm Start；
- Schema、本地测试或镜像构建均不能替代真实 A800 行为结果。
