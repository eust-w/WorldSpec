---
status: Research
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/research/h1-locomotion-policy.md
last-verified: 2026-07-29
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

此外，旧容量 Profile 的一次 32,768 请求步、256 并行环境 A800 PPO 研究级 smoke
已真实执行。Brax 最终报告 33,280 步，训练吞吐约为 2,596.7 steps/s，训练与派生
策略推理均为有限值；该证据固定为 `research_smoke / non_publishable`，没有保存
Checkpoint，不能证明策略质量。

后续对 MuJoCo 3.6 MJX-Warp 容量语义的复核确认：`naconmax` 与 `naccdmax` 是所有
并行世界共享容量，`njmax` 才是每个世界容量。当前 Profile 因此改为每环境
16 个活动接触、8 个 CCD 接触和每世界 `njmax=128`。提交 `101aff7` 的新
Digest 锁定镜像与当前 Profile 的 A800 one-step 已通过；此前 smoke 仍只作为
历史证据。8,192 环境规模预检也已通过，批量状态数值有限且容量零溢出。
容量修订后的第二次 32,768 请求步、256 环境 smoke 随后在 A800 完成：最终报告
33,280 步、约 2,672.75 steps/s，训练和推理数值有限，CCD 与其他容量溢出均为零。
但平均评估 Episode 仅约 87.34 步；该结果仍为 `research_smoke / non_publishable`，
没有 Checkpoint，也不表示策略可用。规范 1 亿步训练、可发布策略和厨房 5/5 L3
行为仍未执行；在这些行为验证完成前，不能进入 L3 状态机。

在投入规范 1 亿步预算前，当前实现新增独立的 `stand-v1` 研究校准门：使用
1,048,576 请求步、2,048 并行环境和严格零速度命令，显式版本化存活、直立、
基座高度、姿态、力矩及动作变化奖励。校准保留严格的五次确定性站立检查，并将
训练期较宽松终止条件与最终验证阈值分开。其 Checkpoint 固定为
`research_only / internal_only`；即使门禁通过，也只允许进入下一课程实验，不等于
规范训练或 L3。当前这部分仅有实现与 Profile，尚无 A800 执行报告。

首次 A800 校准尝试 `worldspec-h1-calibration-vzndt` 已真实进入 PPO、确定性评估和
本地 Checkpoint 打包，但在报告组装阶段因把 `(42,)` 形状直接转为整数而触发
`TypeError`。由于结果标记尚未写出、Pod 随作业清理，策略质量和 Checkpoint 均不能
恢复或推断；该次运行固定记录为 `failed / quality unknown / checkpoint not_recovered`。

修复报告组装后，`stand-v1` 在真实 A800 上完成了第二次运行
`worldspec-h1-calibration-qxpdh`。最终平均 Episode 长度为 124.23 步，相对 87.34
基线提高 1.42 倍，但未达到 350 步和 2 倍的配置门槛；五次确定性站立均在约第 99
步因 `fall_height` 终止，平面漂移约 1.027 米，因此结果固定为
`completed / quality failed / deterministic stand 0/5`。报告证明内部研究
Checkpoint 已生成，但旧 Launcher 在 Pod 完成后才调用 `kubectl cp`，集群拒绝对已
退出容器执行复制，故该 Checkpoint 标记为 `generated_not_retrieved`。这是一条有效的
负质量证据，不能作为可用策略或 1 亿步训练的放行依据。

初始 `stand-v2` 保留 `stand-v1` Profile 作为不可变历史输入，并将受限预算增加到
4,194,304 请求步和 4,096 并行环境，强化存活、直立、基座高度和姿态塑形，同时把
124.23 设置为明确基线。其首次真实 A800 作业在 PPO 前被 Brax 拒绝：
`batchSize × numMinibatches = 128 × 16 = 2048` 不能被 4,096 环境整除。这是配置失败，
不包含任何策略质量证据；该无效 Profile 与日志 Digest 均被保留。Core 现已增加提交前
语义校验，新的 `stand-v2.1` 仅将 `batchSize` 改为 256，使
`256 × 16` 可被 4,096 整除。

产物交接改为两阶段握手：Pod 写出报告和 Checkpoint 后进入
`artifact_ready`，Launcher 在 Pod 仍存活时复制产物并写入确认文件，入口收到确认后
才退出。由于该集群的单流 `kubectl cp` 两次在约 4.7–4.8 MB 处返回
`unexpected EOF`，最终实现改为 512 KiB 独立分块、逐块重试、原子落盘并按报告
校验总大小与 SHA-256。

