---
status: Normative
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../en/decision-register.md
last-verified: 2026-07-29
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

新增或改变 Accepted 决策必须通过 ADR，不允许只改实施文档。
