---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0044-h1-manipulation-unbounded-recovery.md
last-verified: 2026-07-30
---

# ADR-0044：操作平衡使用无界恢复成本继续校准

## 状态

Accepted Design。

## 背景

`suite-isolated-v11` 已在真实 Drobodata A800 上完成七个候选训练和
十四个隔离评测。所有候选的静态起步套件均为 `5/5`，但最佳候选的步行后
套件只有 `4/5`。冻结选择规则选中的 Step 4,915,200 候选在第 2 条步行后
轨迹的 99/100 步因 `fall_height` 终止。

失败轨迹在约前 40 步保持稳定，随后基座位置和速度误差持续增大，恢复命令
最终达到既有控制上限。现有 `baseAnchor` 和 `settleLinear` 都使用指数奖励；
当误差已经较大时，其梯度会趋近于零，不能持续区分“较差”和“更差”的恢复
状态。

仅对该固定失败状态增加采样权重会把正式评测种子泄漏进训练分布，因此不采用
固定状态过采样，也不放宽任何门槛。

## 决策

新增 `unbounded-recovery-checkpoint-portfolio-v12`：

- 从 v11 冻结选择的 Step 4,915,200 Checkpoint Warm Start；
- 恢复 normalizer、policy 和 value，优化器重新初始化；
- 保持状态库生成方法、50/50 重置分布、训练步数、候选数量、控制范围、
  评测种子和全部质量门不变；
- 保留原有指数奖励；
- 新增基座平面锚点平方误差成本，权重 `25.0`；
- 新增停稳平面速度平方误差成本，权重 `2.0`；
- 仍对七个候选执行 `post_walk_capture` 与 `from_rest` 两套独立进程评测，
  只由冻结选择规则决定是否放行。

这两个成本在大误差区仍保持非零梯度，目的是让恢复失败持续产生训练信号，而
不是改变任务定义或验收门槛。

## 结果语义

- 本 ADR 只是新的研究校准路线，不表示策略已经通过。
- v12 只有正式操作平衡门全部通过，才能解锁一次完整厨房单次运行。
- 完整厨房单次通过后，才能启动独立厨房 `5/5`。
- 本阶段不启动新的 100M 训练，也不声明 Controller Candidate 或 L3。
- 若 v12 失败，必须保存真实 A800 报告和 Checkpoint，并按新证据制定下一项
  ADR；不得自动放宽门槛或重试。

## 被否决方案

- 放宽 `fall_height`、漂移、速度或成功次数门槛；
- 只对固定失败种子对应的 Capture 状态过采样；
- 修改恢复命令范围或任务几何并把结果归因于同一策略；
- 跳过操作平衡门直接启动完整厨房或 `5/5`。

## 首次启动证据

首个 v12 Job `worldspec-h1-midterm-pnwr5` 在 `input_verification` 阶段
fail closed。四个输入文件均完成分块上传和 Digest 校验，但入口校验器尚未
登记新的 `loaded-track-settle-manipulation-suite-isolated-v11-failed`
来源阶段，因而报告 `unsupported warm-start source stage`。GPU 训练未开始，
策略结果为 `not_evaluated`。

修复只新增冻结 v11 摘要的字段校验和 Checkpoint 路径选择，不改变 v12
Profile、训练环境、奖励、种子、控制范围或质量门。由于这是训练前的配置缺陷，
修复并通过回归测试后允许用新 Probe Revision 重新启动一次。