`stand-v2.1` 已在真实 A800 上完成并通过全部校准门：最终平均 Episode 为 500 步，
相对 `stand-v1` 提升 4.02 倍；五次 4 秒确定性站立全部通过，最大平面漂移约
0.0217 米，最低基座高度约 0.988 米，日志中无容量溢出。内部 Checkpoint 通过 12 个
分块完整回传，大小为 6,280,684 字节，Digest 为
`sha256:fc91edb936de7391b7e075596e5aaa944acc656664cdb820dbb21c149cf7921c`。
规范报告见
[`locomotion-calibration.a800.passed.json`](../../../examples/h1-kitchen/locomotion-calibration.a800.passed.json)。
该证据仍明确为 `research_calibration / non_publishable / internal_only`：它只放行
下一步行走课程实验，不等于规范 1 亿步训练完成，更不等于厨房任务 L3。

## 中期校准与正式训练门控

下一阶段已冻结为 `loaded-track-settle-v1`。它从上述内部 Checkpoint Warm Start，
只恢复观察归一化、Policy 和 Value 网络；Brax 0.14.2 不恢复优化器状态，因此新运行
明确记录 `optimizerState=reset`，不能称为无缝续训。

中期训练使用最终 Menagerie H1 + 右手 Robotiq 2F-85，预算为 16,777,216 步、
4,096 环境。门控包含五次“3 秒 `0.5 m/s` 前进 + 1 秒停稳”和五次零命令站立回归。
只有平均 Episode 长度不少于 900，且全部十项行为、有限值、关节、接触和容量诊断
通过，才允许创建 1 亿步 Job。任何失败仍必须回传 Checkpoint、Trace 和报告，但固定
为 `non_publishable`，不自动重试或调参。

正式任务型 Profile 使用 100,000,000 步、8,192 环境和厨房短距命令范围，并从通过的
中期 Checkpoint 再次 Warm Start。最终十项测试全部通过时，只能标记
`policy_candidate / internal_only`；这仍不证明“行走—开抽屉—抓杯—放置—关抽屉”
完整任务 5/5，也不构成厨房 L3 证据。

当前仓库已经包含上述 Schema、Warm Start 安全校验、十项评测、Worker 血缘门控、
512 KiB 双向分块传输和两个隔离 A800 Job 的实现。

### 2026-07-29 中期实跑结果

`loaded-track-settle-v1` 已在单张 NVIDIA A800-SXM4-80GB 上真实执行。训练达到
17,203,200 个报告步，最终平均 Episode 长度为 972.125，五次零命令站立回归全部
通过。五次行走—停稳测试中的前进距离、横向漂移、移动阶段速度跟踪、基座高度和
直立性也全部通过。

中期门控仍判定为失败：五次行走测试在 1 秒停稳窗口中的最大线速度为
0.4788–0.4883 m/s，超过 0.20 m/s；最大角速度为 0.5349–0.5940 rad/s，超过
0.40 rad/s。因此正式 100M Job 没有创建，回传 Checkpoint 固定为
`non_publishable / internal_only`。运行中没有 NaN、关节越限、容量溢出或异常接触
诊断；日志另有两条 `ccd_iterations=35` 需要提高的 MuJoCo Warp 建议，它们不是
CCD 容量溢出，但下一次校准前需要单独评估数值影响。

规范化失败证据见
[`locomotion-midterm.a800.failed.json`](../../../examples/h1-kitchen/locomotion-midterm.a800.failed.json)。
完整 Checkpoint、Trace 和原始报告位于忽略提交的本地 `runs/a800/` 目录。按冻结
计划，本次失败后没有自动调参或重试。随后已通过
[ADR-0015](../decisions/0015-h1-transition-braking-calibration.md) 选择方案 A：
保留全部原始门槛，增加 150 步移动到 50 步零命令的显式过渡课程和停稳奖励，并在
训练前先执行唯一 CCD `35 → 50` 候选的数值探针。探针必须在 4,096 环境、200 步
轨迹中无迭代建议和容量溢出；失败则不启动校准。该 CCD 探针已在真实 A800 上通过，
迭代建议、CCD 容量溢出和其他容量溢出均为 0。它只证明声明的 CCD=50 数值探针干净，
不得提前记为停稳改善证据。

### 2026-07-29 过渡校准结果

`loaded_track_settle_transition` 已在同类单张 A800 上完成 17,203,200 个报告步。
行走后的最大停稳线速度由上一版的 0.4788–0.4883 m/s 改善到
0.4020–0.4377 m/s，最大角速度由 0.5349–0.5940 rad/s 改善到
0.4131–0.4529 rad/s，但五次行走测试仍全部超过原始门槛。

同时，五次零命令站立回归由上一版 5/5 通过退化为 0/5：平面漂移达到
0.5112–0.5447 m，停稳线速度为 0.2220–0.2825 m/s。最终平均 Episode 长度也从
972.125 降至 903.4375。运行中无 NaN、关节越限、容量溢出或异常接触。结论是该课程
改善了部分制动指标，但导致站立保持和总体质量退化，正式训练门控失败，未创建
100M Job，也不自动调参或重试。

规范化失败报告见
[`locomotion-transition.a800.failed.json`](../../../examples/h1-kitchen/locomotion-transition.a800.failed.json)。
