---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0013-h1-target-dynamics-retraining.md
last-verified: 2026-07-28
---

# ADR-0013：H1 目标动力学重训路线

## 决策

用户选择 `A + R`：

- `A`：为锁定的 Menagerie H1 与选定夹爪适配或重训步态，不构造混合 H1，也不在
  行走和操作阶段切换模型；
- `R`：首个 L3 案例只使用右手单 Robotiq 2F-85。

步态训练必须以
[`composition-profile.json`](../../../examples/h1-kitchen/composition-profile.json)
选择的组合 Bundle 为目标动力学。已锁定的 Unitree RL Gym 策略只保留为接口参考、
初始化或蒸馏候选；其在目标模型上的失败行为禁止作为可用 Teacher 真值或成功证据。

参考训练路线为 MuJoCo/MJX 上的 PPO，分四个门控阶段：

```text
Stand
→ Velocity Tracking
→ Loaded Velocity Tracking（右手 Robotiq）
→ Stop and Settle（进入操作姿态）
```

具体训练引擎、来源版本、适配边界和原生产物类型由
[ADR-0014](0014-h1-mujoco-playground-ppo-engine.md) 锁定。

标称模型尚未通过前关闭 Domain Randomization。策略发布至少需要绑定目标 Bundle、
CompositionProfile、Source Lock、OCI Digest、Python Package Lock、训练结果和评估
Trace。训练 Worker 必须 fail-closed；缺少锁定运行时、GPU、原生加载证据或输出契约
时不得生成成功结果。

## 已实现的边界

- `train` Job 操作和 CLI 入口；
- 版本化 LocomotionTrainingProfile 与 TrainingResult Schema；
- 目标 Bundle、右手单夹爪、原生加载报告、OCI 与 Package Lock 的绑定门禁；
- 外部锁定训练包 `worldspec_h1_training` 的明确输出契约；
- 规范训练仍为 `blocked / not_executed`，并另存不可发布的研究级 PPO smoke 结果。

Digest 锁定 OCI 与一次 32,768 请求步、256 环境的 PPO smoke 已真实运行并通过
数值与容量门禁，但都绑定容量语义修订前的 Profile。smoke 明确为
`research_smoke / non_publishable`，没有 Checkpoint，也不表示产生了可用新策略。
容量语义修订后的新 Digest 锁定镜像已由提交 `101aff7` 构建，当前 Profile 的
A800 one-step 与 8,192 环境规模预检均已通过；新 smoke、规范 1 亿步训练与五次
连续评估仍是验收阻塞项。

## 后果

- 保留 H1 从行走到操作的连续全身物理语义；
- 训练成本高于混合模型或运动学移动；
- Menagerie 与 MJX 的兼容性、训练超参数和 GPU 成本必须用真实 Spike 决定；
- 任何后续更换夹爪、安装变换或目标 Bundle Digest 都使原训练证据失效。
