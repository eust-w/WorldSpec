---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/interfaces/cli-api.md
last-verified: 2026-07-28
---

# CLI and asynchronous API

The Chinese document is the normative source; this page is its official translation.

The v0.1 surface is CLI/API. The local CAS, SQLite WAL job index, loopback API, and command envelopes listed below are implemented. Creating a Job does not execute a backend: GPU generation, Doctor mesh repair, MuJoCo/Three.js compilation, and L2/L3 certification still require their workers/backends.

| Command | Input | Main output | Current status |
|---|---|---|---|
| `ingest` | local sources and RightsSpec | CAS SourceBundle and AssetDraft | Implemented Envelope |
| `generate` | source artifact and GenerationProfile | recoverable JobSpec | Queue Implemented; Worker Future |
| `validate` | JSON and schema name | structural and semantic diagnostics | Implemented |
| `compile` | WorldDefinition and TargetProfile | recoverable JobSpec | Queue Implemented; Backend Future |
| `certify` | Certificate, optional Ed25519 seed | validated signed/unsigned Certificate | Implemented Envelope |
| `inspect` | JSON, optional Schema | canonical SHA-256 and diagnostics | Implemented |
| `resolve` | CAS digest | original immutable blob | Implemented |
| `doctor diagnose` | JSON/AssetDraft | validator diagnostics | Implemented Baseline |
| `doctor repair` | AssetDraft and Profile | recoverable JobSpec | Queue Implemented; Worker Future |
| `bundle` | build input and Profile | recoverable JobSpec | Queue Implemented; Assembler Future |
| `job get/cancel/wait` | Job ID | job state | Implemented |

Every state-changing operation returns a Job ID. Jobs use `queued/running/succeeded/failed/cancelled/timed_out`; results return immutable artifact references. URI-form IDs must be URL-encoded when used in HTTP paths.

The API never accepts hidden degradation defaults. TargetProfile, BuildIntent, and generation Backend Profile are explicit or resolve through a traceable default Profile.

See [OpenAPI v1](../../../openapi/worldspec-v1.yaml) for the API contract and [Validator implementation](../implementation/validator.md) for CLI diagnostics and boundaries.
