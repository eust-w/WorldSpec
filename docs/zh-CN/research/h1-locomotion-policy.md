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

## 需要用户选择

### A. 为 Menagerie H1 + 目标夹爪适配/重训步态策略（推荐）

- 保留已选定的连续全身动力学和最终 L3 语义；
- 需要 Linux GPU 训练、策略选择和稳定性回归；
- 时间与计算成本最高，但证据链最干净。

### B. 以 Unitree RL Gym 原生下身动力学构造混合 H1

- 复用已验证步态策略，可能更快；
- 需要重新构造可动上身、质量与惯量，并重新校准接触；
- 不再是原样 Menagerie H1，必须产生新的 Model/Derivation 和行为证书。

### C. 行走阶段使用原生模型，操作阶段切换模型或运动学移动

- 最快形成视觉 Demo；
- 状态/动力学不连续，不能满足当前连续物理 L3；
- 只有用户降低验收目标时才可采用。

在选择前，项目停在“组合原生可加载、策略接口兼容、步态行为失败”，不能进入厨房
5/5 L3 状态机。
