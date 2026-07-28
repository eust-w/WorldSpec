---
status: Normative
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/compiler/compiler-model.md
last-verified: 2026-07-28
---

# 编译器模型

编译不是序列化，而是受约束 Lowering：

```text
WorldDefinition
+ TargetProfile
+ BuildIntent
+ BackendCalibration
-> Model Selection
-> Capability Match
-> LoweringPlan
-> Backend IR
-> Artifacts and Reports
```

## TargetProfile

绑定目标、版本、平台、能力矩阵、限制和认证测试。必须是具体 Profile，例如 `mujoco.rigid-manipulation@0.1`，不能只写“支持 MuJoCo”。

## BuildIntent

声明用途、优先级、硬要求、允许降级、预算和证据选择策略。任何未获允许的 `dropped/unsupported` 使 Build 失败。

## LoweringPlan

每个规范对象/能力产生一条状态：`exact / converted / approximated / baked / emulated / dropped / unsupported`，并记录源引用、目标绑定、理由、影响和诊断。

## Backend IR

后端 IR 是编译器私有、版本化和可检查的中间结构，不是 WorldSpec 真源。目标名称不能反向成为永久 ID。

BuildManifest 锁定选择与工具；LossReport 解释语义损失；ConformanceReport 保存测试；Certificate 只引用这些不可变产物。
