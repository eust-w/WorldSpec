---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/architecture/overview.md
last-verified: 2026-07-28
---

# Architecture overview

The Chinese document is the normative source; this page is its official translation.

```text
Sources
  -> Forge (ingest/generate/repair/infer)
  -> AssetDraft
  -> Doctor (validate/diagnose/evidence)
  -> WorldDefinition
  -> Compiler (select/lower/package)
  -> Target Bundle
  -> Conformance + Certificate
```

## Module boundaries

- **Core**: canonical objects and invariants for Entity, Frame, Component, Relation, Model, Representation, Evidence, and Time/State.
- **Forge**: converts mesh, robot descriptions, CAD/USD, or image/video into AssetDraft. Its output is a hypothesis, not truth.
- **Doctor**: performs structural, geometric, physical, evidence, and target-compatibility diagnostics. Repairs create new resources and derivations.
- **Compiler**: creates a LoweringPlan and target bundle from TargetProfile, BuildIntent, and model selection.
- **Manifest**: records content digests, tool versions, profiles, selections, and artifacts for reproducibility.

## Not a union of fields

WorldSpec Core is not the union of MJCF, USD, glTF, and other fields. Versioned Native Payload carries target-specific data; LoweringPlan and LossReport expose differences between canonical meaning and target capability.

## Implementation direction

The deterministic Rust Core validator, CLI, CAS/API, OBJ Doctor, structured robot ingestion, MuJoCo/Three.js reference compilation and local L2 certification, and isolated TRELLIS.2/Nerfstudio workers are implemented. Real GPU generation, Linux x86_64 reference-Profile L2, TypeScript/WASM bindings, full Compiler/Doctor coverage, and H1 L3 remain incomplete. Language choice is not part of schema semantics.
