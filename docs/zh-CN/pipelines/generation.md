---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../en/pipelines/generation.md
last-verified: 2026-07-28
---

# 图像与视频生成

生成是 Forge 的可插拔适配器，不进入 Core。统一接口：

```text
GenerationRequest
  -> BackendPlan
  -> RawGenerationArtifacts
  -> GenerationClaims
  -> AssetDraft
```

## 路由

- 单图：参考 TRELLIS.2 类后端，期望输出带 PBR 的 GLB；必须锁定模型/权重版本与许可。
- 多视角/视频：参考 Nerfstudio 类重建适配器，可输出 NeRF/3DGS/Mesh 派生表示。
- 已有几何：跳过生成，进入 Ingestion/Doctor。

后端能力通过 Profile 声明，不允许把某一模型的私有字段写入 Core。

## 证据边界

- 可见区域可标记 `reconstructed` 或 `generated`；隐藏结构必须有不确定性。
- 尺度需要标尺、相机标定、CAD 或人工尺寸证据；否则保持未知/估计。
- PBR 贴图由模型生成时保持 `generated`。
- 质量、摩擦、关节与可动性不得从视觉合理性直接升级为已测事实。

生成资产默认最高 L2。任务 Profile 与行为测试可使 Bundle 达到 L3，但不会提升上述 Claim 的权威等级。
