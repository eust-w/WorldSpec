---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0033-h1-deterministic-deployment-evaluation.md
last-verified: 2026-07-30
---

# ADR-0033：H1 确定性部署评估与 Warm Start 候选

## 背景

`loaded_track_settle_task_load_survival` 已在 Drobodata A800 上真实执行
17,203,200 个批对齐步骤。七个训练 Checkpoint 中，首个 Checkpoint 的五次
行走—停稳与五次负载站立测试全部通过，但平均 Episode 长度为
`672.4531 < 900`，因此正式训练门正确保持失败。

进一步核对 Brax 0.14.2 的 PPO 接口发现，`deterministic_eval` 默认值为
`false`。当前平均 Episode 长度来自带探索采样的评估策略，而十项行为测试和
实际部署使用确定性策略。一个正式门因此混用了两种策略语义。训练还只评估保存
后的 Checkpoint，没有把已经完成十项短时行为门的 Warm Start 本身作为候选，
所以训练退化时无法保留原策略。

## 决策

新增 `loaded_track_settle_task_load_deployment_eval` 研究阶段：

1. Brax Episode 评估显式使用 `deterministic_eval=true`，与行为测试及部署推理
   语义一致。
2. 平均 Episode 长度门仍为 `900/1000`；速度、漂移、姿态、终止和十项行为门
   全部不变。
3. Warm Start、每个保存后的 Checkpoint 都进入同一确定性正式门排序；打包时只
   保留排序选中的一个候选。
4. Warm Start 锁定为 survival-v3 失败报告中选出的内部 Checkpoint；该策略仍是
   `non_publishable`，不得因为本 ADR 追溯性升级。
5. 训练奖励、课程、载荷、教师、优化器参数和随机种子保持 survival-v3 不变，
   本轮只修正评估口径和候选保留策略。
6. 若确定性长程门仍失败，再以独立 ADR 调整 discount/GAE 时域；本轮不混入
   超参数变化。
7. 即使本阶段通过，也只形成内部负载步态候选；不自动启动 A5、5/5、100M 或
   厨房 L3。

## 边界

- 随机策略评估仍可作为研究指标，但不能替代确定性部署门。
- 本阶段通过不证明探索策略、真机或随机初始化鲁棒性。
- survival-v3 的历史失败报告保持不变；新结论只适用于新 Profile、代码、
  OCI 与执行证据。
