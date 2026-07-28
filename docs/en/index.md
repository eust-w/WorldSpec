---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../zh-CN/index.md
last-verified: 2026-07-28
---

# WorldSpec v0.1 documentation index

The Chinese document is the normative source; English is the official translation. If they conflict, the Chinese text and accepted ADRs govern.

## Document maturity

- **Normative**: required for v0.1 implementation or acceptance.
- **Accepted Design**: architecture accepted, but this repository does not prove implementation.
- **Research**: candidate solution requiring experiments or benchmarks.
- **Future**: excluded from v0.1 code acceptance.
- **Superseded**: retained for traceability but no longer adopted.

## Navigation

- Product: [vision](product/vision.md), [PRD v0.1](product/prd-v0.1.md), [acceptance](product/acceptance.md)
- Architecture: [overview](architecture/overview.md), [object model](architecture/object-model.md), [evidence and uncertainty](architecture/evidence-and-uncertainty.md), [time/state/events](architecture/time-state-events.md), [security and native payload](architecture/security-and-native-payload.md)
- Pipelines: [ingestion](pipelines/ingestion.md), [generation](pipelines/generation.md), [physics and collision](pipelines/physics-collision.md), [SimReady certification](pipelines/simready-certification.md)
- Compiler and interfaces: [compiler model](compiler/compiler-model.md), [MuJoCo](compiler/mujoco.md), [Three.js](compiler/threejs.md), [CLI/API](interfaces/cli-api.md), [reports](interfaces/reports.md)
- Current implementation: [Rust Validator](implementation/validator.md)
- Governance: [decision register](decision-register.md), [versioning](governance/versioning.md), [licensing](governance/licensing.md)
- Research and future: [open questions](research/open-questions.md), [H1 locomotion policy mismatch](research/h1-locomotion-policy.md), [roadmap](roadmap.md)
- ADRs: [decision directory](decisions/README.md)

## Normative binding

The machine-readable specification lives in `schemas/0.1/` and uses JSON Schema Draft 2020-12. JSON is the v0.1 normative binding; YAML may become a future authoring format but is not normative.
