---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/compiler/compiler-model.md
last-verified: 2026-07-28
---

# Compiler model

The Chinese document is the normative source; this page is its official translation.

Compilation is constrained lowering, not serialization:

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

Binds target, version, platform, capability matrix, limits, and certification tests. It is concrete, such as `mujoco.rigid-manipulation@0.1`; “supports MuJoCo” alone is invalid.

## BuildIntent

Declares purpose, priorities, hard requirements, permitted degradation, budgets, and evidence-selection policy. Any unapproved `dropped/unsupported` result fails the Build.

## LoweringPlan

Every canonical object/capability receives one status: `exact / converted / approximated / baked / emulated / dropped / unsupported`, with source reference, target binding, rationale, consequence, and diagnostics.

## Backend IR

Backend IR is compiler-private, versioned, and inspectable; it is not WorldSpec truth. Target names never become permanent IDs.

BuildManifest locks selections and tools; LossReport explains semantic loss; ConformanceReport stores tests; Certificate references only these immutable artifacts.
