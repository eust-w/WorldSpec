---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/pipelines/generation.md
last-verified: 2026-07-28
---

# Image and video generation

The Chinese document is the normative source; this page is its official translation.

Generation is a pluggable Forge adapter, not part of the Core:

```text
GenerationRequest
  -> BackendPlan
  -> RawGenerationArtifacts
  -> GenerationClaims
  -> AssetDraft
```

## Routing

- Single image: a TRELLIS.2-class reference backend, expected to output PBR GLB; model/weight versions and license are locked.
- Multi-view/video: a Nerfstudio-class reconstruction adapter that may output NeRF, 3DGS, or derived meshes.
- Existing geometry: skip generation and enter Ingestion/Doctor.

Backend capability is declared by Profile. Model-private fields never enter Core.

## Evidence boundary

- Visible regions may be `reconstructed` or `generated`; hidden structure carries uncertainty.
- Scale requires a scale marker, camera calibration, CAD, or human measurement; otherwise it remains unknown/estimated.
- Model-created PBR maps remain `generated`.
- Mass, friction, joints, and articulation cannot become measured facts from visual plausibility.

Generated assets are capped at L2 by default. A Task Profile and passing behavior tests may raise the bundle to L3 without raising Claim authority.
