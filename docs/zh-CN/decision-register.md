---
status: Normative
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../en/decision-register.md
last-verified: 2026-07-30
---

# 决策登记

| ID | 决策 | 状态 | ADR |
|---|---|---|---|
| D-001 | 产品是具身资产平台；v0.1 同时验收三条闭环 | Accepted | [ADR-0001](decisions/0001-product-scope-and-name.md) |
| D-002 | WorldSpec 为工作名，公开品牌后定；不采用 SimForge | Accepted | [ADR-0001](decisions/0001-product-scope-and-name.md) |
| D-003 | 仓库为真源；中文规范、英文官方译本 | Accepted | [ADR-0002](decisions/0002-document-and-schema-binding.md) |
| D-004 | JSON + Draft 2020-12 JSON Schema 为规范绑定 | Accepted | [ADR-0002](decisions/0002-document-and-schema-binding.md) |
| D-005 | Rust Core + Python/TypeScript/WASM 绑定 | Accepted Design | [ADR-0003](decisions/0003-implementation-and-runtime.md) |
| D-006 | Linux + NVIDIA 80GB A800/H100 为参考生成环境 | Accepted Design | [ADR-0003](decisions/0003-implementation-and-runtime.md) |
| D-007 | 支持 Mesh、机器人、CAD、USD、图像和视频输入 | Accepted Design | [ADR-0004](decisions/0004-inputs-and-native-payload.md) |
| D-008 | CAD/USD Profile 完备 + Native Payload 保留 | Accepted | [ADR-0004](decisions/0004-inputs-and-native-payload.md) |
| D-009 | v0.1 认证 MuJoCo/Three.js；OpenUSD 不代表 Isaac 认证 | Accepted | [ADR-0005](decisions/0005-targets-and-certification.md) |
| D-010 | 生成资产默认最高 L2；行为验证后可 L3，证据不升级 | Accepted | [ADR-0005](decisions/0005-targets-and-certification.md) |
| D-011 | 生成后端可插拔；TRELLIS.2/Nerfstudio 类参考适配器 | Accepted Design | [ADR-0006](decisions/0006-generation-and-corpus.md) |
| D-012 | Corpus 为合成基准 + 一个授权明确的真实厨房案例 | Accepted Design | [ADR-0006](decisions/0006-generation-and-corpus.md) |
| D-013 | v0.1 入口 CLI/API；Three.js 仅预览调试 | Accepted | [ADR-0007](decisions/0007-product-surface-and-distribution.md) |
| D-014 | 本地 CAS Manifest/Lock/证书；OCI/Marketplace 后移 | Accepted | [ADR-0007](decisions/0007-product-surface-and-distribution.md) |
| D-015 | AGPL-3.0 + 商业许可 + CLA；法律文本待法务 | Accepted Design | [ADR-0008](decisions/0008-licensing-and-contributions.md) |
| D-016 | 现实世界“最大完备表达” | Superseded | 由 Profile Complete + Loss Transparency 取代 |
| D-017 | 单一 Scene Tree 或字段并集 | Superseded | 由对象库、多图与 Profile 取代 |
| D-018 | 跨后端逐帧物理一致 | Superseded | 改为任务/行为容差内一致 |
| D-019 | World/Task/Benchmark Generation、Registry、Marketplace | Future | [路线图](roadmap.md) |
| D-020 | 物理推断、碰撞参数和生成成本阈值 | Research | [开放问题](research/open-questions.md) |
| D-021 | Rust Axum + Python OCI Worker，文件 CAS + SQLite WAL | Accepted Design | [ADR-0009](decisions/0009-v0.1-execution-baseline.md) |
| D-022 | H1 + Robotiq 2F-85，短距步行后完成抽屉放杯任务，固定场景 5/5 | Accepted Design | [ADR-0009](decisions/0009-v0.1-execution-baseline.md) |
| D-023 | 物理、视觉壳与物理不变性分别出证，三者联合验收 | Accepted | [ADR-0009](decisions/0009-v0.1-execution-baseline.md) |
| D-024 | 生成模型包使用逐文件 Digest 的内容寻址只读缓存 | Accepted | [ADR-0010](decisions/0010-generation-model-bundles.md) |
| D-025 | H1/Robotiq 使用锁定 Menagerie 源，步态使用锁定 Unitree RL Gym；不复制 dirty BiGym 载荷 | Accepted Design | [ADR-0011](decisions/0011-h1-reference-sources.md) |
| D-026 | H1/Robotiq 通过独立 Profile、完整命名空间和不可变原生载荷组合；首个 L3 锁定右手单夹爪 | Accepted Design | [ADR-0012](decisions/0012-h1-robotiq-composition.md) |
| D-027 | 采用 A+R：为 Menagerie H1 + 右手单 Robotiq 适配/重训步态，拒绝混合模型和运动学切换 | Accepted Design | [ADR-0013](decisions/0013-h1-target-dynamics-retraining.md) |
| D-028 | H1 重训采用 MuJoCo Playground v0.2.0、MuJoCo/MJX、Warp 与 Brax JAX PPO；目标组合使用专用适配器，训练产物为 Orbax | Accepted Design | [ADR-0014](decisions/0014-h1-mujoco-playground-ppo-engine.md) |
| D-029 | 保持原中期门槛；增加移动到零命令课程和停稳奖励，先以 CCD 35→50 单候选数值探针门控 A800 校准 | Accepted Design | [ADR-0015](decisions/0015-h1-transition-braking-calibration.md) |
| D-030 | A1 使用 60% 行走停稳、40% 站立回放和 stand-v2.1 教师动作蒸馏；先做小规模 A800 校准且不放宽门槛 | Accepted Design | [ADR-0016](decisions/0016-h1-stand-retention-distillation.md) |
| D-031 | A2 将运动与零速度/站立拆为两个冻结策略，由 5 步线性动作混合的确定性 Supervisor 切换；先做零训练 A800 探针 | Accepted Design | [ADR-0017](decisions/0017-h1-dual-policy-supervisor.md) |
| D-032 | A3 从冻结运动策略真实 rollout 采样交接状态，训练独立 Capture Policy；停稳门测最后 0.2 秒静止保持，失败不自动调参或启动 100M | Accepted Design | [ADR-0018](decisions/0018-h1-motion-state-capture-policy.md) |
| D-033 | A4 用速度连续稳定门控串联 Motion、Capture、Stand 三策略；Capture 最多 40 步、交接混合 5 步、纯 Stand 至少 10 步，探针不启动 100M | Accepted Design | [ADR-0019](decisions/0019-h1-phase-aware-supervisor.md) |
| D-034 | A5 冻结 A4 腿部 Supervisor，以右臂 Jacobian/阻抗和物理接触完成固定 primitive 厨房闭环；先单次再 5/5，禁止隐藏抓取约束和 L3 声明 | Accepted Design | [ADR-0020](decisions/0020-h1-fixed-kitchen-integration.md) |
| D-035 | 选择 A5-R：修复杯托、容量和单步 IK 实现，增加固定基座可达性预检；不扩大到全身 MPC/QP，单次通过后才继续 5/5 | Accepted Design | [ADR-0021](decisions/0021-h1-a5-failure-response.md) |
| D-036 | 选择 A5-C：冻结 A4 腿部策略，以底座平面速度、躯干和右臂为 QP 变量并显式加入 MuJoCo 偏置力前馈；先做 CPU/A800 把手跟踪 Spike，通过后才可重跑 A5 | Accepted Design | [ADR-0022](decisions/0022-h1-a5r-dynamic-control-failure.md) |
| D-037 | 选择 A5-CI：控制器、门槛、策略和场景保持不变，补齐终止子通道、关节状态、控制利用率/饱和与活动策略后只做一次 A800 等价诊断重放；失败即归档并停止 | Accepted | [ADR-0023](decisions/0023-h1-a5c-control-spike-failure.md) |
| D-038 | A5-CI 唯一 Attempt 因诊断后处理 `KeyError: control` 失败；正式诊断/控制门均未通过，旧/新控制终止根因保持 unknown；修复仅具本地/CI 证据，不重放、不启动 A5/5-of-5/100M | Accepted | [ADR-0023](decisions/0023-h1-a5c-control-spike-failure.md) |
| D-039 | 用户重新授权 A5-CI 修正重放，目标仅为 `formalDiagnosticReplayGate=passed`；每次使用新 Attempt 且不自动重试，后处理失败必须先交接可用产物，诊断通过后停在 A5/100M 之前 | Accepted | [ADR-0024](decisions/0024-h1-a5ci-corrected-replay.md) |
| D-040 | Attempt-02 完成 A800 重放并定位 `right_hip_yaw` 关节限位，但本地 Receipt 因 `datetime` 未导入而未生成，正式诊断交接仍失败；Receipt 逻辑改为独立、可单测并验证产物身份的 Finalizer 后使用新 Attempt | Accepted | [ADR-0024](decisions/0024-h1-a5ci-corrected-replay.md) |
| D-041 | Attempt-03 完成 GPU 重放、产物与 Receipt 交接，但 Report 的 `equivalenceAssessment` 与冻结 Schema 不一致，正式诊断门仍失败；保持 Schema 不变，修正实现并以真实产物预验证后使用新 Attempt | Accepted | [ADR-0024](decisions/0024-h1-a5ci-corrected-replay.md) |
| D-042 | Attempt-04 完成 GPU 重放、产物、Receipt、诊断完备与静态等价检查，但 Trace 的既有 `activePolicy=blend` 未纳入诊断枚举，正式诊断门仍失败；仅补齐诊断 Schema 枚举并以新 Attempt 重放 | Accepted | [ADR-0024](decisions/0024-h1-a5ci-corrected-replay.md) |
| D-043 | Attempt-05 在 Drobodata A800 完成单次等价诊断重放和完整产物交接，`formalDiagnosticReplayGate=passed`；控制门仍因 `right_hip_yaw` 关节限位失败，Controller 保持 `non_publishable`，停止在 A5/5-of-5/100M 之前 | Accepted | [ADR-0024](decisions/0024-h1-a5ci-corrected-replay.md) |
| D-044 | 选择 A5-CF：保持 A5-C 的 QP、策略、场景、范围、终止条件和质量门不变；任务阶段用 `0.05/0.02` 迟滞触发 Motion，并复用已验证的 Capture 稳定门和 5 步 Blend 完成 Motion→Stand 交接；先单次 A800 Spike，不自动调参或启动 A5/100M | Accepted Design | [ADR-0025](decisions/0025-h1-task-policy-handoff-fix.md) |
| D-045 | A5-CF 在 A800 上消除了 `right_hip_yaw` 交接越限，但任务阶段因躯干/右臂运动导致 `fall_height`，未成为控制候选；选择 A5-CG，锁定底座和躯干，只用四个右臂关节 QP 与显式偏置力前馈做一次门控 | Accepted Design | [ADR-0026](decisions/0026-h1-dynamic-arm-tracking.md) |
| D-046 | A5-CG 在 A800 上保持 Stand Policy 与四关节动态臂隔离，但仍因低位把手目标诱发近奇异屈肘、基座后滑和 `fall_height`；选择 A5-CH，将自制任务几何整体移入已观测的稳定工作空间，门槛和 Controller 不变 | Accepted Design | [ADR-0027](decisions/0027-h1-ergonomic-task-geometry.md) |
| D-047 | A5-CH 在 A800 上仍因右臂扰动后的基座后滑触发 `fall_height`；选择 A5-CJ，以任务原点 PD 命令复用 Motion/Capture/Stand 策略恢复基座，恢复期间冻结右臂目标，全部质量门保持不变 | Accepted Design | [ADR-0028](decisions/0028-h1-task-origin-base-recovery.md) |
| D-048 | A5-CJ 在 A800 上因 PD 产生训练域外负向 `vx` 并最终触发 `fall_height`；选择 A5-CK，仅把纵向恢复命令限制到冻结 Motion Policy 的非负训练域，其他控制语义和质量门不变 | Accepted Design | [ADR-0029](decisions/0029-h1-forward-only-base-recovery.md) |
| D-049 | A5-CK 在域内 `+0.5 m/s` 命令下仍因右臂任务载荷持续后滑并触发 `fall_height`；选择任务载荷感知校准，以 A5-CK held 姿态/力前馈和小幅基座扰动重训下肢策略，不改变观察 ABI 或质量门 | Accepted Design | [ADR-0030](decisions/0030-h1-task-load-aware-locomotion.md) |
| D-050 | 首轮任务载荷校准在 A800 上无数值异常但出现末期退化、停稳超速和负载站立漂移；选择 retention-v3 Warm Start、Stand/Capture 双教师、完整 A5-CK 载荷与逐 Checkpoint 正式门选择，质量门保持不变 | Accepted Design | [ADR-0031](decisions/0031-h1-task-load-retention-and-checkpoint-selection.md) |
| D-051 | task-load-retention 在 A800 上的 Episode 存活继续退化，且历史评估错误地把完整一秒减速段作为静止门；选择最后 0.2 秒终端保持测量、显式终止惩罚与教师动作成本，所有数值门槛不变，并只运行一次 survival 校准 | Accepted Design | [ADR-0032](decisions/0032-h1-terminal-hold-and-survival-shaping.md) |
| D-052 | task-load-survival 的确定性十项行为测试全部通过，但 Brax 平均 Episode 门仍在使用默认随机评估；选择显式确定性部署评估，并把 Warm Start 纳入同一候选排序，所有控制参数和质量门保持不变 | Accepted Design | [ADR-0033](decisions/0033-h1-deterministic-deployment-evaluation.md) |
| D-053 | 确定性部署评估在 A800 上最高只达 801.82/1000 且后期 KL 漂移；长时域修正已真实执行并选择 12,288,000 步 Checkpoint，平均 Episode 长度 996.01/1000、十项行为测试全过，策略仍为 internal_only，未启动 100M/A5/L3 | Accepted | [ADR-0034](decisions/0034-h1-long-horizon-survival-credit.md) |
| D-054 | 正式 100M 已在 A800 完成并回传可恢复 Checkpoint；5/5 行走—停稳通过但 0/5 零命令站立回归因 0.314–0.324 m 漂移失败，策略保持 non_publishable，禁止自动调参、重试或 L3 声明 | Accepted | [ADR-0035](decisions/0035-h1-formal-100m-training-result.md) |
| D-055 | 选择 A6-S：把 100M 终端 Checkpoint 仅作为任务载荷 Motion Policy，复用冻结的 Capture/Stand Supervisor 做一次 A800 十项门控；通过后才可单次完整 A5，再通过后才可厨房 5/5，任一步失败即停止 | Accepted Design | [ADR-0036](decisions/0036-h1-task-load-supervisor-gate.md) |
| D-056 | A6-S 十项门控通过后，新增独立 A6-K1 单次完整厨房 Profile；复用 A6-S 三策略与 A5-CK 控制契约，单次通过只产生内部候选并仅解锁独立 5/5 Profile | Accepted Design | [ADR-0037](decisions/0037-h1-task-load-full-kitchen-single-gate.md) |
| D-057 | 锚点恢复校准把步行后操作平衡提高到 4/5，但训练只使用步行后快照而正式门有一半静态起步；选择 50% 快照、50% 静态起步的混合重置校准，保持 ABI、训练步数、Episode 长度和全部质量门不变 | Accepted Design | [ADR-0038](decisions/0038-h1-manipulation-balance-mixed-reset.md) |
| D-058 | mixed-reset-v3 把静态起步提高到 5/5，但仍有一个步行后初态失败，且步行后评测错误继承了训练混合；选择 75% 步行后、25% 静态训练，并强制两个评测套件使用纯分布，质量门不变 | Accepted Design | [ADR-0039](decisions/0039-h1-manipulation-post-walk-biased-reset.md) |
| D-059 | post-walk-biased-v4 在纯分布评测中退化为步行后 3/5、静态 5/5；选择从最佳 mixed-reset-v3 Checkpoint Warm Start，用同一操作平衡策略重建 Capture 状态库并恢复 50/50 训练，全部质量门不变 | Accepted Design | [ADR-0040](decisions/0040-h1-manipulation-on-policy-continuation.md) |
| D-060 | on-policy-continuation-v5 的终端阶段仅通过步行后 3/5、静态 5/5，但归档保留七个阶段；选择在同运行、同状态库和不变门槛下评估全部已保存 Checkpoint，仅正式通过的候选才可解锁完整厨房单次门 | Accepted Design | [ADR-0041](decisions/0041-h1-manipulation-checkpoint-portfolio.md) |
| D-061 | checkpoint-portfolio-v6 已保存七个 Checkpoint，但逐候选评估因 JAX 缓存挤占 Warp 显存而在正式门前 OOM；选择 platform allocator、训练后/套件间/候选间清缓存的显存隔离，训练与全部质量门不变 | Accepted Design | [ADR-0042](decisions/0042-h1-manipulation-checkpoint-memory-isolation.md) |
| D-062 | memory-isolated-v7 完成 17,203,200 步和七个 Checkpoint 后仍因同进程 JAX/XLA/Warp 生命周期在正式门前 OOM；选择训练进程正常退出后用全新进程只读评估，全部训练语义和质量门不变 | Accepted Design | [ADR-0043](decisions/0043-h1-manipulation-process-isolation.md) |
| D-063 | process-isolated-v8 已证明训练/评估进程边界生效，但评估在候选测试前因 Brax `running_statistics` 导入路径错误终止；v9 只修正为现有代码已使用的 `brax.training.acme` 路径，其他语义不变 | Accepted Design | [ADR-0043](decisions/0043-h1-manipulation-process-isolation.md) |
| D-064 | process-isolated-v9 已进入全新评估进程，但 fail-closed 模型物化器拒绝覆盖训练进程留下的派生目录；v10 为评估使用独立派生模型目录，不改变训练、候选、种子或质量门 | Accepted Design | [ADR-0043](decisions/0043-h1-manipulation-process-isolation.md) |
| D-065 | v10 首张镜像来自 Profile 锁定前提交，运行时常量与源 Profile 血缘不一致并在训练前 fail closed；从锁定提交重建镜像，仅更新 Profile 的 OCI Digest 后重放 | Accepted Design | [ADR-0043](decisions/0043-h1-manipulation-process-isolation.md) |
| D-066 | 锁定 v10 已完成真实 A800 训练、保存七个 Checkpoint 并进入独立评估进程，但单进程复用候选和两套环境仍在首个候选的 `from_rest` 套件因设备内存耗尽终止；v11 为 7 个候选 × 2 个套件各启一个全新 CUDA 进程，再由 CPU 聚合精确 14 份绑定结果，训练与质量门不变 | Accepted Design | [ADR-0043](decisions/0043-h1-manipulation-process-isolation.md) |
| D-067 | suite-isolated-v11 在真实 A800 上完成七候选训练与 14/14 隔离评测，证明运行链路问题已关闭；所有候选静态评测均 5/5，但最佳候选步行后仅 4/5，Step 4,915,200 的第 2 条轨迹在 99/100 步 `fall_height`，因此正式门失败、策略保持 `non_publishable`，禁止完整厨房单次、5/5 和 100M | Accepted | [ADR-0043](decisions/0043-h1-manipulation-process-isolation.md) |

新增或改变 Accepted 决策必须通过 ADR，不允许只改实施文档。
