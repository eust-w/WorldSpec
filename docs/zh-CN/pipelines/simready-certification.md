---
status: Normative
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/pipelines/simready-certification.md
last-verified: 2026-07-28
---

# SimReady 认证流程

```text
Schema Validate
-> Core Invariants
-> Target Compile
-> Native Load
-> Static Conformance
-> Behavior Tests (L3 only)
-> Reports + Certificate
```

## L2

L2 要求目标运行时原生加载产物，所有资源可解析，Frame/单位/质量等静态检查通过，且 LossReport 覆盖所有 Lowering 决策。仅“文件已生成”不算 L2。

## L3

L3 必须绑定版本化 Task/Behavior Profile、初始状态、运行时配置和通过阈值。行为测试至少记录：

- 成功/失败与失败类别；
- 最终状态与关键 Predicate；
- 数值异常、穿透、NaN 和不稳定；
- 资产、编译器、Profile、后端与硬件版本。

`TaskRunReport` 不替代原始运行记录。每次运行必须绑定独立 `RuntimeRecord` Digest；签发器核对 TaskProfile、ControlProfile、全部 PredicateProfile、锁定初始状态、TargetProfile、BuildManifest 与每条 RuntimeRecord。汇总中的 `5/5` 不能替代五条可验证轨迹。

Reference Predicate Engine 只读取规范证据，不读取后端原生布尔量。签发器会从每个 Obligation 的规范 `metrics` 重新计算 truth、robustness 与 confidence，不直接相信报告中的布尔结果。首批实现 `inside`、`stable`、`open`、`closed`、`released`、`upright`、有限值、限位、危险碰撞和穿透谓词；缺失或非有限证据返回 `unknown`。

生成资产可达到 L3，但 Claim 仍保留 Generated/Estimated。MuJoCo 与 Three.js 是 v0.1 认证后端；Three.js 仅认证视觉/场景加载和声明的交互，不认证不存在的动力学。

失败必须区分 invalid、compile_failed、target_load_failed、behavior_failed、backend_limited 与 unknown，不得把超时自动判为资产无效。

## v0.1 已实现边界

- MuJoCo Runner 校验 Bundle Artifact，使用真实 `MjModel.from_xml_path` 加载，并在规定步数后检查 `qpos/qvel/qacc` 有限。
- Three.js Runner 校验 Bundle Artifact，启动 loopback 预览与真实 Chromium，检查 GLB 加载、WebGL、坐标映射、有限 Bounds 并保存截图。
- `worldspec certify` 可从绑定证据生成 L2 候选，只有全部 Digest、Loss 覆盖、必需测试、环境和 Artifact 检查通过后才能输出/签名。
- 当前 macOS arm64 本地 Profile 已分别签发 unsigned MuJoCo/Three.js L2，并验证篡改拒绝。
- 仓库锁定的 Linux x86_64 参考 Profile 在当前 Mac 上会因环境不匹配而失败；尚无该 Profile 的 L2 证据。
- L3 Digest/运行证据核验与签发路径已实现；没有完整 TaskRunReport、全部 RuntimeRecord 或 Predicate 证据时 Fail-Closed。
- 尚无 H1 厨房任务的 5/5 行为 Witness，因此项目级 H1 L3 仍未完成；当前实现不能作为 H1 已通过的证据。
