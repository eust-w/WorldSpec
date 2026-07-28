---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/interfaces/cli-api.md
last-verified: 2026-07-28
---

# CLI and asynchronous API

The Chinese document is the normative source; this page is its official translation.

The v0.1 surface is CLI/API. Only the local Rust `validate` CLI is currently implemented; all other commands and the asynchronous Job API remain planned.

| Command | Input | Main output | Current status |
|---|---|---|---|
| `ingest` | local source or SourceBundle | AssetDraft, diagnostics | Future |
| `generate` | images/video and Backend Profile | AssetDraft, generation evidence | Future |
| `validate` | JSON and schema name | structural and selected semantic diagnostics | Implemented Baseline |
| `compile` | WorldDefinition, TargetProfile, BuildIntent | bundle, LossReport, Manifest | Future |
| `certify` | Build and test Profile | ConformanceReport, Certificate | Future |
| `inspect` | ID/digest/report | human- and machine-readable view | Future |
| `bundle` | validated Build | content-addressed delivery bundle and Lockfile | Future |

Every state-changing operation returns a Job ID. Jobs use `queued/running/succeeded/failed/cancelled`; results return immutable artifact references. Failures include stage, code, message, diagnostics, and retryability.

The API never accepts hidden degradation defaults. TargetProfile, BuildIntent, and generation Backend Profile are explicit or resolve through a traceable default Profile.

See [Validator implementation](../implementation/validator.md) for current CLI usage, diagnostics, and boundaries.
