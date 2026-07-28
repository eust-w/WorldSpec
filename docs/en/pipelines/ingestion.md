---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/pipelines/ingestion.md
last-verified: 2026-07-28
---

# Asset ingestion

The Chinese document is the normative source; this page is its official translation.

Every input first becomes a `SourceBundle` containing file digests, format detection, rights declaration, scan report, unit/frame hints, and Native Payload index. It then becomes an `AssetDraft`, never a certified WorldDefinition directly.

## Profiles

| Profile | Inputs | Main actions | Typical unresolved items |
|---|---|---|---|
| Mesh | GLB, OBJ | nodes, meshes, textures, materials, unit inference | scale, normals, hollow/solid |
| Robot | URDF, MJCF | links/bodies, joints, inertia, meshes, native extensions | controllers, transmissions, loops |
| CAD | STEP, IGES | assembly, B-Rep, tessellation, PMI payload | units, feature history, GD&T |
| OpenUSD | USD family | prims, materials, physics schemas, variants payload | proprietary schemas, plugins |

## Stages

```text
quarantine -> fingerprint -> parse -> normalize draft
-> extract resources -> map canonical fields
-> preserve native payload -> diagnose -> AssetDraft
```

Units, up/forward axes, handedness, and quaternion order are explicit. Inferred values are Claims, never source declarations. Source files are read-only; every repair creates a new blob and Derivation.

“Input accepted” and “input fully understood” are reported separately.
