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

生成资产可达到 L3，但 Claim 仍保留 Generated/Estimated。MuJoCo 与 Three.js 是 v0.1 认证后端；Three.js 仅认证视觉/场景加载和声明的交互，不认证不存在的动力学。

失败必须区分 invalid、compile_failed、target_load_failed、behavior_failed、backend_limited 与 unknown，不得把超时自动判为资产无效。
