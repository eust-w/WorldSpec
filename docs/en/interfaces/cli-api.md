---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/interfaces/cli-api.md
last-verified: 2026-07-28
---

# CLI and asynchronous API

The Chinese document is the normative source; this page is its official translation.

The v0.1 surface is CLI/API. The local CAS, SQLite WAL job index, loopback API, and command envelopes listed below are implemented. The OBJ Doctor, structured robot ingestion, MuJoCo/Three.js reference compilers, isolated generation adapters, and H1 training-gate adapter are implemented. Creating a generation/training Job or passing gate tests still does not prove that a real GPU ran; L2/L3 certification requires the corresponding execution evidence.

| Command | Input | Main output | Current status |
|---|---|---|---|
| `ingest` | local sources and RightsSpec | CAS SourceBundle and AssetDraft | Mesh/URDF/MJCF implemented; CAD/USD isolated inspection skeleton |
| `generate` | source artifact and GenerationProfile | recoverable JobSpec | Queue + TRELLIS.2/Nerfstudio Worker implemented; GPU unaccepted |
| `train` | native-load Conformance and LocomotionTrainingProfile | recoverable JobSpec | the prior Profile passed A800 runtime and research smoke; the capacity-revised current Profile awaits a new image, scale probe, and relocking |
| `validate` | JSON and schema name | structural and semantic diagnostics | Implemented |
| `compile` | WorldDefinition, TargetProfile, and BuildIntent | local reference Bundle | MuJoCo/Three.js reference slices implemented |
| `certify` | L2 evidence; L3 additionally binds Task/Control/Predicate/InitialState/RuntimeRecord/TaskRunReport | digest-bound signed/unsigned Certificate | L2/L3 evidence assessment implemented; H1 5/5 not executed |
| `inspect` | JSON, optional Schema | canonical SHA-256 and diagnostics | Implemented |
| `resolve` | CAS digest | original immutable blob | Implemented |
| `doctor diagnose` | JSON/AssetDraft or OBJ | validator/OBJ diagnostics | Implemented |
| `doctor repair` | OBJ | new OBJ, CAS blob, and Derivation | Degenerate-face repair implemented |
| `bundle` | build input and Profile | recoverable JobSpec | Queue Implemented; Assembler Future |
| `job get/cancel/wait` | Job ID | job state | Implemented |

Every state-changing operation returns a Job ID. Jobs use `queued/running/succeeded/failed/cancelled/timed_out`; results return immutable artifact references. URI-form IDs must be URL-encoded when used in HTTP paths.

The API never accepts hidden degradation defaults. TargetProfile, BuildIntent, and generation Backend Profile are explicit or resolve through a traceable default Profile.

See [OpenAPI v1](../../../openapi/worldspec-v1.yaml) for the API contract and [Validator implementation](../implementation/validator.md) for CLI diagnostics and boundaries.
