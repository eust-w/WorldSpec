---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/decisions/0014-h1-mujoco-playground-ppo-engine.md
last-verified: 2026-07-28
---

# ADR-0014：H1 MuJoCo Playground PPO 训练引擎

## 决策

H1 目标动力学重训采用以下锁定技术栈：

- MuJoCo Playground `v0.2.0`，提交
  `124a73fa3303f75a62f8fe04d329b829ed0ebdfb`；
- MuJoCo `3.6.0` 与 MJX；
- MJX Warp 物理实现；
- Brax JAX PPO 训练器；
- `H1JoystickGaitTracking` 仅作为参考任务和超参数基线；
- `worldspec_h1_loaded_velocity_v1` 作为目标组合 Bundle 的专用适配器。

来源和关键文件 Digest 由
[`h1-training.lock.json`](../../../third_party/h1-training.lock.json) 锁定。

这里必须区分两层：

```text
Brax JAX PPO
→ 优化算法和训练循环

MJX Warp
→ 批量物理执行实现
```

两者不能合并称为“Warp PPO”。

## 适配边界

上游 H1 训练环境使用自己的训练 XML，不能直接证明 WorldSpec 锁定的
Menagerie H1 + 右手 Robotiq 组合可训练。WorldSpec 因此新增目标 Bundle 适配器：

- 不修改来源 Bundle；
- 为派生训练模型增加地面、足部 Site、接触和姿态传感器；
- 绑定目标组合 Digest、控制关节、保持姿态和夹爪命令；
- 生成 Derivation Manifest；
- 先通过真实 MuJoCo 加载，再进入 MJX/Warp 预检。

## 输出契约

Brax JAX PPO 的规范输出是 Orbax/JAX Checkpoint，不伪装成 TorchScript。训练成功结果必须
包含：

- 确定性 Orbax Checkpoint Archive；
- Policy Manifest；
- 五次标称评估 Trace；
- Environment Lock。

后续若需要 ONNX、TorchScript 或其他部署格式，应作为独立的、带验证证据的转换步骤，
不能静默改变训练产物类型。

## 当前证据状态

训练框架选择和来源锁定为 `Accepted Design`。目标运行时已为 `locked`：

- Linux x86_64 OCI 镜像已由 Digest 锁定；
- A800 上 MJX/Warp one-step 预检已通过；
- 一次 32,768 请求步、256 环境的 A800 PPO 研究级 smoke 已执行且容量零溢出；
- smoke 为 `non_publishable`，未保存 Checkpoint，也未生成可发布策略；
- 规范 1 亿步 PPO 未执行；
- 未完成目标 Bundle 五次连续评估。

因此本 ADR 只构成受限 GPU smoke 证据，不构成策略可用、正式训练或 L3 通过证据。

## 后果

- 训练路线复用官方 MuJoCo Playground 的稳定 API 和 H1 经验；
- 目标组合模型仍需独立环境适配和真实训练；
- Playground、JAX、MJX、Warp、Brax 与 CUDA 的完整版本集合必须进入运行时 Lock；
- Ampere 平台必须显式使用最高矩阵乘精度，并由预检拒绝错误配置；
- 更换框架版本、物理实现、目标 Bundle 或控制映射会使训练证据失效。
