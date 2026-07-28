---
status: Research
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/research/h1-locomotion-policy.md
last-verified: 2026-07-28
---

# H1 步态策略动力学域不匹配

## 已执行实验

锁定的 Unitree RL Gym H1 TorchScript 策略通过显式 Adapter 绑定到十个腿部
Joint/Actuator。组合模型的躯干和八个手臂关节由独立 PD Hold 控制，Robotiq 保持打开。
测试环境为 macOS arm64、MuJoCo 3.6.0、Torch 2.12.0，命令为向前 `0.5 m/s`，
仿真 4 秒。

接口层通过：

```text
policy input: 41
policy output: 10, finite
leg mapping: 10
upper-body hold mapping: 9
gripper mapping: 1
```

行为层失败：

```text
final x: -2.224 m
minimum pelvis z: 0.103 m
minimum upright cosine: -0.162
joint-limit violation samples: 1274
```

失败报告为
[`locomotion-conformance.darwin-arm64.failed.json`](../../../examples/h1-kitchen/locomotion-conformance.darwin-arm64.failed.json)。

使用相同观察构造、PD 参数、更新频率和策略，在 Unitree RL Gym 自带原始 H1 模型上
执行同样 4 秒对照，结果为：

```text
forward displacement: 1.437 m
lateral drift: 0.017 m
minimum pelvis z: 0.990 m
minimum upright cosine: 0.999
```

因此目前证据指向**策略训练动力学域与 Menagerie 铰接全身模型不匹配**，而不是
TorchScript 输入输出或十腿关节映射错误。右手夹爪不是唯一原因；无夹爪的 Menagerie
H1 在同样控制下也会跌倒。

## 已冻结的选择

用户已选择 `A + R`，对应
[ADR-0013](../decisions/0013-h1-target-dynamics-retraining.md)：

- 为 Menagerie H1 + 右手单 Robotiq 2F-85 适配/重训步态；
- 保留连续全身动力学和最终 L3 语义；
- 旧 Unitree 策略只作为接口或初始化候选，不作为目标行为证据。

以下路线已否决：

- `B`：以 Unitree RL Gym 原生下身动力学构造混合 H1；
- `C`：行走阶段切换模型或使用运动学移动。

当前项目已解除“路线未决”和“GPU 运行时完全未执行”阻塞：隔离、无凭据的 A800
兼容性 Spike 已通过 JAX GPU、MJX/Warp 加载以及派生 H1+右侧 Robotiq 模型的一次
有限状态 reset/step。随后 Digest 锁定的训练 OCI 也在 A800 上以非 root、只读根
文件系统和无运行时 Secret 的方式通过同一 one-step 门禁，运行时已为 `locked`。

此外，一次 32,768 请求步、256 并行环境的 A800 PPO 研究级 smoke 已真实执行：
Brax 最终报告 33,280 步，训练吞吐约为 2,596.7 steps/s，训练与派生策略推理均为
有限值；在按环境扩展 `naconmax` 后，CCD 与接触容量溢出计数均为零。该证据固定为
`research_smoke / non_publishable`：没有保存 Checkpoint，平均评估 Episode 约为
87.75 步，不能证明策略质量。规范 1 亿步训练、新的可发布策略和厨房 5/5 L3 行为
仍未执行；在这些行为验证完成前，不能进入 L3 状态机。

后续对 MuJoCo 3.6 MJX-Warp 容量语义的复核确认：`naconmax` 与 `naccdmax` 是所有
并行世界共享容量，`njmax` 才是每个世界容量。当前 Profile 因此改为每环境
16 个活动接触、8 个 CCD 接触和每世界 `njmax=128`。提交 `101aff7` 的新
Digest 锁定镜像与当前 Profile 的 A800 one-step 已通过；此前 smoke 仍只作为
历史证据。8,192 环境规模预检也已通过，批量状态数值有限且容量零溢出；新
smoke 仍需真实执行。
