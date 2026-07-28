---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../zh-CN/decision-register.md
last-verified: 2026-07-28
---

# Decision register

The Chinese document is the normative source; this page is its official translation.

| ID | Decision | Status | ADR |
|---|---|---|---|
| D-001 | Embodied-asset platform; v0.1 accepts three loops together | Accepted | [ADR-0001](decisions/0001-product-scope-and-name.md) |
| D-002 | WorldSpec is a working name; public brand later; do not use SimForge | Accepted | [ADR-0001](decisions/0001-product-scope-and-name.md) |
| D-003 | Repository is source of truth; Chinese normative, English official translation | Accepted | [ADR-0002](decisions/0002-document-and-schema-binding.md) |
| D-004 | JSON + Draft 2020-12 JSON Schema is the normative binding | Accepted | [ADR-0002](decisions/0002-document-and-schema-binding.md) |
| D-005 | Rust Core with Python/TypeScript/WASM bindings | Accepted Design | [ADR-0003](decisions/0003-implementation-and-runtime.md) |
| D-006 | Linux + NVIDIA 80 GB A800/H100 reference generation environment | Accepted Design | [ADR-0003](decisions/0003-implementation-and-runtime.md) |
| D-007 | Mesh, robot, CAD, USD, image, and video inputs | Accepted Design | [ADR-0004](decisions/0004-inputs-and-native-payload.md) |
| D-008 | CAD/USD profile completeness + Native Payload preservation | Accepted | [ADR-0004](decisions/0004-inputs-and-native-payload.md) |
| D-009 | v0.1 certifies MuJoCo/Three.js; OpenUSD does not mean Isaac certification | Accepted | [ADR-0005](decisions/0005-targets-and-certification.md) |
| D-010 | Generated assets default to at most L2; behavior validation may reach L3 without evidence promotion | Accepted | [ADR-0005](decisions/0005-targets-and-certification.md) |
| D-011 | Pluggable generation; TRELLIS.2/Nerfstudio-class reference adapters | Accepted Design | [ADR-0006](decisions/0006-generation-and-corpus.md) |
| D-012 | Corpus uses synthetic assets plus one rights-cleared real kitchen | Accepted Design | [ADR-0006](decisions/0006-generation-and-corpus.md) |
| D-013 | v0.1 surface is CLI/API; Three.js is preview/debug | Accepted | [ADR-0007](decisions/0007-product-surface-and-distribution.md) |
| D-014 | Local CAS manifest/lock/certificate; OCI/Marketplace deferred | Accepted | [ADR-0007](decisions/0007-product-surface-and-distribution.md) |
| D-015 | AGPL-3.0 + commercial license + CLA; legal text pending | Accepted Design | [ADR-0008](decisions/0008-licensing-and-contributions.md) |
| D-016 | “Maximally complete model of reality” | Superseded | Replaced by Profile Complete + Loss Transparency |
| D-017 | Single Scene Tree or field union | Superseded | Replaced by object store, multiple graphs, and Profiles |
| D-018 | Frame-by-frame cross-backend physics equality | Superseded | Replaced by task/behavior tolerance |
| D-019 | World/Task/Benchmark Generation, Registry, Marketplace | Future | [roadmap](roadmap.md) |
| D-020 | Physics inference, collision parameters, and generation cost thresholds | Research | [open questions](research/open-questions.md) |
| D-021 | Rust Axum + Python OCI workers with file CAS + SQLite WAL | Accepted Design | [ADR-0009](decisions/0009-v0.1-execution-baseline.md) |
| D-022 | H1 + Robotiq 2F-85, short walk then drawer/mug task, fixed-scene 5/5 | Accepted Design | [ADR-0009](decisions/0009-v0.1-execution-baseline.md) |
| D-023 | Separate physical, visual-shell, and physical-invariance evidence with joint acceptance | Accepted | [ADR-0009](decisions/0009-v0.1-execution-baseline.md) |
| D-024 | Generation model bundles use a per-file-digest content-addressed read-only cache | Accepted | [ADR-0010](decisions/0010-generation-model-bundles.md) |
| D-025 | H1/Robotiq use locked Menagerie sources and locomotion uses locked Unitree RL Gym; dirty BiGym payloads are not copied | Accepted Design | [ADR-0011](decisions/0011-h1-reference-sources.md) |
| D-026 | H1/Robotiq composition uses a separate profile, complete namespacing, and immutable native payloads; the right single gripper is only an experiment candidate | Accepted Design | [ADR-0012](decisions/0012-h1-robotiq-composition.md) |
| D-027 | Menagerie H1 locomotion path: retrain/adapt, hybrid model, or visual-demo downgrade | Research / User Decision Required | [experiment and options](research/h1-locomotion-policy.md) |

Changing an Accepted decision requires an ADR; editing only implementation prose is insufficient.
